#!/usr/bin/env python3
"""surf - CLI for the SURF web research service.

Config via environment variables:
  SURF_URL          Host and port of the SURF service, e.g. localhost:17777 (required)
  SURF_API_TOKEN    Bearer token when SURF_AUTH_MODE=token (optional)

Usage:
  surf search "<query>" [--max-results N]
  surf extract <url> [<url>...]
  surf fetch <url>
  surf preflight
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


def _request(
    method: str,
    url: str,
    payload: dict | None = None,
    timeout: float = _TIMEOUT,
    allow_http_errors: bool = False,
) -> httpx.Response:
    try:
        resp = httpx.request(
            method,
            url,
            json=payload,
            headers=_headers(),
            timeout=timeout,
        )
        if not allow_http_errors:
            resp.raise_for_status()
        return resp
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


def _post(url: str, payload: dict, timeout: float = _TIMEOUT) -> dict:
    return _request("POST", url, payload, timeout).json()


def _json_response(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {"success": False, "error": response.text}
    return body if isinstance(body, dict) else {"data": body}


def _fetch_data(response: dict) -> dict:
    """Unwrap the server's FetchResponse.data envelope."""
    data = response.get("data")
    return data if isinstance(data, dict) else response


def _extract_failure_count(data: dict) -> int:
    reported = data.get("failure_count")
    if isinstance(reported, int):
        return reported
    return sum(1 for result in data.get("results", []) if result.get("error"))


def _print_json(data: dict) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_search(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _post(
        f"{base}/search/query",
        {"query": args.query, "max_results": args.max_results},
        args.timeout,
    )

    if args.json:
        _print_json(data)
        return

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
    data = _post(
        f"{base}/search/extract",
        {"urls": args.urls},
        args.timeout,
    )

    if args.json:
        _print_json(data)
        if _extract_failure_count(data) or data.get("success") is False:
            sys.exit(1)
        return

    results = data.get("results", [])
    if not results:
        print("No extraction results.", file=sys.stderr)
        sys.exit(1)

    for r in results:
        url = r.get("url") or ""
        print(f"=== {url} ===")
        if r.get("error"):
            print(f"Error: {r['error']}", file=sys.stderr)
        content = r.get("content") or r.get("text") or ""
        if content:
            print(content)
        print()

    if _extract_failure_count(data) or data.get("success") is False:
        sys.exit(1)


def cmd_fetch(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _post(
        f"{base}/fetch/request",
        {"method": "GET", "url": args.url},
        args.timeout,
    )

    if args.json:
        _print_json(data)
        return

    # Prefer the text body; fall back to raw JSON for structured responses
    result = _fetch_data(data)
    content = result.get("content") or result.get("body") or result.get("text")
    if content is None:
        structured = result.get("json")
        content = (
            json.dumps(structured, indent=2)
            if structured is not None
            else json.dumps(result, indent=2)
        )
    print(content)


def cmd_preflight(args: argparse.Namespace) -> None:
    """Run non-mutating service, runtime, SearXNG, and outbound probes."""
    base = _base_url()
    checks = [
        ("service", "GET", "/health/live", None),
        ("browser runtime", "GET", "/health/runtime", None),
        ("SearXNG", "GET", "/health/searxng", None),
        (
            "outbound fetch",
            "POST",
            "/fetch/request",
            {"method": "GET", "url": args.probe_url},
        ),
    ]
    results = []
    for name, method, path, payload in checks:
        try:
            response = _request(
                method,
                f"{base}{path}",
                payload,
                args.timeout,
                allow_http_errors=True,
            )
            body = _json_response(response)
            passed = response.is_success and body.get("success", True) is not False
            results.append(
                {
                    "name": name,
                    "ok": passed,
                    "status_code": response.status_code,
                    "body": body,
                }
            )
        except SystemExit:
            results.append({"name": name, "ok": False, "error": "request failed"})

    if args.json:
        _print_json({"success": all(item["ok"] for item in results), "checks": results})
    else:
        for item in results:
            state = "ok" if item["ok"] else "fail"
            detail = item.get("status_code", item.get("error", "unknown"))
            print(f"[{state}] {item['name']}: {detail}")

    if not all(item["ok"] for item in results):
        sys.exit(1)


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
    p_search.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_search.add_argument("--json", action="store_true", help="Print the raw JSON response")

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
    p_extract.add_argument(
        "--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds"
    )
    p_extract.add_argument("--json", action="store_true", help="Print the raw JSON response")

    # fetch
    p_fetch = sub.add_parser(
        "fetch",
        help="Direct HTTP fetch of a single URL",
        description="Issue a raw GET request via SURF's fetch endpoint.",
    )
    p_fetch.add_argument("url", help="URL to fetch")
    p_fetch.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_fetch.add_argument("--json", action="store_true", help="Print the raw JSON response")

    p_preflight = sub.add_parser(
        "preflight",
        help="Probe service dependencies and outbound access",
        description="Run non-mutating readiness probes against SURF.",
    )
    p_preflight.add_argument(
        "--probe-url",
        default="https://example.com",
        help="URL used for the outbound fetch probe (default: https://example.com)",
    )
    p_preflight.add_argument(
        "--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds"
    )
    p_preflight.add_argument("--json", action="store_true", help="Print JSON results")

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
    elif args.command == "preflight":
        cmd_preflight(args)


if __name__ == "__main__":
    main()
