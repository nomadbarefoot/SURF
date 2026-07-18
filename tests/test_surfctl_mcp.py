import pytest

import surfctl
from mcp.server.fastmcp.exceptions import ToolError


class FakeBridge:
    def __init__(self, payload):
        self.payload = payload

    async def request(self, *_args, **_kwargs):
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
