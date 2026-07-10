"""Tests for SearXNG autowake runtime."""
from __future__ import annotations

import pytest

from services import searxng_runtime as runtime


@pytest.mark.asyncio
async def test_probe_searxng_reachable(monkeypatch):
    class FakeResp:
        status_code = 200
        text = "OK"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return FakeResp()

    monkeypatch.setattr(runtime.httpx, "AsyncClient", lambda **kw: FakeClient())
    result = await runtime.probe_searxng()
    assert result["reachable"] is True


@pytest.mark.asyncio
async def test_ensure_skips_autowake_when_up(monkeypatch):
    async def fake_probe(**kw):
        return {"reachable": True, "ms": 1}

    monkeypatch.setattr(runtime, "probe_searxng", fake_probe)
    result = await runtime.ensure_searxng()
    assert result["status"] == "ready"
    assert result["autowake"] is False


@pytest.mark.asyncio
async def test_ensure_reports_down_when_autowake_disabled(monkeypatch):
    async def fake_probe(**kw):
        return {"reachable": False, "error": "connect_error"}

    monkeypatch.setattr(runtime, "probe_searxng", fake_probe)
    monkeypatch.setattr(runtime.settings, "searxng_autowake_enabled", False)
    result = await runtime.ensure_searxng()
    assert result["status"] == "down"
    assert "autowake disabled" in result.get("error", "")
