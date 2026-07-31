"""Tests for BrowserProfileService."""
import os
from pathlib import Path

import pytest
import yaml

from services.browser_profile_service import BrowserProfileService


@pytest.fixture
def profile_service(tmp_path, monkeypatch):
    config = {
        "version": "1.0",
        "default_mode": "standard",
        "modes": {
            "standard": {
                "description": "Default",
                "enabled": True,
                "session_overrides": {
                    "stealth_strategy": "minimal",
                    "headed": False,
                    "block_mode": "conservative",
                    "viewport": {"width": 1920, "height": 1080},
                },
                "challenge_ladder": {"max_total_attempts": 2},
                "human_behavior": {"enabled": False},
                "proxy": {"mode": "direct"},
            },
            "resilient": {
                "description": "Resilient",
                "enabled": True,
                "session_overrides": {
                    "stealth_strategy": "balanced",
                    "headed": False,
                    "block_mode": "conservative",
                },
                "challenge_ladder": {"max_total_attempts": 4},
                "human_behavior": {"enabled": True},
                "proxy": {"mode": "sticky"},
            },
            "aggressive": {
                "description": "Aggressive",
                "enabled": False,
                "requires_env": "SURF_ALLOW_AGGRESSIVE_MODE",
                "session_overrides": {"stealth_strategy": "aggressive"},
                "challenge_ladder": {"max_total_attempts": 8},
                "human_behavior": {"enabled": True},
                "proxy": {"mode": "sticky"},
            },
        },
        "sites": [
            {"origin": "https://example.com", "mode": "resilient", "reason": "soft bot checks"}
        ],
        "proxy_pool": {
            "proxies": [
                {
                    "server": "http://proxy.example.com:8080",
                    "username": "${PROXY_USER}",
                    "password": "${PROXY_PASS}",
                    "protocol": "http",
                }
            ]
        },
    }
    config_path = tmp_path / "browser_profiles.yaml"
    config_path.write_text(yaml.safe_dump(config))

    monkeypatch.setenv("PROXY_USER", "alice")
    monkeypatch.setenv("PROXY_PASS", "secret")

    service = BrowserProfileService(config_path=str(config_path))
    service.load()
    return service


def test_resolve_standard_mode(profile_service):
    resolved = profile_service.resolve(requested_mode="standard")
    assert resolved.mode == "standard"
    assert resolved.session_overrides["stealth_strategy"] == "minimal"
    assert resolved.proxy_mode == "direct"


def test_site_rule_forces_mode(profile_service):
    resolved = profile_service.resolve(requested_mode="standard", url="https://example.com/path")
    assert resolved.mode == "resilient"
    assert resolved.session_overrides["stealth_strategy"] == "balanced"
    assert resolved.warnings


def test_unknown_mode_falls_back_to_default(profile_service):
    resolved = profile_service.resolve(requested_mode="nonexistent")
    assert resolved.mode == "standard"


def test_aggressive_mode_requires_env(profile_service, monkeypatch):
    monkeypatch.delenv("SURF_ALLOW_AGGRESSIVE_MODE", raising=False)
    with pytest.raises(Exception):
        profile_service.resolve(requested_mode="aggressive")


def test_aggressive_mode_allowed_when_env_set(profile_service, monkeypatch):
    monkeypatch.setenv("SURF_ALLOW_AGGRESSIVE_MODE", "true")
    resolved = profile_service.resolve(requested_mode="aggressive")
    assert resolved.mode == "aggressive"
    assert resolved.session_overrides["stealth_strategy"] == "aggressive"


def test_sticky_proxy_expands_env_vars(profile_service):
    resolved = profile_service.resolve(requested_mode="resilient")
    assert resolved.proxy_mode == "sticky"
    assert resolved.proxy_entry is not None
    assert resolved.proxy_entry["server"] == "http://proxy.example.com:8080"
    assert resolved.proxy_entry["username"] == "alice"
    assert resolved.proxy_entry["password"] == "secret"


def test_sticky_proxy_pool_rotates_and_wraps(profile_service):
    profile_service._proxy_pool = {
        "proxies": [
            {"server": ""},
            {"server": "proxy-one.example.com:8080"},
            {"server": "proxy-two.example.com:8080"},
        ]
    }

    first = profile_service._select_proxy()
    second = profile_service._select_proxy()
    third = profile_service._select_proxy()

    assert first["server"] == "http://proxy-one.example.com:8080"
    assert second["server"] == "http://proxy-two.example.com:8080"
    assert third["server"] == first["server"]


def test_reload_resets_proxy_rotation(profile_service):
    profile_service._select_proxy()
    assert profile_service._proxy_cursor == 0  # Single-entry pool wraps immediately.
    profile_service._proxy_cursor = 1

    profile_service.reload()

    assert profile_service._proxy_cursor == 0


def test_stealth_strategy_normalization(profile_service):
    resolved = profile_service.resolve(requested_mode="resilient")
    assert resolved.session_overrides["stealth_strategy"] == "balanced"


def test_list_modes(profile_service, monkeypatch):
    monkeypatch.delenv("SURF_ALLOW_AGGRESSIVE_MODE", raising=False)
    modes = profile_service.list_modes()
    names = {m["name"] for m in modes}
    assert names == {"standard", "resilient", "aggressive"}
    aggressive = next(m for m in modes if m["name"] == "aggressive")
    assert aggressive["enabled"] == "False"
    assert aggressive["requires_env"] == "SURF_ALLOW_AGGRESSIVE_MODE"


def test_aggressive_mode_allowed_with_admin_token(profile_service, monkeypatch):
    monkeypatch.delenv("SURF_ALLOW_AGGRESSIVE_MODE", raising=False)
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "admin_token", "admin-secret-123")
    resolved = profile_service.resolve(
        requested_mode="aggressive", admin_token="admin-secret-123"
    )
    assert resolved.mode == "aggressive"


def test_aggressive_mode_rejected_with_bad_admin_token(profile_service, monkeypatch):
    monkeypatch.delenv("SURF_ALLOW_AGGRESSIVE_MODE", raising=False)
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "admin_token", "admin-secret-123")
    with pytest.raises(Exception):
        profile_service.resolve(
            requested_mode="aggressive", admin_token="wrong-token"
        )
