"""Remote embedding client for SURF's semantic ranking pipeline."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import List, Optional

import httpx
import structlog

from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

Embedding = List[float]
_embed_available: Optional[bool] = None
_embed_provider: Optional["LiteLLMEmbeddingProvider"] = None


def _normalize(vector: List[float]) -> Embedding:
    values = [float(value) for value in vector]
    norm = math.sqrt(math.fsum(value * value for value in values))
    return [value / norm for value in values] if norm > 0 else values


def cosine_similarity(left: Embedding, right: Embedding) -> float:
    """Return cosine similarity for two equal-length embedding vectors."""
    if not left or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return math.fsum(a * b for a, b in zip(left, right)) / (
        left_norm * right_norm
    )


class EmbeddingProvider(ABC):
    """Abstract text-to-vector encoder."""

    @abstractmethod
    async def encode_many(self, texts: List[str]) -> Optional[List[Embedding]]:
        """Return normalized vectors for a batch, or None on failure."""
        ...

    async def encode(self, text: str) -> Optional[Embedding]:
        vectors = await self.encode_many([text])
        return vectors[0] if vectors else None


class LiteLLMEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embedding client backed by the local LiteLLM proxy."""

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport

    async def encode_many(self, texts: List[str]) -> Optional[List[Embedding]]:
        global _embed_available

        if not texts:
            return []

        headers = {}
        if settings.embedding_api_key:
            headers["Authorization"] = f"Bearer {settings.embedding_api_key}"

        try:
            async with httpx.AsyncClient(
                timeout=settings.embedding_timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{settings.embedding_base_url.rstrip('/')}/embeddings",
                    headers=headers,
                    json={"model": settings.embedding_model, "input": texts},
                )
                response.raise_for_status()
                payload = response.json()

            rows = sorted(payload.get("data", []), key=lambda row: row.get("index", -1))
            if len(rows) != len(texts):
                raise ValueError(
                    f"expected {len(texts)} embeddings, received {len(rows)}"
                )
            vectors = [_normalize(row["embedding"]) for row in rows]
            dimensions = {len(vector) for vector in vectors}
            if len(dimensions) != 1 or 0 in dimensions:
                raise ValueError("embedding response has inconsistent dimensions")

            _embed_available = True
            return vectors
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            _embed_available = False
            logger.warning("embedding_request_failed", error=str(exc))
            return None


def get_embedder() -> EmbeddingProvider:
    """Return the process-wide remote embedding provider."""
    global _embed_provider
    if _embed_provider is None:
        _embed_provider = LiteLLMEmbeddingProvider()
    return _embed_provider


async def _encode(text: str) -> Optional[Embedding]:
    return await get_embedder().encode(text)


async def _encode_many(texts: List[str]) -> Optional[List[Embedding]]:
    return await get_embedder().encode_many(texts)


def is_embedder_available() -> bool:
    """Report whether the most recent embedding request succeeded."""
    return _embed_available is True
