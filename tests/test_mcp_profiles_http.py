from fastapi.testclient import TestClient

from config import get_settings
from core.foundation import _route_profiles
from main import app


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "contract-test", "version": "1"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _clear_legacy_auth(monkeypatch):
    for name in ("SURF_API_TOKEN", "SURF_ADMIN_TOKEN", "SURF_AUTH_MODE"):
        monkeypatch.delenv(name, raising=False)


def test_web_mcp_streamable_http_handshake_is_keyless_on_loopback(monkeypatch):
    _clear_legacy_auth(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "host", "127.0.0.1")

    with TestClient(app, base_url="http://127.0.0.1:17777") as client:
        response = client.post("/mcp/web", json=INITIALIZE, headers=MCP_HEADERS)
        session_headers = {
            **MCP_HEADERS,
            "Mcp-Session-Id": response.headers["mcp-session-id"],
            "Mcp-Protocol-Version": "2025-06-18",
        }
        client.post(
            "/mcp/web",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=session_headers,
        )
        tools = client.post(
            "/mcp/web",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=session_headers,
        )

    assert response.status_code == 200
    assert response.headers["mcp-session-id"]
    assert response.json()["result"]["serverInfo"]["name"] == "SURF web"
    assert {tool["name"] for tool in tools.json()["result"]["tools"]} == {
        "web_search",
        "web_extract",
        "web_fetch",
        "youtube_transcript",
    }


def test_ui_mcp_requires_ui_key(monkeypatch):
    _clear_legacy_auth(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "browse_key", "b" * 32)
    monkeypatch.setattr(settings, "ui_key", "u" * 32)

    with TestClient(app, base_url="http://127.0.0.1:17777") as client:
        assert client.post("/mcp/ui", json=INITIALIZE, headers=MCP_HEADERS).status_code == 401
        wrong = client.post(
            "/mcp/ui",
            json=INITIALIZE,
            headers={**MCP_HEADERS, "Authorization": f"Bearer {'b' * 32}"},
        )
        allowed = client.post(
            "/mcp/ui",
            json=INITIALIZE,
            headers={**MCP_HEADERS, "Authorization": f"Bearer {'u' * 32}"},
        )

    assert wrong.status_code == 403
    assert allowed.status_code == 200


def test_mcp_accepts_only_explicit_extra_service_host(monkeypatch):
    _clear_legacy_auth(monkeypatch)
    monkeypatch.setenv("SURF_MCP_ALLOWED_HOSTS", "surf:17777")

    with TestClient(app, base_url="http://surf:17777") as client:
        allowed = client.post("/mcp/web", json=INITIALIZE, headers=MCP_HEADERS)
    with TestClient(app, base_url="http://attacker.invalid:17777") as client:
        rejected = client.post("/mcp/web", json=INITIALIZE, headers=MCP_HEADERS)

    assert allowed.status_code == 200
    assert rejected.status_code == 421


def test_route_profile_matrix_is_explicit():
    assert _route_profiles("POST", "/search/query") == {"web"}
    assert _route_profiles("POST", "/fetch/request") == {"web", "browse", "ui"}
    assert _route_profiles("POST", "/browser/interact") == {"ui"}
    assert _route_profiles("POST", "/browser/navigate") == {"browse", "ui"}
    assert _route_profiles("POST", "/finance/macro") == {"finance"}
    assert _route_profiles("GET", "/health/metrics") == {"ops"}
