#!/usr/bin/env python3
"""surf - CLI for the SURF web research service.

Config via environment variables:
  SURF_URL          Host and port of the SURF service, e.g. localhost:17777 (required)
  SURF_BROWSE_KEY   Read-oriented browser profile key
  SURF_UI_KEY       Interactive browser profile key
  SURF_OPS_KEY      Operations profile key

Usage:
  surf search "<query>" [--max-results N]
  surf extract <url> [<url>...]
  surf fetch <url>
  surf transcript <youtube-url>
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


def _profile_for_url(url: str) -> str | None:
    path = httpx.URL(url).path
    if path in {"/browser/interact", "/browser/press-key", "/browser/viewport", "/browser/batch"}:
        return "ui"
    if path.startswith(("/sessions/", "/browser/", "/browse/", "/downloads/")):
        return "browse"
    if path.startswith("/finance/"):
        return "finance"
    if path == "/health/runtime":
        return "browse"
    if path.startswith("/health/") and path not in {
        "/health/live",
        "/health/ready",
        "/health/searxng",
    }:
        return "ops"
    return None


def _headers(url: str, profile: str | None = None) -> dict:
    selected = profile or _profile_for_url(url)
    token = os.environ.get(f"SURF_{selected.upper()}_KEY", "").strip() if selected else ""
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _request(
    method: str,
    url: str,
    payload: dict | None = None,
    timeout: float = _TIMEOUT,
    allow_http_errors: bool = False,
    headers: dict | None = None,
) -> httpx.Response:
    try:
        request_headers = _headers(url)
        if headers:
            request_headers.update(headers)
        resp = httpx.request(
            method,
            url,
            json=payload,
            headers=request_headers,
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


def _post(
    url: str,
    payload: dict,
    timeout: float = _TIMEOUT,
    headers: dict | None = None,
) -> dict:
    return _request("POST", url, payload, timeout, headers=headers).json()


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


def cmd_transcript(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _post(
        f"{base}/youtube/transcript",
        {
            "url": args.url,
            "languages": args.languages or None,
            "allow_auto_captions": not args.no_auto_captions,
            "max_text_length": args.max_text_length,
        },
        args.timeout,
    )

    if args.json:
        _print_json(data)
        return

    content = data.get("content") or ""
    if content:
        print(content)
    artifact = data.get("artifact") or {}
    path = artifact.get("absolute_path") or artifact.get("path")
    if path:
        print(f"Saved full transcript: {path}", file=sys.stderr)


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
# Browser subcommand handlers
# ---------------------------------------------------------------------------


def _browser_payload(args: argparse.Namespace, extra: dict | None = None) -> dict:
    """Build a payload from argparse args, dropping None values."""
    payload = vars(args).copy()
    for key in (
        "command",
        "json",
        "timeout",
    ):
        payload.pop(key, None)
    payload = {k: v for k, v in payload.items() if v is not None}
    if extra:
        payload.update(extra)
    return payload


def cmd_browse(args: argparse.Namespace) -> None:
    """One-shot browse workflow."""
    base = _base_url()
    data = _browser_payload(args)
    data["url"] = args.url
    readiness = {}
    if args.wait_selector:
        readiness["selector"] = args.wait_selector
    if args.wait_text:
        readiness["text"] = args.wait_text
    if args.wait_url:
        readiness["url_contains"] = args.wait_url
    if args.wait_js:
        readiness["js_predicate"] = args.wait_js
    if args.dom_stable_ms:
        readiness["dom_stable_ms"] = args.dom_stable_ms
    if args.network_quiet_ms:
        readiness["network_quiet_ms"] = args.network_quiet_ms
    if readiness:
        data["readiness"] = readiness
    for key in (
        "wait_selector",
        "wait_text",
        "wait_url",
        "wait_js",
        "dom_stable_ms",
        "network_quiet_ms",
    ):
        data.pop(key, None)

    headers = _headers(f"{base}/browse/browse", "ui") if args.mode == "aggressive" else None
    result = _post(f"{base}/browse/browse", data, args.timeout, headers=headers)
    if args.json:
        _print_json(result)
    else:
        transition = result.get("transition", {})
        print(f"URL: {result.get('url', '')}")
        print(f"Title: {result.get('title', '')}")
        print(
            f"Settled: {transition.get('readiness_reason', 'unknown')} "
            f"({transition.get('elapsed_ms', 0)}ms)"
        )
        if result.get("challenge"):
            print(f"Challenge: {result['challenge']}", file=sys.stderr)
        content = result.get("content", "")
        if content:
            print(content)
        if result.get("screenshot_artifact"):
            print(
                f"Screenshot: {result['screenshot_artifact'].get('path', '')}",
                file=sys.stderr,
            )
        if result.get("session_id"):
            print(f"Session: {result['session_id']}", file=sys.stderr)

    if not result.get("success"):
        sys.exit(1)


def cmd_session_create(args: argparse.Namespace) -> None:
    base = _base_url()
    config = {
        "headed": args.headed,
        "persist_profile": args.persist_profile,
        "block_mode": args.block_mode,
        "content_mode": args.content_mode,
    }
    if args.profile_id:
        config["profile_id"] = args.profile_id
    result = _post(
        f"{base}/sessions/",
        {"config": config},
        args.timeout,
    )
    if args.json:
        _print_json(result)
    else:
        print(result.get("session_id", ""))


def cmd_session_close(args: argparse.Namespace) -> None:
    base = _base_url()
    suffix = "?force=true" if args.force else ""
    resp = _request("DELETE", f"{base}/sessions/{args.session_id}{suffix}", timeout=args.timeout)
    body = _json_response(resp)
    if args.json:
        _print_json(body)


def cmd_navigate(args: argparse.Namespace) -> None:
    base = _base_url()
    data = {
        "session_id": args.session_id,
        "url": args.url,
        "wait_until": args.wait_until,
    }
    if args.timeout:
        data["timeout"] = int(args.timeout * 1000)
    result = _post(f"{base}/browser/navigate", data, args.timeout)
    _output_or_exit(result, args)


def cmd_observe(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _browser_payload(args)
    data["session_id"] = args.session_id
    result = _post(f"{base}/browser/observe", data, args.timeout)
    _output_or_exit(result, args)


def cmd_screenshot(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _browser_payload(args)
    data["session_id"] = args.session_id
    result = _post(f"{base}/browser/screenshot", data, args.timeout)
    _output_or_exit(result, args)


def cmd_extract_page(args: argparse.Namespace) -> None:
    base = _base_url()
    if args.structured:
        data = {
            "session_id": args.session_id,
            "content_type": args.content_type,
        }
        if args.selector:
            data["selector"] = args.selector
        if args.timeout:
            data["timeout"] = int(args.timeout * 1000)
        result = _post(f"{base}/browser/extract-structured", data, args.timeout)
    else:
        data = {
            "session_id": args.session_id,
            "extract_type": args.extract_type,
        }
        if args.selector:
            data["selector"] = args.selector
        if args.timeout:
            data["timeout"] = int(args.timeout * 1000)
        result = _post(f"{base}/browser/extract", data, args.timeout)
    _output_or_exit(result, args)


def cmd_interact(args: argparse.Namespace) -> None:
    base = _base_url()
    action = getattr(args, "action", None) or args.command
    data = {
        "session_id": args.session_id,
        "action": action,
        "selector": args.selector,
    }
    if hasattr(args, "value") and args.value is not None:
        data["value"] = args.value
    if args.timeout:
        data["timeout"] = int(args.timeout * 1000)
    result = _post(f"{base}/browser/interact", data, args.timeout)
    _output_or_exit(result, args)


def cmd_scroll(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _browser_payload(args)
    data["session_id"] = args.session_id
    result = _post(f"{base}/browser/scroll", data, args.timeout)
    _output_or_exit(result, args)


def cmd_wait(args: argparse.Namespace) -> None:
    base = _base_url()
    data = _browser_payload(args)
    data["session_id"] = args.session_id
    if args.timeout:
        data["timeout"] = int(args.timeout * 1000)
    result = _post(f"{base}/browser/wait", data, args.timeout)
    _output_or_exit(result, args)


def cmd_challenge(args: argparse.Namespace) -> None:
    base = _base_url()
    data = {"session_id": args.session_id}
    if args.timeout:
        data["timeout"] = int(args.timeout * 1000)
    result = _post(f"{base}/browser/detect-captcha", data, args.timeout)
    _output_or_exit(result, args)


def _output_or_exit(result: dict, args: argparse.Namespace) -> None:
    if args.json:
        _print_json(result)
    else:
        data = result.get("data", result)
        content = data.get("content") or data.get("text") or data.get("html")
        if content is None:
            content = json.dumps(data, indent=2)
        print(content)
    if not result.get("success", True):
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
            "  SURF_BROWSE_KEY   read-oriented browser profile key\n"
            "  SURF_UI_KEY       interactive browser profile key\n"
            "  SURF_OPS_KEY      operations profile key\n"
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

    p_transcript = sub.add_parser(
        "transcript",
        help="Download one public YouTube transcript",
        description=(
            "Fetch original-language YouTube captions, print bounded timestamped "
            "text, and save the complete transcript as a Markdown artifact."
        ),
    )
    p_transcript.add_argument("url", help="Single YouTube video URL")
    p_transcript.add_argument(
        "--language",
        action="append",
        dest="languages",
        metavar="LANG",
        help="Preferred language code; repeat to provide fallbacks",
    )
    p_transcript.add_argument(
        "--no-auto-captions",
        action="store_true",
        help="Require a manual caption track",
    )
    p_transcript.add_argument(
        "--max-text-length",
        type=int,
        default=20000,
        metavar="N",
        help="Maximum transcript characters printed inline (default: 20000)",
    )
    p_transcript.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="HTTP timeout in seconds (default: 90)",
    )
    p_transcript.add_argument(
        "--json", action="store_true", help="Print the raw JSON response"
    )

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

    # browse
    p_browse = sub.add_parser(
        "browse",
        help="One-shot browse a URL",
        description="Create a session, navigate, settle, extract, and close.",
    )
    p_browse.add_argument("url", help="URL to browse")
    p_browse.add_argument(
        "--mode", default="standard", help="Browsing mode (default: standard)"
    )
    p_browse.add_argument(
        "--content-mode", default="compact", help="Observation content mode"
    )
    p_browse.add_argument(
        "--wait-selector", help="Wait for this CSS selector before extracting"
    )
    p_browse.add_argument("--wait-text", help="Wait for this text")
    p_browse.add_argument("--wait-url", help="Wait for URL fragment")
    p_browse.add_argument(
        "--wait-js", help="Boolean JavaScript expression to wait for"
    )
    p_browse.add_argument(
        "--dom-stable-ms", type=int, help="DOM stability window in ms"
    )
    p_browse.add_argument(
        "--network-quiet-ms", type=int, help="Network quiet window in ms"
    )
    p_browse.add_argument("--screenshot", action="store_true", help="Capture screenshot")
    p_browse.add_argument(
        "--headed", action="store_true", help="Use a headed browser"
    )
    p_browse.add_argument(
        "--keep-session", action="store_true", help="Return a live session ID"
    )
    p_browse.add_argument(
        "--extract-download", action="store_true", help="Extract document downloads"
    )
    p_browse.add_argument(
        "--max-text-length", type=int, default=8000, help="Max extracted text length"
    )
    p_browse.add_argument(
        "--max-items", type=int, default=100, help="Max links/forms/actions/tables"
    )
    p_browse.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_browse.add_argument("--json", action="store_true", help="Print raw JSON response")

    # session-create
    p_session_create = sub.add_parser(
        "session-create",
        help="Create a browser session",
        description="Create a persistent or ephemeral browser session.",
    )
    p_session_create.add_argument(
        "--profile-id", default="agent-default", help="Profile ID"
    )
    p_session_create.add_argument(
        "--headed", action="store_true", help="Launch a visible browser"
    )
    p_session_create.add_argument(
        "--persist-profile", action="store_true", default=True, help="Persist profile"
    )
    p_session_create.add_argument(
        "--block-mode", default="conservative", help="Ad/resource block mode"
    )
    p_session_create.add_argument(
        "--content-mode", default="compact", help="Default observation mode"
    )
    p_session_create.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_session_create.add_argument("--json", action="store_true", help="Print raw JSON response")

    # session-close
    p_session_close = sub.add_parser(
        "session-close", help="Close a browser session"
    )
    p_session_close.add_argument("session_id", help="Session ID")
    p_session_close.add_argument(
        "--force", action="store_true", help="Force close even if busy"
    )
    p_session_close.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_session_close.add_argument("--json", action="store_true", help="Print raw JSON response")

    # navigate
    p_navigate = sub.add_parser("navigate", help="Navigate a session to a URL")
    p_navigate.add_argument("session_id", help="Session ID")
    p_navigate.add_argument("url", help="URL")
    p_navigate.add_argument(
        "--wait-until", default="domcontentloaded", help="Navigation wait condition"
    )
    p_navigate.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_navigate.add_argument("--json", action="store_true", help="Print raw JSON response")

    # observe
    p_observe = sub.add_parser("observe", help="Observe the current page")
    p_observe.add_argument("session_id", help="Session ID")
    p_observe.add_argument("--content-mode", default="compact", help="Content mode")
    p_observe.add_argument("--max-text-length", type=int, default=8000)
    p_observe.add_argument("--max-items", type=int, default=100)
    p_observe.add_argument("--screenshot", action="store_true")
    p_observe.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_observe.add_argument("--json", action="store_true", help="Print raw JSON response")

    # screenshot
    p_screenshot = sub.add_parser("screenshot", help="Capture a screenshot")
    p_screenshot.add_argument("session_id", help="Session ID")
    p_screenshot.add_argument("--selector", help="Element selector")
    p_screenshot.add_argument("--full-page", action="store_true")
    p_screenshot.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_screenshot.add_argument("--json", action="store_true", help="Print raw JSON response")

    # extract-page
    p_extract_page = sub.add_parser("extract-page", help="Extract page content")
    p_extract_page.add_argument("session_id", help="Session ID")
    p_extract_page.add_argument(
        "--type",
        default="text",
        choices=["text", "html", "table", "links", "images"],
        dest="extract_type",
    )
    p_extract_page.add_argument("--selector", help="CSS selector")
    p_extract_page.add_argument(
        "--structured", action="store_true", help="Use structured extraction"
    )
    p_extract_page.add_argument("--content-type", default="general")
    p_extract_page.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_extract_page.add_argument("--json", action="store_true", help="Print raw JSON response")

    # click / type / hover / select
    for action in ("click", "hover", "select"):
        p_act = sub.add_parser(action, help=f"{action.capitalize()} an element")
        p_act.add_argument("session_id", help="Session ID")
        p_act.add_argument("selector", help="CSS selector")
        if action == "select":
            p_act.add_argument("value", help="Option value to select")
        p_act.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
        p_act.add_argument("--json", action="store_true", help="Print raw JSON response")

    p_type = sub.add_parser("type", help="Type into an element")
    p_type.add_argument("session_id", help="Session ID")
    p_type.add_argument("selector", help="CSS selector")
    p_type.add_argument("value", help="Text to type")
    p_type.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_type.add_argument("--json", action="store_true", help="Print raw JSON response")

    # scroll
    p_scroll = sub.add_parser("scroll", help="Scroll the page or an element")
    p_scroll.add_argument("session_id", help="Session ID")
    p_scroll.add_argument("--selector", help="Element selector")
    p_scroll.add_argument("--direction", default="down", choices=["up", "down"])
    p_scroll.add_argument("--amount", type=int, help="Pixels to scroll")
    p_scroll.add_argument("--until-selector", help="Stop selector")
    p_scroll.add_argument("--until-text", help="Stop text")
    p_scroll.add_argument("--max-steps", type=int, default=50)
    p_scroll.add_argument("--dwell-ms", type=int, default=300)
    p_scroll.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_scroll.add_argument("--json", action="store_true", help="Print raw JSON response")

    # wait
    p_wait = sub.add_parser("wait", help="Wait for a page condition")
    p_wait.add_argument("session_id", help="Session ID")
    p_wait.add_argument("--selector", help="CSS selector")
    p_wait.add_argument("--text", help="Text to wait for")
    p_wait.add_argument("--url-contains", help="URL fragment")
    p_wait.add_argument("--url-regex", help="URL regex")
    p_wait.add_argument("--js-predicate", help="Boolean JS expression")
    p_wait.add_argument("--load-state", help="Playwright load state")
    p_wait.add_argument("--dom-stable-ms", type=int)
    p_wait.add_argument("--network-quiet-ms", type=int)
    p_wait.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_wait.add_argument("--json", action="store_true", help="Print raw JSON response")

    # challenge
    p_challenge = sub.add_parser("challenge", help="Detect challenge/CAPTCHA")
    p_challenge.add_argument("session_id", help="Session ID")
    p_challenge.add_argument("--timeout", type=float, default=_TIMEOUT, help="HTTP timeout in seconds")
    p_challenge.add_argument("--json", action="store_true", help="Print raw JSON response")

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
    elif args.command == "transcript":
        cmd_transcript(args)
    elif args.command == "preflight":
        cmd_preflight(args)
    elif args.command == "browse":
        cmd_browse(args)
    elif args.command == "session-create":
        cmd_session_create(args)
    elif args.command == "session-close":
        cmd_session_close(args)
    elif args.command == "navigate":
        cmd_navigate(args)
    elif args.command == "observe":
        cmd_observe(args)
    elif args.command == "screenshot":
        cmd_screenshot(args)
    elif args.command == "extract-page":
        cmd_extract_page(args)
    elif args.command in ("click", "hover", "select"):
        cmd_interact(args)
    elif args.command == "type":
        cmd_interact(args)
    elif args.command == "scroll":
        cmd_scroll(args)
    elif args.command == "wait":
        cmd_wait(args)
    elif args.command == "challenge":
        cmd_challenge(args)


if __name__ == "__main__":
    main()
