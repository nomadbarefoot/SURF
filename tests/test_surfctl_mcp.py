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
