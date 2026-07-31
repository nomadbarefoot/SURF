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
    monkeypatch.setattr(
        surfctl,
        "MCP_BRIDGE",
        FakeBridge(
            {
                "ok": False,
                "status_code": 403,
                "json": {"detail": {"code": "OUTBOUND_TARGET_BLOCKED"}},
            }
        ),
    )

    with pytest.raises(ToolError, match="OUTBOUND_TARGET_BLOCKED"):
        await surfctl.app_call("POST", "/fetch/request", {})


@pytest.mark.asyncio
async def test_app_call_turns_application_failure_into_tool_error(monkeypatch):
    monkeypatch.setattr(
        surfctl,
        "MCP_BRIDGE",
        FakeBridge({"ok": True, "json": {"success": False, "error": "SearXNG down"}}),
    )

    with pytest.raises(ToolError, match="SearXNG down"):
        await surfctl.app_call("POST", "/search/query", {})


@pytest.mark.asyncio
async def test_youtube_transcript_is_registered_in_free_tier(monkeypatch):
    monkeypatch.delenv("SURF_API_TOKEN", raising=False)
    server = surfctl.build_mcp_server()
    names = {tool.name for tool in await server.list_tools()}
    assert "youtube_transcript" in names


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("admin_token", "expected_headers"),
    [
        ("admin-secret", {"X-Surf-Admin-Token": "admin-secret"}),
        (None, None),
        ("", None),
    ],
)
async def test_browser_browse_admin_token_header(
    monkeypatch, admin_token, expected_headers
):
    bridge = FakeBridge({"ok": True, "json": {"success": True}})
    monkeypatch.setattr(surfctl, "MCP_BRIDGE", bridge)
    server = surfctl.build_mcp_server()
    arguments = {"url": "https://example.com"}
    if admin_token is not None:
        arguments["admin_token"] = admin_token

    await server.call_tool("browser_browse", arguments)

    args, kwargs = bridge.calls[-1]
    assert args[:2] == ("POST", "/browse/browse")
    assert kwargs["headers"] == expected_headers
