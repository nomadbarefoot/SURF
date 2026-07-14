#!/usr/bin/env python3
"""surf - CLI for the SURF web research service.

Config via environment variables:
  SURF_URL          Host and port of the SURF service, e.g. localhost:17777 (required)
  SURF_API_TOKEN    Bearer token when SURF_AUTH_MODE=token (optional)

Usage:
  surf search "<query>" [--max-results N]
  surf extract <url> [<url>...]
  surf fetch <url>
"""

import argparse
import json
import os
import sys

import httpx

_TIMEOUT = 30.0


def _base_url() -> str:
    raw = os.environ.get("SURF_URL", "").strip()
    if not raw:
        print(
            "Error: SURF_URL is not set. "
            "Set SURF_URL=host:port (e.g. localhost:17777)",
            file=sys.stderr,
        )
        sys.exit(2)
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = f"http://{raw}"
    return raw.rstrip("/")


def _headers() -> dict:
    token = os.environ.get("SURF_API_TOKEN", "").strip()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _post(url: str, payload: dict) -> dict:
    try:
        resp = httpx.post(url, json=payload, headers=_headers(), timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
            detail = (
                body.get("error", {}).get("message")
                or body.get("detail")
                or exc.response.text
            )
        except Exception:
            detail = exc.response.text
        print(f"Error: HTTP {exc.response.status_code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as exc:
        print(f"Error: could not reach SURF at {_base_url()}: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_search(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _post(
        f"{base}/search/query",
        {"query": args.query, "max_results": args.max_results},
    )

    results = data.get("results", [])
    if not results:
        msg = data.get("error") or "No results returned."
        if not data.get("success", True):
            print(f"Warning: {msg}", file=sys.stderr)
        else:
            print("No results.", file=sys.stderr)
        return

    for i, r in enumerate(results, 1):
        title = r.get("title") or "(no title)"
        url = r.get("url") or ""
        snippet = (r.get("snippet") or "").strip()
        print(f"{i}. {title}")
        print(f"   {url}")
        if snippet:
            print(f"   {snippet}")
        print()


def cmd_extract(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _post(f"{base}/search/extract", {"urls": args.urls})

    results = data.get("results", [])
    if not results:
        print("No extraction results.", file=sys.stderr)
        sys.exit(1)

    for r in results:
        url = r.get("url") or ""
        print(f"=== {url} ===")
        if r.get("error"):
            print(f"Error: {r['error']}", file=sys.stderr)
        else:
            content = r.get("content") or r.get("text") or ""
            print(content)
        print()


def cmd_fetch(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _post(f"{base}/fetch/request", {"method": "GET", "url": args.url})

    # Prefer the text body; fall back to raw JSON for structured responses
    content = data.get("content") or data.get("body") or data.get("text")
    if content is None:
        content = json.dumps(data, indent=2)
    print(content)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surf",
        description="CLI for the SURF web research service.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  SURF_URL          host:port of the SURF service (required)\n"
            "  SURF_API_TOKEN    bearer token when SURF_AUTH_MODE=token\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # search
    p_search = sub.add_parser(
        "search",
        help="Run a web search query",
        description="Query the SURF search endpoint and print numbered results.",
    )
    p_search.add_argument("query", help="Search query string")
    p_search.add_argument(
        "--max-results",
        type=int,
        default=5,
        metavar="N",
        help="Maximum number of results to return (default: 5)",
    )

    # extract
    p_extract = sub.add_parser(
        "extract",
        help="Extract page content from one or more URLs",
        description=(
            "Fetch and extract readable content from one or more URLs "
            "using SURF's parallel extraction pipeline."
        ),
    )
    p_extract.add_argument("urls", nargs="+", metavar="url", help="URL(s) to extract")

    # fetch
    p_fetch = sub.add_parser(
        "fetch",
        help="Direct HTTP fetch of a single URL",
        description="Issue a raw GET request via SURF's fetch endpoint.",
    )
    p_fetch.add_argument("url", help="URL to fetch")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "search":
        cmd_search(args)
    elif args.command == "extract":
        cmd_extract(args)
    elif args.command == "fetch":
        cmd_fetch(args)


if __name__ == "__main__":
    main()
