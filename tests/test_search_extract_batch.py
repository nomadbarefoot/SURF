"""Unit tests for headless batch extraction timeout behavior."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.search_service import SearchService


@pytest.mark.asyncio
async def test_headless_batch_keeps_completed_results_on_slow_peer():
    """A slow URL must not mark already-finished URLs as Global timeout."""
    svc = SearchService()
    urls = ["https://fast.example/a", "https://slow.example/b"]

    async def fake_extract(url, *_args, **_kwargs):
        if "fast" in url:
            await asyncio.sleep(0.05)
            return {"url": url, "success": True, "title": "Fast", "content": "ok", "ms": 50}
        await asyncio.sleep(10)
        return {"url": url, "success": True, "title": "Slow", "content": "ok", "ms": 10000}

    with patch.object(svc, "_extract_single", side_effect=fake_extract):
        with patch("services.search_service.settings") as mock_settings:
            mock_settings.search_extract_timeout = 1
            results = await svc._extract_batch_headless(
                urls, MagicMock(), MagicMock(), "reader", 8000
            )

    by_url = {r["url"]: r for r in results}
    assert by_url["https://fast.example/a"]["success"] is True
    assert by_url["https://slow.example/b"]["success"] is False
    assert by_url["https://slow.example/b"]["error"] == "Global timeout"


@pytest.mark.asyncio
async def test_deep_extract_skips_headed_retry_for_headless_success():
    svc = SearchService()
    urls = ["https://ok.example/article"]
    relevance = {urls[0]: 0.95}

    with patch.object(
        svc,
        "_extract_batch_headless",
        new=AsyncMock(
            return_value=[{"url": urls[0], "success": True, "title": "T", "content": "body", "ms": 100}]
        ),
    ):
        with patch.object(svc, "_extract_single_headed", new=AsyncMock()) as headed:
            out = await svc.deep_extract(urls, relevance=relevance)

    headed.assert_not_called()
    assert out["results"][0]["success"] is True
