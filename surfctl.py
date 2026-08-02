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
from contextvars import ContextVar
import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:17777"
ROOT = Path(__file__).resolve().parent

TOOL_DESCRIPTIONS: dict[str, str] = {
    "web_search": "Search the web.",
    "web_extract": "Extract readable content from URLs.",
    "web_fetch": "Fetch a public URL with GET.",
    "youtube_transcript": "Get a timestamped YouTube transcript.",
    "browser_create_session": "Create a browser session.",
    "browser_close_session": "Close a browser session.",
    "browser_navigate": "Navigate to a URL.",
    "browser_snapshot": "Inspect the current page and its interactive elements.",
    "browser_click": "Click an element.",
    "browser_type": "Type text into an element.",
    "browser_press_key": "Press a keyboard key.",
    "browser_console": "Manage captured console messages.",
    "browser_resize": "Resize the browser viewport.",
    "browser_wait_for": "Wait for a page condition.",
    "browser_links": "List links on the current page.",
    "browser_take_screenshot": "Capture a page or element screenshot.",
    "browser_extract_data": "Extract structured data from the current page.",
    "browser_scroll": "Scroll the page or an element.",
    "browser_hover": "Hover over an element.",
    "browser_select_option": "Select an option.",
    "browser_detect_challenge": "Detect a CAPTCHA or browser challenge.",
    "browser_browse": "Open a URL and return its rendered content.",
    "browser_download": "Download a URL or clicked file.",
    "browser_network_start": "Start capturing network requests.",
    "browser_network_requests": "List captured network requests.",
    "browser_network_stop": "Stop capturing network requests.",
    "finance_analyst_consensus": "Get analyst price targets and EPS estimates.",
    "finance_insider_transactions": "Get insider transactions and promoter pledges.",
    "finance_corporate_actions": "Get dividends, splits, buybacks, and other corporate actions.",
    "finance_macro": "Get sovereign yield, credit spread, and FX data.",
    "finance_equity_risk_premium": "Get equity risk premiums and country default spreads.",
    "finance_us_snapshot": "Get a basic US equity snapshot.",
}

WEB_TOOLS: frozenset[str] = frozenset(
    {"web_search", "web_extract", "web_fetch", "youtube_transcript"}
)
BROWSE_TOOLS: frozenset[str] = frozenset(
    {
        "browser_create_session",
        "browser_close_session",
        "browser_navigate",
        "browser_snapshot",
        "browser_console",
        "browser_wait_for",
        "browser_links",
        "browser_take_screenshot",
        "browser_extract_data",
        "browser_scroll",
        "browser_detect_challenge",
        "browser_browse",
        "browser_download",
        "browser_network_start",
        "browser_network_requests",
        "browser_network_stop",
    }
)
UI_TOOLS: frozenset[str] = frozenset(
    name for name in TOOL_DESCRIPTIONS if name.startswith("browser_")
)
FINANCE_TOOLS: frozenset[str] = frozenset(
    name for name in TOOL_DESCRIPTIONS if name.startswith("finance_")
)
PROFILE_TOOLS: dict[str, frozenset[str]] = {
    "web": WEB_TOOLS,
    "browse": BROWSE_TOOLS,
    "ui": UI_TOOLS,
    "finance": FINANCE_TOOLS,
}
PROFILE_KEY_ENVS = {
    "browse": "SURF_BROWSE_KEY",
    "ui": "SURF_UI_KEY",
    "finance": "SURF_FINANCE_KEY",
}


def tool_metadata(name: str) -> dict[str, str]:
    return {"name": name, "description": TOOL_DESCRIPTIONS[name]}


def profile_instructions(profile: str) -> str:
    """Load the canonical profile guidance from its repository-owned skill."""
    path = ROOT / "skills" / f"surf-{profile}" / "SKILL.md"
    content = path.read_text(encoding="utf-8")
    if content.startswith("---\n"):
        content = content.split("---\n", 2)[-1]
    return content.strip()


class SurfAppBridge:
    def __init__(
        self,
        timeout: float,
        profile: str = "web",
        manage_app_lifespan: bool = True,
    ):
        self.timeout = timeout
        self.profile = profile
        self.manage_app_lifespan = manage_app_lifespan
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

            if self.manage_app_lifespan:
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
        request_headers = build_headers(body, headers or {}, self.profile)
        if "error" in request_headers:
            return request_headers
        response = await self._client.request(
            method.upper(),
            absolute_url(path),
            content=body,
            headers=request_headers,
        )
        return response_payload(str(response.url), response.status_code, response.text)


MCP_BRIDGE: ContextVar[SurfAppBridge | None] = ContextVar(
    "surf_mcp_bridge", default=None
)


def ensure_venv_python() -> None:
    if os.getenv("SURFCTL_NO_VENV_REEXEC"):
        return
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if Path(sys.executable) == venv_python or str(sys.executable).startswith(
        str(ROOT / ".venv")
    ):
        return

    env = os.environ.copy()
    env["SURFCTL_NO_VENV_REEXEC"] = "1"
    os.execve(
        str(venv_python),
        [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        env,
    )


def build_headers(
    data: str | bytes | None,
    headers: dict[str, str],
    profile: str = "web",
) -> dict[str, str]:
    request_headers = {"User-Agent": "surfctl/stdio"}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    key_env = PROFILE_KEY_ENVS.get(profile)
    token = os.getenv(key_env) if key_env else None
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


async def stdio_server(timeout: float, profile: str = "web") -> int:
    stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        async with SurfAppBridge(timeout, profile=profile) as bridge:
            stdout.write(
                json.dumps(
                    {"ready": True, "transport": "stdio", "protocol": "surfctl-jsonl"}
                )
                + "\n"
            )
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
                stdout.write(
                    json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
                )
                stdout.flush()
    finally:
        sys.stdout = stdout
    return 0


async def stdio_request(
    bridge: SurfAppBridge, request: dict[str, Any]
) -> dict[str, Any]:
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


async def app_call(
    method: str,
    path: str,
    data: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    bridge = MCP_BRIDGE.get()
    if bridge is None:
        raise RuntimeError("SURF MCP bridge is not initialized")
    payload = await bridge.request(method, path, data, headers=headers)
    if not payload.get("ok"):
        raise_mcp_tool_error(payload)
    result = payload.get("json") if payload.get("json") is not None else payload
    if isinstance(result, dict) and (
        result.get("success") is False or result.get("ok") is False
    ):
        raise_mcp_tool_error(result)
    return result


def raise_mcp_tool_error(payload: dict[str, Any]) -> None:
    """Convert an HTTP/application failure into MCP's isError response."""
    from mcp.server.fastmcp.exceptions import ToolError

    detail = payload.get("json", payload)
    if isinstance(detail, dict):
        detail = detail.get("detail", detail.get("error", detail))
    raise ToolError(json.dumps(detail, sort_keys=True, default=str))


def mcp_lifespan(profile: str, *, embedded: bool = False):
    @asynccontextmanager
    async def lifespan(_server):
        async with SurfAppBridge(
            float(os.getenv("SURF_MCP_TIMEOUT", "180")),
            profile=profile,
            manage_app_lifespan=not embedded,
        ) as bridge:
            token = MCP_BRIDGE.set(bridge)
            try:
                yield {}
            finally:
                MCP_BRIDGE.reset(token)

    return lifespan


def build_mcp_server(profile: str = "web", *, embedded: bool = False):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    if profile not in PROFILE_TOOLS:
        raise ValueError(f"unknown SURF profile: {profile}")
    full_access = profile != "web"

    instructions = profile_instructions(profile)
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_hosts.extend(
        host.strip()
        for host in os.getenv("SURF_MCP_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    )

    mcp = FastMCP(
        f"SURF {profile}",
        instructions=instructions,
        log_level="ERROR",
        lifespan=mcp_lifespan(profile, embedded=embedded),
        streamable_http_path="/",
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
            ],
        ),
    )

    # ---- Free tier (always registered) --------------------------------------

    @mcp.tool(**tool_metadata("web_fetch"))
    async def web_fetch(
        url: str,
        params: dict[str, Any] | None = None,
        timeout: int = 30000,
    ) -> dict[str, Any]:
        data = {
            "method": "GET",
            "url": url,
            "backend": "auto",
            "params": params,
            "timeout": min(max(timeout, 1), 30000),
        }
        return await app_call("POST", "/fetch/request", data)

    @mcp.tool(**tool_metadata("web_search"))
    async def web_search(
        query: str,
        max_results: int = 10,
        engines: list[str] | None = None,
        categories: list[str] | None = None,
        language: str = "en",
        time_range: str | None = None,
        min_relevance: float | None = None,
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
        if min_relevance is not None:
            data["min_relevance"] = min_relevance
        return await app_call("POST", "/search/query", data)

    @mcp.tool(**tool_metadata("web_extract"))
    async def web_extract(
        urls: list[str],
        content_mode: str = "reader",
        max_text_length: int = 8000,
        relevance: dict[str, float] | None = None,
        refine_query: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "urls": urls,
            "content_mode": content_mode,
            "max_text_length": max_text_length,
        }
        if relevance is not None:
            data["relevance"] = relevance
        if refine_query is not None:
            data["refine_query"] = refine_query
        return await app_call("POST", "/search/extract", data)

    @mcp.tool(**tool_metadata("youtube_transcript"))
    async def youtube_transcript(
        url: str,
        languages: list[str] | None = None,
        allow_auto_captions: bool = True,
        max_text_length: int = 20000,
    ) -> dict[str, Any]:
        return await app_call(
            "POST",
            "/youtube/transcript",
            {
                "url": url,
                "languages": languages,
                "allow_auto_captions": allow_auto_captions,
                "max_text_length": max_text_length,
            },
        )

    # ---- Specialist profiles ------------------------------------------------

    if full_access:

        @mcp.tool(**tool_metadata("browser_create_session"))
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

        @mcp.tool(**tool_metadata("browser_close_session"))
        async def browser_close_session(
            session_id: str, force: bool = False
        ) -> dict[str, Any]:
            suffix = "?force=true" if force else ""
            return await app_call("DELETE", f"/sessions/{session_id}{suffix}")

        @mcp.tool(**tool_metadata("browser_navigate"))
        async def browser_navigate(
            session_id: str,
            url: str,
            wait_until: str = "domcontentloaded",
            timeout: int | None = None,
            readiness: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            data: dict[str, Any] = {
                "session_id": session_id,
                "url": url,
                "wait_until": wait_until,
            }
            if timeout is not None:
                data["timeout"] = timeout
            if readiness is not None:
                data["readiness"] = readiness
            return await app_call("POST", "/browser/navigate", data)

        @mcp.tool(**tool_metadata("browser_snapshot"))
        async def browser_snapshot(
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

        @mcp.tool(**tool_metadata("browser_click"))
        async def browser_click(
            session_id: str,
            selector: str | None = None,
            handle: str | None = None,
            timeout: int | None = None,
            contract_version: str | None = "interaction.v1",
        ) -> dict[str, Any]:
            data: dict[str, Any] = {
                "session_id": session_id,
                "action": "click",
            }
            if selector is not None:
                data["selector"] = selector
            if handle is not None:
                data["handle"] = handle
            if contract_version is not None:
                data["contract_version"] = contract_version
            if timeout is not None:
                data["timeout"] = timeout
            return await app_call("POST", "/browser/interact", data)

        @mcp.tool(**tool_metadata("browser_type"))
        async def browser_type(
            session_id: str,
            value: str,
            selector: str | None = None,
            handle: str | None = None,
            timeout: int | None = None,
            contract_version: str | None = "interaction.v1",
        ) -> dict[str, Any]:
            data: dict[str, Any] = {
                "session_id": session_id,
                "action": "type",
                "value": value,
            }
            if selector is not None:
                data["selector"] = selector
            if handle is not None:
                data["handle"] = handle
            if contract_version is not None:
                data["contract_version"] = contract_version
            if timeout is not None:
                data["timeout"] = timeout
            return await app_call("POST", "/browser/interact", data)

        @mcp.tool(**tool_metadata("browser_press_key"))
        async def browser_press_key(session_id: str, key: str, selector: str | None = None, handle: str | None = None, timeout: int = 30000) -> dict[str, Any]:
            return await app_call("POST", "/browser/press-key", {"session_id": session_id, "key": key, "selector": selector, "handle": handle, "timeout": timeout})

        @mcp.tool(**tool_metadata("browser_console"))
        async def browser_console(session_id: str, action: str = "read", limit: int = 100, clear_after_read: bool = False) -> dict[str, Any]:
            return await app_call("POST", "/browser/console", {"session_id": session_id, "action": action, "limit": limit, "clear_after_read": clear_after_read})

        @mcp.tool(**tool_metadata("browser_resize"))
        async def browser_resize(session_id: str, width: int, height: int, timeout: int = 30000) -> dict[str, Any]:
            return await app_call("POST", "/browser/viewport", {"session_id": session_id, "width": width, "height": height, "timeout": timeout})

        @mcp.tool(**tool_metadata("browser_wait_for"))
        async def browser_wait_for(
            session_id: str,
            selector: str | None = None,
            text: str | None = None,
            url_contains: str | None = None,
            url_regex: str | None = None,
            js_predicate: str | None = None,
            load_state: str | None = None,
            dom_stable_ms: int | None = None,
            network_quiet_ms: int | None = None,
            timeout: int = 30000,
        ) -> dict[str, Any]:
            data: dict[str, Any] = {
                "session_id": session_id,
                "selector": selector,
                "text": text,
                "url_contains": url_contains,
                "url_regex": url_regex,
                "js_predicate": js_predicate,
                "load_state": load_state,
                "dom_stable_ms": dom_stable_ms,
                "network_quiet_ms": network_quiet_ms,
                "timeout": timeout,
            }
            return await app_call(
                "POST",
                "/browser/wait",
                {k: v for k, v in data.items() if v is not None},
            )

        @mcp.tool(**tool_metadata("browser_links"))
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
            links = (
                result.get("data", {}).get("content")
                or result.get("data", {})
                .get("data", {})
                .get("raw_content", {})
                .get("links")
                or []
            )
            if contains:
                needle = contains.lower()
                links = [
                    link
                    for link in links
                    if needle
                    in (
                        link.get("url", "")
                        + " "
                        + link.get("href", "")
                        + " "
                        + link.get("text", "")
                    ).lower()
                ]
            return {"success": True, "count": len(links), "links": links[:max_items]}

        @mcp.tool(**tool_metadata("browser_take_screenshot"))
        async def browser_take_screenshot(
            session_id: str,
            selector: str | None = None,
            full_page: bool = False,
            timeout: int | None = None,
        ) -> dict[str, Any]:
            data: dict[str, Any] = {"session_id": session_id, "full_page": full_page}
            if selector is not None:
                data["selector"] = selector
            if timeout is not None:
                data["timeout"] = timeout
            return await app_call("POST", "/browser/screenshot", data)

        @mcp.tool(**tool_metadata("browser_extract_data"))
        async def browser_extract_data(
            session_id: str,
            content_type: str = "general",
            selector: str | None = None,
            timeout: int | None = None,
        ) -> dict[str, Any]:
            data: dict[str, Any] = {
                "session_id": session_id,
                "content_type": content_type,
            }
            if selector is not None:
                data["selector"] = selector
            if timeout is not None:
                data["timeout"] = timeout
            return await app_call("POST", "/browser/extract-structured", data)

        @mcp.tool(**tool_metadata("browser_scroll"))
        async def browser_scroll(
            session_id: str,
            selector: str | None = None,
            direction: str = "down",
            amount: int | None = None,
            until_selector: str | None = None,
            until_text: str | None = None,
            max_steps: int = 50,
            dwell_ms: int = 300,
            timeout: int | None = None,
        ) -> dict[str, Any]:
            data: dict[str, Any] = {
                "session_id": session_id,
                "selector": selector,
                "direction": direction,
                "max_steps": max_steps,
                "dwell_ms": dwell_ms,
            }
            if amount is not None:
                data["amount"] = amount
            if until_selector is not None:
                data["until_selector"] = until_selector
            if until_text is not None:
                data["until_text"] = until_text
            if timeout is not None:
                data["timeout"] = timeout
            return await app_call("POST", "/browser/scroll", data)

        @mcp.tool(**tool_metadata("browser_hover"))
        async def browser_hover(
            session_id: str,
            selector: str | None = None,
            handle: str | None = None,
            timeout: int | None = None,
            contract_version: str | None = "interaction.v1",
        ) -> dict[str, Any]:
            data: dict[str, Any] = {
                "session_id": session_id,
                "action": "hover",
            }
            if selector is not None:
                data["selector"] = selector
            if handle is not None:
                data["handle"] = handle
            if contract_version is not None:
                data["contract_version"] = contract_version
            if timeout is not None:
                data["timeout"] = timeout
            return await app_call("POST", "/browser/interact", data)

        @mcp.tool(**tool_metadata("browser_select_option"))
        async def browser_select_option(
            session_id: str,
            value: str,
            selector: str | None = None,
            handle: str | None = None,
            timeout: int | None = None,
            contract_version: str | None = "interaction.v1",
        ) -> dict[str, Any]:
            data: dict[str, Any] = {
                "session_id": session_id,
                "action": "select",
                "value": value,
            }
            if selector is not None:
                data["selector"] = selector
            if handle is not None:
                data["handle"] = handle
            if contract_version is not None:
                data["contract_version"] = contract_version
            if timeout is not None:
                data["timeout"] = timeout
            return await app_call("POST", "/browser/interact", data)

        @mcp.tool(**tool_metadata("browser_detect_challenge"))
        async def browser_detect_challenge(
            session_id: str,
            selector: str | None = None,
            timeout: int | None = None,
        ) -> dict[str, Any]:
            data: dict[str, Any] = {"session_id": session_id}
            if selector is not None:
                data["selector"] = selector
            if timeout is not None:
                data["timeout"] = timeout
            return await app_call("POST", "/browser/detect-captcha", data)

        @mcp.tool(**tool_metadata("browser_browse"))
        async def browser_browse(
            url: str,
            mode: str = "standard",
            content_mode: str = "compact",
            readiness: dict[str, Any] | None = None,
            include_screenshot: bool = False,
            keep_session: bool = False,
            extract_download: bool = True,
            max_text_length: int = 8000,
            max_items: int = 100,
            timeout: int = 30000,
        ) -> dict[str, Any]:
            data: dict[str, Any] = {
                "url": url,
                "mode": mode,
                "content_mode": content_mode,
                "include_screenshot": include_screenshot,
                "keep_session": keep_session,
                "extract_download": extract_download,
                "max_text_length": max_text_length,
                "max_items": max_items,
                "timeout": timeout,
            }
            if readiness is not None:
                data["readiness"] = readiness
            return await app_call("POST", "/browse/browse", data)

        @mcp.tool(**tool_metadata("browser_download"))
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
            raise_mcp_tool_error({"error": "provide url or session_id+selector"})

        @mcp.tool(**tool_metadata("browser_network_start"))
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

        @mcp.tool(**tool_metadata("browser_network_requests"))
        async def browser_network_requests(session_id: str) -> dict[str, Any]:
            return await app_call("GET", f"/browser/network/events/{session_id}")

        @mcp.tool(**tool_metadata("browser_network_stop"))
        async def browser_network_stop(session_id: str) -> dict[str, Any]:
            return await app_call(
                "POST", "/browser/network/stop", {"session_id": session_id}
            )

        # ---- Finance Pack ---------------------------------------------------

        @mcp.tool(**tool_metadata("finance_analyst_consensus"))
        async def finance_analyst_consensus(symbol: str, market: str = "IN") -> dict[str, Any]:
            return await app_call(
                "POST", "/finance/consensus", {"symbol": symbol, "market": market}
            )

        @mcp.tool(**tool_metadata("finance_insider_transactions"))
        async def finance_insider_transactions(symbol: str, market: str = "IN") -> dict[str, Any]:
            return await app_call(
                "POST", "/finance/insider", {"symbol": symbol, "market": market}
            )

        @mcp.tool(**tool_metadata("finance_corporate_actions"))
        async def finance_corporate_actions(
            symbol: str, market: str = "IN"
        ) -> dict[str, Any]:
            return await app_call(
                "POST", "/finance/corp_actions", {"symbol": symbol, "market": market}
            )

        @mcp.tool(**tool_metadata("finance_macro"))
        async def finance_macro(country: str = "IN") -> dict[str, Any]:
            return await app_call("POST", "/finance/macro", {"country": country})

        @mcp.tool(**tool_metadata("finance_equity_risk_premium"))
        async def finance_equity_risk_premium(home: str = "IN", foreign: str = "US") -> dict[str, Any]:
            return await app_call(
                "POST", "/finance/erp", {"home": home, "foreign": foreign}
            )

        @mcp.tool(**tool_metadata("finance_us_snapshot"))
        async def finance_us_snapshot(symbol: str) -> dict[str, Any]:
            return await app_call(
                "POST", "/finance/snapshot_us", {"symbol": symbol, "market": "US"}
            )

    enabled = PROFILE_TOOLS[profile]
    registered = set(TOOL_DESCRIPTIONS) if full_access else set(WEB_TOOLS)
    for name in registered - enabled:
        mcp.remove_tool(name)
    return mcp


def main() -> int:
    ensure_venv_python()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stdio_parser = subparsers.add_parser(
        "stdio", help="Run raw JSONL API over stdin/stdout"
    )
    stdio_parser.add_argument("--timeout", type=float, default=180.0)
    stdio_parser.add_argument(
        "--profile", choices=tuple(PROFILE_TOOLS), default="web"
    )
    mcp_parser = subparsers.add_parser("mcp", help="Run MCP server over stdin/stdout")
    mcp_parser.add_argument(
        "--profile", choices=tuple(PROFILE_TOOLS), default="web"
    )

    args = parser.parse_args()
    if args.command == "stdio":
        key_env = PROFILE_KEY_ENVS.get(args.profile)
        if key_env and not os.getenv(key_env):
            parser.error(f"{args.profile} profile requires {key_env}")
        return asyncio.run(stdio_server(args.timeout, args.profile))
    if args.command == "mcp":
        key_env = PROFILE_KEY_ENVS.get(args.profile)
        if key_env and not os.getenv(key_env):
            parser.error(f"{args.profile} profile requires {key_env}")
        build_mcp_server(args.profile).run(transport="stdio")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
