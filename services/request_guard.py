"""Request guard — pattern-based denylist for search queries and target URLs.

Loaded from config/request_guard.yaml at first use.  The guard is intentionally
conservative: it blocks clear-cut harmful acquisition or CSAM requests without
tripping on security research, CVE analysis, or general infosec vocabulary.

Structure is designed so a smarter classifier can replace ``_matches`` later
without touching callers.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import List, NamedTuple, Optional

import yaml
from fastapi import HTTPException, status
from utils.url_security import safe_url_for_log

logger = logging.getLogger(__name__)

_GUARD_YAML = Path(__file__).parent.parent / "config" / "request_guard.yaml"


class _Rule(NamedTuple):
    category: str
    kind: str  # "query" | "url" | "both"
    reason: str
    compiled: List[re.Pattern]


class RequestGuard:
    """Singleton guard that checks content against the compiled rule set.

    Raises ``HTTPException(403)`` when a rule fires.
    """

    def __init__(self, yaml_path: Optional[Path] = None) -> None:
        self._rules: List[_Rule] = []
        self._load(yaml_path or _GUARD_YAML)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning("request_guard.yaml not found at %s — guard disabled", path)
            return
        with path.open() as fh:
            cfg = yaml.safe_load(fh) or {}
        for cat in cfg.get("categories", []):
            compiled = [
                re.compile(p, re.IGNORECASE) for p in cat.get("patterns", [])
            ]
            self._rules.append(
                _Rule(
                    category=cat.get("category", "unknown"),
                    kind=cat.get("kind", "both"),
                    reason=cat.get("reason", "Blocked by request guard"),
                    compiled=compiled,
                )
            )
        logger.debug("request_guard loaded %d rules from %s", len(self._rules), path)

    # ------------------------------------------------------------------
    # Internal matching (replaceable by a classifier later)
    # ------------------------------------------------------------------

    def _matches(self, content: str, kind: str) -> Optional[str]:
        """Return the block reason string if content matches a rule, else None.

        *kind* is either ``"query"`` or ``"url"``.
        """
        for rule in self._rules:
            if rule.kind != "both" and rule.kind != kind:
                continue
            for pattern in rule.compiled:
                if pattern.search(content):
                    return rule.reason
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_query(self, query: str) -> None:
        """Raise HTTP 403 if *query* matches a denylist rule."""
        reason = self._matches(query, "query")
        if reason:
            logger.warning("request_guard blocked query reason=%r", reason)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=reason,
            )

    def check_url(self, url: str) -> None:
        """Raise HTTP 403 if *url* matches a denylist rule."""
        reason = self._matches(url, "url")
        if reason:
            logger.warning(
                "request_guard blocked url reason=%r url=%r",
                reason,
                safe_url_for_log(url),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=reason,
            )

    def check_urls(self, urls: List[str]) -> None:
        """Raise HTTP 403 if any URL in *urls* matches a denylist rule."""
        for url in urls:
            self.check_url(url)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_guard: Optional[RequestGuard] = None


def get_guard(yaml_path: Optional[Path] = None) -> RequestGuard:
    """Return the module-level ``RequestGuard`` singleton."""
    global _guard
    if _guard is None:
        _guard = RequestGuard(yaml_path)
    return _guard
