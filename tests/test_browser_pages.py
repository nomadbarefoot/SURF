"""Tests for the per-session page registry and BrowserType honesty."""
import pytest

from config import get_settings
from core.foundation import ConfigurationError, BrowserOperationError
from services.session_service import SessionService


pytestmark = pytest.mark.asyncio


async def test_session_initializes_page_registry():
    service = SessionService()
    await service.initialize()
    try:
        session = await service.create_session(user_id="tester")
        assert session.active_page_id == "page_0"
        assert "page_0" in session.pages
        pages = await service.list_pages(session.session_id)
        assert len(pages) == 1
        assert pages[0]["page_id"] == "page_0"
        assert pages[0]["active"] is True
    finally:
        await service.cleanup()


async def test_create_and_switch_pages():
    service = SessionService()
    await service.initialize()
    try:
        session = await service.create_session(user_id="tester")
        sid = session.session_id

        created = await service.create_page(sid)
        assert created["page_id"] == "page_1"
        assert created["active"] is True
        assert set(created["pages"]) == {"page_0", "page_1"}

        listed = await service.list_pages(sid)
        assert {p["page_id"]: p["active"] for p in listed} == {
            "page_0": False,
            "page_1": True,
        }

        switched = await service.switch_page(sid, "page_0")
        assert switched["page_id"] == "page_0"
        assert switched["active"] is True
        assert session.active_page_id == "page_0"
        assert session.page == session.pages["page_0"]
    finally:
        await service.cleanup()


async def test_close_page_updates_active_page():
    service = SessionService()
    await service.initialize()
    try:
        session = await service.create_session(user_id="tester")
        sid = session.session_id
        await service.create_page(sid)
        await service.create_page(sid)

        closed = await service.close_page(sid, "page_1")
        assert closed["closed_page_id"] == "page_1"
        assert closed["active_page_id"] == "page_2"
        assert "page_1" not in session.pages

        # Closing the only remaining page is not allowed.
        await service.close_page(sid, "page_2")
        with pytest.raises(BrowserOperationError):
            await service.close_page(sid, "page_0")
    finally:
        await service.cleanup()


async def test_page_ceiling_is_enforced():
    service = SessionService()
    await service.initialize()
    try:
        session = await service.create_session(user_id="tester")
        sid = session.session_id
        max_pages = get_settings().max_pages_per_session
        for _ in range(max_pages - 1):
            await service.create_page(sid)
        assert len(session.pages) == max_pages

        with pytest.raises(Exception) as exc_info:
            await service.create_page(sid)
        assert "pages_per_session" in str(exc_info.value).lower()
    finally:
        await service.cleanup()


async def test_unknown_browser_type_fails():
    service = SessionService()
    await service.initialize()
    try:
        with pytest.raises(ConfigurationError) as exc_info:
            await service.create_session(user_config={"browser_type": "edge"})
        assert "browser_type" in str(exc_info.value).lower()
    finally:
        await service.cleanup()


async def test_honest_missing_browser_engine():
    service = SessionService()
    await service.initialize()
    try:
        # WebKit is almost certainly not installed in this environment, so the
        # launch should fail with an explicit ConfigurationError rather than
        # silently falling back to Chromium.
        with pytest.raises(ConfigurationError) as exc_info:
            await service.create_session(
                user_config={"browser_type": "webkit", "headed": False}
            )
        msg = str(exc_info.value).lower()
        assert "webkit" in msg
        assert "not installed" in msg or "browser_type" in msg
    finally:
        await service.cleanup()
