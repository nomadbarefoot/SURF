"""One-off HTTP fetch service for Surf Browser Service."""
import asyncio
import time
from typing import Any, Dict, Optional, List
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit, parse_qsl

import structlog

from core.foundation import BrowserOperationError, ResourceLimitError
from models.schemas import FetchBackend
from services.outbound_policy import OutboundPolicyError, get_outbound_policy
from utils.url_security import safe_url_for_log

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
            result = await self._request_with_redirects(
                selected_backend,
                method,
                url,
                headers,
                params,
                body,
                json_body,
                timeout,
                cookies,
                impersonate,
                browser_context,
            )

            result["backend"] = selected_backend
            result["duration_ms"] = int((time.time() - started) * 1000)
            result["warnings"] = self._response_warnings(result.get("status"))
            return result
        except (OutboundPolicyError, ResourceLimitError):
            raise
        except Exception as e:
            logger.error(
                "Fetch request failed",
                url=safe_url_for_log(url),
                backend=selected_backend,
                error=str(e),
            )
            raise BrowserOperationError("fetch", str(e))

    async def _request_with_redirects(
        self,
        selected_backend: str,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]],
        params: Optional[Dict[str, Any]],
        body: Optional[Any],
        json_body: Optional[Any],
        timeout: int,
        cookies: Optional[List[Dict[str, Any]]],
        impersonate: Optional[str],
        browser_context: Optional[Any],
    ) -> Dict[str, Any]:
        """Execute bounded redirects, validating every destination before I/O."""
        from config import get_settings

        settings = get_settings()
        policy = get_outbound_policy()
        current_url = url
        current_method = method.upper()
        current_headers = dict(headers or {})
        current_params = params
        current_body = body
        current_json = json_body

        for redirect_count in range(settings.outbound_max_redirects + 1):
            await policy.validate(current_url)
            request_cookies = cookies
            if browser_context is not None and selected_backend != FetchBackend.BROWSER.value:
                # Ask Playwright for cookies applicable to this exact URL so
                # domain/path/Secure rules are honored on every redirect hop.
                request_cookies = await browser_context.cookies([current_url])
            result = await self._request_once(
                selected_backend,
                current_method,
                current_url,
                current_headers or None,
                current_params,
                current_body,
                current_json,
                timeout,
                request_cookies,
                impersonate,
                browser_context,
            )
            location = self._header(result.get("headers", {}), "location")
            status = int(result.get("status") or 0)
            if status not in {301, 302, 303, 307, 308} or not location:
                result["redirect_count"] = redirect_count
                return result
            if redirect_count >= settings.outbound_max_redirects:
                raise BrowserOperationError(
                    "fetch", f"Too many redirects (maximum {settings.outbound_max_redirects})"
                )

            next_url = urljoin(str(result.get("url") or current_url), location)
            await policy.validate(next_url)
            if self._origin(current_url) != self._origin(next_url):
                current_headers = self._without_sensitive_headers(current_headers)

            if status == 303 or (status in {301, 302} and current_method == "POST"):
                current_method = "GET"
                current_body = None
                current_json = None
            current_url = next_url
            current_params = None

        raise BrowserOperationError("fetch", "Redirect processing failed")

    async def _request_once(
        self,
        selected_backend: str,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]],
        params: Optional[Dict[str, Any]],
        body: Optional[Any],
        json_body: Optional[Any],
        timeout: int,
        cookies: Optional[List[Dict[str, Any]]],
        impersonate: Optional[str],
        browser_context: Optional[Any],
    ) -> Dict[str, Any]:
        if selected_backend == FetchBackend.BROWSER.value:
            return await self._request_browser_context(
                browser_context, method, url, headers, params, body, json_body, timeout
            )
        if selected_backend == FetchBackend.CURL_CFFI.value:
            return await self._request_curl_cffi(
                method, url, headers, params, body, json_body, timeout, cookies, impersonate
            )
        if selected_backend == FetchBackend.CLOUDSCRAPER.value:
            return await self._request_cloudscraper(
                method, url, headers, params, body, json_body, timeout, cookies
            )
        return await self._request_httpx(
            method, url, headers, params, body, json_body, timeout, cookies
        )

    def _select_backend(self, backend: str) -> str:
        if backend == FetchBackend.AUTO.value:
            try:
                import curl_cffi  # noqa: F401
                return FetchBackend.CURL_CFFI.value
            except ImportError:
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
            timeout=timeout,
            max_redirects=0,
        )
        self._enforce_content_length(response.headers)
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

        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout / 1000) as client:
            async with client.stream(
                method.upper(),
                url,
                headers=headers,
                params=params,
                content=body,
                json=json_body,
                cookies=self._cookie_dict(cookies)
            ) as response:
                self._enforce_content_length(response.headers)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    self._extend_limited(content, chunk)
                return self._format_response(
                    response.status_code,
                    str(response.url),
                    response.headers,
                    bytes(content),
                )

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

        content = bytearray()

        def collect(chunk: bytes) -> None:
            self._extend_limited(content, chunk)

        async with AsyncSession(impersonate=impersonate or "chrome", timeout=timeout / 1000) as session:
            response = await session.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                data=body,
                json=json_body,
                cookies=self._cookie_dict(cookies),
                allow_redirects=False,
                content_callback=collect,
            )
            self._enforce_content_length(response.headers)
            return self._format_response(response.status_code, response.url, response.headers, bytes(content))

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
                allow_redirects=False,
                stream=True,
            )
            self._enforce_content_length(response.headers)
            content = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    self._extend_limited(content, chunk)
            return self._format_response(response.status_code, response.url, response.headers, bytes(content))

        return await asyncio.to_thread(run_request)

    def _format_response(self, status: int, url: str, headers: Any, content: Any) -> Dict[str, Any]:
        from config import get_settings

        raw = content if isinstance(content, bytes) else str(content).encode("utf-8", errors="replace")
        limit = get_settings().max_response_size
        if len(raw) > limit:
            raise ResourceLimitError("response_bytes", limit, len(raw))
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
            if len(raw) <= get_settings().max_json_parse_size:
                data["json"] = json.loads(text)
            else:
                data["json"] = None
        except Exception:
            data["json"] = None
        return data

    def _enforce_content_length(self, headers: Any) -> None:
        from config import get_settings

        value = self._header(dict(headers), "content-length")
        if not value:
            return
        try:
            length = int(value)
        except (TypeError, ValueError):
            return
        limit = get_settings().max_response_size
        if length > limit:
            raise ResourceLimitError("response_bytes", limit, length)

    def _extend_limited(self, content: bytearray, chunk: bytes) -> None:
        from config import get_settings

        limit = get_settings().max_response_size
        projected = len(content) + len(chunk)
        if projected > limit:
            raise ResourceLimitError("response_bytes", limit, projected)
        content.extend(chunk)

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

    @staticmethod
    def _header(headers: Dict[str, Any], name: str) -> Optional[str]:
        needle = name.lower()
        for key, value in headers.items():
            if str(key).lower() == needle:
                return str(value)
        return None

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int]:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        port = parsed.port or (443 if scheme == "https" else 80)
        return scheme, (parsed.hostname or "").lower().rstrip("."), port

    @staticmethod
    def _without_sensitive_headers(headers: Dict[str, str]) -> Dict[str, str]:
        sensitive = {"authorization", "proxy-authorization", "cookie"}
        return {key: value for key, value in headers.items() if key.lower() not in sensitive}

    def _response_warnings(self, status: Optional[int]) -> List[str]:
        if status in (401, 403):
            return ["Authentication or access challenge likely; browser mode may be required."]
        if status == 429:
            return ["Rate limit response detected; back off before retrying."]
        if status and status >= 500:
            return ["Server error response detected; retry conservatively."]
        return []
