from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import surfctl
from playwright.async_api import async_playwright
from controllers.browser_controller import console_capture, press_key, resize_viewport
from models.schemas import ConsoleCaptureRequest, KeyPressRequest, ViewportResizeRequest
from services.browser_service import BrowserService


class SessionOperations:
    def __init__(self, session=object()):
        self.session = session

    @asynccontextmanager
    async def session_operation(self, session_id, operation):
        yield self.session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("primitive_request", "controller", "method", "expected"),
    [
        (KeyPressRequest(session_id="sess_12345678", key="Escape"), press_key, "press_key", ("Escape", None, None, 30000)),
        (ConsoleCaptureRequest(session_id="sess_12345678", action="start", limit=12), console_capture, "manage_console_capture", ("start", 12, False)),
        (ViewportResizeRequest(session_id="sess_12345678", width=390, height=844), resize_viewport, "resize_viewport", (390, 844, 30000)),
    ],
)
async def test_http_primitive_controller_forwards(primitive_request, controller, method, expected):
    browser = AsyncMock()
    getattr(browser, method).return_value = {"ok": True}
    result = await controller(primitive_request, browser, SessionOperations(), {})
    assert result.success is True
    assert getattr(browser, method).await_args.args[1:] == expected


@pytest.mark.asyncio
async def test_console_capture_is_bounded_and_has_clear_stop_lifecycle():
    service = BrowserService()
    handlers = {}
    page = Mock()
    page.on.side_effect = lambda event, handler: handlers.__setitem__(event, handler)
    session = SimpleNamespace(session_id="sess_12345678", active_page_id="page_0", page=page)

    started = await service.manage_console_capture(session, "start", 2)
    assert started["active"] and started["capacity"] == 2
    for text in ("one", "two", "three"):
        handlers["console"](SimpleNamespace(type="log", text=text, location={"url": "x"}))
    read = await service.manage_console_capture(session, "read", 10)
    assert [entry["text"] for entry in read["entries"]] == ["two", "three"]
    await service.manage_console_capture(session, "clear")
    assert (await service.manage_console_capture(session, "read"))["entries"] == []
    stopped = await service.manage_console_capture(session, "stop")
    assert stopped["active"] is False
    assert page.remove_listener.call_count == 2


@pytest.mark.asyncio
async def test_press_key_preserves_focus_without_target():
    service = BrowserService()
    page = SimpleNamespace(keyboard=SimpleNamespace(press=AsyncMock()))
    session = SimpleNamespace(page=page)
    result = await service.press_key(session, "Control+K", timeout=500)
    page.keyboard.press.assert_awaited_once_with("Control+K")
    assert result["focus_behavior"] == "preserved"


@pytest.mark.asyncio
async def test_resize_reports_actual_dimensions_on_same_page():
    service = BrowserService()
    page = SimpleNamespace(set_viewport_size=AsyncMock(), evaluate=AsyncMock(return_value={"width": 390, "height": 844}))
    session = SimpleNamespace(page=page, active_page_id="page_0")
    result = await service.resize_viewport(session, 390, 844, 500)
    page.set_viewport_size.assert_awaited_once_with({"width": 390, "height": 844})
    assert result["actual"] == {"width": 390, "height": 844}


@pytest.mark.asyncio
async def test_mcp_registers_all_ui_testing_primitives():
    names = {tool.name for tool in await surfctl.build_mcp_server("ui").list_tools()}
    assert {"browser_press_key", "browser_console", "browser_resize"} <= names


@pytest.mark.asyncio
async def test_primitives_operate_on_one_live_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 800, "height": 600})
        session = SimpleNamespace(
            session_id="sess_12345678", active_page_id="page_0", page=page
        )
        service = BrowserService()
        try:
            await page.set_content("<input id='field'><script>window.keys=[]; field.onkeydown=e=>keys.push(e.key)</script>")
            await service.manage_console_capture(session, "start", 2)
            await page.evaluate("console.log('first'); console.error('second'); console.warn('third')")
            await service.press_key(session, "Enter", selector="#field", timeout=1000)
            resized = await service.resize_viewport(session, 390, 844, 1000)
            captured = await service.manage_console_capture(session, "read", 10)
            assert await page.evaluate("keys") == ["Enter"]
            assert resized["actual"] == {"width": 390, "height": 844}
            assert [(entry["type"], entry["text"]) for entry in captured["entries"]] == [
                ("error", "second"), ("warning", "third")
            ]
        finally:
            await service.manage_console_capture(session, "stop")
            await browser.close()
