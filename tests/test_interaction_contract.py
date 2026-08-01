from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from models.schemas import InteractionAction
from services.browser_service import BrowserService
from services.element_registry import element_registry
from services.session_service import SessionService
import services.outbound_policy as outbound_policy
from config import get_settings


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def interaction_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        service = BrowserService()
        service.initialized = True
        session = SimpleNamespace(
            session_id="sess_interaction_test",
            page=page,
            pages={"page_0": page},
            active_page_id="page_0",
            config=SimpleNamespace(timeout=1000),
            metadata={"blocker": {}, "last_navigation_blocker": {}},
        )
        yield service, session, page
        await browser.close()


async def interact(service, session, action, **kwargs):
    return await service.interact_with_element(
        session=session,
        action=action,
        contract_version="interaction.v1",
        timeout=1000,
        **kwargs,
    )


async def test_ambiguity_and_not_found_are_distinct(interaction_page):
    service, session, page = interaction_page
    await page.set_content("<button>Alpha</button><button>Beta</button>")

    ambiguous = await interact(service, session, InteractionAction.CLICK, selector="button")
    missing = await interact(service, session, InteractionAction.CLICK, selector=".missing")

    assert ambiguous["reason"] == "ambiguous"
    assert ambiguous["target"]["match_count"] == 2
    assert [item["name"] for item in ambiguous["candidates"]] == ["Alpha", "Beta"]
    assert all(item["handle"].startswith("surf:e1:page_0:") for item in ambiguous["candidates"])
    chosen = await interact(
        service, session, InteractionAction.CLICK,
        handle=ambiguous["candidates"][1]["handle"],
    )
    assert chosen["reason"] == "completed"
    assert chosen["element_before"]["name"] == "Beta"
    assert missing["reason"] == "not_found"
    assert missing["target"]["match_count"] == 0


async def test_observed_handles_round_trip_and_report_effect(interaction_page):
    service, session, page = interaction_page
    await page.set_content("""
      <label><input id="check" type="checkbox"> Done</label>
      <input id="text" value="old">
      <select id="select"><option value="a">A</option><option value="b">B</option></select>
      <button id="hover" onmouseenter="this.dataset.hovered='yes'">Hover</button>
    """)
    observed = await service.observe_page(session, content_mode="ui")
    handles = {item["locator"]: item["handle"] for item in observed["elements"]}

    clicked = await interact(service, session, InteractionAction.CLICK, handle=handles["#check"])
    typed = await interact(service, session, InteractionAction.TYPE, handle=handles["#text"], value="new")
    selected = await interact(service, session, InteractionAction.SELECT, handle=handles["#select"], value="b")
    hovered = await interact(service, session, InteractionAction.HOVER, handle=handles["#hover"])

    assert [result["reason"] for result in (clicked, typed, selected, hovered)] == ["completed"] * 4
    assert clicked["element_before"]["checked"] is False
    inventory_checkbox = next(item for item in observed["elements"] if item["locator"] == "#check")
    assert inventory_checkbox["role"] == clicked["element_before"]["role"] == "checkbox"
    assert clicked["element_after"]["checked"] is True
    assert clicked["effect"]["changed_fields"]["checked"] == {"before": False, "after": True}
    assert await page.locator("#text").input_value() == "new"
    assert await page.locator("#select").input_value() == "b"
    assert await page.locator("#hover").get_attribute("data-hovered") == "yes"


@pytest.mark.parametrize("field_name", ["cvc", "token"])
async def test_sensitive_named_text_inputs_never_echo_values(interaction_page, field_name):
    service, session, page = interaction_page
    await page.set_content(f"<input id='sensitive' name='{field_name}' value='before-secret'>")

    result = await interact(
        service, session, InteractionAction.TYPE,
        selector="#sensitive", value="after-secret",
    )

    assert result["reason"] == "completed"
    assert result["element_before"]["value_redacted"] is True
    assert result["element_after"]["value_redacted"] is True
    assert "value" not in result["element_before"]
    assert "value" not in result["element_after"]


async def test_password_fill_reports_success_without_echoing_value(interaction_page):
    service, session, page = interaction_page
    await page.set_content("<input id='password' type='password'>")

    result = await interact(
        service, session, InteractionAction.TYPE,
        selector="#password", value="super-secret",
    )

    assert result["reason"] == "completed"
    assert result["element_after"]["value_redacted"] is True
    assert result["element_after"]["value_applied"] is True
    assert "value" not in result["element_before"]
    assert "value" not in result["element_after"]


async def test_large_inventory_returns_only_live_handles(interaction_page):
    service, session, page = interaction_page
    await page.set_content("".join(
        f"<button id='button-{index}'>Button {index}</button>" for index in range(600)
    ))

    observed = await service.observe_page(session, content_mode="ui", limit=75)

    assert observed["total"] == 600
    assert len(observed["elements"]) == 75
    for item in observed["elements"]:
        record = element_registry.get(item["handle"], session.session_id, "page_0")
        frame = service._frame_by_identity(page, record.frame_id)
        assert frame is not None
        assert await frame.locator(record.locator).count() == 1


async def test_recovery_never_extends_caller_deadline(interaction_page):
    service, session, page = interaction_page
    await page.set_content("<button id='hidden' style='display:none'>Hidden</button>")

    started = __import__("time").monotonic()
    result = await service.interact_with_element(
        session=session,
        action=InteractionAction.CLICK,
        selector="#hidden",
        contract_version="interaction.v1",
        timeout=100,
    )
    elapsed_ms = int((__import__("time").monotonic() - started) * 1000)

    assert result["reason"] == "not_visible"
    assert elapsed_ms <= 175


async def test_hover_revealed_control_can_be_clicked(interaction_page):
    service, session, page = interaction_page
    await page.set_content("""
      <style>.destroy { display:none } li:hover .destroy { display:block }</style>
      <ul><li id='todo'>Todo <button class='destroy' onclick='this.closest("li").remove()'>Delete</button></li></ul>
    """)

    result = await interact(
        service, session, InteractionAction.CLICK, selector=".destroy"
    )

    assert result["reason"] == "completed"
    assert await page.locator("#todo").count() == 0
    assert {item["resolution"] for item in result["recoveries"]} >= {
        "hover_then_recheck"
    }


async def test_genuinely_invisible_control_remains_not_visible(interaction_page):
    service, session, page = interaction_page
    await page.set_content("<button id='hidden' style='display:none'>Hidden</button>")

    result = await interact(
        service, session, InteractionAction.CLICK, selector="#hidden"
    )

    assert result["reason"] == "not_visible"
    assert any(
        item["resolution"] == "hover_then_recheck"
        for item in result["recoveries"]
    )


async def test_blocked_main_frame_navigation_is_attributed_to_click(interaction_page, monkeypatch):
    service, session, page = interaction_page
    session.config.block_resources = []
    session.config.block_mode = "off"
    routes = SessionService()
    policy_settings = get_settings().model_copy(
        update={"outbound_allow_private_networks": False}
    )
    monkeypatch.setattr(outbound_policy, "get_settings", lambda: policy_settings)
    session.metadata["blocker"] = routes._new_blocker_stats(session.config)
    await page.route("**/*", lambda route: routes._handle_route(route, session))
    await page.set_content("<a id='blocked' href='http://127.0.0.1/private'>Blocked</a>")

    result = await interact(
        service, session, InteractionAction.CLICK, selector="#blocked"
    )

    assert result["reason"] == "navigation_blocked"
    assert result["effect"]["attempted_url"] == "http://127.0.0.1/private"
    assert result["effect"]["block_reason"] == "outbound_policy"
    assert result["effect"]["blocker_delta"]["requests_blocked"] == 1


async def test_blocked_subframe_navigation_is_not_attributed_to_click(interaction_page, monkeypatch):
    service, session, page = interaction_page
    session.config.block_resources = []
    session.config.block_mode = "off"
    routes = SessionService()
    policy_settings = get_settings().model_copy(
        update={"outbound_allow_private_networks": False}
    )
    monkeypatch.setattr(outbound_policy, "get_settings", lambda: policy_settings)
    session.metadata["blocker"] = routes._new_blocker_stats(session.config)
    await page.route("**/*", lambda route: routes._handle_route(route, session))
    await page.set_content("""
      <iframe id='ad'></iframe>
      <button id='unrelated' onclick='window.clicked=true; ad.src="http://127.0.0.1/ad"'>Click</button>
    """)

    result = await interact(
        service, session, InteractionAction.CLICK, selector="#unrelated"
    )

    assert result["reason"] == "completed"
    assert await page.evaluate("window.clicked") is True
    assert session.metadata["blocker"]["blocked_navigation_sequence"] == 1


async def test_fingerprint_changed_handle_is_rejected_without_action(interaction_page):
    service, session, page = interaction_page
    await page.set_content("<button id='target' onclick='window.acted=true'>Original</button>")
    observed = await service.observe_page(session, content_mode="ui")
    handle = next(item["handle"] for item in observed["elements"] if item["locator"] == "#target")
    await page.locator("#target").evaluate("el => el.textContent = 'Replacement'")

    result = await interact(service, session, InteractionAction.CLICK, handle=handle)

    assert result["reason"] == "stale_handle"
    assert result["error"]["stale_cause"] == "fingerprint_mismatch"
    assert await page.evaluate("window.acted === true") is False


async def test_verified_handle_never_retargets_after_dom_replacement(interaction_page):
    service, session, page = interaction_page
    await page.set_content("""
      <div style='height:2000px'></div>
      <button id='target' onclick='window.replacementActed=true'>Original</button>
      <script>
        window.addEventListener('scroll', () => {
          const old = document.querySelector('#target');
          if (!old || old.dataset.replaced) return;
          const replacement = old.cloneNode(true);
          replacement.dataset.replaced = 'yes';
          replacement.textContent = 'Original';
          old.replaceWith(replacement);
        }, {once: true});
      </script>
    """)
    observed = await service.observe_page(session, content_mode="ui")
    handle = next(item["handle"] for item in observed["elements"] if item["locator"] == "#target")

    result = await interact(service, session, InteractionAction.CLICK, handle=handle)

    assert result["reason"] == "stale_handle"
    assert result["error"]["stale_cause"] == "detached_after_verification"
    assert await page.evaluate("window.replacementActed === true") is False


async def test_select_option_taxonomy_and_readonly(interaction_page):
    service, session, page = interaction_page
    await page.set_content("""
      <input id="readonly" readonly value="fixed">
      <select id="single"><option value="a">A</option></select>
      <select id="duplicate"><option value="x">First</option><option value="x">Second</option></select>
    """)

    readonly = await interact(service, session, InteractionAction.TYPE, selector="#readonly", value="changed")
    missing = await interact(service, session, InteractionAction.SELECT, selector="#single", value="missing")
    ambiguous = await interact(service, session, InteractionAction.SELECT, selector="#duplicate", value="x")

    assert readonly["reason"] == "readonly"
    assert missing["reason"] == "option_not_found"
    assert ambiguous["reason"] == "option_ambiguous"
    assert await page.locator("#readonly").input_value() == "fixed"


@pytest.mark.parametrize(
    ("markup", "setup"),
    [
        ("<button id='x' disabled onclick='window.acted=true'>Go</button>", "setTimeout(() => x.disabled=false, 100)"),
        ("<button id='x' style='display:none' onclick='window.acted=true'>Go</button>", "setTimeout(() => x.style.display='block', 100)"),
        ("<button id='x' onclick='window.acted=true'>Go</button><div id='cover'></div>", "Object.assign(cover.style,{position:'fixed',inset:'0',zIndex:'10'}); setTimeout(() => cover.remove(), 100)"),
    ],
)
async def test_actionability_failures_self_resolve_within_original_deadline(interaction_page, markup, setup):
    service, session, page = interaction_page
    await page.set_content(markup)
    await page.evaluate(setup)

    result = await interact(service, session, InteractionAction.CLICK, selector="#x")

    assert result["reason"] == "completed"
    assert result["timing"]["elapsed_ms"] <= result["timing"]["timeout_ms"]
    assert await page.evaluate("window.acted === true") is True
