#!/usr/bin/env python3
"""Run search+extract ETL and save stage-by-stage artifacts for inspection."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_QUERIES = [
    "India stock market outlook 2026 Nifty Sensex forecast",
    "India bond market RBI monetary policy 2026",
    "India FII DII flows equity market 2025 2026",
    "India financial sector banking NBFC outlook 2026",
    "India IPO market SME listings 2026",
    "India rupee outlook debt yields 2026",
]


def _slug_from_url(url: str) -> str:
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0])
    path = re.sub(r"[^a-z0-9]+", "-", url.split(host, 1)[-1].lower()).strip("-")[:48]
    return f"{host}-{path}" if path else host


def _save_markdown_samples(
    results: List[Dict[str, Any]],
    out_dir: Path,
    *,
    count: int,
    run_id: str,
) -> List[Path]:
    """Write full extracted markdown for the top N successful URLs."""
    saved: List[Path] = []
    successful = [r for r in results if r.get("success") and r.get("content")]
    for idx, r in enumerate(successful[:count], start=1):
        slug = _slug_from_url(r.get("url", f"sample-{idx}"))
        path = out_dir / f"{run_id}-sample-{idx}-{slug}.md"
        lines = [
            f"<!-- etl-run: {run_id} -->",
            f"<!-- url: {r.get('url')} -->",
            f"<!-- extracted_ms: {r.get('ms')} -->",
            "",
            r.get("content", ""),
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        saved.append(path)
    return saved


def _trim_result(r: Dict[str, Any], *, include_content: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "url": r.get("url"),
        "success": bool(r.get("success")),
        "ms": r.get("ms"),
    }
    if r.get("success"):
        out["title"] = r.get("title", "")
        out["tokens"] = r.get("tokens", 0)
        if include_content:
            out["content"] = r.get("content", "")
        else:
            content = r.get("content", "") or ""
            out["content_preview"] = content[:500]
    else:
        out["error"] = r.get("error")
        if r.get("challenge_blocked"):
            out["challenge_blocked"] = True
    return out


async def run_etl(
    queries: List[str],
    *,
    max_results: int,
    max_extract_urls: int,
    include_content: bool,
    refine_query: Optional[str] = None,
) -> Dict[str, Any]:
    from core.foundation import cleanup_services, get_search_service
    from services.challenge_resolver import ChallengeResolver

    service = await get_search_service()
    run: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "queries": [],
        "search_hits": [],
        "extract_plan": {},
        "stages": {},
        "final": {},
        "stats": {},
    }

    try:
        all_hits: Dict[str, Dict[str, Any]] = {}
        for q in queries:
            search_out = await service.search(q, max_results=max_results)
            q_record = {
                "query": q,
                "success": search_out.get("success"),
                "ms": search_out.get("ms"),
                "result_count": len(search_out.get("results") or []),
                "error": search_out.get("error"),
            }
            run["queries"].append(q_record)
            if not search_out.get("success"):
                continue
            for hit in search_out.get("results") or []:
                url = hit.get("url")
                if not url:
                    continue
                prev = all_hits.get(url)
                if prev is None or hit.get("relevance", 0) > prev.get("relevance", 0):
                    all_hits[url] = hit

        ranked = sorted(all_hits.values(), key=lambda h: h.get("relevance", 0), reverse=True)
        run["search_hits"] = [
            {
                "url": h.get("url"),
                "title": h.get("title"),
                "snippet": (h.get("snippet") or "")[:240],
                "relevance": h.get("relevance"),
            }
            for h in ranked
        ]

        urls = [h["url"] for h in ranked[:max_extract_urls]]
        relevance = {h["url"]: h.get("relevance", 0.0) for h in ranked[:max_extract_urls]}
        run["extract_plan"] = {
            "url_count": len(urls),
            "relevance_threshold": float(os.getenv("SURF_SEARCH_HEADED_RELEVANCE_THRESHOLD", "0.7")),
            "urls": urls,
            "relevance": relevance,
        }

        from core.foundation import get_session_service, get_browser_service

        session_service = await get_session_service()
        browser_service = await get_browser_service()

        headless_raw = await service._extract_batch_headless(
            urls, session_service, browser_service, "reader", 8000, refine_query
        )
        headless_by_url = {u: r for u, r in zip(urls, headless_raw)}
        run["stages"]["headless"] = [
            _trim_result({**r, "url": u}, include_content=include_content)
            for u, r in zip(urls, headless_raw)
        ]

        retry_urls = [
            u
            for u in urls
            if ChallengeResolver.should_headed_retry(
                u, headless_by_url.get(u, {"success": False}), relevance
            )
        ]
        run["extract_plan"]["headed_retry_urls"] = retry_urls
        run["extract_plan"]["headed_retry_reasons"] = {
            u: {
                "relevance": relevance.get(u, 0.0),
                "headless_success": bool(headless_by_url.get(u, {}).get("success")),
                "headless_error": headless_by_url.get(u, {}).get("error"),
                "challenge_blocked": bool(headless_by_url.get(u, {}).get("challenge_blocked")),
                "retryable": ChallengeResolver.is_retryable_failure(headless_by_url.get(u, {})),
            }
            for u in retry_urls
        }

        headed_raw: List[Dict[str, Any]] = []
        for url in retry_urls:
            headed_raw.append(
                await service._extract_single_headed(
                    url, session_service, browser_service, "reader", 8000, refine_query
                )
            )
        run["stages"]["headed_retry"] = [
            _trim_result(r, include_content=include_content) for r in headed_raw
        ]

        final_by_url = dict(headless_by_url)
        for url, r in zip(retry_urls, headed_raw):
            final_by_url[url] = {**r, "url": url}

        final_public = [service._public_result(final_by_url.get(u, {"url": u, "success": False})) for u in urls]
        run["final"] = {
            "results": [_trim_result(r, include_content=include_content) for r in final_public],
            "success_count": sum(1 for r in final_public if r.get("success")),
            "failure_count": sum(1 for r in final_public if not r.get("success")),
        }
        run["_full_results"] = final_public
        run["stats"] = service.get_stats()
        run["finished_at"] = datetime.now(timezone.utc).isoformat()
        return run
    finally:
        await cleanup_services()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SURF search ETL and save artifacts")
    parser.add_argument("--topic", default="indian financial markets outlook 2026")
    parser.add_argument("--query", action="append", dest="queries", help="Override search queries")
    parser.add_argument("--max-results", type=int, default=8)
    parser.add_argument("--max-extract", type=int, default=10)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--full-content", action="store_true", help="Include full extracted markdown in JSON")
    parser.add_argument(
        "--markdown-samples",
        type=int,
        default=3,
        help="Save full markdown files for this many successful extractions (0 to disable)",
    )
    parser.add_argument("--searxng-url", default=os.getenv("SURF_SEARXNG_BASE_URL", "http://localhost:8888"))
    args = parser.parse_args()

    os.environ["SURF_SEARXNG_BASE_URL"] = args.searxng_url
    os.environ.setdefault("SURF_LOG_LEVEL", "ERROR")

    queries = args.queries or DEFAULT_QUERIES
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = args.output or (ROOT / "research" / f"etl-run-{run_id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    payload = asyncio.run(
        run_etl(
            queries,
            max_results=args.max_results,
            max_extract_urls=args.max_extract,
            include_content=args.full_content,
            refine_query=args.topic,
        )
    )
    payload["topic"] = args.topic
    full_results = payload.pop("_full_results", payload.get("final", {}).get("results", []))
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    markdown_paths: List[Path] = []
    if args.markdown_samples > 0:
        markdown_paths = _save_markdown_samples(
            full_results,
            out.parent,
            count=args.markdown_samples,
            run_id=run_id,
        )
        payload["markdown_samples"] = [str(p) for p in markdown_paths]

    print(f"Saved ETL artifact: {out}")
    for p in markdown_paths:
        print(f"Saved markdown sample: {p}")
    print(
        f"Search hits: {len(payload.get('search_hits', []))} | "
        f"Extracted: {payload.get('final', {}).get('success_count', 0)}/"
        f"{payload.get('extract_plan', {}).get('url_count', 0)} | "
        f"Headed retries: {len(payload.get('extract_plan', {}).get('headed_retry_urls', []))}"
    )
    for r in payload.get("final", {}).get("results", []):
        status = "OK" if r.get("success") else "FAIL"
        err = f" — {r.get('error')}" if not r.get("success") else ""
        print(f"  [{status}] {r.get('url')} ({r.get('ms')}ms){err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
