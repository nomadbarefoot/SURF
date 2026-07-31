"""Browser profile resolution for named modes and site-specific rules.

Clients may request a mode by name (standard, resilient, interactive,
aggressive). Arbitrary per-request proxy, patch, or fingerprint overrides are
rejected. Site rules and environment gates are applied here.
"""
from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import structlog
import yaml

from config import get_settings
from core.foundation import ConfigurationError
from models.schemas import StealthStrategy

logger = structlog.get_logger()

BUILTIN_MODES = {"standard", "resilient", "interactive", "aggressive"}


@dataclass
class ResolvedProfile:
    """Resolved profile ready to apply to a SessionConfig."""

    mode: str
    session_overrides: Dict[str, Any]
    challenge_ladder: Dict[str, Any]
    human_behavior: Dict[str, Any]
    proxy_mode: str
    proxy_entry: Optional[Dict[str, Any]] = None
    warnings: Optional[List[str]] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class BrowserProfileService:
    """Load browser_profiles.yaml and resolve modes to concrete settings."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._default_config_path()
        self._raw: Dict[str, Any] = {}
        self._modes: Dict[str, Dict[str, Any]] = {}
        self._sites: List[Dict[str, Any]] = []
        self._proxy_pool: List[Dict[str, Any]] = []
        self._proxy_cursor = 0
        self.default_mode = "standard"
        self._loaded = False

    @staticmethod
    def _default_config_path() -> str:
        base = Path(__file__).parent.parent
        return str(base / "config" / "browser_profiles.yaml")

    def load(self) -> None:
        """Load profile configuration from disk."""
        if self._loaded:
            return
        path = Path(self.config_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._raw = yaml.safe_load(f) or {}
            except Exception as exc:
                logger.error("Failed to load browser profiles", path=str(path), error=str(exc))
                self._raw = {}
        else:
            logger.warning("Browser profile config not found, using defaults", path=str(path))
            self._raw = {}

        self.default_mode = self._raw.get("default_mode", "standard")
        self._modes = self._raw.get("modes", {})
        self._sites = self._raw.get("sites", []) or []
        self._proxy_pool = self._raw.get("proxy_pool", {}) or {}
        self._loaded = True

    def reload(self) -> None:
        """Force reload from disk."""
        self._proxy_cursor = 0
        self._loaded = False
        self.load()

    def resolve(
        self,
        requested_mode: Optional[str] = None,
        url: Optional[str] = None,
        admin_token: Optional[str] = None,
    ) -> ResolvedProfile:
        """Resolve a requested mode plus optional URL to a concrete profile.

        An admin token can unlock gated modes (e.g. aggressive) even when the
        environment gate is not set, so high-priority requests can opt in
        without a server restart.
        """
        self.load()
        mode = self._effective_mode(requested_mode, url)
        mode_config = self._modes.get(mode, {})

        settings = get_settings()
        required_env = mode_config.get("requires_env")
        env_satisfied = not required_env or os.getenv(required_env) == "true"
        admin_override = bool(
            admin_token
            and settings.admin_token
            and secrets.compare_digest(admin_token, settings.admin_token)
        )
        gate_open = env_satisfied or admin_override

        if not mode_config.get("enabled", False) and not (required_env and gate_open):
            raise ConfigurationError(
                "browser_profile",
                f"Browsing mode '{mode}' is not enabled in browser_profiles.yaml",
            )

        if required_env and not gate_open:
            raise ConfigurationError(
                "browser_profile",
                f"Mode '{mode}' requires {required_env}=true or an admin token",
            )

        session_overrides = dict(mode_config.get("session_overrides", {}))
        stealth_strategy = session_overrides.get("stealth_strategy")
        if stealth_strategy:
            session_overrides["stealth_strategy"] = self._normalize_stealth_strategy(stealth_strategy)

        proxy_mode = mode_config.get("proxy", {}).get("mode", "direct")
        proxy_entry = None
        if proxy_mode == "sticky":
            proxy_entry = self._select_proxy()

        warnings: List[str] = []
        if requested_mode and requested_mode != mode:
            warnings.append(f"URL rule forced mode '{mode}' over requested '{requested_mode}'")

        return ResolvedProfile(
            mode=mode,
            session_overrides=session_overrides,
            challenge_ladder=mode_config.get("challenge_ladder", {}),
            human_behavior=mode_config.get("human_behavior", {}),
            proxy_mode=proxy_mode,
            proxy_entry=proxy_entry,
            warnings=warnings,
        )

    def list_modes(self) -> List[Dict[str, str]]:
        """Return a summary of configured modes."""
        self.load()
        result = []
        for name, config in self._modes.items():
            required_env = config.get("requires_env")
            env_satisfied = not required_env or os.getenv(required_env) == "true"
            enabled = config.get("enabled", False) or (bool(required_env) and env_satisfied)
            result.append(
                {
                    "name": name,
                    "description": config.get("description", ""),
                    "enabled": str(enabled),
                    "requires_env": required_env or "",
                }
            )
        return result

    def _effective_mode(self, requested_mode: Optional[str], url: Optional[str]) -> str:
        """Pick the final mode using URL rules and request."""
        requested_mode = requested_mode or self.default_mode
        if requested_mode not in self._modes:
            logger.warning(
                "Unknown browsing mode requested, falling back to default",
                requested_mode=requested_mode,
                default=self.default_mode,
            )
            requested_mode = self.default_mode

        if url:
            origin = self._origin(url)
            for rule in self._sites:
                if self._origin(rule.get("origin", "")) == origin:
                    rule_mode = rule.get("mode")
                    if rule_mode and rule_mode in self._modes:
                        return rule_mode
        return requested_mode

    @staticmethod
    def _origin(url: str) -> str:
        """Return scheme://host:port origin, normalizing default ports."""
        parsed = urlsplit(url)
        scheme = (parsed.scheme or "https").lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port
        if port is None:
            if scheme == "https":
                port = 443
            elif scheme == "http":
                port = 80
        return f"{scheme}://{host}:{port}"

    @staticmethod
    def _normalize_stealth_strategy(value: str) -> str:
        mapping = {
            "none": StealthStrategy.NONE.value,
            "minimal": StealthStrategy.MINIMAL.value,
            "balanced": StealthStrategy.BALANCED.value,
            "aggressive": StealthStrategy.AGGRESSIVE.value,
            "legacy": StealthStrategy.LEGACY.value,
        }
        normalized = mapping.get(str(value).lower().strip())
        if normalized:
            return normalized
        logger.warning("Unknown stealth_strategy in profile, using minimal", value=value)
        return StealthStrategy.MINIMAL.value

    def _select_proxy(self) -> Optional[Dict[str, Any]]:
        """Select one proxy from the configured pool."""
        entries = self._proxy_pool.get("proxies", []) if isinstance(self._proxy_pool, dict) else []
        if not entries:
            return None
        valid_entries = []
        for entry in entries:
            expanded = self._expand_proxy_entry(entry)
            if expanded:
                valid_entries.append(expanded)
        if not valid_entries:
            return None
        selected = valid_entries[self._proxy_cursor % len(valid_entries)]
        self._proxy_cursor = (self._proxy_cursor + 1) % len(valid_entries)
        return selected

    @staticmethod
    def _expand_proxy_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Expand environment variables and validate a proxy entry."""
        server = BrowserProfileService._expand_env(entry.get("server", ""))
        username = BrowserProfileService._expand_env(entry.get("username", ""))
        password = BrowserProfileService._expand_env(entry.get("password", ""))
        protocol = BrowserProfileService._expand_env(entry.get("protocol", "http")).lower() or "http"
        if not server:
            return None
        if not server.startswith(("http://", "https://", "socks5://")):
            server = f"{protocol}://{server}"
        result = {"server": server, "protocol": protocol}
        if username:
            result["username"] = username
        if password:
            result["password"] = password
        return result

    @staticmethod
    def _expand_env(value: Any) -> Any:
        """Expand ${VAR} and ${VAR:-default} patterns in strings."""
        if not isinstance(value, str):
            return value

        def replacer(match: re.Match) -> str:
            inner = match.group(1)
            if ":-" in inner:
                var, default = inner.split(":-", 1)
                return os.getenv(var, default)
            return os.getenv(inner, "")

        return re.sub(r"\$\{([^}]+)\}", replacer, value)


_browser_profile_service: Optional[BrowserProfileService] = None


def get_browser_profile_service() -> BrowserProfileService:
    """Lazy singleton for BrowserProfileService."""
    global _browser_profile_service
    if _browser_profile_service is None:
        _browser_profile_service = BrowserProfileService()
        _browser_profile_service.load()
    return _browser_profile_service


def reset_browser_profile_service() -> None:
    """Reset singleton, mainly for tests."""
    global _browser_profile_service
    _browser_profile_service = None
