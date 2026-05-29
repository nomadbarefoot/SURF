"""Adblock-backed request blocking for SURF browser sessions."""
import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import structlog

from config.settings import settings

logger = structlog.get_logger()


FALLBACK_FILTERS = [
    "||doubleclick.net^",
    "||googlesyndication.com^",
    "||google-analytics.com^",
    "||googletagmanager.com^",
    "||facebook.com/tr^",
    "||adsystem.com^",
    "||adservice.google.com^",
    "||analytics.google.com^",
]

COMMON_TWO_PART_PUBLIC_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk",
    "co.in", "firm.in", "net.in", "org.in", "gen.in", "ind.in",
    "com.au", "net.au", "org.au",
    "com.br", "com.cn", "com.sg", "co.jp", "co.kr", "co.nz", "co.za"
}


class AdblockService:
    """Small wrapper around the Brave/adblock-rust Python bindings."""

    def __init__(self) -> None:
        self.engine = None
        self.available = False
        self.loaded_filters = 0
        self.filter_sources: List[str] = []

    async def initialize(self) -> None:
        """Initialize the blocking engine from cached or downloaded lists."""
        try:
            import adblock

            filters = await self._load_filters()
            filter_set = adblock.FilterSet(False)
            filter_set.add_filters(filters)
            self.engine = adblock.Engine(filter_set, True)
            self.available = True
            self.loaded_filters = len(filters)
            logger.info("Adblock service initialized", filters=self.loaded_filters)
        except Exception as e:
            self.engine = None
            self.available = False
            self.loaded_filters = 0
            logger.warning("Adblock service unavailable; falling back to resource blocking", error=str(e))

    async def _load_filters(self) -> List[str]:
        filters: List[str] = []
        cache_dir = self._path(settings.adblock_cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        for url in settings.adblock_filter_urls:
            cache_path = cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.txt"
            text = None
            if self._cache_fresh(cache_path):
                text = cache_path.read_text(encoding="utf-8", errors="ignore")
            else:
                text = await self._download_filter_list(url)
                if text:
                    cache_path.write_text(text, encoding="utf-8")
            if text:
                self.filter_sources.append(url)
                filters.extend(self._filter_lines(text))

        if not filters:
            self.filter_sources.append("fallback")
            filters.extend(FALLBACK_FILTERS)
        return filters

    async def _download_filter_list(self, url: str) -> Optional[str]:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.warning("Filter list download failed", url=url, error=str(e))
            return None

    def should_block(self, url: str, source_url: str, resource_type: str, mode: str) -> Dict[str, Any]:
        """Return a blocking decision for a request."""
        mode = mode or "off"
        if mode == "off":
            return {"blocked": False, "reason": "off"}

        resource_type = resource_type or "other"
        if resource_type in self._resource_blocks_for_mode(mode):
            return {"blocked": True, "reason": "resource_type", "filter": resource_type}

        if not self.engine:
            return {"blocked": False, "reason": "engine_unavailable"}

        if mode == "conservative" and self._protected_conservative_request(url, source_url, resource_type):
            return {"blocked": False, "reason": "protected_request"}

        try:
            result = self.engine.check_network_urls(url, source_url or url, resource_type)
            if getattr(result, "matched", False):
                return {
                    "blocked": True,
                    "reason": "filter",
                    "filter": getattr(result, "filter", None) or "network_filter"
                }
            return {"blocked": False, "reason": "no_match"}
        except Exception as e:
            logger.debug("Adblock decision failed", url=url, error=str(e))
            return {"blocked": False, "reason": "error", "error": str(e)}

    def stats(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "loaded_filters": self.loaded_filters,
            "filter_sources": self.filter_sources,
        }

    def _resource_blocks_for_mode(self, mode: str) -> set:
        if mode == "token_saver":
            return {"image", "media", "font"}
        if mode == "conservative":
            return {"media", "font"}
        return set()

    def _protected_conservative_request(self, url: str, source_url: str, resource_type: str) -> bool:
        if resource_type in {"document", "xhr", "fetch", "websocket", "eventsource"}:
            return True
        if resource_type in {"script", "stylesheet"} and self._same_site(url, source_url):
            return True
        return False

    def _same_site(self, url: str, source_url: str) -> bool:
        return self._site(url) == self._site(source_url)

    def _site(self, url: str) -> str:
        host = urlparse(url).hostname or ""
        parts = host.split(".")
        if len(parts) >= 3 and ".".join(parts[-2:]) in COMMON_TWO_PART_PUBLIC_SUFFIXES:
            return ".".join(parts[-3:])
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host

    def _filter_lines(self, text: str) -> List[str]:
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.startswith("!") and not line.startswith("[")
        ]

    def _cache_fresh(self, path: Path) -> bool:
        return path.exists() and (time.time() - path.stat().st_mtime) < settings.adblock_cache_ttl_seconds

    def _path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = Path(__file__).parent.parent / path
        return path
