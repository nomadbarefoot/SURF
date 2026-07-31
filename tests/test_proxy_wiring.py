"""Tests for StickyProxyPool."""
import os
from pathlib import Path

import pytest
import yaml

from utils.proxy_manager import StickyProxyPool, get_proxy_pool, reset_proxy_pool


@pytest.fixture
def proxy_pool(tmp_path, monkeypatch):
    config = {
        "proxies": [
            {
                "server": "http://proxy1.example.com:8080",
                "username": "${PROXY_USER}",
                "password": "${PROXY_PASS}",
                "protocol": "http",
            },
            {
                "server": "http://proxy2.example.com:8080",
                "username": "",
                "password": "",
                "protocol": "http",
            },
            {
                "server": "http://127.0.0.1:9999",
                "protocol": "http",
            },
        ],
        "rotation": {"max_failures": 2, "reset_interval": 3600},
        "allow_private_proxies": False,
    }
    config_path = tmp_path / "proxy_config.yaml"
    config_path.write_text(yaml.safe_dump(config))

    monkeypatch.setenv("PROXY_USER", "alice")
    monkeypatch.setenv("PROXY_PASS", "secret")

    pool = StickyProxyPool(config_path=str(config_path))
    pool.load()
    return pool


def test_private_proxy_rejected(proxy_pool):
    # The 127.0.0.1 entry should have been dropped.
    servers = {e["server"] for e in proxy_pool._entries}
    assert "http://127.0.0.1:9999" not in servers


def test_env_credentials_expanded(proxy_pool):
    entry = proxy_pool._entries[0]
    assert entry["username"] == "alice"
    assert entry["password"] == "secret"
    assert "****" in entry["redacted_server"]


def test_assign_returns_sticky_proxy(proxy_pool):
    opts = proxy_pool.assign("ctx-1")
    assert opts is not None
    assert "server" in opts
    # Same context gets same proxy.
    opts2 = proxy_pool.assign("ctx-1")
    assert opts2["server"] == opts["server"]


def test_failure_rotation(proxy_pool):
    opts = proxy_pool.assign("ctx-1")
    first_server = opts["server"]
    proxy_pool.report_failure("ctx-1", "proxy connection refused")
    proxy_pool.report_failure("ctx-1", "proxy connection refused")
    # After max failures, the context should be unassigned and next assign
    # may pick a different proxy.
    assert "ctx-1" not in proxy_pool._assignments
    opts2 = proxy_pool.assign("ctx-1")
    assert opts2 is not None


def test_non_proxy_failure_does_not_rotate(proxy_pool):
    opts = proxy_pool.assign("ctx-1")
    proxy_pool.report_failure("ctx-1", "HTTP 500 from origin")
    proxy_pool.report_failure("ctx-1", "HTTP 500 from origin")
    # Should still be assigned because failure is not proxy-classified.
    assert "ctx-1" in proxy_pool._assignments


def test_stats_are_redacted(proxy_pool):
    proxy_pool.assign("ctx-1")
    stats = proxy_pool.stats()
    assert stats["total_entries"] == 2
    for entry in stats["entries"]:
        assert "secret" not in entry["server"]
        # If a username is present, password should be masked.
        if "alice" in entry["server"]:
            assert "****" in entry["server"]


def test_global_singleton(tmp_path, monkeypatch):
    config = {
        "proxies": [{"server": "http://singleton.example.com:8080"}],
        "allow_private_proxies": False,
    }
    path = tmp_path / "proxy_config.yaml"
    path.write_text(yaml.safe_dump(config))
    reset_proxy_pool()
    pool = get_proxy_pool()
    pool.config_path = str(path)
    pool.reload()
    assert pool._entries
    assert pool._entries[0]["server"] == "http://singleton.example.com:8080"
    reset_proxy_pool()
