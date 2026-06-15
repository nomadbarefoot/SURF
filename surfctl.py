#!/usr/bin/env python3
"""SURF agent bridge.

Agent-facing modes are stdio only:
- `surfctl.py mcp` exposes a compact MCP browser tool set.
- `surfctl.py stdio` exposes raw JSONL API requests.

`start_surf.py` remains the optional manual HTTP development server.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://surf.local"
ROOT = Path(__file__).resolve().parent


class SurfAppBridge:
    def __init__(self, timeout: float):
        self.timeout = timeout
        self._client = None
        self._lifespan = None

    async def __aenter__(self) -> "SurfAppBridge":
        import httpx

        stdout = sys.stdout
        previous_log_level = os.environ.get("SURF_LOG_LEVEL")
        os.environ["SURF_LOG_LEVEL"] = os.getenv("SURFCTL_APP_LOG_LEVEL", "ERROR")
        sys.stdout = sys.stderr
        try:
            from main import app

            self._lifespan = app.router.lifespan_context(app)
            await self._lifespan.__aenter__()
            transport = httpx.ASGITransport(app=app)
            self._client = httpx.AsyncClient(
                transport=transport,
                timeout=self.timeout,
                base_url=DEFAULT_BASE_URL,
            )
            return self
        finally:
            if previous_log_level is None:
                os.environ.pop("SURF_LOG_LEVEL", None)
            else:
                os.environ["SURF_LOG_LEVEL"] = previous_log_level
            sys.stdout = stdout

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()
        if self._lifespan:
            await self._lifespan.__aexit__(exc_type, exc, tb)

    async def request(
        self,
        method: str,
        path: str,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        assert self._client is not None
        body = json.dumps(data) if isinstance(data, (dict, list)) else data
        request_headers = build_headers(body, headers or {})
        if "error" in request_headers:
            return request_headers
        response = await self._client.request(
            method.upper(),
            absolute_url(path),
            content=body,
            headers=request_headers,
        )
        return response_payload(str(response.url), response.status_code, response.text)


MCP_BRIDGE: SurfAppBridge | None = None


def ensure_venv_python() -> None:
    if os.getenv("SURFCTL_NO_VENV_REEXEC"):
        return
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if Path(sys.executable) == venv_python or str(sys.executable).startswith(str(ROOT / ".venv")):
        return

    env = os.environ.copy()
    env["SURFCTL_NO_VENV_REEXEC"] = "1"
    os.execve(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)


def build_headers(data: str | bytes | None, headers: dict[str, str]) -> dict[str, str]:
    request_headers = {"User-Agent": "surfctl/stdio"}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    token = os.getenv("SURF_API_TOKEN")
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    request_headers.update(headers)
    return request_headers


def response_payload(url: str, status_code: int, body: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": 200 <= status_code < 300,
        "url": url,
        "status_code": status_code,
    }
    try:
        payload["json"] = json.loads(body) if body else None
    except json.JSONDecodeError:
        payload["text"] = body
    return payload


def absolute_url(target: str) -> str:
    if target.startswith(("http://", "https://")):
        return target
    path = target if target.startswith("/") else f"/{target}"
    return f"{DEFAULT_BASE_URL}{path}"


def with_request_id(request: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if "id" in request:
        payload["id"] = request["id"]
    return payload


async def stdio_server(timeout: float) -> int:
    stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        async with SurfAppBridge(timeout) as bridge:
            stdout.write(json.dumps({"ready": True, "transport": "stdio", "protocol": "surfctl-jsonl"}) + "\n")
            stdout.flush()
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                    if str(request.get("method", "")).upper() in {"QUIT", "EXIT"}:
                        stdout.write(json.dumps({"ok": True, "closed": True}) + "\n")
                        stdout.flush()
                        break
                    payload = await stdio_request(bridge, request)
                except Exception as error:
                    payload = {"ok": False, "error": str(error)}
                stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
                stdout.flush()
    finally:
        sys.stdout = stdout
    return 0


async def stdio_request(bridge: SurfAppBridge, request: dict[str, Any]) -> dict[str, Any]:
    method = str(request.get("method", "GET")).upper()
    path = str(request.get("path", "/"))
    headers = request.get("headers") if isinstance(request.get("headers"), dict) else {}
    payload = await bridge.request(method, path, request.get("data"), headers)
    payload["transport"] = "stdio"
    return with_request_id(request, payload)


def session_config(
    profile_id: str = "agent-default",
    persist_profile: bool = True,
    headed: bool = False,
    background_headed: bool = True,
    block_mode: str = "conservative",
    content_mode: str = "compact",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = {
        "profile_id": profile_id,
        "persist_profile": persist_profile,
        "headed": headed,
        "silent": not headed,
        "background_headed": background_headed,
        "block_mode": block_mode,
        "content_mode": content_mode,
    }
    if config:
        merged.update(config)
        if "headed" in merged and "silent" not in config:
            merged["silent"] = not bool(merged["headed"])
    return merged


async def app_call(method: str, path: str, data: Any = None) -> dict[str, Any]:
    if MCP_BRIDGE is None:
        raise RuntimeError("SURF MCP bridge is not initialized")
    payload = await MCP_BRIDGE.request(method, path, data)
    if not payload.get("ok"):
        return payload
    return payload.get("json") if payload.get("json") is not None else payload


@asynccontextmanager
async def mcp_lifespan(_server):
    global MCP_BRIDGE
    async with SurfAppBridge(float(os.getenv("SURF_MCP_TIMEOUT", "180"))) as bridge:
        MCP_BRIDGE = bridge
        try:
            yield {}
        finally:
            MCP_BRIDGE = None


def build_mcp_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "SURF",
        instructions="Prefer SURF for local browsing, scraping, downloads, and browser-cookie fetches.",
        log_level="ERROR",
        lifespan=mcp_lifespan,
    )

    @mcp.tool(name="browser_health", description="Health.")
    async def browser_health() -> dict[str, Any]:
        return await app_call("GET", "/health/runtime")

    @mcp.tool(name="browser_create_session", description="Create session.")
    async def browser_create_session(
        profile_id: str = "agent-default",
        persist_profile: bool = True,
        headed: bool = False,
        background_headed: bool = True,
        block_mode: str = "conservative",
        content_mode: str = "compact",
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await app_call(
            "POST",
            "/sessions/",
            {
                "config": session_config(
                    profile_id=profile_id,
                    persist_profile=persist_profile,
                    headed=headed,
                    background_headed=background_headed,
                    block_mode=block_mode,
                    content_mode=content_mode,
                    config=config,
                )
            },
        )

    @mcp.tool(name="browser_close_session", description="Close session.")
    async def browser_close_session(session_id: str, force: bool = False) -> dict[str, Any]:
        suffix = "?force=true" if force else ""
        return await app_call("DELETE", f"/sessions/{session_id}{suffix}")

    @mcp.tool(name="browser_navigate", description="Navigate.")
    async def browser_navigate(
        session_id: str,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int | None = None,
    ) -> dict[str, Any]:
        data = {"session_id": session_id, "url": url, "wait_until": wait_until}
        if timeout is not None:
            data["timeout"] = timeout
        return await app_call("POST", "/browser/navigate", data)

    @mcp.tool(name="browser_observe", description="Observe page.")
    async def browser_observe(
        session_id: str,
        content_mode: str = "compact",
        max_text_length: int = 8000,
        max_items: int = 100,
        include_screenshot: bool = False,
    ) -> dict[str, Any]:
        return await app_call(
            "POST",
            "/browser/observe",
            {
                "session_id": session_id,
                "content_mode": content_mode,
                "max_text_length": max_text_length,
                "max_items": max_items,
                "include_screenshot": include_screenshot,
            },
        )

    @mcp.tool(name="browser_click", description="Click.")
    async def browser_click(session_id: str, selector: str, timeout: int | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {"session_id": session_id, "action": "click", "selector": selector}
        if timeout is not None:
            data["timeout"] = timeout
        return await app_call("POST", "/browser/interact", data)

    @mcp.tool(name="browser_type", description="Type.")
    async def browser_type(session_id: str, selector: str, value: str, timeout: int | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {"session_id": session_id, "action": "type", "selector": selector, "value": value}
        if timeout is not None:
            data["timeout"] = timeout
        return await app_call("POST", "/browser/interact", data)

    @mcp.tool(name="browser_wait", description="Wait.")
    async def browser_wait(
        session_id: str,
        selector: str | None = None,
        text: str | None = None,
        url_contains: str | None = None,
        load_state: str | None = None,
        timeout: int = 30000,
    ) -> dict[str, Any]:
        return await app_call(
            "POST",
            "/browser/wait",
            {
                "session_id": session_id,
                "selector": selector,
                "text": text,
                "url_contains": url_contains,
                "load_state": load_state,
                "timeout": timeout,
            },
        )

    @mcp.tool(name="browser_links", description="Extract links.")
    async def browser_links(
        session_id: str,
        selector: str | None = None,
        contains: str | None = None,
        max_items: int = 5000,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"session_id": session_id, "extract_type": "links"}
        if selector:
            data["selector"] = selector
        result = await app_call("POST", "/browser/extract", data)
        links = result.get("data", {}).get("content") or result.get("data", {}).get("data", {}).get("raw_content", {}).get("links") or []
        if contains:
            needle = contains.lower()
            links = [
                link for link in links
                if needle in (link.get("url", "") + " " + link.get("href", "") + " " + link.get("text", "")).lower()
            ]
        return {"success": True, "count": len(links), "links": links[:max_items]}

    @mcp.tool(name="browser_fetch", description="Fetch.")
    async def browser_fetch(
        url: str,
        method: str = "GET",
        session_id: str | None = None,
        backend: str = "auto",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        save_to_downloads: bool = False,
        output_dir: str | None = None,
        filename: str | None = None,
        overwrite: bool = False,
        timeout: int = 30000,
    ) -> dict[str, Any]:
        data = {
            "method": method,
            "url": url,
            "session_id": session_id,
            "backend": backend,
            "headers": headers,
            "params": params,
            "json": json_body,
            "save_to_downloads": save_to_downloads,
            "output_dir": output_dir,
            "download_filename": filename,
            "overwrite": overwrite,
            "timeout": timeout,
        }
        return await app_call("POST", "/fetch/request", data)

    @mcp.tool(name="browser_download", description="Download.")
    async def browser_download(
        url: str | None = None,
        session_id: str | None = None,
        selector: str | None = None,
        filename: str | None = None,
        output_dir: str | None = None,
        overwrite: bool = False,
        timeout: int = 60000,
    ) -> dict[str, Any]:
        if url:
            return await app_call(
                "POST",
                "/fetch/request",
                {
                    "method": "GET",
                    "url": url,
                    "session_id": session_id,
                    "backend": "browser" if session_id else "auto",
                    "save_to_downloads": True,
                    "download_filename": filename,
                    "output_dir": output_dir,
                    "overwrite": overwrite,
                    "timeout": timeout,
                },
            )
        if session_id and selector:
            return await app_call(
                "POST",
                "/browser/download/click",
                {
                    "session_id": session_id,
                    "selector": selector,
                    "filename": filename,
                    "output_dir": output_dir,
                    "overwrite": overwrite,
                    "timeout": timeout,
                },
            )
        return {"ok": False, "error": "provide url or session_id+selector"}

    @mcp.tool(name="browser_network_start", description="Start network.")
    async def browser_network_start(
        session_id: str,
        url_contains: str | None = None,
        include_body: bool = False,
        max_body_bytes: int = 65536,
    ) -> dict[str, Any]:
        return await app_call(
            "POST",
            "/browser/network/start",
            {
                "session_id": session_id,
                "url_contains": url_contains,
                "include_body": include_body,
                "max_body_bytes": max_body_bytes,
            },
        )

    @mcp.tool(name="browser_network_events", description="Read network.")
    async def browser_network_events(session_id: str) -> dict[str, Any]:
        return await app_call("GET", f"/browser/network/events/{session_id}")

    @mcp.tool(name="browser_network_stop", description="Stop network.")
    async def browser_network_stop(session_id: str) -> dict[str, Any]:
        return await app_call("POST", "/browser/network/stop", {"session_id": session_id})

    @mcp.tool(name="browser_search", description="Search via SearXNG. Returns titles, snippets, URLs.")
    async def browser_search(
        query: str,
        max_results: int = 10,
        engines: list[str] | None = None,
        categories: list[str] | None = None,
        language: str = "en",
        time_range: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "language": language,
        }
        if engines is not None:
            data["engines"] = engines
        if categories is not None:
            data["categories"] = categories
        if time_range is not None:
            data["time_range"] = time_range
        return await app_call("POST", "/search/query", data)

    @mcp.tool(name="browser_search_extract", description="Deep-extract full page content from URLs in parallel.")
    async def browser_search_extract(
        urls: list[str],
        content_mode: str = "reader",
        max_text_length: int = 8000,
        relevance: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "urls": urls,
            "content_mode": content_mode,
            "max_text_length": max_text_length,
        }
        if relevance is not None:
            data["relevance"] = relevance
        return await app_call("POST", "/search/extract", data)

    return mcp


def main() -> int:
    ensure_venv_python()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stdio_parser = subparsers.add_parser("stdio", help="Run raw JSONL API over stdin/stdout")
    stdio_parser.add_argument("--timeout", type=float, default=180.0)
    subparsers.add_parser("mcp", help="Run MCP server over stdin/stdout")

    args = parser.parse_args()
    if args.command == "stdio":
        return asyncio.run(stdio_server(args.timeout))
    if args.command == "mcp":
        build_mcp_server().run(transport="stdio")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
