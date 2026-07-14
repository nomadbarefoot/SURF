"""Search provider abstraction: Exa primary, SearXNG fallback."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx
import structlog

from config import get_settings
from services.searxng_runtime import ensure_searxng
from utils.text import clean_text as _clean_text

logger = structlog.get_logger()
settings = get_settings()


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
        if not self._api_key:
            return {
                "success": False,
                "provider": self.name,
                "results": [],
                "ms": 0,
                "cost": None,
                "error": "SURF_EXA_API_KEY is not set",
                "metadata": {},
            }

        # Fetch the full provider pool regardless of the caller's output size;
        # trimming to max_results is the ETL layer's job (_finalize_results).
        num_results = max(1, self._default_num_results)

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
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/search",
                    json=payload,
                    headers={
                        "x-api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
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
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/search", params=params, headers=headers
            )
            resp.raise_for_status()
            return resp.json()


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
