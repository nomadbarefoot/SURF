"""HTTP middleware and privileged health-route boundary tests."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import get_settings
from core.foundation import RateLimitMiddleware, RequestSizeLimitMiddleware
from main import app


@pytest.mark.asyncio
async def test_chunked_request_is_rejected_before_application_runs():
    called = False

    async def downstream(_scope, _receive, _send):
        nonlocal called
        called = True

    middleware = RequestSizeLimitMiddleware(downstream, max_body_size=5)
    messages = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    await middleware(
        {"type": "http", "method": "POST", "path": "/", "headers": []},
        receive,
        send,
    )

    assert called is False
    assert sent[0]["status"] == 413
    payload = json.loads(sent[1]["body"])
    assert payload["error"]["code"] == "REQUEST_TOO_LARGE"


def test_rate_limit_returns_429_without_exception_translation():
    test_app = FastAPI()
    test_app.add_middleware(
        RateLimitMiddleware,
        requests_per_window=1,
        window_seconds=60,
    )

    @test_app.get("/limited")
    async def limited():
        return {"ok": True}

    with TestClient(test_app, raise_server_exceptions=False) as client:
        assert client.get("/limited").status_code == 200
        response = client.get("/limited")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(response.headers["Retry-After"]) >= 1


def test_only_liveness_is_anonymous_among_health_details(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "loopback")
    monkeypatch.setattr(settings, "api_token", "health-token")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/metrics").status_code == 403
        response = client.get(
            "/health/runtime",
            headers={"Authorization": "Bearer health-token"},
        )

    assert response.status_code == 200
    assert response.json()["browser_runtime"]["status"] == "not_started"
