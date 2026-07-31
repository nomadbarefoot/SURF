"""Tests for PageReadinessService SPA settlement."""
import asyncio
import pytest

from services.page_readiness_service import PageReadinessService, ReadinessTimeoutError
from tests.fixtures.browser_site import run_fixture_server


pytestmark = pytest.mark.asyncio


async def test_wait_for_selector_after_hydration(allow_private_networks):
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()
        try:
            session = await session_service.create_session(
                user_config={"headed": False, "persist_profile": False}
            )
            page = session.page
            await page.goto(f"{base}/spa-hydrate", wait_until="domcontentloaded")
            result = await PageReadinessService.wait(
                page, {"selector": '[data-testid="hydrated"]', "timeout": 10000}
            )
            assert result["success"]
            assert result["readiness_reason"] == "selector"
        finally:
            await session_service.cleanup()
            await browser_service.cleanup()


async def test_wait_dom_stable_ignores_persistent_connections(allow_private_networks):
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()
        try:
            session = await session_service.create_session(
                user_config={"headed": False, "persist_profile": False}
            )
            page = session.page
            # Open a WebSocket that stays alive; readiness should still succeed.
            await page.goto(f"{base}/spa-hydrate", wait_until="domcontentloaded")
            await page.evaluate(
                f"""
                () => {{
                    const ws = new WebSocket('ws://{base.replace("http://", "")}/ws');
                    window.__test_ws = ws;
                }}
                """
            )
            await asyncio.sleep(0.2)
            result = await PageReadinessService.wait(
                page, {"dom_stable_ms": 500, "network_quiet_ms": 500, "timeout": 10000}
            )
            assert result["success"]
            assert result["readiness_reason"] in ("dom_stable", "network_quiet")
        finally:
            await session_service.cleanup()
            await browser_service.cleanup()


async def test_wait_url_contains_after_spa_route(allow_private_networks):
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()
        try:
            session = await session_service.create_session(
                user_config={"headed": False, "persist_profile": False}
            )
            page = session.page
            await page.goto(f"{base}/spa-router", wait_until="domcontentloaded")
            await page.click("#link-a")
            result = await PageReadinessService.wait(
                page, {"url_contains": "/route-a", "timeout": 10000}
            )
            assert result["success"]
            assert "/route-a" in result["final_url"]
        finally:
            await session_service.cleanup()
            await browser_service.cleanup()


async def test_wait_js_predicate(allow_private_networks, monkeypatch):
    from config import get_settings

    monkeypatch.setattr(get_settings(), "readiness_allow_js_predicate", True)
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()
        try:
            session = await session_service.create_session(
                user_config={"headed": False, "persist_profile": False}
            )
            page = session.page
            await page.goto(f"{base}/spa-hydrate", wait_until="domcontentloaded")
            result = await PageReadinessService.wait(
                page, {"js_predicate": "document.querySelector('[data-testid=\\\"hydrated\\\"]') !== null", "timeout": 10000}
            )
            assert result["success"]
            assert result["readiness_reason"] == "js_predicate"
        finally:
            await session_service.cleanup()
            await browser_service.cleanup()


async def test_wait_timeout_raises(allow_private_networks):
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()
        try:
            session = await session_service.create_session(
                user_config={"headed": False, "persist_profile": False}
            )
            page = session.page
            await page.goto(f"{base}/spa-hydrate", wait_until="domcontentloaded")
            with pytest.raises(ReadinessTimeoutError):
                await PageReadinessService.wait(
                    page, {"selector": "#does-not-exist", "timeout": 500}
                )
        finally:
            await session_service.cleanup()
            await browser_service.cleanup()


async def test_js_predicate_is_disabled_by_default(allow_private_networks):
    """Caller-supplied JS is off unless explicitly enabled."""
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()
        try:
            session = await session_service.create_session(
                user_config={"headed": False, "persist_profile": False}
            )
            page = session.page
            await page.goto(f"{base}/spa-hydrate", wait_until="domcontentloaded")
            with pytest.raises(ReadinessTimeoutError) as exc:
                await PageReadinessService.wait(
                    page, {"js_predicate": "true", "timeout": 5000}
                )
            assert exc.value.stage == "js_predicate_disabled"
        finally:
            await session_service.cleanup()
            await browser_service.cleanup()


async def test_js_predicate_malformed_input_fails_closed(allow_private_networks, monkeypatch):
    """A predicate that is not a clean expression must not wedge the wrapper.

    This is not a sandbox test -- when enabled, js_predicate runs caller JS by
    design. It only pins that a malformed predicate degrades to a normal
    readiness outcome rather than throwing an unhandled page error.
    """
    from config import get_settings

    monkeypatch.setattr(get_settings(), "readiness_allow_js_predicate", True)
    async with run_fixture_server() as base:
        from services.session_service import SessionService
        from services.browser_service import BrowserService

        session_service = SessionService()
        browser_service = BrowserService()
        await session_service.initialize()
        await browser_service.initialize()
        try:
            session = await session_service.create_session(
                user_config={"headed": False, "persist_profile": False}
            )
            page = session.page
            await page.goto(f"{base}/spa-hydrate", wait_until="domcontentloaded")
            # Syntactically invalid as an expression: the wrapper catches it and
            # keeps returning false until the deadline, rather than propagating
            # a raw JS error to the caller.
            with pytest.raises(ReadinessTimeoutError):
                await PageReadinessService.wait(
                    page,
                    {"js_predicate": "this is not valid javascript !!", "timeout": 2000},
                )
        finally:
            await session_service.cleanup()
            await browser_service.cleanup()
