"""Focused tests for authenticated screenshot artifact retrieval."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import get_settings
from controllers import artifact_controller
from core.foundation import get_download_service
from services.download_service import DownloadService


def test_screenshot_artifact_contract_and_security(tmp_path, monkeypatch):
    settings = get_settings()
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    screenshot = screenshots / "page.png"
    screenshot.write_bytes(b"\x89PNG\r\nscreenshot-bytes")
    monkeypatch.setattr(settings, "screenshots_dir", str(screenshots))
    monkeypatch.setattr(settings, "downloads_dir", str(tmp_path / "downloads"))
    monkeypatch.setattr(settings, "auth_mode", "token")
    monkeypatch.setattr(settings, "api_token", "artifact-token")
    service = DownloadService()
    test_app = FastAPI()
    test_app.include_router(artifact_controller.router, prefix="/artifacts")
    test_app.dependency_overrides[get_download_service] = lambda: service

    artifact = service.register_artifact(
        str(screenshot), content_type="image/png", filename="page.png"
    )
    assert artifact["artifact_id"].startswith("art_")
    assert artifact["content_url"] == f"/artifacts/{artifact['artifact_id']}/content"
    assert "path" not in artifact
    assert "absolute_path" not in artifact

    with TestClient(test_app, raise_server_exceptions=False) as client:
        assert client.get(artifact["content_url"]).status_code == 401
        response = client.get(
            artifact["content_url"],
            headers={"Authorization": "Bearer artifact-token"},
        )
        assert response.status_code == 200
        assert response.content == screenshot.read_bytes()
        assert response.headers["content-type"] == "image/png"
        assert 'filename="page.png"' in response.headers["content-disposition"]

        headers = {"Authorization": "Bearer artifact-token"}
        assert client.get("/artifacts/art_unknown/content", headers=headers).status_code == 404
        assert client.get("/artifacts/art_..%2F..%2Fetc%2Fpasswd/content", headers=headers).status_code == 404


def test_expired_screenshot_artifact_returns_404(tmp_path, monkeypatch):
    settings = get_settings()
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    screenshot = screenshots / "expired.png"
    screenshot.write_bytes(b"expired")
    monkeypatch.setattr(settings, "screenshots_dir", str(screenshots))
    monkeypatch.setattr(settings, "downloads_dir", str(tmp_path / "downloads"))
    service = DownloadService()
    artifact = service.register_artifact(str(screenshot), content_type="image/png")

    monkeypatch.setattr(settings, "download_retention_seconds", -1)
    try:
        service.get_download(artifact["artifact_id"])
        raise AssertionError("expired artifact remained retrievable")
    except Exception as exc:
        assert "not found" in str(exc).lower()
