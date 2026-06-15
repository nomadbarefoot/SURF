#!/usr/bin/env python3
"""Probe structured extraction + refinement on diverse sites."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SITES = {
    "dailyfinancial": (
        "https://dailyfinancial.in/indian-stock-market-trends-sensex-nifty-insights-2026-predictions-for-savvy-investors/",
        "India stock market outlook 2026 Nifty Sensex forecast",
    ),
    "swapxtimes": (
        "https://swapxtimes.com/india-stock-market-2026.html",
        "India stock market outlook 2026 Nifty Sensex forecast",
    ),
    "timesofindia": (
        "https://timesofindia.indiatimes.com/business/india-business/stock-market-outlook-2026-why-did-sensex-nifty-underperform-in-2025-where-are-indices-headed-next-year-top-things-to-know/articleshow/126273827.cms",
        "India stock market outlook 2026 Nifty Sensex forecast",
    ),
    "taxguru": (
        "https://taxguru.in/rbi/rbi-policy-february-2026-key-rates-measures.html",
        "India bond market RBI monetary policy 2026",
    ),
}


async def probe_site(name: str, url: str, query: str) -> dict:
    from core.foundation import cleanup_services, get_browser_service, get_session_service
    from services.search_service import SearchService

    svc = SearchService()
    ss = await get_session_service()
    bs = await get_browser_service()
    try:
        result = await svc._extract_single(
            url, ss, bs, "reader", 12000, refine_query=query, headed=False
        )
        content = result.get("content") or ""
        return {
            "name": name,
            "url": url,
            "query": query,
            "success": result.get("success"),
            "tokens": result.get("tokens"),
            "sections": result.get("sections"),
            "ms": result.get("ms"),
            "error": result.get("error"),
            "has_h2": "## " in content,
            "has_table": "| --- |" in content or "|--" in content,
            "has_disclaimer": "disclaimer" in content.lower(),
            "has_related": "related stories" in content.lower(),
            "preview": content[:1200],
            "content_length": len(content),
        }
    finally:
        await cleanup_services()


async def run(names: list[str], output: Path) -> int:
    os.environ.setdefault("SURF_LOG_LEVEL", "ERROR")
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "sites": []}

    for name in names:
        url, query = SITES[name]
        print(f"\n--- {name} ---")
        row = await probe_site(name, url, query)
        report["sites"].append(row)
        status = "OK" if row["success"] else "FAIL"
        print(
            f"  [{status}] tokens={row.get('tokens')} sections={row.get('sections')} "
            f"h2={row.get('has_h2')} table={row.get('has_table')} "
            f"disclaimer={row.get('has_disclaimer')} related={row.get('has_related')} ({row.get('ms')}ms)"
        )
        if not row.get("success"):
            print(f"  error: {row.get('error')}")

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved: {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", action="append", choices=sorted(SITES.keys()))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    names = sorted(SITES.keys()) if args.all else (args.site or ["dailyfinancial", "swapxtimes", "taxguru"])
    out = args.output or ROOT / "research" / f"structured-extract-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    return asyncio.run(run(names, out))


if __name__ == "__main__":
    raise SystemExit(main())
