"""OpenAI-compatible embedding client for SURF's semantic ranking pipeline.

Any server exposing ``POST {base_url}/embeddings`` works: Ollama, LiteLLM,
OpenAI, vLLM, or text-embeddings-inference. When ``SURF_EMBEDDING_BASE_URL``
is unset, semantic scoring is disabled and callers fall back to BM25.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import List, Literal, Optional

import httpx
import structlog

from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

Embedding = List[float]
EmbeddingInputType = Literal["query", "document"]
QUERY_PREFIX = "search_query: "
DOCUMENT_PREFIX = "search_document: "
# Leave headroom inside Nomic v2's 512-token context for its multilingual
# tokenizer. The previous SentenceTransformers backend truncated implicitly.
MAX_INPUT_CHARS = 1_000
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


def is_embedding_configured() -> bool:
    """Report whether an embedding endpoint is configured at all."""
    return bool((settings.embedding_base_url or "").strip())


class LiteLLMEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embedding client (name kept for compatibility)."""

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport

    async def encode_many(self, texts: List[str]) -> Optional[List[Embedding]]:
        global _embed_available

        if not texts:
            return []
        if not is_embedding_configured():
            _embed_available = False
            return None

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
                    json=_request_body(texts),
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


def _request_body(texts: List[str]) -> dict:
    body: dict = {"model": settings.embedding_model, "input": texts}
    if settings.embedding_dimensions > 0:
        body["dimensions"] = settings.embedding_dimensions
    return body


async def probe_embeddings() -> dict:
    """Embed one short query and report whether semantic ranking is live."""
    info = {
        "configured": is_embedding_configured(),
        "base_url": settings.embedding_base_url,
        "model": settings.embedding_model,
    }
    if not info["configured"]:
        return {
            **info,
            "status": "disabled",
            "hint": "Set SURF_EMBEDDING_BASE_URL (and SURF_EMBEDDING_MODEL); "
            "search is using BM25 only.",
        }
    vector = await get_embedder().encode(_prefix("health check", "query"))
    if vector is None:
        return {
            **info,
            "status": "down",
            "hint": "Endpoint configured but the embedding request failed; "
            "check the URL, model name, and API key. Search falls back to BM25.",
        }
    return {**info, "status": "ready", "dimensions": len(vector)}


def get_embedder() -> EmbeddingProvider:
    """Return the process-wide remote embedding provider."""
    global _embed_provider
    if _embed_provider is None:
        _embed_provider = LiteLLMEmbeddingProvider()
    return _embed_provider


async def _encode(text: str) -> Optional[Embedding]:
    return await _encode_query(text)


def _prefix(text: str, input_type: EmbeddingInputType) -> str:
    """Apply the Nomic retrieval prefix once at the semantic boundary."""
    prefix = QUERY_PREFIX if input_type == "query" else DOCUMENT_PREFIX
    while text.startswith((QUERY_PREFIX, DOCUMENT_PREFIX)):
        text = text.split(": ", 1)[1]
    return f"{prefix}{text}"[:MAX_INPUT_CHARS]


async def _encode_query(text: str) -> Optional[Embedding]:
    return await get_embedder().encode(_prefix(text, "query"))


async def _encode_document(text: str) -> Optional[Embedding]:
    return await get_embedder().encode(_prefix(text, "document"))


async def _encode_many(texts: List[str]) -> Optional[List[Embedding]]:
    return await _encode_documents(texts)


async def _encode_documents(texts: List[str]) -> Optional[List[Embedding]]:
    return await get_embedder().encode_many(
        [_prefix(text, "document") for text in texts]
    )


async def _encode_query_and_documents(
    query: str, documents: List[str]
) -> Optional[List[Embedding]]:
    """Encode one retrieval query and its document candidates in one request."""
    return await get_embedder().encode_many(
        [_prefix(query, "query")]
        + [_prefix(document, "document") for document in documents]
    )


def is_embedder_available() -> bool:
    """Report whether the most recent embedding request succeeded."""
    return _embed_available is True
