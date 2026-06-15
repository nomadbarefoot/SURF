#!/usr/bin/env python3
"""Probe candidate Cloudflare challenge URLs and test headed captcha resolution."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Known / likely CF challenge pages (Turnstile, interstitial, robot check).
CANDIDATE_URLS = {
    "longforecast": "https://www.longforecast.com/sensex-forecast",
    "longforecast_alt": "https://longforecast.com/sensex",
    "nowsecure": "https://nowsecure.nl/",
    "nopecha_demo": "https://nopecha.com/demo/cloudflare",
    "scrapingbee_cf": "https://www.scrapingbee.com/blog/how-to-bypass-cloudflare/",
    "timesofindia": "https://timesofindia.indiatimes.com/markets/stocks/news",
    "fortuneindia": "https://www.fortuneindia.com/investing",
    "crunchbase": "https://www.crunchbase.com/",
    "discord": "https://discord.com/invite/cloudflare",
}


async def probe_headless(url: str) -> Dict[str, Any]:
    from core.foundation import cleanup_services, get_browser_service, get_session_service
    from services.challenge_resolver import ChallengeResolver

    session_service = await get_session_service()
    browser_service = await get_browser_service()
    try:
        from services.search_service import SearchService

        svc = SearchService()
        result = await svc._extract_single(
            url, session_service, browser_service, "reader", 4000, headed=False
        )
        title = result.get("title", "")
        return {
            "url": url,
            "mode": "headless",
            "success": result.get("success"),
            "challenge_blocked": bool(result.get("challenge_blocked")),
            "error": result.get("error"),
            "ms": result.get("ms"),
            "likely_cf": bool(result.get("challenge_blocked"))
            or ChallengeResolver.is_retryable_failure(result),
        }
    finally:
        await cleanup_services()


async def probe_headed(url: str) -> Dict[str, Any]:
    from scripts.search_extract_harness import run_extract

    payload = await run_extract(
        [url],
        relevance=None,
        force_headed=True,
        skip_headless=True,
        max_text_length=4000,
    )
    r = (payload.get("results") or [{}])[0]
    return {
        "url": url,
        "mode": "headed",
        "success": r.get("success"),
        "error": r.get("error"),
        "ms": r.get("ms"),
        "title": r.get("title", ""),
        "content_preview": (r.get("content") or "")[:300],
    }


async def run_probe(names: List[str], output: Path) -> int:
    os.environ.setdefault("SURF_SEARCH_EXTRACT_TIMEOUT_HEADED", "180")
    os.environ.setdefault("SURF_SEARCH_NAV_TIMEOUT_HEADED", "60000")
    os.environ.setdefault("SURF_SEARCH_CHALLENGE_WAIT_HEADED", "45000")
    os.environ.setdefault("SURF_ENABLE_STEALTH", "true")
    os.environ.setdefault("SURF_ENABLE_ENHANCED_MOUSE_MOVEMENT", "true")

    report: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "candidates": [],
    }

    cf_targets: List[str] = []
    for name in names:
        url = CANDIDATE_URLS[name]
        print(f"\n--- Probing {name}: {url} ---")
        headless = await probe_headless(url)
        print(f"  headless: success={headless['success']} cf={headless['likely_cf']} ({headless.get('ms')}ms)")
        headed = None
        if not headless.get("success"):
            headed = await probe_headed(url)
            print(
                f"  headed:   success={headed['success']} ({headed.get('ms')}ms)"
                + (f" — {headed.get('error')}" if not headed.get("success") else "")
            )
        else:
            print("  headed:   skipped (headless succeeded)")
        if headless.get("likely_cf"):
            cf_targets.append(name)

        report["candidates"].append({"name": name, "headless": headless, "headed": headed})

    report["cf_like"] = cf_targets
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved CF probe report: {output}")
    print(f"CF-like URLs: {', '.join(cf_targets) if cf_targets else '(none)'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe CF challenge URLs")
    parser.add_argument("--preset", action="append", choices=sorted(CANDIDATE_URLS.keys()))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.all:
        names = sorted(CANDIDATE_URLS.keys())
    elif args.preset:
        names = args.preset
    else:
        names = ["longforecast", "nowsecure", "nopecha_demo"]

    out = args.output or (
        ROOT / "research" / f"cf-captcha-probe-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    )
    return asyncio.run(run_probe(names, out))


if __name__ == "__main__":
    raise SystemExit(main())
