"""Unit tests for the request guard pattern filter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services.request_guard import RequestGuard, get_guard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_YAML_PATH = Path(__file__).parent.parent / "config" / "request_guard.yaml"


@pytest.fixture
def guard():
    """Fresh RequestGuard loaded from the real config file."""
    return RequestGuard(_YAML_PATH)


# ---------------------------------------------------------------------------
# Unit: check_query
# ---------------------------------------------------------------------------


def test_benign_query_passes(guard):
    """Ordinary research query must not be blocked."""
    guard.check_query("Python web scraping best practices")


def test_benign_security_research_passes(guard):
    """Security research terms must not be blocked."""
    guard.check_query("CVE-2024-1234 vulnerability analysis")
    guard.check_query("malware detection techniques")
    guard.check_query("how ransomware works — defence guide")


def test_malware_download_query_blocked(guard):
    """Query requesting malware download should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_query("ransomware download free")
    assert exc_info.value.status_code == 403


def test_exploit_kit_query_blocked(guard):
    """Exploit kit acquisition should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_query("exploit kit download")
    assert exc_info.value.status_code == 403


def test_phishing_kit_query_blocked(guard):
    """Phishing kit query should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_query("phishing kit free download")
    assert exc_info.value.status_code == 403


def test_credential_stealer_query_blocked(guard):
    """Credential stealer query should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_query("credential stealer source code")
    assert exc_info.value.status_code == 403


def test_csam_query_blocked(guard):
    """CSAM-related query should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_query("child pornography")
    assert exc_info.value.status_code == 403


def test_doxxing_tutorial_query_blocked(guard):
    """Doxxing tutorial query should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_query("how to dox someone step by step")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Unit: check_url
# ---------------------------------------------------------------------------


def test_benign_url_passes(guard):
    """Normal URL must not be blocked."""
    guard.check_url("https://example.com/article")


def test_malware_builder_url_blocked(guard):
    """URL containing malware builder terms should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_url("https://evil.example.com/trojan-builder-download")
    assert exc_info.value.status_code == 403


def test_phishing_kit_url_blocked(guard):
    """URL containing phishing kit terms should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_url("https://darksite.example/phishing-kit")
    assert exc_info.value.status_code == 403


def test_csam_url_blocked(guard):
    """URL containing CSAM-related terms should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_url("https://bad.example.com/child-sex-abuse-material")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Unit: check_urls (list)
# ---------------------------------------------------------------------------


def test_check_urls_all_benign_passes(guard):
    """List of benign URLs should not be blocked."""
    guard.check_urls(["https://example.com", "https://news.ycombinator.com"])


def test_check_urls_one_bad_blocks(guard):
    """If any URL in the list is bad, the whole call should raise 403."""
    with pytest.raises(HTTPException) as exc_info:
        guard.check_urls([
            "https://example.com",
            "https://evil.example.com/phishing-kit",
        ])
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Unit: doxxing kind=query must NOT fire on URL checks
# ---------------------------------------------------------------------------


def test_doxxing_pattern_does_not_fire_on_url(guard):
    """Doxxing rules are query-only; a URL containing similar text is allowed."""
    # This should not raise — kind=query rules are skipped for URL checks
    guard.check_url("https://example.com/how-to-dox-someone")


# ---------------------------------------------------------------------------
# Integration: HTTP 403 via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_search_service():
    """Stub out the search service so the controller doesn't try to do real work."""
    mock_svc = AsyncMock()
    mock_svc.search = AsyncMock(return_value={"success": True, "results": [], "ms": 1})
    mock_svc.deep_extract = AsyncMock(return_value={"results": []})
    mock_svc.get_stats = lambda: {}
    with patch("controllers.search_controller.get_search_service", return_value=mock_svc):
        yield


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_blocked_search_query_returns_403(client):
    resp = client.post(
        "/search/query",
        json={"query": "ransomware download free", "max_results": 3},
    )
    assert resp.status_code == 403


def test_benign_search_query_passes_guard(client):
    resp = client.post(
        "/search/query",
        json={"query": "Python web scraping tutorial", "max_results": 3},
    )
    # The mock service returns success; 200 or 500 is fine — just not 403
    assert resp.status_code != 403


def test_blocked_extract_url_returns_403(client):
    resp = client.post(
        "/search/extract",
        json={"urls": ["https://evil.example.com/phishing-kit"]},
    )
    assert resp.status_code == 403


def test_benign_extract_url_passes_guard(client):
    resp = client.post(
        "/search/extract",
        json={"urls": ["https://example.com/article"]},
    )
    assert resp.status_code != 403
