"""Tests for the LiteLLM embedding client."""

from __future__ import annotations

import json
import math

import httpx
import pytest

from services import embeddings


@pytest.fixture(autouse=True)
def reset_embedder_state(monkeypatch):
    embeddings._embed_available = None
    embeddings._embed_provider = None
    monkeypatch.setattr(embeddings.settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(
        embeddings.settings, "embedding_model", "embed-text"
    )
    monkeypatch.setattr(embeddings.settings, "embedding_dimensions", 768)
    monkeypatch.setattr(
        embeddings.settings, "embedding_base_url", "http://litellm:4000/v1"
    )


def _provider(handler):
    return embeddings.LiteLLMEmbeddingProvider(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_encode_many_batches_request_and_normalizes_vectors():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 5.0]},
                    {"index": 0, "embedding": [3.0, 4.0]},
                ]
            },
        )

    vectors = await _provider(handler).encode_many(["first", "second"])

    assert captured == {
        "authorization": "Bearer test-key",
        "payload": {
            "model": "embed-text",
            "input": ["first", "second"],
            "dimensions": 768,
        },
    }
    assert vectors is not None
    assert vectors[0] == pytest.approx([0.6, 0.8])
    assert vectors[1] == pytest.approx([0.0, 1.0])
    assert embeddings.is_embedder_available() is True


@pytest.mark.asyncio
async def test_encode_returns_single_vector():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [2, 0]}]}
        )

    vector = await _provider(handler).encode("query")

    assert vector == [1.0, 0.0]


@pytest.mark.asyncio
async def test_query_and_document_prefixes_are_applied_once():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 1.0]},
                ]
            },
        )

    embeddings._embed_provider = _provider(handler)
    vectors = await embeddings._encode_query_and_documents(
        "topic", ["search_document: already tagged"]
    )

    assert vectors is not None
    assert captured["payload"] == {
        "model": "embed-text",
        "input": ["search_query: topic", "search_document: already tagged"],
        "dimensions": 768,
    }


@pytest.mark.asyncio
async def test_prefixed_inputs_are_bounded_for_nomic_context():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]}
        )

    embeddings._embed_provider = _provider(handler)
    await embeddings._encode_document("x" * 10_000)

    value = captured["payload"]["input"][0]
    assert len(value) == embeddings.MAX_INPUT_CHARS
    assert value.startswith(embeddings.DOCUMENT_PREFIX)


@pytest.mark.asyncio
async def test_request_failure_marks_provider_unavailable():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    assert await _provider(handler).encode_many(["query"]) is None
    assert embeddings.is_embedder_available() is False


@pytest.mark.asyncio
async def test_invalid_batch_response_fails_closed():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    assert await _provider(handler).encode_many(["query"]) is None


def test_get_embedder_singleton():
    first = embeddings.get_embedder()
    second = embeddings.get_embedder()
    assert isinstance(first, embeddings.LiteLLMEmbeddingProvider)
    assert first is second


def test_cosine_similarity_handles_unnormalized_vectors():
    assert embeddings.cosine_similarity([3.0, 0.0], [4.0, 0.0]) == pytest.approx(
        1.0
    )
    assert embeddings.cosine_similarity([1.0, 0.0], [0.0, 2.0]) == pytest.approx(
        0.0
    )
    assert math.isfinite(embeddings.cosine_similarity([0.0], [0.0]))
