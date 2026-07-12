"""Search service: provider-based search (Exa primary, SearXNG fallback) + parallel deep extraction.

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
from services.challenge_resolver import ChallengeResolver
from services.content_refiner import ContentRefiner
from services.embeddings import _encode, is_embedder_available
from services.search_providers import SearchProviderRegistry
from utils.text import clean_text as _clean_text

logger = structlog.get_logger()
settings = get_settings()


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

    norm = 1.0 / (
        1.0 + math.exp(-score / (1.0 if score > 3 else 1.2 if score > 1.5 else 2.0))
    )
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
    """Cosine similarity via local sentence-transformers embeddings, 0-1."""
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
        self._registry = SearchProviderRegistry()
        self._semaphore = asyncio.Semaphore(settings.max_search_sessions)
        self._headed_semaphore = asyncio.Semaphore(settings.max_search_headed_sessions)
        self._stats = {
            # legacy SearXNG keys (kept for backward compatibility)
            "searxng_calls": 0,
            "searxng_successes": 0,
            "searxng_failures": 0,
            "searxng_empty": 0,
            "avg_searxng_ms": 0.0,
            "last_searxng_error": None,
            # Exa + generic search keys
            "exa_calls": 0,
            "exa_successes": 0,
            "exa_failures": 0,
            "exa_empty": 0,
            "avg_exa_ms": 0.0,
            "last_exa_error": None,
            "search_calls": 0,
            "search_successes": 0,
            "search_failures": 0,
            "search_fallbacks": 0,
            "extract_calls": 0,
            "extract_successes": 0,
            "extract_failures": 0,
            "extract_headed_retries": 0,
            "avg_extract_ms": 0.0,
        }

    # ---- Stage 1: provider search -----------------------------------------

    async def search(
        self,
        query: str,
        max_results: int = 10,
        engines: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        language: str = "en",
        time_range: Optional[str] = None,
        provider: Optional[str] = None,
        fallback: Optional[bool] = None,
        min_relevance: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Search via the configured provider, falling back to the secondary provider
        on failure or empty results. Applies hybrid BM25 + semantic re-ranking and
        URL deduplication on the final result set, then filters to results above
        the configured relevance threshold.
        """
        requested_provider = (provider or settings.search_provider or "exa").lower()
        allow_fallback = (
            fallback if fallback is not None else settings.exa_fallback_enabled
        )

        primary = self._registry.get(requested_provider)
        if primary is None:
            return {
                "success": False,
                "error": f"Unknown search provider: {requested_provider}",
            }

        secondary: Optional[Any] = None
        if allow_fallback:
            secondary = self._registry.fallback()

        # Try primary provider
        result = await primary.search(
            query=query,
            max_results=max_results,
            engines=engines,
            categories=categories,
            language=language,
            time_range=time_range,
        )
        self._record_provider_stats(primary.name, result)

        if result["success"] and result["results"]:
            return await self._finalize_results(
                query, result, max_results, min_relevance=min_relevance
            )

        # Try fallback provider when enabled
        if allow_fallback and secondary is not None:
            self._stats["search_fallbacks"] += 1
            fallback_result = await secondary.search(
                query=query,
                max_results=max_results,
                engines=engines,
                categories=categories,
                language=language,
                time_range=time_range,
            )
            self._record_provider_stats(secondary.name, fallback_result)
            if fallback_result["success"] and fallback_result["results"]:
                return await self._finalize_results(
                    query, fallback_result, max_results, min_relevance=min_relevance
                )
            result = fallback_result

        # No provider succeeded or returned results
        return {
            "success": False,
            "error": result.get("error") or "No search results",
            "provider": result.get("provider"),
            "metadata": result.get("metadata"),
        }

    def _record_provider_stats(
        self, provider_name: str, result: Dict[str, Any]
    ) -> None:
        """Update provider-specific and aggregate counters."""
        prefix = provider_name.lower()
        calls_key = f"{prefix}_calls"
        successes_key = f"{prefix}_successes"
        failures_key = f"{prefix}_failures"
        empty_key = f"{prefix}_empty"
        avg_key = f"avg_{prefix}_ms"
        last_error_key = f"last_{prefix}_error"

        self._stats["search_calls"] += 1
        if self._stats.get(calls_key) is not None:
            self._stats[calls_key] += 1

        if result.get("success"):
            self._stats["search_successes"] += 1
            if self._stats.get(successes_key) is not None:
                self._stats[successes_key] += 1

            if not result.get("results"):
                self._stats["search_failures"] += (
                    1  # empty counts as failure at service level
                )
                if self._stats.get(empty_key) is not None:
                    self._stats[empty_key] += 1

            ms = result.get("ms", 0)
            if self._stats.get(avg_key) is not None:
                n = self._stats[successes_key]
                self._stats[avg_key] = round(
                    self._stats[avg_key] + (ms - self._stats[avg_key]) / n, 1
                )
        else:
            self._stats["search_failures"] += 1
            if self._stats.get(failures_key) is not None:
                self._stats[failures_key] += 1
            if self._stats.get(last_error_key) is not None:
                self._stats[last_error_key] = result.get("error")

    async def _finalize_results(
        self,
        query: str,
        provider_result: Dict[str, Any],
        max_results: int,
        min_relevance: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Dedupe, score, sort, filter by relevance threshold, and trim."""
        results = self._dedup([self._normalize(r) for r in provider_result["results"]])
        if not results:
            return {
                "success": False,
                "error": "No results after deduplication",
                "provider": provider_result.get("provider"),
                "metadata": provider_result.get("metadata"),
            }

        scores = await asyncio.gather(*[_relevance(r, query) for r in results])
        for r, s in zip(results, scores):
            r["relevance"] = round(s, 3)
        results.sort(key=lambda r: r["relevance"], reverse=True)

        threshold = (
            min_relevance
            if min_relevance is not None
            else settings.search_relevance_threshold
        )
        passing = [r for r in results if r["relevance"] >= threshold]

        if passing:
            results = passing[:max_results]
        else:
            results = results[:3]
            return {
                "success": False,
                "error": f"No results above relevance threshold ({threshold})",
                "results": results,
                "provider": provider_result.get("provider"),
                "ms": provider_result.get("ms"),
                "cost": provider_result.get("cost"),
                "metadata": {
                    **(provider_result.get("metadata") or {}),
                    "relevance_threshold": threshold,
                    "below_threshold": True,
                },
            }

        return {
            "success": True,
            "results": results,
            "provider": provider_result.get("provider"),
            "ms": provider_result.get("ms"),
            "cost": provider_result.get("cost"),
            "metadata": provider_result.get("metadata"),
        }

    # ---- Stage 2: parallel deep extraction ---------------------------------

    async def deep_extract(
        self,
        urls: List[str],
        content_mode: str = "reader",
        max_text_length: int = 8000,
        relevance: Optional[Dict[str, float]] = None,
        refine_query: Optional[str] = None,
        *,
        force_headed: bool = False,
        skip_headless: bool = False,
    ) -> Dict[str, Any]:
        from core.foundation import get_session_service, get_browser_service

        session_service = await get_session_service()
        browser_service = await get_browser_service()
        start = time.monotonic()
        relevance_map = relevance or {}

        if skip_headless and force_headed:
            initial_results = [
                {
                    "url": u,
                    "success": False,
                    "error": ChallengeResolver.agent_error(),
                    "challenge_blocked": True,
                }
                for u in urls
            ]
        elif skip_headless:
            initial_results = []
        else:
            initial_results = await self._extract_batch_headless(
                urls,
                session_service,
                browser_service,
                content_mode,
                max_text_length,
                refine_query,
            )

        by_url: Dict[str, Dict[str, Any]] = {}
        for requested, result in zip(urls, initial_results):
            by_url[requested] = {**result, "url": requested}

        if not skip_headless:
            retry_urls = [
                u
                for u in urls
                if ChallengeResolver.should_headed_retry(
                    u, by_url.get(u, {"success": False}), relevance_map
                )
            ]
        elif force_headed:
            retry_urls = list(urls)
        else:
            retry_urls = []

        for url in retry_urls:
            self._stats["extract_headed_retries"] += 1
            headed_result = await self._extract_single_headed(
                url,
                session_service,
                browser_service,
                content_mode,
                max_text_length,
                refine_query,
            )
            by_url[url] = {**headed_result, "url": url}

        cleaned = []
        for u in urls:
            result = by_url.get(u)
            if result is None:
                result = {
                    "url": u,
                    "success": False,
                    "error": ChallengeResolver.agent_error(),
                }
            cleaned.append(self._public_result(result))

        total_ms = int((time.monotonic() - start) * 1000)
        ok = sum(1 for r in cleaned if r.get("success"))
        fail = len(cleaned) - ok
        self._stats["extract_calls"] += 1
        self._stats["extract_successes"] += ok
        self._stats["extract_failures"] += fail
        n = self._stats["extract_calls"]
        self._stats["avg_extract_ms"] = round(
            self._stats["avg_extract_ms"]
            + (total_ms - self._stats["avg_extract_ms"]) / n,
            1,
        )

        return {"success": True, "results": cleaned, "total_ms": total_ms}

    async def _extract_batch_headless(
        self,
        urls: List[str],
        session_service,
        browser_service,
        content_mode: str,
        max_text_length: int,
        refine_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        async def _bounded(url: str) -> Dict[str, Any]:
            async with self._semaphore:
                try:
                    return await asyncio.wait_for(
                        self._extract_single(
                            url,
                            session_service,
                            browser_service,
                            content_mode,
                            max_text_length,
                            refine_query=refine_query,
                            headed=False,
                        ),
                        timeout=settings.search_extract_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning("search_extract_headless_timeout", url=url)
                    return {
                        "url": url,
                        "success": False,
                        "error": "Global timeout",
                        "ms": settings.search_extract_timeout * 1000,
                    }

        results = await asyncio.gather(
            *[_bounded(u) for u in urls], return_exceptions=True
        )

        cleaned: List[Dict[str, Any]] = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                cleaned.append({"url": url, "success": False, "error": str(result)})
            else:
                cleaned.append(result)
        return cleaned

    async def _extract_single_headed(
        self,
        url: str,
        session_service,
        browser_service,
        content_mode: str,
        max_text_length: int,
        refine_query: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with self._headed_semaphore:
            try:
                return await asyncio.wait_for(
                    self._extract_single(
                        url,
                        session_service,
                        browser_service,
                        content_mode,
                        max_text_length,
                        refine_query=refine_query,
                        headed=True,
                    ),
                    timeout=settings.search_extract_timeout_headed,
                )
            except asyncio.TimeoutError:
                logger.warning("search_extract_headed_timeout", url=url)
                return {
                    "url": url,
                    "success": False,
                    "error": "Global timeout",
                    "ms": settings.search_extract_timeout_headed * 1000,
                }

    async def _extract_single(
        self,
        url: str,
        session_service,
        browser_service,
        content_mode: str,
        max_text_length: int,
        *,
        refine_query: Optional[str] = None,
        headed: bool,
    ) -> Dict[str, Any]:
        start = time.monotonic()
        session = None
        nav_timeout = (
            settings.search_nav_timeout_headed
            if headed
            else settings.search_nav_timeout_headless
        )
        try:
            user_config: Dict[str, Any] = {
                "profile_id": f"_search_{uuid.uuid4().hex[:6]}",
                "persist_profile": False,
                "headed": headed,
                "silent": not headed,
                "background_headed": True,
                "block_mode": "conservative",
                "content_mode": content_mode,
            }
            if headed and settings.enable_stealth:
                user_config["stealth"] = True

            session = await session_service.create_session(
                user_config=user_config,
                pool="search",
            )
            sid = session.session_id
            challenge_outcome = None
            async with session_service.session_operation(sid, "search_extract") as sess:
                await browser_service.navigate_to_url(sess, url, timeout=nav_timeout)
                if headed:
                    challenge_outcome = await ChallengeResolver.resolve_headed(
                        sess.page
                    )
                else:
                    await ChallengeResolver.wait_passive(
                        sess.page, settings.search_challenge_wait_headless
                    )
                obs = await self._observe_extract(
                    browser_service, sess, content_mode, max_text_length
                )
                structured = await browser_service.observe_structured(sess)
                refined = await ContentRefiner.refine(
                    structured,
                    query=refine_query,
                    title=_clean_text(structured.get("title", "")),
                    url=structured.get("url", url),
                )

            ms = int((time.monotonic() - start) * 1000)
            raw_text = refined.get("markdown") or obs.get("visible_text", "")
            title = _clean_text(refined.get("title") or obs.get("title", ""))

            if ChallengeResolver.is_challenge_page(title, raw_text):
                logger.info(
                    "search_extract_challenge_blocked",
                    url=url,
                    headed=headed,
                    challenge_outcome=challenge_outcome,
                    page_url=obs.get("url", url),
                )
                return {
                    "url": url,
                    "success": False,
                    "error": ChallengeResolver.agent_error(),
                    "challenge_blocked": True,
                    "ms": ms,
                }

            cleaned_text = _clean_text(raw_text)
            use_flat_fallback = (
                refined.get("section_count", 0) == 0
                or refined.get("chars", 0) < settings.search_min_content_chars
            )
            if use_flat_fallback:
                fallback_text = _clean_text(obs.get("visible_text", ""))
                if len(fallback_text) > len(cleaned_text):
                    logger.info(
                        "search_extract_structured_fallback",
                        url=url,
                        sections=refined.get("section_count"),
                        refined_chars=refined.get("chars"),
                        flat_chars=len(fallback_text),
                    )
                    cleaned_text = fallback_text
                    content = self._to_markdown(
                        title, cleaned_text, obs.get("url", url)
                    )
                    tokens = max(1, len(cleaned_text) // 4)
                elif len(cleaned_text) < settings.search_min_content_chars:
                    logger.info(
                        "search_extract_insufficient_content",
                        url=url,
                        headed=headed,
                        chars=len(cleaned_text),
                        blocks=refined.get("block_count"),
                        content_mode=obs.get("content_mode", content_mode),
                    )
                    return {
                        "url": url,
                        "success": False,
                        "error": "Insufficient content",
                        "ms": ms,
                    }
                else:
                    content = refined.get("markdown") or self._to_markdown(
                        title, cleaned_text, obs.get("url", url)
                    )
                    tokens = refined.get("tokens") or max(1, len(cleaned_text) // 4)
            else:
                content = refined.get("markdown") or self._to_markdown(
                    title, cleaned_text, obs.get("url", url)
                )
                tokens = refined.get("tokens") or max(1, len(cleaned_text) // 4)

            logger.info(
                "search_extract_ok",
                url=url,
                headed=headed,
                challenge_outcome=challenge_outcome,
                page_url=obs.get("url", url),
                ms=ms,
                sections=refined.get("section_count"),
                dropped=refined.get("dropped_sections"),
            )
            return {
                "url": url,
                "title": title,
                "content": content,
                "tokens": tokens,
                "success": True,
                "ms": ms,
                "sections": refined.get("section_count"),
            }
        except Exception as exc:
            ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "search_extract_failed", url=url, headed=headed, error=str(exc)
            )
            return {"url": url, "success": False, "error": str(exc), "ms": ms}
        finally:
            if session:
                try:
                    await session_service.close_session(session.session_id, force=True)
                except Exception:
                    pass

    def get_stats(self) -> Dict[str, Any]:
        s = self._stats
        total = s["search_calls"]
        rate = round(s["search_successes"] / total * 100, 1) if total else 0.0
        return {
            **s,
            "searxng_success_rate": (
                round(s["searxng_successes"] / s["searxng_calls"] * 100, 1)
                if s["searxng_calls"]
                else 0.0
            ),
            "exa_success_rate": (
                round(s["exa_successes"] / s["exa_calls"] * 100, 1)
                if s["exa_calls"]
                else 0.0
            ),
            "search_success_rate": rate,
            "embedder_active": is_embedder_available(),
        }

    async def _observe_extract(
        self,
        browser_service,
        session,
        content_mode: str,
        max_text_length: int,
    ) -> Dict[str, Any]:
        """Observe page text, falling back to compact/full when reader output is too thin."""
        obs = await browser_service.observe_page(
            session, content_mode=content_mode, max_text_length=max_text_length
        )
        if content_mode != "reader":
            return obs

        text = _clean_text(obs.get("visible_text", ""))
        if len(text) >= settings.search_min_content_chars:
            return obs

        for fallback_mode in ("compact", "full"):
            fallback = await browser_service.observe_page(
                session, content_mode=fallback_mode, max_text_length=max_text_length
            )
            fallback_text = _clean_text(fallback.get("visible_text", ""))
            if len(fallback_text) > len(text):
                logger.info(
                    "search_extract_reader_fallback",
                    url=fallback.get("url"),
                    from_chars=len(text),
                    to_chars=len(fallback_text),
                    fallback_mode=fallback_mode,
                )
                obs = fallback
                text = fallback_text
            if len(text) >= settings.search_min_content_chars:
                break
        return obs

    @staticmethod
    def _public_result(result: Dict[str, Any]) -> Dict[str, Any]:
        public = {
            "url": result.get("url"),
            "success": bool(result.get("success")),
            "ms": result.get("ms"),
        }
        if result.get("success"):
            public["title"] = result.get("title", "")
            public["content"] = result.get("content", "")
            public["tokens"] = result.get("tokens", 0)
        else:
            error = result.get("error") or ChallengeResolver.agent_error()
            if result.get(
                "challenge_blocked"
            ) or ChallengeResolver.is_retryable_failure(result):
                error = ChallengeResolver.agent_error()
            public["error"] = error
        return public

    @staticmethod
    def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Final normalization pass on provider results (cleans and fills defaults)."""
        return {
            "title": _clean_text(raw.get("title", "")),
            "snippet": _clean_text(raw.get("snippet", "")),
            "url": raw.get("url", ""),
            "source": raw.get("source"),
            "published": raw.get("published"),
        }

    @staticmethod
    def _dedup(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: Dict[str, Dict[str, Any]] = {}
        for r in results:
            url = str(r.get("url", "")).lower().strip()
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
