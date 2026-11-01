"""Search provider abstraction: Exa primary, SearXNG fallback.

Exa runs in one of two modes: the REST API when ``SURF_EXA_API_KEY`` is set,
or Exa's free hosted MCP endpoint when it is not (``SURF_EXA_KEYLESS_ENABLED``).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx
import structlog

from config import get_settings
from core.foundation import ResourceLimitError
from services.searxng_runtime import ensure_searxng
from utils.text import clean_text as _clean_text

logger = structlog.get_logger()
settings = get_settings()


async def _bounded_json_request(
    method: str,
    url: str,
    *,
    timeout: float,
    **request_kwargs: Any,
) -> Dict[str, Any]:
    """Read provider JSON incrementally under the configured parse budget.

    Uses ``aiter_bytes()`` so httpx decompresses Content-Encoding for us.
    Do not rebuild an ``httpx.Response`` with the original encoding headers —
    that re-applies gzip/deflate to already-decoded bytes and breaks Exa
    (Content-Encoding: gzip + chunked).
    """
    limit = get_settings().max_json_parse_size
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(method, url, **request_kwargs) as response:
            declared = response.headers.get("content-length")
            if declared:
                try:
                    declared_size = int(declared)
                except ValueError:
                    declared_size = 0
                if declared_size > limit:
                    raise ResourceLimitError("provider_response_bytes", limit, declared_size)

            content = bytearray()
            async for chunk in response.aiter_bytes():
                projected = len(content) + len(chunk)
                if projected > limit:
                    raise ResourceLimitError("provider_response_bytes", limit, projected)
                content.extend(chunk)

            # raise_for_status on the stream response after the body is read so
            # HTTPStatusError can still expose response content when needed.
            response.raise_for_status()
            data = json.loads(bytes(content))
            if not isinstance(data, dict):
                raise ValueError("Search provider returned a non-object JSON response")
            return data


class SearchProvider(ABC):
    """Abstract base for a web-search backend."""

    name: str = "abstract"

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 10,
        *,
        engines: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        language: str = "en",
        time_range: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return a normalized search response.

        Response shape:
        {
            "success": bool,
            "provider": str,
            "results": List[{title, snippet, url, source, published?}],
            "ms": int,
            "cost": Optional[float],
            "error": Optional[str],
            "metadata": Dict[str, Any],
        }
        """
        ...


# Exa mode is fixed to "auto" — evaluation showed the best cost/latency/quality
# trade-off. instant/fast/deep/deep-lite/deep-reasoning are intentionally not
# exposed; deep modes also pull full page text and cost more per query.
EXA_SEARCH_MODE = "auto"


class ExaSearchProvider(SearchProvider):
    """
    Exa (https://exa.ai) neural search provider.

    Uses mode=auto with highlights contents (see EXA_SEARCH_MODE comment).
    """

    name = "exa"

    def __init__(self) -> None:
        self._api_key = settings.exa_api_key or None
        self._base_url = (settings.exa_base_url or "https://api.exa.ai").rstrip("/")
        self._timeout = settings.exa_timeout or 30
        self._default_num_results = settings.exa_num_results or 10
        self._contents = self._build_contents_config()

    def _build_contents_config(self) -> Dict[str, Any]:
        """Use highlights by default; allow text/summary only via explicit settings."""
        cfg: Dict[str, Any] = {}
        if settings.exa_contents_highlights:
            cfg["highlights"] = True
        elif settings.exa_contents_text:
            cfg["text"] = True
        elif settings.exa_contents_summary:
            cfg["summary"] = True
        else:
            cfg["highlights"] = True
        return cfg

    def _normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert an Exa result record into the common SURF shape."""
        highlights = raw.get("highlights") or []
        text = raw.get("text") or ""
        summary = raw.get("summary") or ""
        snippet = (
            " ".join(str(h) for h in highlights) if highlights else (text or summary)
        )
        return {
            "title": _clean_text(str(raw.get("title") or "")),
            "snippet": _clean_text(snippet),
            "url": str(raw.get("url") or ""),
            "source": "exa",
            "published": raw.get("publishedDate"),
            "score": raw.get("score"),
            "id": raw.get("id"),
        }

    async def search(
        self,
        query: str,
        max_results: int = 10,
        *,
        engines: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        language: str = "en",
        time_range: Optional[str] = None,
        mode: Optional[str] = None,  # ignored; Exa always uses EXA_SEARCH_MODE
    ) -> Dict[str, Any]:
        if not self._api_key and not settings.exa_keyless_enabled:
            return {
                "success": False,
                "provider": self.name,
                "results": [],
                "ms": 0,
                "cost": None,
                "error": "SURF_EXA_API_KEY is not set and keyless Exa is disabled",
                "metadata": {},
            }

        unsupported = {
            name: value
            for name, value in {
                "engines": engines,
                "categories": categories,
                "time_range": time_range,
            }.items()
            if value
        }
        if unsupported:
            return {
                "success": False,
                "provider": self.name,
                "results": [],
                "ms": 0,
                "cost": None,
                "error": "Exa does not support the requested provider-specific constraints",
                "metadata": {"unsupported_constraints": sorted(unsupported)},
            }

        # Respect the caller's output ceiling while retaining a provider-side cap.
        num_results = max(1, min(max_results, self._default_num_results))
        if not self._api_key:
            return await self._search_keyless(query, num_results)

        payload: Dict[str, Any] = {
            "query": query,
            "type": EXA_SEARCH_MODE,
            "numResults": num_results,
            "contents": self._contents,
        }
        if language:
            payload["language"] = language

        t0 = time.monotonic()
        try:
            data = await _bounded_json_request(
                "POST",
                f"{self._base_url}/search",
                timeout=self._timeout,
                json=payload,
                headers={
                    "x-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPStatusError as exc:
            ms = int((time.monotonic() - t0) * 1000)
            error = (
                f"Exa returned {exc.response.status_code}: {exc.response.text[:200]}"
            )
            logger.warning(
                "exa_search_http_error", status=exc.response.status_code, error=str(exc)
            )
            return {
                "success": False,
                "provider": self.name,
                "results": [],
                "ms": ms,
                "cost": None,
                "error": error,
                "metadata": {"mode": EXA_SEARCH_MODE},
            }
        except Exception as exc:
            ms = int((time.monotonic() - t0) * 1000)
            logger.warning("exa_search_failed", error=str(exc))
            return {
                "success": False,
                "provider": self.name,
                "results": [],
                "ms": ms,
                "cost": None,
                "error": str(exc),
                "metadata": {"mode": EXA_SEARCH_MODE},
            }

        raw_results = data.get("results", [])
        results = [self._normalize(r) for r in raw_results]
        ms = int((time.monotonic() - t0) * 1000)
        cost = data.get("costDollars")
        autopilot = data.get("autopilotMode")

        logger.info(
            "exa_search_ok",
            query=query,
            mode=EXA_SEARCH_MODE,
            results=len(results),
            ms=ms,
            cost=cost,
            autopilot=autopilot,
        )

        return {
            "success": True,
            "provider": self.name,
            "results": results,
            "ms": ms,
            "cost": cost,
            "error": None,
            "metadata": {
                "mode": EXA_SEARCH_MODE,
                "autopilot_mode": autopilot,
                "requested_num_results": num_results,
            },
        }


    @property
    def mode(self) -> str:
        if self._api_key:
            return "api"
        return "keyless_mcp" if settings.exa_keyless_enabled else "disabled"

    async def _search_keyless(self, query: str, num_results: int) -> Dict[str, Any]:
        """Search through Exa's hosted MCP server (no API key, rate-limited)."""
        t0 = time.monotonic()
        metadata: Dict[str, Any] = {"mode": "keyless_mcp", "requested_num_results": num_results}

        def failure(error: str) -> Dict[str, Any]:
            logger.warning("exa_keyless_search_failed", error=error)
            return {
                "success": False,
                "provider": self.name,
                "results": [],
                "ms": int((time.monotonic() - t0) * 1000),
                "cost": None,
                "error": error,
                "metadata": metadata,
            }

        try:
            text = await _exa_mcp_call_with_retry(
                settings.exa_mcp_url,
                "web_search_exa",
                {"query": query, "numResults": num_results},
                timeout=self._timeout,
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            hint = " (free keyless tier is rate-limited; set SURF_EXA_API_KEY)" if status_code == 429 else ""
            return failure(f"Exa MCP returned {status_code}{hint}")
        except Exception as exc:
            return failure(f"Exa MCP request failed: {exc}")

        results = parse_exa_mcp_results(text)[:num_results]
        ms = int((time.monotonic() - t0) * 1000)
        if not results:
            return failure("Exa MCP returned no parseable results")
        logger.info("exa_keyless_search_ok", query=query, results=len(results), ms=ms)
        return {
            "success": True,
            "provider": self.name,
            "results": results,
            "ms": ms,
            "cost": None,
            "error": None,
            "metadata": metadata,
        }


# The free endpoint rate-limits bursts, so keyless calls are queued and 429s
# are retried with backoff. Created lazily to bind to the running event loop.
_EXA_KEYLESS_CONCURRENCY = 2
_EXA_KEYLESS_RETRIES = 3
_exa_keyless_gate: Optional[asyncio.Semaphore] = None


async def _exa_mcp_call_with_retry(
    url: str, tool: str, arguments: Dict[str, Any], *, timeout: float
) -> str:
    global _exa_keyless_gate
    if _exa_keyless_gate is None:
        _exa_keyless_gate = asyncio.Semaphore(_EXA_KEYLESS_CONCURRENCY)
    async with _exa_keyless_gate:
        for attempt in range(_EXA_KEYLESS_RETRIES + 1):
            try:
                return await _exa_mcp_call(url, tool, arguments, timeout=timeout)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429 or attempt == _EXA_KEYLESS_RETRIES:
                    raise
                retry_after = exc.response.headers.get("retry-after", "")
                delay = float(retry_after) if retry_after.isdigit() else 1.0 * 2**attempt
                logger.info("exa_keyless_rate_limited", attempt=attempt + 1, delay=delay)
                await asyncio.sleep(min(delay, 8.0))
    raise RuntimeError("unreachable")


async def _exa_mcp_call(
    url: str, tool: str, arguments: Dict[str, Any], *, timeout: float
) -> str:
    """Call one tool on a stateless Streamable HTTP MCP server; return its text."""
    limit = get_settings().max_json_parse_size
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > limit:
                    raise ResourceLimitError("provider_response_bytes", limit, len(body) + len(chunk))
                body.extend(chunk)
            response.raise_for_status()

    raw = bytes(body).decode("utf-8", errors="replace")
    message: Optional[Dict[str, Any]] = None
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                candidate = json.loads(line[5:].strip())
                if isinstance(candidate, dict) and ("result" in candidate or "error" in candidate):
                    message = candidate
    else:
        message = json.loads(raw)
    if not isinstance(message, dict):
        raise ValueError("no JSON-RPC response in Exa MCP stream")
    if message.get("error"):
        err = message["error"]
        raise ValueError(err.get("message") if isinstance(err, dict) else str(err))
    result = message.get("result") or {}
    text = "\n".join(
        part.get("text", "")
        for part in result.get("content", [])
        if isinstance(part, dict) and part.get("type") == "text"
    )
    if result.get("isError"):
        raise ValueError(text[:200] or "Exa MCP tool error")
    return text


_EXA_MCP_FIELD = re.compile(r"^(Title|URL|Published|Author):[ \t]*(.*)$", re.M)


def parse_exa_mcp_results(text: str) -> List[Dict[str, Any]]:
    """Parse Exa MCP's ``Title:/URL:/Highlights:`` blocks into SURF results."""
    results: List[Dict[str, Any]] = []
    for block in re.split(r"\n-{3,}\n(?=\s*Title:)", text):
        head, _, highlights = block.partition("Highlights:")
        fields = {key: value.strip() for key, value in _EXA_MCP_FIELD.findall(head)}
        url = fields.get("URL", "")
        if not url.startswith(("http://", "https://")):
            continue
        published = fields.get("Published")
        results.append(
            {
                "title": _clean_text(fields.get("Title", "")),
                "snippet": _clean_text(highlights.strip()),
                "url": url,
                "source": "exa",
                "published": None if published in (None, "", "N/A") else published,
            }
        )
    return results


class SearXNGSearchProvider(SearchProvider):
    """
    SearXNG metasearch provider. Preserves the original SURF autowake + retry
    behaviour and returns results in the common normalized shape.
    """

    name = "searxng"

    def __init__(self) -> None:
        self._base_url = settings.searxng_base_url or "http://localhost:8888"
        self._timeout = settings.searxng_timeout or 10

    def _normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "title": _clean_text(str(raw.get("title") or "")),
            "snippet": _clean_text(str(raw.get("content") or "")),
            "url": str(raw.get("url") or ""),
            "source": raw.get("engine") or "searxng",
            "published": raw.get("publishedDate"),
        }

    async def search(
        self,
        query: str,
        max_results: int = 10,
        *,
        engines: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        language: str = "en",
        time_range: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"q": query, "format": "json", "language": language}
        if engines:
            params["engines"] = ",".join(engines)
        elif settings.searxng_engines:
            params["engines"] = ",".join(settings.searxng_engines)
        if categories:
            params["categories"] = ",".join(categories)
        if time_range:
            params["time_range"] = time_range

        t0 = time.monotonic()
        data: Optional[Dict[str, Any]] = None
        last_error: Optional[str] = None
        wake_info: Optional[Dict[str, Any]] = None

        try:
            data = await self._fetch(params)
        except httpx.ConnectError:
            if not settings.searxng_autowake_enabled:
                last_error = f"Cannot reach SearXNG at {self._base_url}"
            else:
                wake_info = await ensure_searxng()
                if wake_info.get("status") == "ready":
                    try:
                        data = await self._fetch(params)
                    except httpx.ConnectError:
                        wake_info = await ensure_searxng(force=True)
                        if wake_info.get("status") == "ready":
                            try:
                                data = await self._fetch(params)
                            except httpx.ConnectError:
                                last_error = f"Cannot reach SearXNG at {self._base_url} after autowake"
                        else:
                            last_error = f"Cannot reach SearXNG at {self._base_url}"
                else:
                    last_error = f"Cannot reach SearXNG at {self._base_url}"
        except httpx.HTTPStatusError as exc:
            last_error = f"SearXNG returned {exc.response.status_code}"
        except Exception as exc:
            last_error = str(exc)

        ms = int((time.monotonic() - t0) * 1000)

        if data is None:
            logger.warning("searxng_search_failed", error=last_error, ms=ms)
            return {
                "success": False,
                "provider": self.name,
                "results": [],
                "ms": ms,
                "cost": None,
                "error": last_error or "Unknown SearXNG error",
                "metadata": {"wake": wake_info},
            }

        raw_results = data.get("results", [])
        results = [self._normalize(r) for r in raw_results]
        logger.info("searxng_search_ok", query=query, results=len(results), ms=ms)

        return {
            "success": True,
            "provider": self.name,
            "results": results,
            "ms": ms,
            "cost": None,
            "error": None,
            "metadata": {"wake": wake_info},
        }

    async def _fetch(self, params: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"X-Forwarded-For": "127.0.0.1"}
        return await _bounded_json_request(
            "GET",
            f"{self._base_url}/search",
            timeout=self._timeout,
            params=params,
            headers=headers,
        )


class SearchProviderRegistry:
    """Simple registry that creates providers on demand."""

    def __init__(self) -> None:
        self._providers: Dict[str, SearchProvider] = {}

    def get(self, name: str) -> Optional[SearchProvider]:
        if name not in self._providers:
            if name == "exa":
                self._providers[name] = ExaSearchProvider()
            elif name == "searxng":
                self._providers[name] = SearXNGSearchProvider()
        return self._providers.get(name)

    def primary(self) -> Optional[SearchProvider]:
        primary = (settings.search_provider or "exa").lower()
        return self.get(primary)

    def fallback(self) -> Optional[SearchProvider]:
        fallback = (settings.search_fallback_provider or "searxng").lower()
        if fallback == (settings.search_provider or "exa").lower():
            return None
        return self.get(fallback)

    def all_configured(self) -> List[SearchProvider]:
        providers: List[SearchProvider] = []
        primary = self.primary()
        fallback = self.fallback()
        if primary:
            providers.append(primary)
        if fallback:
            providers.append(fallback)
        return providers
