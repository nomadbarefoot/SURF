import asyncio
import os

import pytest

import surfctl
from mcp.server.fastmcp.exceptions import ToolError


class FakeBridge:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.payload


@pytest.mark.asyncio
async def test_app_call_turns_http_failure_into_tool_error(monkeypatch):
    bridge = FakeBridge(
        {
            "ok": False,
            "status_code": 403,
            "json": {"detail": {"code": "OUTBOUND_TARGET_BLOCKED"}},
        }
    )
    token = surfctl.MCP_BRIDGE.set(bridge)
    try:
        with pytest.raises(ToolError, match="OUTBOUND_TARGET_BLOCKED"):
            await surfctl.app_call("POST", "/fetch/request", {})
    finally:
        surfctl.MCP_BRIDGE.reset(token)


@pytest.mark.asyncio
async def test_app_call_turns_application_failure_into_tool_error(monkeypatch):
    bridge = FakeBridge(
        {"ok": True, "json": {"success": False, "error": "SearXNG down"}}
    )
    token = surfctl.MCP_BRIDGE.set(bridge)
    try:
        with pytest.raises(ToolError, match="SearXNG down"):
            await surfctl.app_call("POST", "/search/query", {})
    finally:
        surfctl.MCP_BRIDGE.reset(token)


@pytest.mark.asyncio
async def test_public_contract_is_exact():
    server = surfctl.build_mcp_server("web")
    tools = {tool.name: tool.description for tool in await server.list_tools()}
    assert tools == {
        name: surfctl.TOOL_DESCRIPTIONS[name]
        for name in surfctl.WEB_TOOLS
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["web", "browse", "ui", "finance"])
async def test_profile_contracts_are_exact(profile):
    server = surfctl.build_mcp_server(profile)
    tools = {
        tool.name: tool.description
        for tool in await server.list_tools()
    }
    expected = surfctl.PROFILE_TOOLS[profile]
    assert tools == {name: surfctl.TOOL_DESCRIPTIONS[name] for name in expected}
    assert all(description.endswith(".") for description in tools.values())
    assert all(len(description) <= 72 for description in tools.values())
    assert server.instructions == surfctl.profile_instructions(profile)


def test_canonical_contract_has_32_unique_tools():
    assert len(surfctl.TOOL_DESCRIPTIONS) == 32
    assert set().union(*surfctl.PROFILE_TOOLS.values()) == set(surfctl.TOOL_DESCRIPTIONS)


@pytest.mark.asyncio
async def test_web_fetch_is_get_only_and_bounded(monkeypatch):
    bridge = FakeBridge({"ok": True, "json": {"success": True}})
    token = surfctl.MCP_BRIDGE.set(bridge)
    try:
        server = surfctl.build_mcp_server("web")
        await server.call_tool(
            "web_fetch",
            {"url": "https://example.com", "params": {"q": "surf"}, "timeout": 90000},
        )
    finally:
        surfctl.MCP_BRIDGE.reset(token)

    data = bridge.calls[-1][0][2]
    assert data == {
        "method": "GET",
        "url": "https://example.com",
        "backend": "auto",
        "params": {"q": "surf"},
        "timeout": 30000,
    }


@pytest.mark.asyncio
async def test_browser_browse_uses_profile_authorization():
    bridge = FakeBridge({"ok": True, "json": {"success": True}})
    token = surfctl.MCP_BRIDGE.set(bridge)
    try:
        await surfctl.build_mcp_server("browse").call_tool(
            "browser_browse", {"url": "https://example.com"}
        )
    finally:
        surfctl.MCP_BRIDGE.reset(token)

    args, kwargs = bridge.calls[-1]
    assert args[:2] == ("POST", "/browse/browse")
    assert kwargs["headers"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("browser_click", {"session_id": "sess_test", "selector": "#go"}),
        ("browser_type", {"session_id": "sess_test", "selector": "#name", "value": "A"}),
        ("browser_hover", {"session_id": "sess_test", "selector": "#go"}),
        ("browser_select_option", {"session_id": "sess_test", "selector": "#kind", "value": "a"}),
    ],
)
async def test_mcp_interactions_default_to_structured_outcomes(monkeypatch, tool_name, arguments):
    bridge = FakeBridge({"ok": True, "json": {"success": True}})
    token = surfctl.MCP_BRIDGE.set(bridge)
    try:
        await surfctl.build_mcp_server("ui").call_tool(tool_name, arguments)
    finally:
        surfctl.MCP_BRIDGE.reset(token)

    data = bridge.calls[-1][0][2]
    assert data["contract_version"] == "interaction.v1"
    assert data["selector"] == arguments["selector"]


# ---------------------------------------------------------------------------
# Profile selection and keyless stdio
# ---------------------------------------------------------------------------


def _clear_env(monkeypatch, *names):
    """Unset names so monkeypatch restores (removes) them after the test."""
    for name in names:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)


def test_parse_profiles_lists_all_and_ui_superset():
    assert surfctl.parse_profiles("web") == ("web",)
    assert surfctl.parse_profiles("browse, web") == ("web", "browse")
    assert surfctl.parse_profiles("all") == ("web", "ui", "finance")
    assert surfctl.parse_profiles("ui,browse") == ("ui",)
    with pytest.raises(ValueError):
        surfctl.parse_profiles("web,nope")
    with pytest.raises(ValueError):
        surfctl.parse_profiles(" , ")


def test_combined_profile_server_exposes_union_of_tools():
    tools = {t.name for t in asyncio.run(surfctl.build_mcp_server("web,finance").list_tools())}
    assert tools == set(surfctl.WEB_TOOLS) | set(surfctl.FINANCE_TOOLS)
    all_tools = asyncio.run(surfctl.build_mcp_server("all").list_tools())
    assert len(all_tools) == len(surfctl.TOOL_DESCRIPTIONS)


def test_ensure_stdio_keys_generates_distinct_keys_only_when_missing(monkeypatch):
    _clear_env(monkeypatch, "SURF_BROWSE_KEY", "SURF_FINANCE_KEY")
    monkeypatch.setenv("SURF_UI_KEY", "u" * 40)
    generated = surfctl.ensure_stdio_keys(("web", "ui", "finance"), require_keys=False)
    assert generated == ["SURF_FINANCE_KEY"]
    assert len(os.environ["SURF_FINANCE_KEY"]) >= 32
    assert os.environ["SURF_UI_KEY"] == "u" * 40
    browse_generated = surfctl.ensure_stdio_keys(("browse",), require_keys=False)
    assert browse_generated == ["SURF_BROWSE_KEY"]
    assert os.environ["SURF_BROWSE_KEY"] != os.environ["SURF_FINANCE_KEY"]


def test_ensure_stdio_keys_strict_mode_rejects_missing(monkeypatch):
    _clear_env(monkeypatch, "SURF_BROWSE_KEY")
    with pytest.raises(SystemExit, match="SURF_BROWSE_KEY"):
        surfctl.ensure_stdio_keys(("web", "browse"), require_keys=True)
    assert "SURF_BROWSE_KEY" not in os.environ


def test_bridge_picks_credential_allowed_for_route():
    bridge = surfctl.SurfAppBridge(1, profile="web,browse,finance")
    assert bridge.auth_profile("POST", "/search/query") == "web"
    assert bridge.auth_profile("POST", "/browser/navigate") == "browse"
    assert bridge.auth_profile("POST", "/finance/macro") == "finance"
    assert bridge.auth_profile("POST", "/fetch/request") == "browse"
