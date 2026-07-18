"""Tests for the provider-based search layer."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from core.foundation import get_search_service
from services.search_providers import (
    ExaSearchProvider,
    SearXNGSearchProvider,
    SearchProviderRegistry,
)
from services.search_service import SearchService


@pytest.fixture
def exa_provider():
    """Exa provider using settings from the environment/.env."""
    return ExaSearchProvider()


@pytest.fixture
def registry():
    return SearchProviderRegistry()


@pytest.fixture
def service():
    return SearchService()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def patch_relevance():
    """Keep service-level tests fast and independent of the local embedder."""
    async def fixed_scores(items, _query):
        return [0.9] * len(items)

    with patch("services.search_service._relevance_many", side_effect=fixed_scores):
        yield


# ---------------------------------------------------------------------------
# Exa provider integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SURF_RUN_INTEGRATION_TESTS") != "1",
    reason="set SURF_RUN_INTEGRATION_TESTS=1 to call Exa",
)
async def test_exa_provider_real_auto_returns_results(exa_provider):
    """A real Exa call should return ranked results with auto/highlights defaults."""
    result = await exa_provider.search(
        query="OpenAI o3 model release date",
        max_results=3,
    )
    if not result["success"] and "not set" in (result.get("error") or ""):
        pytest.skip("SURF_EXA_API_KEY is not set")

    assert result["success"] is True
    assert result["provider"] == "exa"
    assert len(result["results"]) >= 1
    for r in result["results"]:
        assert r["url"]
        assert r["title"]
        assert r["snippet"]
        assert r["source"] == "exa"
    assert result["ms"] > 0


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SURF_RUN_INTEGRATION_TESTS") != "1",
    reason="set SURF_RUN_INTEGRATION_TESTS=1 to call Exa",
)
async def test_exa_provider_uses_auto_mode(exa_provider):
    """Exa always searches with mode=auto regardless of any legacy mode arg."""
    result = await exa_provider.search(
        query="OpenAI o3 model release date",
        max_results=3,
        mode="deep-reasoning",  # ignored
    )
    if not result["success"] and "not set" in (result.get("error") or ""):
        pytest.skip("SURF_EXA_API_KEY is not set")

    assert result["success"] is True
    assert result["metadata"]["mode"] == "auto"


@pytest.mark.asyncio
async def test_exa_provider_missing_key_returns_error():
    """Without an API key the provider should fail fast and report the reason."""
    with patch("services.search_providers.settings.exa_api_key", None):
        provider = ExaSearchProvider()
        result = await provider.search("anything")

    assert result["success"] is False
    assert "SURF_EXA_API_KEY" in result["error"]


@pytest.mark.asyncio
async def test_exa_rejects_constraints_it_cannot_honor():
    with patch("services.search_providers.settings.exa_api_key", "test-key"):
        provider = ExaSearchProvider()
        result = await provider.search("anything", engines=["google"])

    assert result["success"] is False
    assert result["metadata"]["unsupported_constraints"] == ["engines"]


@pytest.mark.asyncio
async def test_exa_respects_caller_result_ceiling():
    with patch("services.search_providers.settings.exa_api_key", "test-key"):
        provider = ExaSearchProvider()
    request = AsyncMock(return_value={"results": []})

    with patch("services.search_providers._bounded_json_request", request):
        await provider.search("anything", max_results=2)

    assert request.await_args.kwargs["json"]["numResults"] == 2


# ---------------------------------------------------------------------------
# SearXNG provider normalization
# ---------------------------------------------------------------------------


def test_searxng_normalize_maps_common_fields():
    provider = SearXNGSearchProvider()
    raw = {
        "title": "  Some Title  ",
        "content": "  Some snippet  ",
        "url": "https://example.com",
        "engine": "google",
    }
    normalized = provider._normalize(raw)
    assert normalized["title"] == "Some Title"
    assert normalized["snippet"] == "Some snippet"
    assert normalized["url"] == "https://example.com"
    assert normalized["source"] == "google"


# ---------------------------------------------------------------------------
# SearchService orchestration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_uses_primary_provider_results(service):
    primary = AsyncMock()
    primary.name = "exa"
    primary.search = AsyncMock(
        return_value={
            "success": True,
            "provider": "exa",
            "results": [
                {
                    "title": "T1",
                    "url": "https://a.com",
                    "snippet": "S1",
                    "source": "exa",
                },
                {
                    "title": "T2",
                    "url": "https://b.com",
                    "snippet": "S2",
                    "source": "exa",
                },
            ],
            "ms": 100,
            "cost": 0.007,
            "metadata": {"mode": "auto"},
        }
    )

    with patch.object(service._registry, "get", return_value=primary):
        with patch.object(service._registry, "fallback", return_value=None):
            result = await service.search("query", max_results=10, provider="exa")

    assert result["success"] is True
    assert result["provider"] == "exa"
    assert len(result["results"]) == 2
    assert "relevance" in result["results"][0]
    primary.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_falls_back_when_primary_fails(service):
    primary = AsyncMock()
    primary.name = "exa"
    primary.search = AsyncMock(
        return_value={
            "success": False,
            "provider": "exa",
            "results": [],
            "error": "Exa API error",
            "metadata": {},
        }
    )

    fallback = AsyncMock()
    fallback.name = "searxng"
    fallback.search = AsyncMock(
        return_value={
            "success": True,
            "provider": "searxng",
            "results": [
                {
                    "title": "T",
                    "url": "https://c.com",
                    "snippet": "S",
                    "source": "google",
                },
            ],
            "ms": 200,
            "metadata": {},
        }
    )

    with patch.object(
        service._registry,
        "get",
        side_effect=lambda name: primary if name == "exa" else fallback,
    ):
        with patch.object(service._registry, "fallback", return_value=fallback):
            result = await service.search(
                "query", max_results=10, provider="exa", fallback=True
            )

    assert result["success"] is True
    assert result["provider"] == "searxng"
    assert len(result["results"]) == 1
    primary.search.assert_awaited_once()
    fallback.search.assert_awaited_once()
    assert service._stats["search_fallbacks"] == 1


@pytest.mark.asyncio
async def test_service_falls_back_when_primary_empty(service):
    primary = AsyncMock()
    primary.name = "exa"
    primary.search = AsyncMock(
        return_value={
            "success": True,
            "provider": "exa",
            "results": [],
            "ms": 50,
            "metadata": {},
        }
    )

    fallback = AsyncMock()
    fallback.name = "searxng"
    fallback.search = AsyncMock(
        return_value={
            "success": True,
            "provider": "searxng",
            "results": [
                {
                    "title": "T",
                    "url": "https://c.com",
                    "snippet": "S",
                    "source": "google",
                },
            ],
            "ms": 200,
            "metadata": {},
        }
    )

    with patch.object(
        service._registry,
        "get",
        side_effect=lambda name: primary if name == "exa" else fallback,
    ):
        with patch.object(service._registry, "fallback", return_value=fallback):
            result = await service.search(
                "query", max_results=10, provider="exa", fallback=True
            )

    assert result["success"] is True
    assert result["provider"] == "searxng"
    fallback.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_respects_fallback_disabled(service):
    primary = AsyncMock()
    primary.name = "exa"
    primary.search = AsyncMock(
        return_value={
            "success": False,
            "provider": "exa",
            "results": [],
            "error": "Exa API error",
            "metadata": {},
        }
    )

    fallback = AsyncMock()
    fallback.name = "searxng"
    fallback.search = AsyncMock(
        return_value={
            "success": True,
            "provider": "searxng",
            "results": [
                {
                    "title": "T",
                    "url": "https://c.com",
                    "snippet": "S",
                    "source": "google",
                }
            ],
            "ms": 200,
            "metadata": {},
        }
    )

    with patch.object(
        service._registry,
        "get",
        side_effect=lambda name: primary if name == "exa" else fallback,
    ):
        with patch.object(service._registry, "fallback", return_value=fallback):
            result = await service.search(
                "query", max_results=10, provider="exa", fallback=False
            )

    assert result["success"] is False
    fallback.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_does_not_retry_the_requested_provider_as_fallback(service):
    primary = AsyncMock()
    primary.name = "exa"
    primary.search = AsyncMock(
        return_value={
            "success": False,
            "provider": "exa",
            "results": [],
            "error": "failed",
            "metadata": {},
        }
    )

    with patch.object(service._registry, "get", return_value=primary):
        with patch.object(service._registry, "fallback", return_value=primary):
            result = await service.search("query", provider="exa", fallback=True)

    assert result["success"] is False
    primary.search.assert_awaited_once()


# ---------------------------------------------------------------------------
# Relevance threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_filters_results_below_threshold(service):
    """Results under the relevance threshold are dropped from the final set."""
    primary = AsyncMock()
    primary.name = "exa"
    primary.search = AsyncMock(
        return_value={
            "success": True,
            "provider": "exa",
            "results": [
                {
                    "title": "High",
                    "url": "https://high.com",
                    "snippet": "S",
                    "source": "exa",
                },
                {
                    "title": "Low",
                    "url": "https://low.com",
                    "snippet": "S",
                    "source": "exa",
                },
            ],
            "ms": 100,
            "metadata": {"mode": "auto"},
        }
    )

    with patch(
        "services.search_service._relevance_many", return_value=[0.8, 0.3]
    ):
        with patch.object(service._registry, "get", return_value=primary):
            with patch.object(service._registry, "fallback", return_value=None):
                result = await service.search("query", max_results=10, provider="exa")

    assert result["success"] is True
    assert len(result["results"]) == 1
    assert result["results"][0]["url"] == "https://high.com"


@pytest.mark.asyncio
async def test_service_returns_top_three_when_none_pass_threshold(service):
    """When no result reaches the threshold, return success=false with top 3."""
    primary = AsyncMock()
    primary.name = "exa"
    primary.search = AsyncMock(
        return_value={
            "success": True,
            "provider": "exa",
            "results": [
                {"title": "A", "url": "https://a.com", "snippet": "S", "source": "exa"},
                {"title": "B", "url": "https://b.com", "snippet": "S", "source": "exa"},
                {"title": "C", "url": "https://c.com", "snippet": "S", "source": "exa"},
                {"title": "D", "url": "https://d.com", "snippet": "S", "source": "exa"},
            ],
            "ms": 100,
            "metadata": {"mode": "auto"},
        }
    )

    with patch(
        "services.search_service._relevance_many", return_value=[0.1] * 4
    ):
        with patch.object(service._registry, "get", return_value=primary):
            with patch.object(service._registry, "fallback", return_value=None):
                result = await service.search("query", max_results=10, provider="exa")

    assert result["success"] is False
    assert "No results above relevance threshold" in result["error"]
    assert len(result["results"]) == 3
    assert result["metadata"]["below_threshold"] is True


@pytest.mark.asyncio
async def test_service_min_relevance_override(service):
    """Per-request min_relevance overrides the global threshold."""
    primary = AsyncMock()
    primary.name = "exa"
    primary.search = AsyncMock(
        return_value={
            "success": True,
            "provider": "exa",
            "results": [
                {
                    "title": "Just ok",
                    "url": "https://ok.com",
                    "snippet": "S",
                    "source": "exa",
                },
            ],
            "ms": 100,
            "metadata": {"mode": "auto"},
        }
    )

    with patch("services.search_service._relevance_many", return_value=[0.4]):
        with patch.object(service._registry, "get", return_value=primary):
            with patch.object(service._registry, "fallback", return_value=None):
                result = await service.search(
                    "query", max_results=10, provider="exa", min_relevance=0.3
                )

    assert result["success"] is True
    assert result["results"][0]["url"] == "https://ok.com"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_creates_exa_and_searxng_providers(registry):
    assert isinstance(registry.get("exa"), ExaSearchProvider)
    assert isinstance(registry.get("searxng"), SearXNGSearchProvider)
    assert registry.get("unknown") is None


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------


def test_settings_defaults_favor_exa_auto():
    from config import get_settings

    settings = get_settings()
    assert settings.search_provider == "exa"
    assert settings.search_fallback_provider == "searxng"
    assert settings.exa_num_results == 10
    assert settings.exa_contents_highlights is True
    assert settings.exa_fallback_enabled is True
    assert settings.search_relevance_threshold == 0.5
    assert settings.embedding_base_url == "http://127.0.0.1:4000/v1"
    assert settings.embedding_model == "embedding"
    assert settings.embedding_timeout == 15.0


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def test_search_query_endpoint_uses_provider(client):
    """The /search/query endpoint should return provider results with relevance scores."""

    async def fake_search(*args, **kwargs):
        return {
            "success": True,
            "provider": "exa",
            "results": [
                {
                    "title": "Hello",
                    "url": "https://example.com",
                    "snippet": "World",
                    "source": "exa",
                },
            ],
            "ms": 100,
            "cost": 0.007,
            "metadata": {"mode": "auto"},
        }

    mock_service = AsyncMock()
    mock_service.search = AsyncMock(side_effect=fake_search)

    app.dependency_overrides[get_search_service] = lambda: mock_service
    try:
        response = client.post(
            "/search/query", json={"query": "test", "max_results": 5}
        )
    finally:
        app.dependency_overrides.pop(get_search_service, None)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["provider"] == "exa"
    assert len(data["results"]) == 1
    assert data["results"][0]["url"] == "https://example.com"
    mock_service.search.assert_awaited_once()


def test_search_query_endpoint_with_provider_override(client):
    """The endpoint should pass provider/fallback overrides to the service."""
    captured = {}

    async def fake_search(*args, **kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "provider": kwargs.get("provider", "exa"),
            "results": [],
            "ms": 100,
            "metadata": {},
        }

    mock_service = AsyncMock()
    mock_service.search = AsyncMock(side_effect=fake_search)

    app.dependency_overrides[get_search_service] = lambda: mock_service
    try:
        response = client.post(
            "/search/query",
            json={
                "query": "test",
                "provider": "exa",
                "fallback": False,
            },
        )
    finally:
        app.dependency_overrides.pop(get_search_service, None)

    assert response.status_code == 200
    assert captured["provider"] == "exa"
    assert captured["fallback"] is False


def test_search_query_endpoint_returns_error_when_no_results(client):
    """The endpoint should return a structured error when no provider succeeds."""

    async def fake_search(*args, **kwargs):
        return {
            "success": False,
            "provider": "exa",
            "results": [],
            "error": "Rate limit",
            "metadata": {},
        }

    mock_service = AsyncMock()
    mock_service.search = AsyncMock(side_effect=fake_search)

    app.dependency_overrides[get_search_service] = lambda: mock_service
    try:
        response = client.post(
            "/search/query", json={"query": "test", "fallback": False}
        )
    finally:
        app.dependency_overrides.pop(get_search_service, None)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "Rate limit" in data["error"]
