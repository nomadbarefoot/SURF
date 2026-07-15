"""Bounded provider response reader tests."""
from __future__ import annotations

import gzip
from unittest.mock import patch

import httpx
import pytest

from core.foundation import ResourceLimitError
from services.search_providers import _bounded_json_request


def _patch_client(transport: httpx.MockTransport):
    original_client = httpx.AsyncClient

    def client_factory(*_args, **kwargs):
        return original_client(transport=transport, timeout=kwargs.get("timeout"))

    return patch(
        "services.search_providers.httpx.AsyncClient", side_effect=client_factory
    )


@pytest.mark.asyncio
async def test_provider_json_reader_rejects_oversized_stream():
    async def handler(_request):
        return httpx.Response(200, content=b'{"value":"' + b"x" * 100 + b'"}')

    transport = httpx.MockTransport(handler)

    with _patch_client(transport):
        with patch("services.search_providers.get_settings") as mocked_settings:
            mocked_settings.return_value.max_json_parse_size = 32
            with pytest.raises(ResourceLimitError):
                await _bounded_json_request(
                    "GET", "https://provider.example/search", timeout=1
                )


@pytest.mark.asyncio
async def test_provider_json_reader_returns_object():
    async def handler(_request):
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(handler)

    with _patch_client(transport):
        with patch("services.search_providers.get_settings") as mocked_settings:
            mocked_settings.return_value.max_json_parse_size = 1024
            result = await _bounded_json_request(
                "GET", "https://provider.example/search", timeout=1
            )

    assert result == {"results": []}


@pytest.mark.asyncio
async def test_provider_json_reader_handles_gzip_content_encoding():
    """Regression: Exa returns gzip+chunked; do not double-decode via Response rebuild."""

    payload = b'{"results":[{"url":"https://example.com"}]}'
    compressed = gzip.compress(payload)

    async def handler(_request):
        return httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
                "transfer-encoding": "chunked",
            },
            content=compressed,
        )

    transport = httpx.MockTransport(handler)

    with _patch_client(transport):
        with patch("services.search_providers.get_settings") as mocked_settings:
            mocked_settings.return_value.max_json_parse_size = 1024
            result = await _bounded_json_request(
                "GET", "https://api.exa.ai/search", timeout=1
            )

    assert result == {"results": [{"url": "https://example.com"}]}
