"""Injectable sticky proxy pool for SURF browser contexts.

A context gets one proxy at launch and keeps it for its lifetime. Rotation
happens only after classified transport/proxy failures within the configured
budget. Credentials are expanded from environment variables and redacted in
logs.
"""
from __future__ import annotations

import os
import re
import time
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import structlog
import yaml

from config import get_settings

logger = structlog.get_logger()


class ProxyError(Exception):
    """Raised when a proxy configuration or operation is invalid."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class StickyProxyPool:
    """Sticky proxy selection and rotation manager."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._default_config_path()
        self._entries: List[Dict[str, Any]] = []
        self._max_failures = 3
        self._reset_interval_seconds = 3600
        self._allow_private = False
        self._loaded = False
        self._assignments: Dict[str, Dict[str, Any]] = {}
        self._failure_counts: Dict[str, int] = {}
        self._last_failure_time: Dict[str, float] = {}
        self._success_counts: Dict[str, int] = {}

    @staticmethod
    def _default_config_path() -> str:
        base = Path(__file__).parent.parent
        return str(base / "config" / "proxy_config.yaml")

    def load(self) -> None:
        """Load proxy configuration from disk."""
        if self._loaded:
            return
        path = Path(self.config_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            except Exception as exc:
                logger.error("Failed to load proxy config", path=str(path), error=str(exc))
                raw = {}
        else:
            logger.warning("Proxy config not found, running without proxies", path=str(path))
            raw = {}

        rotation = raw.get("rotation", {})
        self._max_failures = int(rotation.get("max_failures", 3))
        self._reset_interval_seconds = int(rotation.get("reset_interval", 3600))
        self._allow_private = bool(raw.get("allow_private_proxies", False))

        self._entries = []
        for entry in raw.get("proxies", []) or []:
            expanded = self._expand_and_validate(entry)
            if expanded:
                self._entries.append(expanded)

        self._loaded = True

    def reload(self) -> None:
        """Force reload from disk."""
        self._loaded = False
        self._entries = []
        self._assignments = {}
        self._failure_counts = {}
        self._last_failure_time = {}
        self._success_counts = {}
        self.load()

    def assign(self, context_id: str) -> Optional[Dict[str, Any]]:
        """Assign a proxy to a context and return its options."""
        self.load()
        if not self._entries:
            return None

        # If this context already has a sticky assignment, reuse it unless it
        # has been marked failed.
        existing = self._assignments.get(context_id)
        if existing and self._failure_counts.get(existing["_entry_id"], 0) < self._max_failures:
            return self._to_context_options(existing)

        # Pick the entry with the lowest failure count, then most recent success.
        candidates = sorted(
            self._entries,
            key=lambda e: (
                self._failure_counts.get(e["_entry_id"], 0),
                -self._success_counts.get(e["_entry_id"], 0),
                self._failure_counts.get(e["_entry_id"], 0),
            ),
        )
        chosen = candidates[0]
        self._assignments[context_id] = chosen
        logger.info(
            "proxy_assigned",
            context_id=context_id,
            server=chosen["redacted_server"],
        )
        return self._to_context_options(chosen)

    def release(self, context_id: str) -> None:
        """Release a context's sticky assignment."""
        self._assignments.pop(context_id, None)

    def report_success(self, context_id: str) -> None:
        entry = self._assignments.get(context_id)
        if not entry:
            return
        entry_id = entry["_entry_id"]
        self._success_counts[entry_id] = self._success_counts.get(entry_id, 0) + 1
        # Decay failures on success.
        if self._failure_counts.get(entry_id, 0) > 0:
            self._failure_counts[entry_id] -= 1

    def report_failure(self, context_id: str, reason: str) -> None:
        """Report a failure. Rotate only on transport/proxy-classified reasons."""
        entry = self._assignments.get(context_id)
        if not entry:
            return
        entry_id = entry["_entry_id"]
        self._failure_counts[entry_id] = self._failure_counts.get(entry_id, 0) + 1
        self._last_failure_time[entry_id] = time.time()

        if self._is_proxy_failure(reason):
            logger.warning(
                "proxy_failure_recorded",
                context_id=context_id,
                server=entry["redacted_server"],
                reason=reason,
                failures=self._failure_counts[entry_id],
            )
            if self._failure_counts[entry_id] >= self._max_failures:
                logger.warning(
                    "proxy_marked_failed",
                    context_id=context_id,
                    server=entry["redacted_server"],
                )
                self._assignments.pop(context_id, None)
        else:
            logger.debug(
                "proxy_failure_not_rotated",
                context_id=context_id,
                reason=reason,
            )

    def stats(self) -> Dict[str, Any]:
        """Return redacted proxy pool statistics."""
        self.load()
        return {
            "total_entries": len(self._entries),
            "active_assignments": len(self._assignments),
            "entries": [
                {
                    "server": entry["redacted_server"],
                    "failures": self._failure_counts.get(entry["_entry_id"], 0),
                    "successes": self._success_counts.get(entry["_entry_id"], 0),
                }
                for entry in self._entries
            ],
        }

    def _expand_and_validate(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        server = self._expand_env(entry.get("server", ""))
        username = self._expand_env(entry.get("username", ""))
        password = self._expand_env(entry.get("password", ""))
        protocol = self._expand_env(entry.get("protocol", "http")).lower() or "http"

        if not server:
            return None

        parsed = urlparse(server)
        if parsed.scheme not in {"http", "https", "socks5"}:
            if not parsed.scheme:
                parsed = urlparse(f"{protocol}://{server}")
            else:
                logger.warning("Invalid proxy protocol", server=server)
                return None

        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            logger.warning("Invalid proxy server", server=server)
            return None

        try:
            addr = ip_address(host)
            if not self._allow_private and (addr.is_private or addr.is_loopback):
                logger.warning("Rejecting private/loopback proxy", host=host)
                return None
        except ValueError:
            # Hostname: allow unless it resolves to a private address; that
            # check is the responsibility of OutboundPolicy at connection time.
            pass

        full_server = f"{parsed.scheme}://{host}:{port}"
        entry_id = f"{parsed.scheme}://{host}:{port}"
        redacted = full_server
        if username:
            redacted = f"{parsed.scheme}://{username}:****@{host}:{port}"

        return {
            "_entry_id": entry_id,
            "server": full_server,
            "redacted_server": redacted,
            "username": username,
            "password": password,
            "protocol": parsed.scheme,
        }

    @staticmethod
    def _expand_env(value: Any) -> Any:
        if not isinstance(value, str):
            return value

        def replacer(match: re.Match) -> str:
            inner = match.group(1)
            if ":-" in inner:
                var, default = inner.split(":-", 1)
                return os.getenv(var, default)
            return os.getenv(inner, "")

        return re.sub(r"\$\{([^}]+)\}", replacer, value)

    @staticmethod
    def _to_context_options(entry: Dict[str, Any]) -> Dict[str, Any]:
        options: Dict[str, Any] = {"server": entry["server"]}
        if entry.get("username"):
            options["username"] = entry["username"]
        if entry.get("password"):
            options["password"] = entry["password"]
        return options

    @staticmethod
    def _is_proxy_failure(reason: str) -> bool:
        lower = reason.lower()
        proxy_reasons = (
            "proxy",
            "tunnel",
            "econnrefused",
            "enetunreach",
            "etimedout",
            "timeout",
            "connection refused",
            "connect",
            "socks",
        )
        return any(token in lower for token in proxy_reasons)


# Global singleton for legacy / module-level access.
_pool: Optional[StickyProxyPool] = None


def get_proxy_pool() -> StickyProxyPool:
    """Return the global sticky proxy pool, loading it on first use."""
    global _pool
    if _pool is None:
        _pool = StickyProxyPool()
        _pool.load()
    return _pool


def reset_proxy_pool() -> None:
    """Reset the global pool, mainly for tests."""
    global _pool
    _pool = None


# Legacy compatibility functions.
def load_proxy_config(config_path: str = "config/proxy_config.yaml") -> Dict[str, Any]:
    pool = StickyProxyPool(config_path)
    pool.load()
    return {
        "proxies": [e["server"] for e in pool._entries],
        "rotation": {
            "max_failures": pool._max_failures,
            "reset_interval": pool._reset_interval_seconds,
        },
    }


def initialize_proxies(config_path: str = "config/proxy_config.yaml") -> bool:
    pool = get_proxy_pool()
    if config_path != pool.config_path:
        pool = StickyProxyPool(config_path)
        pool.load()
        global _pool
        _pool = pool
    return len(pool._entries) > 0


def get_proxy_for_request() -> Optional[Dict[str, Any]]:
    """Legacy: return a proxy for the current request without stickiness."""
    pool = get_proxy_pool()
    # Use a synthetic context id.
    return pool.assign(context_id=f"legacy_{id(pool)}")


def mark_proxy_success(proxy_index: int) -> None:
    logger.debug("mark_proxy_success is deprecated; use StickyProxyPool.report_success")


def mark_proxy_failure(proxy_index: int) -> None:
    logger.debug("mark_proxy_failure is deprecated; use StickyProxyPool.report_failure")


def get_proxy_stats() -> Dict[str, Any]:
    return get_proxy_pool().stats()
