from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from config import get_settings
from main import app
from services.download_service import DownloadService
from services.fetch_service import FetchService
from services.outbound_policy import ValidatedTarget
from utils.path_policy import resolve_export_directory


def test_loopback_protected_route_requires_configured_token(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "loopback")
    monkeypatch.setattr(settings, "api_token", "expected-token")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/auth/me").status_code == 403
        assert client.get(
            "/auth/me", headers={"Authorization": "Bearer arbitrary"}
        ).status_code == 403
        response = client.get(
            "/auth/me", headers={"Authorization": "Bearer expected-token"}
        )

    assert response.status_code == 200
    assert response.json()["user"]["auth_type"] == "local_token"


@pytest.mark.asyncio
async def test_session_cookies_are_scoped_again_for_each_redirect():
    service = FetchService()
    policy = AsyncMock()
    policy.validate.return_value = ValidatedTarget(
        url="https://example.com",
        scheme="https",
        host="example.com",
        port=443,
        addresses=("93.184.216.34",),
    )
    browser_context = AsyncMock()
    browser_context.cookies.side_effect = [
        [{"name": "first", "value": "one", "domain": "example.com"}],
        [{"name": "second", "value": "two", "domain": "other.example"}],
    ]
    responses = [
        {
            "status": 302,
            "url": "https://example.com/start",
            "headers": {"location": "https://other.example/final"},
            "_content_bytes": b"",
        },
        {
            "status": 200,
            "url": "https://other.example/final",
            "headers": {},
            "_content_bytes": b"ok",
        },
    ]

    with patch("services.fetch_service.get_outbound_policy", return_value=policy):
        with patch.object(service, "_request_once", new=AsyncMock(side_effect=responses)) as request_once:
            await service._request_with_redirects(
                "httpx",
                "GET",
                "https://example.com/start",
                None,
                None,
                None,
                None,
                1000,
                None,
                None,
                browser_context,
            )

    assert browser_context.cookies.await_args_list[0].args[0] == ["https://example.com/start"]
    assert browser_context.cookies.await_args_list[1].args[0] == ["https://other.example/final"]
    assert request_once.await_args_list[0].args[8][0]["name"] == "first"
    assert request_once.await_args_list[1].args[8][0]["name"] == "second"


def test_external_output_directory_is_blocked_by_default(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "export_roots", [])
    with pytest.raises(Exception, match="outside configured export roots"):
        resolve_export_directory(str(tmp_path / "outside"))


@pytest.mark.asyncio
async def test_download_can_write_inside_explicit_export_root(tmp_path, monkeypatch):
    settings = get_settings()
    export_root = tmp_path / "exports"
    monkeypatch.setattr(settings, "export_roots", [str(export_root)])
    monkeypatch.setattr(settings, "downloads_dir", str(tmp_path / "downloads"))
    service = DownloadService()

    record = await service.save_bytes(
        b"safe",
        filename="artifact.txt",
        output_dir=str(export_root / "run"),
    )

    assert (export_root / "run" / "artifact.txt").read_bytes() == b"safe"
    assert record["external"] is True


def test_symlink_cannot_escape_export_root(tmp_path, monkeypatch):
    settings = get_settings()
    export_root = tmp_path / "exports"
    outside = tmp_path / "outside"
    export_root.mkdir()
    outside.mkdir()
    (export_root / "escape").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(settings, "export_roots", [str(export_root)])

    with pytest.raises(Exception, match="outside configured export roots"):
        resolve_export_directory(str(export_root / "escape"))
