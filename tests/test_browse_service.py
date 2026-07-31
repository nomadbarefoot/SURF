"""Tests for the one-shot BrowseService."""
import pytest

from services.browse_service import BrowseService
from tests.fixtures.browser_site import run_fixture_server


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def reset_global_services():
    """Drop process-wide service singletons after each test.

    BrowseService falls back to the module-level singletons when a collaborator
    is not injected. Leaving them populated makes later tests observe a started
    browser runtime (see test_http_boundaries.py), so ordering decides the
    outcome instead of the assertion.
    """
    yield
    from core.foundation import cleanup_services

    await cleanup_services()


class FakeProfileService:
    def __init__(self, mode="standard"):
        self.mode = mode

    def resolve(self, requested_mode=None, url=None, **kwargs):
        from services.browser_profile_service import ResolvedProfile

        return ResolvedProfile(
            mode=requested_mode or self.mode,
            session_overrides={
                "headed": False,
                "stealth_strategy": "minimal",
                "block_mode": "conservative",
            },
            challenge_ladder={
                "passive_wait_ms": 2000,
                "max_passive_attempts": 1,
                "allow_reload": False,
                "allow_headed_retry": False,
                "allow_checkbox_assist": False,
                "max_total_attempts": 1,
            },
            human_behavior={"enabled": False},
            proxy_mode="direct",
            proxy_entry=None,
            warnings=[],
        )


async def test_browse_standard_extracts_content(allow_private_networks):
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()

        service = BrowseService(
            session_service=session_service,
            browser_service=browser_service,
            profile_service=FakeProfileService("standard"),
        )
        await service.initialize()
        try:
            result = await service.browse(
                url=f"{base}/spa-hydrate",
                readiness={"selector": '[data-testid="hydrated"]', "timeout": 10000},
            )
            assert result["success"]
            assert "Hydrated Content" in (result.get("content") or "")
            assert result["transition"]["readiness_reason"] == "selector"
            assert result.get("session_id") is None
        finally:
            await service.cleanup()
            await browser_service.cleanup()
            await session_service.cleanup()


async def test_browse_challenge_detection(allow_private_networks):
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()

        service = BrowseService(
            session_service=session_service,
            browser_service=browser_service,
            profile_service=FakeProfileService("standard"),
        )
        await service.initialize()
        try:
            result = await service.browse(
                url=f"{base}/challenge-delay",
                timeout=10000,
            )
            challenge = result.get("challenge") or {}
            assert challenge.get("type") == "cloudflare"
            # The fixture clears after 2.5s; standard mode may clear it.
            assert challenge.get("state") in ("challenge_detected", "cleared")
        finally:
            await service.cleanup()
            await browser_service.cleanup()
            await session_service.cleanup()


async def test_browse_keep_session(allow_private_networks):
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()

        service = BrowseService(
            session_service=session_service,
            browser_service=browser_service,
            profile_service=FakeProfileService("standard"),
        )
        await service.initialize()
        try:
            result = await service.browse(
                url=f"{base}/spa-hydrate",
                readiness={"selector": '[data-testid="hydrated"]', "timeout": 10000},
                keep_session=True,
            )
            assert result["success"]
            assert result.get("session_id", "").startswith("sess_")
        finally:
            await service.cleanup()
            await browser_service.cleanup()
            await session_service.cleanup()


async def test_browse_extracts_document_response(allow_private_networks):
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()

        service = BrowseService(
            session_service=session_service,
            browser_service=browser_service,
            profile_service=FakeProfileService("standard"),
        )
        await service.initialize()
        try:
            result = await service.browse(url=f"{base}/plain-doc", timeout=10000)
            assert result["success"]
            assert result["transition"]["readiness_reason"] == "document_extract"
            assert "Plain document content" in (result.get("content") or "")
            assert result.get("document_extract", {}).get("format") == "text"
        finally:
            await service.cleanup()
            await browser_service.cleanup()
            await session_service.cleanup()


async def test_browse_unsupported_mode():
    from services.browser_profile_service import BrowserProfileService

    service = BrowseService(profile_service=BrowserProfileService())
    await service.initialize()
    try:
        with pytest.raises(Exception):
            await service.browse(url="https://example.com", mode="aggressive")
    finally:
        await service.cleanup()
