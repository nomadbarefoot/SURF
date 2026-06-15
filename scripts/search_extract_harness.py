#!/usr/bin/env python3
"""Shared harness for isolated search-extract integration tests."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Known failure URLs from india-financial-markets research (2026-06-16).
FAILED_URLS = {
    "timesofindia": "https://timesofindia.indiatimes.com/markets/stocks/news",
    "fortuneindia": "https://www.fortuneindia.com/investing",
    "financialexpress_ok": "https://www.financialexpress.com/market/is-india-in-an-epic-bubble-here-is-what-6-market-gurus-forecast-about-2026-4089572/",
    "longforecast": "https://www.longforecast.com/sensex-forecast",
    "gripinvest_ok": "https://www.gripinvest.in/blog/sensex-returns-outlook",
}

DEFAULT_RELEVANCE = {url: 0.95 for url in FAILED_URLS.values()}


def print_result(label: str, payload: Dict[str, Any]) -> int:
    print(f"\n=== {label} ===")
    print(json.dumps(payload, indent=2, default=str)[:8000])
    results = payload.get("results") or []
    ok = sum(1 for r in results if r.get("success"))
    print(f"\nSummary: {ok}/{len(results)} succeeded, total_ms={payload.get('total_ms')}")
    for r in results:
        status = "OK" if r.get("success") else "FAIL"
        err = f" — {r.get('error')}" if not r.get("success") else ""
        print(f"  [{status}] {r.get('url')} ({r.get('ms')}ms){err}")
    return 0 if ok else 1


async def run_extract(
    urls: List[str],
    *,
    relevance: Optional[Dict[str, float]] = None,
    force_headed: bool = False,
    skip_headless: bool = False,
    content_mode: str = "reader",
    max_text_length: int = 8000,
) -> Dict[str, Any]:
    from core.foundation import cleanup_services, get_search_service

    service = await get_search_service()
    try:
        return await service.deep_extract(
            urls=urls,
            content_mode=content_mode,
            max_text_length=max_text_length,
            relevance=relevance,
            force_headed=force_headed,
            skip_headless=skip_headless,
        )
    finally:
        await cleanup_services()


def apply_env_overrides(args: argparse.Namespace) -> None:
    if args.searxng_url:
        os.environ["SURF_SEARXNG_BASE_URL"] = args.searxng_url
    if args.headed_timeout:
        os.environ["SURF_SEARCH_EXTRACT_TIMEOUT_HEADED"] = str(args.headed_timeout)
    if args.headless_timeout:
        os.environ["SURF_SEARCH_EXTRACT_TIMEOUT"] = str(args.headless_timeout)
    if args.challenge_wait:
        os.environ["SURF_SEARCH_CHALLENGE_WAIT_HEADED"] = str(args.challenge_wait)
    _reload_settings()


def _reload_settings() -> None:
    from config.settings import get_settings

    get_settings.cache_clear()
    import config.settings as settings_mod
    import services.challenge_resolver as challenge_mod
    import services.search_service as search_mod

    settings_mod.settings = get_settings()
    challenge_mod.settings = settings_mod.settings
    search_mod.settings = settings_mod.settings


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--url", action="append", dest="urls", help="URL to extract (repeatable)")
    parser.add_argument("--preset", choices=sorted(FAILED_URLS.keys()), help="Named URL from research failures")
    parser.add_argument("--relevance", type=float, default=0.95, help="Relevance score for headed retry")
    parser.add_argument("--searxng-url", default=os.getenv("SURF_SEARXNG_BASE_URL"))
    parser.add_argument("--headed-timeout", type=int, default=None)
    parser.add_argument("--headless-timeout", type=int, default=None)
    parser.add_argument("--challenge-wait", type=int, default=None, help="Headed challenge wait ms")
    return parser


def resolve_urls(args: argparse.Namespace) -> List[str]:
    urls = list(args.urls or [])
    if args.preset:
        urls.append(FAILED_URLS[args.preset])
    if not urls:
        urls = [FAILED_URLS["gripinvest_ok"]]
    return urls


def relevance_for(urls: List[str], score: float) -> Dict[str, float]:
    return {u: score for u in urls}
