"""Tests for the browse controller endpoint."""
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_browse_endpoint_requires_auth(client):
    response = client.post("/browse/browse", json={"url": "https://example.com"})
    # In loopback mode without a token, /browse is not in FREE_TIER_ROUTES.
    assert response.status_code == 403


def test_browse_endpoint_returns_browse_result(client, monkeypatch):
    from config import get_settings
    from services import browse_service as bs_module
    from core import foundation

    settings = get_settings()
    monkeypatch.setattr(settings, "api_token", "test-token")

    async def fake_browse(*, url, **kwargs):
        return {
            "success": True,
            "url": url,
            "title": "Mock",
            "content": "mock content",
            "content_mode": "compact",
            "transition": {
                "initial_url": url,
                "final_url": url,
                "route_changed": False,
                "response_status": 200,
                "elapsed_ms": 100,
                "readiness_reason": "selector",
                "timeout_stage": None,
                "challenge_state": "cleared",
            },
            "challenge": None,
            "screenshot_artifact": None,
            "warnings": [],
            "session_id": None,
        }

    fake_service = bs_module.BrowseService()
    fake_service.browse = fake_browse  # type: ignore[method-assign]
    monkeypatch.setattr(foundation, "_browse_service", fake_service)

    response = client.post(
        "/browse/browse",
        json={"url": "https://example.com"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["url"].startswith("https://example.com")
    assert data["content"] == "mock content"


def test_browse_endpoint_propagates_browse_error(client, monkeypatch):
    from config import get_settings
    from services import browse_service as bs_module
    from core import foundation

    settings = get_settings()
    monkeypatch.setattr(settings, "api_token", "test-token")

    async def fake_browse(*, url, **kwargs):
        raise bs_module.BrowserOperationError("browse", "mode not enabled")

    fake_service = bs_module.BrowseService()
    fake_service.browse = fake_browse  # type: ignore[method-assign]
    monkeypatch.setattr(foundation, "_browse_service", fake_service)

    response = client.post(
        "/browse/browse",
        json={"url": "https://example.com", "mode": "aggressive"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 500
    assert "not enabled" in response.json()["detail"].lower()


def test_browse_endpoint_maps_egress_denial_to_403(client, monkeypatch):
    """Egress denials must surface as 403, not a generic 500.

    BrowseService wraps unexpected errors in BrowserOperationError; if it did
    that to OutboundPolicyError too, the controller's 403 handler would be
    unreachable dead code.
    """
    from config import get_settings
    from services import browse_service as bs_module
    from services.outbound_policy import OutboundPolicyError
    from core import foundation

    settings = get_settings()
    monkeypatch.setattr(settings, "api_token", "test-token")

    async def fake_browse(*, url, **kwargs):
        raise OutboundPolicyError("Target blocked by egress policy")

    fake_service = bs_module.BrowseService()
    fake_service.browse = fake_browse  # type: ignore[method-assign]
    monkeypatch.setattr(foundation, "_browse_service", fake_service)

    response = client.post(
        "/browse/browse",
        json={"url": "https://example.com"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert "egress policy" in response.json()["detail"].lower()
