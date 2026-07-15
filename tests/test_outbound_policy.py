from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from config import get_settings
from services.fetch_service import FetchService
from services.outbound_policy import OutboundPolicy, OutboundPolicyError, ValidatedTarget


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/hosts",
        "ftp://example.com/file",
        "http://user:password@example.com/",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
async def test_policy_blocks_unsafe_targets(url):
    with pytest.raises(OutboundPolicyError):
        await OutboundPolicy().validate(url)


@pytest.mark.asyncio
async def test_policy_accepts_public_literal_address():
    target = await OutboundPolicy().validate("https://8.8.8.8/dns-query")
    assert target.host == "8.8.8.8"
    assert target.addresses == ("8.8.8.8",)


@pytest.mark.asyncio
async def test_policy_blocks_private_dns_answer():
    policy = OutboundPolicy()
    with patch.object(policy, "_resolve", new=AsyncMock(return_value=("10.0.0.8",))):
        with pytest.raises(OutboundPolicyError):
            await policy.validate("https://internal.example/")


@pytest.mark.asyncio
async def test_exact_allowlist_permits_private_target(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "outbound_allowed_hosts", ["internal.example"])
    policy = OutboundPolicy()
    with patch.object(policy, "_resolve", new=AsyncMock(return_value=("10.0.0.8",))):
        target = await policy.validate("https://internal.example/")
    assert target.addresses == ("10.0.0.8",)


@pytest.mark.asyncio
async def test_wildcard_allowlist_does_not_match_apex(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "outbound_allowed_hosts", ["*.internal.example"])
    policy = OutboundPolicy()
    with patch.object(policy, "_resolve", new=AsyncMock(return_value=("10.0.0.8",))):
        await policy.validate("https://api.internal.example/")
        with pytest.raises(OutboundPolicyError):
            await policy.validate("https://internal.example/")


@pytest.mark.asyncio
async def test_fetch_revalidates_redirect_and_strips_credentials():
    service = FetchService()
    policy = AsyncMock()
    policy.validate.return_value = ValidatedTarget(
        url="https://example.com",
        scheme="https",
        host="example.com",
        port=443,
        addresses=("93.184.216.34",),
    )
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
            result = await service._request_with_redirects(
                "httpx",
                "GET",
                "https://example.com/start",
                {"Authorization": "Bearer secret", "X-Test": "ok"},
                None,
                None,
                None,
                1000,
                None,
                None,
                None,
            )

    assert result["redirect_count"] == 1
    second_headers = request_once.await_args_list[1].args[3]
    assert "Authorization" not in second_headers
    assert second_headers["X-Test"] == "ok"
    assert policy.validate.await_count == 3
