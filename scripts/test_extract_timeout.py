#!/usr/bin/env python3
"""Isolated test: headed timeout budget — verifies page is not torn down early."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.search_extract_harness import (  # noqa: E402
    apply_env_overrides,
    base_parser,
    print_result,
    resolve_urls,
    run_extract,
)


async def main() -> int:
    parser = base_parser("Test headed timeout — uses long challenge wait to simulate slow CF")
    parser.add_argument(
        "--min-ms",
        type=int,
        default=30000,
        help="Fail if total_ms is below this (detects early teardown)",
    )
    args = parser.parse_args()
    apply_env_overrides(args)
    os.environ["SURF_SEARCH_EXTRACT_TIMEOUT_HEADED"] = str(args.headed_timeout or 180)
    os.environ["SURF_SEARCH_NAV_TIMEOUT_HEADED"] = "60000"
    os.environ["SURF_SEARCH_CHALLENGE_WAIT_HEADED"] = str(args.challenge_wait or 45000)

    urls = resolve_urls(args)
    t0 = time.monotonic()
    payload = await run_extract(
        urls,
        relevance=None,
        force_headed=True,
        skip_headless=True,
    )
    elapsed = int((time.monotonic() - t0) * 1000)
    payload["wall_ms"] = elapsed

    rc = print_result("timeout", payload)
    total_ms = payload.get("total_ms") or 0
    if total_ms < args.min_ms and not any(r.get("success") for r in payload.get("results", [])):
        print(f"\nWARN: completed in {total_ms}ms (< {args.min_ms}ms) — possible early timeout teardown")
        return 2
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
