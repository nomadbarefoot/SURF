"""Page readiness and SPA settlement helpers.

Waits for explicit success conditions on a Playwright page while tolerating
long-lived transports (WebSockets, event sources, analytics long-polls) that
would otherwise keep a page from reaching Playwright's networkidle.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional, Dict, Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
import structlog

from config import get_settings

logger = structlog.get_logger()


class ReadinessTimeoutError(Exception):
    """Raised when no readiness condition succeeds within the deadline."""

    def __init__(self, reason: str, stage: str, elapsed_ms: int):
        self.reason = reason
        self.stage = stage
        self.elapsed_ms = elapsed_ms
        super().__init__(f"Readiness timeout: {stage} after {elapsed_ms}ms")


class PageReadinessService:
    """Settle a page after navigation or interaction."""

    # Persistent transports that should not gate network-quiet readiness.
    _PERSISTENT_RESOURCE_TYPES = {"websocket", "eventsource"}

    @staticmethod
    async def wait(
        page: Page,
        spec: Optional[Dict[str, Any]] = None,
        start_url: Optional[str] = None,
        default_timeout: int = 30000,
    ) -> Dict[str, Any]:
        """Wait for a page to become ready according to *spec*.

        Exactly one condition is used: the first one *present* in the spec, in
        this precedence order. They are not alternatives to be raced — if the
        chosen condition times out, the wait fails rather than trying the next.

        1. load_state (Playwright load state)
        2. selector visible
        3. text present
        4. url_contains / url_regex
        5. js_predicate true
        6. DOM stable for dom_stable_ms
        7. network quiet for network_quiet_ms

        So supplying both ``load_state`` and ``selector`` waits only on
        ``load_state``; pass just the condition that actually gates the content.

        If *spec* is None, waits for domcontentloaded then a short DOM/network
        stability window. Returns diagnostics about which condition succeeded.
        """
        spec = spec or {}
        timeout = spec.get("timeout") or default_timeout
        deadline = time.monotonic() + (timeout / 1000.0)
        started_at = time.monotonic()
        initial_url = start_url or page.url

        # Helper to compute remaining ms, never below a small buffer.
        def remaining_ms() -> int:
            return max(100, int((deadline - time.monotonic()) * 1000))

        try:
            # 1. Playwright load state if requested.
            load_state = spec.get("load_state")
            if load_state:
                state_value = load_state.value if hasattr(load_state, "value") else str(load_state)
                await page.wait_for_load_state(state_value, timeout=remaining_ms())
                return PageReadinessService._ok(
                    initial_url, page.url, "load_state", started_at
                )

            # 2. Selector visible.
            selector = spec.get("selector")
            if selector:
                await page.wait_for_selector(selector, timeout=remaining_ms())
                return PageReadinessService._ok(
                    initial_url, page.url, "selector", started_at
                )

            # 3. Text present.
            text = spec.get("text")
            if text:
                locator = page.get_by_text(text)
                await locator.first.wait_for(timeout=remaining_ms())
                return PageReadinessService._ok(
                    initial_url, page.url, "text", started_at
                )

            # 4. URL contains / regex.
            url_contains = spec.get("url_contains")
            url_regex = spec.get("url_regex")
            if url_contains or url_regex:
                predicate = (
                    "(fragment) => window.location.href.includes(fragment)"
                    if url_contains
                    else "(pattern) => new RegExp(pattern).test(window.location.href)"
                )
                arg = url_contains or url_regex
                await page.wait_for_function(predicate, arg=arg, timeout=remaining_ms())
                return PageReadinessService._ok(
                    initial_url,
                    page.url,
                    "url_contains" if url_contains else "url_regex",
                    started_at,
                )

            # 5. JS predicate true.
            js_predicate = spec.get("js_predicate")
            if js_predicate:
                if not get_settings().readiness_allow_js_predicate:
                    raise ReadinessTimeoutError(
                        "js_predicate is disabled; set readiness_allow_js_predicate=true "
                        "to permit caller-supplied JavaScript",
                        "js_predicate_disabled",
                        int((time.monotonic() - started_at) * 1000),
                    )
                # This executes caller-supplied JavaScript in the page context.
                # That is the feature, so no amount of wrapping makes it safe --
                # the settings gate above is the actual control. Passing the
                # source as an argument (rather than interpolating it into this
                # function's own body) at least keeps the wrapper itself intact
                # and the failure mode a returned false instead of a syntax
                # error, but it is not a sandbox. Treat callers as trusted.
                await page.wait_for_function(
                    """(source) => {
                        try { return Boolean(new Function('return (' + source + ')')()); }
                        catch (e) { return false; }
                    }""",
                    arg=js_predicate,
                    timeout=remaining_ms(),
                )
                return PageReadinessService._ok(
                    initial_url, page.url, "js_predicate", started_at
                )

            # Default: wait for domcontentloaded first, then stability.
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=remaining_ms())
            except PlaywrightTimeoutError:
                pass

            # 6. DOM stable.
            dom_stable_ms = spec.get("dom_stable_ms")
            if dom_stable_ms:
                await PageReadinessService._wait_dom_stable(
                    page, dom_stable_ms, remaining_ms()
                )
                return PageReadinessService._ok(
                    initial_url, page.url, "dom_stable", started_at
                )

            # 7. Network quiet.
            network_quiet_ms = spec.get("network_quiet_ms")
            if network_quiet_ms:
                await PageReadinessService._wait_network_quiet(
                    page, network_quiet_ms, remaining_ms()
                )
                return PageReadinessService._ok(
                    initial_url, page.url, "network_quiet", started_at
                )

            # Absolute fallback: short DOM + network stability window.
            fallback_ms = min(3000, remaining_ms())
            try:
                await PageReadinessService._wait_dom_stable(page, 500, fallback_ms)
            except ReadinessTimeoutError:
                pass
            try:
                await PageReadinessService._wait_network_quiet(page, 500, remaining_ms())
                return PageReadinessService._ok(
                    initial_url, page.url, "network_quiet_fallback", started_at
                )
            except ReadinessTimeoutError:
                pass

            return PageReadinessService._ok(
                initial_url, page.url, "domcontentloaded_fallback", started_at
            )

        except PlaywrightTimeoutError as exc:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            raise ReadinessTimeoutError(str(exc), "explicit_wait", elapsed_ms)
        except ReadinessTimeoutError:
            # Propagate as-is: the original stage (dom_stable / network_quiet /
            # js_predicate_disabled) is what callers surface as timeout_stage.
            raise

    @staticmethod
    async def _wait_dom_stable(page: Page, stable_ms: int, timeout_ms: int) -> None:
        """Wait until no DOM mutations observed for *stable_ms* milliseconds."""
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        # Inject a one-shot observer that reports the timestamp of the last mutation.
        await page.evaluate(
            """
            () => {
                if (window.__surf_dom_observer) return;
                window.__surf_last_dom_mutation = performance.now();
                window.__surf_dom_observer = new MutationObserver(() => {
                    window.__surf_last_dom_mutation = performance.now();
                });
                window.__surf_dom_observer.observe(document.body || document.documentElement, {
                    childList: true, subtree: true, attributes: true, characterData: true
                });
            }
            """
        )

        poll_interval = max(50, min(stable_ms // 4, 250)) / 1000.0
        try:
            while time.monotonic() < deadline:
                last_mutation = await page.evaluate(
                    "() => window.__surf_last_dom_mutation || performance.now()"
                )
                now_perf = await page.evaluate("() => performance.now()")
                quiet_for = now_perf - last_mutation
                if quiet_for >= stable_ms:
                    return
                await asyncio.sleep(poll_interval)

            elapsed_ms = int((time.monotonic() - (deadline - timeout_ms / 1000.0)) * 1000)
            raise ReadinessTimeoutError("DOM not stable", "dom_stable", elapsed_ms)
        finally:
            # Kept sessions outlive this wait; leaving the observer attached
            # would keep firing callbacks for the life of the page.
            try:
                await page.evaluate(
                    """
                    () => {
                        if (window.__surf_dom_observer) {
                            window.__surf_dom_observer.disconnect();
                            delete window.__surf_dom_observer;
                            delete window.__surf_last_dom_mutation;
                        }
                    }
                    """
                )
            except Exception:
                pass

    @staticmethod
    async def _wait_network_quiet(page: Page, quiet_ms: int, timeout_ms: int) -> None:
        """Wait until no non-persistent network requests for *quiet_ms* milliseconds."""
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        # Keyed by request identity, not URL: two concurrent requests to the
        # same URL must not cancel each other out when the first responds.
        active_requests: Dict[int, float] = {}
        last_active_at = time.monotonic()

        # A request that never completes (aborted, hung) would otherwise pin the
        # page as "busy" forever, so entries age out.
        stale_after = max(timeout_ms / 1000.0, 10.0)

        def on_request(request):
            if request.resource_type in PageReadinessService._PERSISTENT_RESOURCE_TYPES:
                return
            active_requests[id(request)] = time.monotonic()

        def on_response(response):
            active_requests.pop(id(response.request), None)
            nonlocal last_active_at
            last_active_at = time.monotonic()

        def on_request_failed(request):
            active_requests.pop(id(request), None)
            nonlocal last_active_at
            last_active_at = time.monotonic()

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)

        try:
            poll_interval = max(50, min(quiet_ms // 4, 250)) / 1000.0
            while time.monotonic() < deadline:
                now = time.monotonic()
                for key, started in list(active_requests.items()):
                    if now - started > stale_after:
                        active_requests.pop(key, None)
                if not active_requests and (now - last_active_at) * 1000 >= quiet_ms:
                    return
                await asyncio.sleep(poll_interval)

            elapsed_ms = int((time.monotonic() - (deadline - timeout_ms / 1000.0)) * 1000)
            raise ReadinessTimeoutError("Network not quiet", "network_quiet", elapsed_ms)
        finally:
            page.remove_listener("request", on_request)
            page.remove_listener("response", on_response)
            page.remove_listener("requestfailed", on_request_failed)

    @staticmethod
    def _ok(initial_url: str, final_url: str, reason: str, started_at: float) -> Dict[str, Any]:
        return {
            "success": True,
            "initial_url": initial_url,
            "final_url": final_url,
            "route_changed": initial_url != final_url,
            "readiness_reason": reason,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
        }
