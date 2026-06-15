"""Search service: SearXNG integration + parallel deep extraction via SURF sessions.

Ported from SENTRY ETL patterns:
- Text cleaning (HTML strip, Unicode normalization, zero-width removal)
- BM25 + semantic hybrid relevance scoring
- URL-based deduplication with score preference
- Markdown-oriented output, minimal metadata
"""
from __future__ import annotations

import asyncio
import html
import math
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
import numpy as np
import structlog

from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# ---------------------------------------------------------------------------
# Embedding via local LiteLLM proxy (OpenAI-compatible /v1/embeddings)
# ---------------------------------------------------------------------------
_EMBED_CLIENT: Optional[httpx.AsyncClient] = None
_EMBED_AVAILABLE: Optional[bool] = None


def _get_embed_client() -> Optional[httpx.AsyncClient]:
    global _EMBED_CLIENT
    if _EMBED_CLIENT is None:
        _EMBED_CLIENT = httpx.AsyncClient(
            base_url=settings.embedding_base_url,
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            timeout=10,
        )
    return _EMBED_CLIENT


async def _encode(text: str) -> Optional[np.ndarray]:
    global _EMBED_AVAILABLE
    if _EMBED_AVAILABLE is False:
        return None
    client = _get_embed_client()
    if client is None:
        return None
    try:
        resp = await client.post(
            "/embeddings",
            json={"model": settings.embedding_model, "input": text},
        )
        resp.raise_for_status()
        vec = resp.json()["data"][0]["embedding"]
        if _EMBED_AVAILABLE is None:
            _EMBED_AVAILABLE = True
            logger.info("search_embedder_connected", model=settings.embedding_model)
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        return arr / norm if norm > 0 else arr
    except Exception as exc:
        if _EMBED_AVAILABLE is None:
            _EMBED_AVAILABLE = False
            logger.warning("search_embedder_unavailable", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Text cleaning (ported from SENTRY shared/utils/string_utils.py)
# ---------------------------------------------------------------------------
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s+")
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
_ZERO_WIDTH_RE = re.compile(r"[​‌‍﻿]")
_UNICODE_DASH_RE = re.compile(r"[‐‑‒–—―]")


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    text = _UNICODE_DASH_RE.sub("-", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Relevance scoring (ported from SENTRY shared/etl/transformers/helpers.py)
# ---------------------------------------------------------------------------

def _bm25(item: Dict[str, Any], query: str) -> float:
    """BM25 relevance score, normalized 0-1."""
    query_terms = re.findall(r"\w+", query.lower())
    if not query_terms:
        return 0.0
    doc_text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    doc_terms = re.findall(r"\w+", doc_text)
    if not doc_terms:
        return 0.0

    k1, b, avg_dl = 1.5, 0.75, 100
    freq: Dict[str, int] = {}
    for t in doc_terms:
        freq[t] = freq.get(t, 0) + 1

    score = 0.0
    matched = 0
    idf = math.log(2.0 / 1.1)
    for t in query_terms:
        if t not in freq:
            continue
        matched += 1
        tf = freq[t]
        score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(doc_terms) / avg_dl))

    norm = 1.0 / (1.0 + math.exp(-score / (1.0 if score > 3 else 1.2 if score > 1.5 else 2.0)))
    ratio = matched / len(query_terms)
    if ratio >= 1.0:
        norm = min(1.0, norm * 1.2)
    elif ratio >= 0.5:
        norm = min(1.0, norm * 1.05)
    if ratio < 0.3:
        norm *= 0.5
    elif ratio < 0.5:
        norm *= 0.75
    return min(max(norm, 0.0), 1.0)


async def _semantic(item: Dict[str, Any], query: str) -> Optional[float]:
    """Cosine similarity via LiteLLM embeddings, 0-1."""
    doc_text = f"{item.get('title', '')} {item.get('snippet', '')}".strip()
    if not doc_text:
        return None
    q_emb, d_emb = await asyncio.gather(_encode(query), _encode(doc_text))
    if q_emb is None or d_emb is None:
        return None
    return float(min(max(np.dot(q_emb, d_emb), 0.0), 1.0))


async def _relevance(item: Dict[str, Any], query: str) -> float:
    """Hybrid score: 60% BM25 + 40% semantic. Falls back to BM25-only."""
    bm25 = _bm25(item, query)
    sem = await _semantic(item, query)
    if sem is not None:
        return min(max(0.6 * bm25 + 0.4 * sem, 0.0), 1.0)
    return bm25


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SearchService:

    def __init__(self):
        self._semaphore = asyncio.Semaphore(settings.max_search_sessions)
        self._stats = {
            "searxng_calls": 0,
            "searxng_successes": 0,
            "searxng_failures": 0,
            "searxng_empty": 0,
            "extract_calls": 0,
            "extract_successes": 0,
            "extract_failures": 0,
            "avg_searxng_ms": 0.0,
            "avg_extract_ms": 0.0,
            "last_searxng_error": None,
        }

    # ---- Stage 1: SearXNG search ------------------------------------------

    async def search(
        self,
        query: str,
        max_results: int = 10,
        engines: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        language: str = "en",
        time_range: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._stats["searxng_calls"] += 1
        t0 = time.monotonic()

        params: Dict[str, Any] = {"q": query, "format": "json", "language": language}
        if engines:
            params["engines"] = ",".join(engines)
        elif settings.searxng_engines:
            params["engines"] = ",".join(settings.searxng_engines)
        if categories:
            params["categories"] = ",".join(categories)
        if time_range:
            params["time_range"] = time_range

        try:
            async with httpx.AsyncClient(timeout=settings.searxng_timeout) as client:
                resp = await client.get(f"{settings.searxng_base_url}/search", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            self._stats["searxng_failures"] += 1
            self._stats["last_searxng_error"] = f"Cannot reach SearXNG at {settings.searxng_base_url}"
            return {"success": False, "error": self._stats["last_searxng_error"]}
        except httpx.HTTPStatusError as exc:
            self._stats["searxng_failures"] += 1
            self._stats["last_searxng_error"] = f"SearXNG returned {exc.response.status_code}"
            return {"success": False, "error": self._stats["last_searxng_error"]}
        except Exception as exc:
            self._stats["searxng_failures"] += 1
            self._stats["last_searxng_error"] = str(exc)
            return {"success": False, "error": str(exc)}

        raw = data.get("results", [])
        if not raw:
            self._stats["searxng_empty"] += 1

        results = self._dedup([self._normalize(r) for r in raw])

        # Score & rank (parallel embedding calls)
        scores = await asyncio.gather(*[_relevance(r, query) for r in results])
        for r, s in zip(results, scores):
            r["relevance"] = round(s, 3)
        results.sort(key=lambda r: r["relevance"], reverse=True)
        results = results[:max_results]

        ms = round((time.monotonic() - t0) * 1000)
        self._stats["searxng_successes"] += 1
        n = self._stats["searxng_successes"]
        self._stats["avg_searxng_ms"] = round(self._stats["avg_searxng_ms"] + (ms - self._stats["avg_searxng_ms"]) / n, 1)

        return {"success": True, "results": results, "ms": ms}

    # ---- Stage 2: parallel deep extraction --------------------------------

    async def deep_extract(
        self,
        urls: List[str],
        content_mode: str = "reader",
        max_text_length: int = 8000,
    ) -> Dict[str, Any]:
        from core.foundation import get_session_service, get_browser_service
        session_service = await get_session_service()
        browser_service = await get_browser_service()
        start = time.monotonic()

        async def _bounded(url: str) -> Dict[str, Any]:
            async with self._semaphore:
                return await self._extract_single(
                    url, session_service, browser_service, content_mode, max_text_length
                )

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_bounded(u) for u in urls], return_exceptions=True),
                timeout=settings.search_extract_timeout,
            )
        except asyncio.TimeoutError:
            results = [{"url": u, "success": False, "error": "Global timeout"} for u in urls]

        cleaned = []
        for r in results:
            if isinstance(r, Exception):
                cleaned.append({"url": "unknown", "success": False, "error": str(r)})
            else:
                cleaned.append(r)

        total_ms = int((time.monotonic() - start) * 1000)

        ok = sum(1 for r in cleaned if r.get("success"))
        fail = len(cleaned) - ok
        self._stats["extract_calls"] += 1
        self._stats["extract_successes"] += ok
        self._stats["extract_failures"] += fail
        n = self._stats["extract_calls"]
        self._stats["avg_extract_ms"] = round(self._stats["avg_extract_ms"] + (total_ms - self._stats["avg_extract_ms"]) / n, 1)

        return {"success": True, "results": cleaned, "total_ms": total_ms}

    # ---- Single page extraction -------------------------------------------

    async def _extract_single(
        self, url, session_service, browser_service, content_mode, max_text_length,
    ) -> Dict[str, Any]:
        start = time.monotonic()
        session = None
        try:
            session = await session_service.create_session(
                user_config={
                    "profile_id": f"_search_{uuid.uuid4().hex[:6]}",
                    "persist_profile": False,
                    "headed": True,
                    "silent": False,
                    "background_headed": True,
                    "block_mode": "conservative",
                    "content_mode": content_mode,
                },
                pool="search",
            )
            sid = session.session_id
            async with session_service.session_operation(sid, "search_extract") as sess:
                await browser_service.navigate_to_url(sess, url, timeout=20000)
                await self._wait_past_challenge(sess.page)
                obs = await browser_service.observe_page(
                    sess, content_mode=content_mode, max_text_length=max_text_length
                )
            ms = int((time.monotonic() - start) * 1000)
            raw_text = obs.get("visible_text", "")
            title = _clean_text(obs.get("title", ""))

            if self._is_challenge_page(title, raw_text):
                return {"url": url, "success": False, "error": "Bot protection wall", "ms": ms}

            content = self._to_markdown(title, _clean_text(raw_text), obs.get("url", url))
            return {
                "url": obs.get("url", url),
                "title": title,
                "content": content,
                "tokens": obs.get("token_estimate", 0),
                "success": True,
                "ms": ms,
            }
        except Exception as exc:
            ms = int((time.monotonic() - start) * 1000)
            logger.warning("search_extract_failed", url=url, error=str(exc))
            return {"url": url, "success": False, "error": str(exc), "ms": ms}
        finally:
            if session:
                try:
                    await session_service.close_session(session.session_id, force=True)
                except Exception:
                    pass

    def get_stats(self) -> Dict[str, Any]:
        s = self._stats
        total = s["searxng_calls"]
        rate = round(s["searxng_successes"] / total * 100, 1) if total else 0.0
        return {**s, "searxng_success_rate": rate, "embedder_active": _EMBED_AVAILABLE is True}

    # ---- Helpers ----------------------------------------------------------

    @staticmethod
    async def _wait_past_challenge(page, timeout_ms: int = 12000) -> None:
        try:
            title = await page.title()
            if "just a moment" not in (title or "").lower():
                return
            await page.wait_for_function(
                "() => !document.title.toLowerCase().includes('just a moment')",
                timeout=timeout_ms,
            )
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

    @staticmethod
    def _is_challenge_page(title: str, text: str) -> bool:
        low = (title + " " + text).lower()
        markers = ["just a moment", "checking your browser", "performing security verification"]
        return any(m in low for m in markers)

    @staticmethod
    def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "title": _clean_text(raw.get("title", "")),
            "snippet": _clean_text(raw.get("content", "")),
            "url": raw.get("url", ""),
            "source": raw.get("engine"),
        }

    @staticmethod
    def _dedup(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: Dict[str, Dict[str, Any]] = {}
        for r in results:
            url = r["url"].lower().strip()
            if url and url not in seen:
                seen[url] = r
        return list(seen.values())

    @staticmethod
    def _to_markdown(title: str, text: str, url: str) -> str:
        lines = [f"# {title}", ""] if title else []
        lines.append(text)
        lines.append("")
        lines.append(f"*Source: {url}*")
        return "\n".join(lines)
