"""Tests for the local sentence-transformers embedding pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from services import embeddings


@pytest.fixture(autouse=True)
def reset_embedder_state():
    """Isolate embedding state between tests."""
    embeddings._embed_available = None
    embeddings._embed_model = None
    embeddings._embed_provider = None
    yield


@pytest.mark.asyncio
async def test_local_embedder_returns_normalized_vector():
    vec = await embeddings._encode("SURF local embedding test")
    assert vec is not None
    assert vec.dtype == np.float32
    assert vec.shape == (768,)
    assert abs(np.linalg.norm(vec) - 1.0) < 1e-5


@pytest.mark.asyncio
async def test_embedder_availability_after_encode():
    assert embeddings.is_embedder_available() is False
    await embeddings._encode("warmup")
    assert embeddings.is_embedder_available() is True


def test_get_embedder_singleton():
    a = embeddings.get_embedder()
    b = embeddings.get_embedder()
    assert isinstance(a, embeddings.LocalEmbeddingProvider)
    assert a is b


@pytest.mark.asyncio
async def test_encode_reuses_loaded_model():
    first = await embeddings._encode("first")
    second = await embeddings._encode("second")
    assert first is not None
    assert second is not None
    assert first.shape == second.shape
    assert embeddings.is_embedder_available() is True
