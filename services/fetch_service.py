"""One-off HTTP fetch service for Surf Browser Service."""
import asyncio
import time
from typing import Any, Dict, Optional, List
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import structlog

from core.foundation import BrowserOperationError
from models.schemas import FetchBackend

logger = structlog.get_logger()


class FetchService:
    """HTTP fetch service with lightweight and browser-like backends."""

    async def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        json_body: Optional[Any] = None,
        timeout: int = 30000,
        backend: FetchBackend = FetchBackend.AUTO,
        cookies: Optional[List[Dict[str, Any]]] = None,
        impersonate: Optional[str] = "chrome",
        browser_context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Execute a one-off HTTP request."""
        backend_value = backend.value if hasattr(backend, "value") else str(backend)
        selected_backend = self._select_backend(backend_value)
        started = time.time()

        try:
            if selected_backend == FetchBackend.BROWSER.value:
                result = await self._request_browser_context(
                    browser_context, method, url, headers, params, body, json_body, timeout
                )
            elif selected_backend == FetchBackend.CURL_CFFI.value:
                result = await self._request_curl_cffi(
                    method, url, headers, params, body, json_body, timeout, cookies, impersonate
                )
            elif selected_backend == FetchBackend.CLOUDSCRAPER.value:
                result = await self._request_cloudscraper(
                    method, url, headers, params, body, json_body, timeout, cookies
                )
            else:
                result = await self._request_httpx(
                    method, url, headers, params, body, json_body, timeout, cookies
                )

            result["backend"] = selected_backend
            result["duration_ms"] = int((time.time() - started) * 1000)
            result["warnings"] = self._response_warnings(result.get("status"))
            return result
        except Exception as e:
            logger.error("Fetch request failed", url=url, backend=selected_backend, error=str(e))
            raise BrowserOperationError("fetch", str(e))

    def _select_backend(self, backend: str) -> str:
        if backend == FetchBackend.AUTO.value:
            return FetchBackend.HTTPX.value
        return backend

    async def _request_browser_context(
        self,
        browser_context: Any,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]],
        params: Optional[Dict[str, Any]],
        body: Optional[Any],
        json_body: Optional[Any],
        timeout: int
    ) -> Dict[str, Any]:
        if browser_context is None:
            raise BrowserOperationError("fetch", "browser backend requires a session_id with a browser context")
        request_url = self._url_with_params(url, params)
        data = body
        if json_body is not None:
            import json
            data = json.dumps(json_body)
            headers = {**(headers or {}), "content-type": "application/json"}
        response = await browser_context.request.fetch(
            request_url,
            method=method.upper(),
            headers=headers,
            data=data,
            timeout=timeout
        )
        content = await response.body()
        return self._format_response(response.status, response.url, response.headers, content)

    async def _request_httpx(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]],
        params: Optional[Dict[str, Any]],
        body: Optional[Any],
        json_body: Optional[Any],
        timeout: int,
        cookies: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout / 1000) as client:
            response = await client.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                content=body,
                json=json_body,
                cookies=self._cookie_dict(cookies)
            )
            return self._format_response(response.status_code, str(response.url), response.headers, response.content)

    async def _request_curl_cffi(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]],
        params: Optional[Dict[str, Any]],
        body: Optional[Any],
        json_body: Optional[Any],
        timeout: int,
        cookies: Optional[List[Dict[str, Any]]],
        impersonate: Optional[str]
    ) -> Dict[str, Any]:
        try:
            from curl_cffi.requests import AsyncSession
        except ImportError as e:
            raise BrowserOperationError("fetch", "curl_cffi backend requested but curl_cffi is not installed") from e

        async with AsyncSession(impersonate=impersonate or "chrome", timeout=timeout / 1000) as session:
            response = await session.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                data=body,
                json=json_body,
                cookies=self._cookie_dict(cookies),
                allow_redirects=True
            )
            return self._format_response(response.status_code, response.url, response.headers, response.content)

    async def _request_cloudscraper(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]],
        params: Optional[Dict[str, Any]],
        body: Optional[Any],
        json_body: Optional[Any],
        timeout: int,
        cookies: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        try:
            import cloudscraper
        except ImportError as e:
            raise BrowserOperationError("fetch", "cloudscraper backend requested but cloudscraper is not installed") from e

        def run_request():
            scraper = cloudscraper.create_scraper()
            response = scraper.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                data=body,
                json=json_body,
                timeout=timeout / 1000,
                cookies=self._cookie_dict(cookies),
                allow_redirects=True
            )
            return self._format_response(response.status_code, response.url, response.headers, response.content)

        return await asyncio.to_thread(run_request)

    def _format_response(self, status: int, url: str, headers: Any, content: Any) -> Dict[str, Any]:
        raw = content if isinstance(content, bytes) else str(content).encode("utf-8", errors="replace")
        text = raw.decode("utf-8", errors="replace")
        data = {
            "status": status,
            "url": url,
            "headers": dict(headers),
            "text": text,
            "text_preview": text[:4000],
            "length": len(raw),
            "_content_bytes": raw
        }
        try:
            import json
            data["json"] = json.loads(text)
        except Exception:
            data["json"] = None
        return data

    def _url_with_params(self, url: str, params: Optional[Dict[str, Any]]) -> str:
        if not params:
            return url
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        query.update({key: str(value) for key, value in params.items()})
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def _cookie_dict(self, cookies: Optional[List[Dict[str, Any]]]) -> Dict[str, str]:
        if not cookies:
            return {}
        return {
            cookie["name"]: cookie.get("value", "")
            for cookie in cookies
            if cookie.get("name")
        }

    def _response_warnings(self, status: Optional[int]) -> List[str]:
        if status in (401, 403):
            return ["Authentication or access challenge likely; browser mode may be required."]
        if status == 429:
            return ["Rate limit response detected; back off before retrying."]
        if status and status >= 500:
            return ["Server error response detected; retry conservatively."]
        return []
