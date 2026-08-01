from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from services.browser_service import BrowserService


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def observed_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        service = BrowserService()
        service.initialized = True
        session = SimpleNamespace(
            session_id="sess_observe_test",
            page=page,
            pages={"page_0": page},
            active_page_id="page_0",
            config=SimpleNamespace(timeout=5000),
            metadata={"blocker": {}, "last_navigation_blocker": {}},
        )
        yield service, session, page
        await browser.close()


async def test_inventory_bare_inputs_radios_and_locators(observed_page):
    service, session, page = observed_page
    await page.set_content("""
      <input class="new-todo" placeholder="What needs to be done?">
      <label><input type="radio" name="size" value="small" checked> Small</label>
      <label><input type="radio" name="size" value="medium"> Medium</label>
      <label><input type="radio" name="size" value="large"> Large</label>
      <textarea name="comments"></textarea><button>Submit order</button>
    """)
    result = await service.observe_page(session, content_mode="ui")
    assert any(item["placeholder"] == "What needs to be done?" for item in result["elements"])
    radios = [item for item in result["elements"] if item.get("input_type") == "radio"]
    assert [item["value"] for item in radios] == ["small", "medium", "large"]
    assert [item["state"]["checked"] for item in radios] == [True, False, False]
    text_input = next(item for item in result["elements"] if item.get("placeholder") == "What needs to be done?")
    assert set(text_input["state"]) >= {"visible", "enabled"}
    assert "checked" not in text_input["state"]
    assert any(item["tag"] == "textarea" for item in result["elements"])
    assert any(item["name"] == "Submit order" for item in result["elements"])
    assert all(item["locator"] and item["handle"].startswith("surf:e1:page_0:") for item in result["elements"])
    assert all(action["selector_hint"] for action in result["actions"])


async def test_live_visibility_and_word_boundaries(observed_page):
    service, session, page = observed_page
    await page.set_content("""
      <main><button>Mark all as complete</button><div>Buy groceries</div>
      <div style="display:none">Hidden study 1</div><div hidden>Hidden study 2</div>
      <div aria-hidden="true">Hidden study 3</div><span>2 items left</span>
      <nav><a href="#/">All</a><a href="#/active">Active</a><a href="#/completed">Completed</a></nav></main>
    """)
    compact = await service.observe_page(session, content_mode="compact")
    ui = await service.observe_page(session, content_mode="ui")
    assert "Hidden study" not in compact["visible_text"]
    assert "Hidden study" not in ui["visible_text"]
    assert "Mark all as completeBuy groceries" not in ui["visible_text"]
    assert "2 items left" in ui["visible_text"]
    assert all(label in ui["visible_text"] for label in ("All", "Active", "Completed"))
    assert 0 <= compact["reduction_ratio"] <= 1
    assert compact["truncated"] is False


async def test_inventory_pagination_metadata(observed_page):
    service, session, page = observed_page
    await page.set_content("".join(f'<button aria-label="Action {i}">A{i}</button>' for i in range(200)))
    first = await service.observe_page(session, content_mode="ui")
    assert len(first["elements"]) == 75
    assert first["total"] == 200
    assert first["next_cursor"] == "75"
    assert first["counts_by_role"] == {"button": 200}
    assert first["visible_count"] == 200
    assert first["hidden_count"] == 0
    second = await service.observe_page(session, content_mode="ui", cursor=first["next_cursor"])
    assert second["elements"][0]["index"] == 75


async def test_scope_handle_is_verified_and_never_falls_back_to_document(observed_page):
    service, session, page = observed_page
    await page.set_content("""
      <section id='scope' tabindex='0'><button id='inside'>Inside</button></section>
      <button id='outside'>Outside</button>
    """)
    full = await service.observe_page(session, content_mode="ui")
    scope_handle = next(
        item["handle"] for item in full["elements"] if item["locator"] == "#scope"
    )

    scoped = await service.observe_page(
        session, content_mode="ui", scope_handle=scope_handle
    )
    assert [item["locator"] for item in scoped["elements"]] == ["#inside"]

    await page.locator("#scope").evaluate("el => el.id = 'changed'")
    stale = await service.observe_page(
        session, content_mode="ui", scope_handle=scope_handle
    )
    assert stale["reason"] == "stale_handle"
