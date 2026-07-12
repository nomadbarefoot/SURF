"""Local native embedding pipeline.

SURF uses sentence-transformers in-process instead of an external embedding
proxy. The model is loaded lazily on first encode() call and cached for the
process lifetime.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional

import numpy as np
import structlog

from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Module-level singleton state for the local embedding model.
_embed_lock: asyncio.Lock = asyncio.Lock()
_embed_model: Any = None
_embed_available: Optional[bool] = None
_embed_provider: Optional["LocalEmbeddingProvider"] = None


class EmbeddingProvider(ABC):
    """Abstract base for a text-to-dense-vector encoder."""

    @abstractmethod
    async def encode(self, text: str) -> Optional[np.ndarray]:
        """Return a normalized embedding vector or None if encoding fails."""
        ...


class LocalEmbeddingProvider(EmbeddingProvider):
    """sentence-transformers based local encoder.

    Defaults to all-mpnet-base-v2 for quality. The model downloads on first use
    and is cached under the standard HuggingFace cache directory (~/.cache).
    """

    def _choose_device(self) -> str:
        explicit = settings.embedding_device
        if explicit and explicit.lower() not in {"auto", "cpu"}:
            logger.warning(
                "embedding_device_forced_to_cpu",
                requested=explicit,
                reason="SURF uses CPU-only torch to keep install size small",
            )
        return "cpu"

    def _load_model(self) -> Any:
        from sentence_transformers import SentenceTransformer

        device = self._choose_device()
        model_name = settings.embedding_model
        logger.info("embedding_model_loading", model=model_name, device=device)
        model = SentenceTransformer(model_name, device=device)
        logger.info("embedding_model_loaded", model=model_name, device=device)
        return model

    async def encode(self, text: str) -> Optional[np.ndarray]:
        global _embed_model, _embed_available

        if _embed_available is False:
            return None

        if _embed_model is None:
            async with _embed_lock:
                if _embed_model is None:
                    try:
                        _embed_model = await asyncio.get_running_loop().run_in_executor(
                            None, self._load_model
                        )
                        _embed_available = True
                    except Exception as exc:
                        _embed_available = False
                        logger.warning("embedding_model_load_failed", error=str(exc))
                        return None

        try:
            vec = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _embed_model.encode(
                    text, convert_to_numpy=True, show_progress_bar=False
                ),
            )
        except Exception as exc:
            logger.warning("embedding_encode_failed", error=str(exc))
            return None

        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        return arr / norm if norm > 0 else arr


def get_embedder() -> EmbeddingProvider:
    """Return the configured embedding provider singleton."""
    global _embed_provider
    if _embed_provider is None:
        _embed_provider = LocalEmbeddingProvider()
    return _embed_provider


async def _encode(text: str) -> Optional[np.ndarray]:
    """Convenience wrapper used by SearchService and ContentRefiner."""
    return await get_embedder().encode(text)


def is_embedder_available() -> bool:
    """Best-effort availability check for stats/health."""
    return _embed_available is True
