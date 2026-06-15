#!/usr/bin/env python3
"""Isolated test: headless extraction path only."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.search_extract_harness import (  # noqa: E402
    apply_env_overrides,
    base_parser,
    print_result,
    relevance_for,
    resolve_urls,
    run_extract,
)


async def main() -> int:
    parser = base_parser("Test headless search extraction (no headed retry)")
    args = parser.parse_args()
    apply_env_overrides(args)
    urls = resolve_urls(args)
    payload = await run_extract(
        urls,
        relevance=relevance_for(urls, args.relevance),
        force_headed=False,
        skip_headless=False,
    )
    return print_result("headless", payload)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
