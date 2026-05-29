"""One-off HTTP fetch service for Surf Browser Service."""
import asyncio
import time
from typing import Any, Dict, Optional, List

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
        impersonate: Optional[str] = "chrome"
    ) -> Dict[str, Any]:
        """Execute a one-off HTTP request."""
        backend_value = backend.value if hasattr(backend, "value") else str(backend)
        selected_backend = self._select_backend(backend_value)
        started = time.time()

        try:
            if selected_backend == FetchBackend.CURL_CFFI.value:
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
            return self._format_response(response.status_code, str(response.url), response.headers, response.text)

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
            return self._format_response(response.status_code, response.url, response.headers, response.text)

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
            return self._format_response(response.status_code, response.url, response.headers, response.text)

        return await asyncio.to_thread(run_request)

    def _format_response(self, status: int, url: str, headers: Any, text: str) -> Dict[str, Any]:
        data = {
            "status": status,
            "url": url,
            "headers": dict(headers),
            "text": text,
            "text_preview": text[:4000],
            "length": len(text)
        }
        try:
            import json
            data["json"] = json.loads(text)
        except Exception:
            data["json"] = None
        return data

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
