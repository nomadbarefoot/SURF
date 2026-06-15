#!/usr/bin/env python3
"""Isolated test: headed challenge resolver (passive wait + click attempts)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.search_extract_harness import (  # noqa: E402
    FAILED_URLS,
    apply_env_overrides,
    base_parser,
    print_result,
    resolve_urls,
    run_extract,
)


async def main() -> int:
    parser = base_parser("Test headed challenge resolution on CF-protected pages")
    parser.set_defaults(preset="longforecast")
    args = parser.parse_args()
    apply_env_overrides(args)
    os.environ.setdefault("SURF_SEARCH_EXTRACT_TIMEOUT_HEADED", "180")
    os.environ.setdefault("SURF_SEARCH_NAV_TIMEOUT_HEADED", "60000")
    os.environ.setdefault("SURF_SEARCH_CHALLENGE_WAIT_HEADED", "45000")
    os.environ.setdefault("SURF_ENABLE_STEALTH", "true")
    os.environ.setdefault("SURF_ENABLE_ENHANCED_MOUSE_MOVEMENT", "true")

    urls = resolve_urls(args)
    if not args.urls and not args.preset:
        urls = [FAILED_URLS["longforecast"]]

    payload = await run_extract(
        urls,
        relevance=None,
        force_headed=True,
        skip_headless=True,
    )
    return print_result("challenge", payload)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
