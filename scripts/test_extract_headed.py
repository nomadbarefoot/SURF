#!/usr/bin/env python3
"""Isolated test: headed extraction with extended per-URL timeout."""
from __future__ import annotations

import asyncio
import os
import sys
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
    parser = base_parser("Test headed search extraction (skip headless, force headed)")
    args = parser.parse_args()
    apply_env_overrides(args)
    os.environ.setdefault("SURF_SEARCH_EXTRACT_TIMEOUT_HEADED", "180")
    os.environ.setdefault("SURF_SEARCH_NAV_TIMEOUT_HEADED", "60000")
    os.environ.setdefault("SURF_SEARCH_CHALLENGE_WAIT_HEADED", "45000")
    urls = resolve_urls(args)
    payload = await run_extract(
        urls,
        relevance=None,
        force_headed=True,
        skip_headless=True,
    )
    return print_result("headed", payload)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
