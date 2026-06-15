"""Internal Cloudflare / bot-challenge handling for search extraction.

Opaque to agents — used only by SearchService headed retry path.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict, Optional

import structlog
from playwright.async_api import Page

from config import get_settings
from utils.anti_detection import HumanMimicry, HumanMouseMovement

logger = structlog.get_logger()
settings = get_settings()

_CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "checking your browser",
    "performing security verification",
    "attention required",
    "robot challenge",
)

_CHALLENGE_TEXT_MARKERS = (
    "just a moment",
    "checking your browser",
    "performing security verification",
    "verify you are human",
    "cloudflare",
    "turnstile",
)

_TURNSTILE_IFRAME_SELECTORS = (
    'iframe[src*="challenges.cloudflare.com"]',
    'iframe[src*="turnstile"]',
    'iframe[title*="Cloudflare"]',
    'iframe[title*="challenge"]',
)


class ChallengeResolver:
    """Resolve passive and interactive challenge pages during headed extraction."""

    @staticmethod
    def is_challenge_page(title: str, text: str) -> bool:
        low = f"{title} {text}".lower()
        return any(m in low for m in _CHALLENGE_TITLE_MARKERS + _CHALLENGE_TEXT_MARKERS)

    @staticmethod
    def is_retryable_failure(result: Dict[str, Any]) -> bool:
        if result.get("success"):
            return False
        error = (result.get("error") or "").lower()
        retryable = (
            "unavailable",
            "timeout",
            "bot protection",
            "challenge",
            "global timeout",
            "insufficient content",
        )
        if any(token in error for token in retryable):
            return True
        return bool(result.get("challenge_blocked"))

    @staticmethod
    def should_headed_retry(
        url: str,
        result: Dict[str, Any],
        relevance: Optional[Dict[str, float]],
    ) -> bool:
        if not ChallengeResolver.is_retryable_failure(result):
            return False
        score = (relevance or {}).get(url, 0.0)
        return score >= settings.search_headed_relevance_threshold

    @staticmethod
    def agent_error() -> str:
        return "Page unavailable"

    @staticmethod
    async def wait_passive(page: Page, timeout_ms: int) -> bool:
        deadline = time.monotonic() + (timeout_ms / 1000)
        while time.monotonic() < deadline:
            if await ChallengeResolver._is_cleared(page):
                return True
            await asyncio.sleep(0.5)
        return await ChallengeResolver._is_cleared(page)

    @staticmethod
    async def resolve_headed(page: Page) -> str:
        """Passive wait → human priming → bounded click attempts. Returns outcome label."""
        wait_ms = settings.search_challenge_wait_headed
        for attempt in range(settings.search_headed_max_attempts):
            if await ChallengeResolver.wait_passive(page, wait_ms):
                logger.info("challenge_resolved_passive", attempt=attempt + 1)
                return "passive"

            await ChallengeResolver._prime_human(page)

            clicked = await ChallengeResolver._attempt_challenge_click(page)
            if clicked:
                if await ChallengeResolver.wait_passive(page, min(wait_ms, 30000)):
                    logger.info("challenge_resolved_clicked", attempt=attempt + 1)
                    return "clicked"

            if attempt < settings.search_headed_max_attempts - 1:
                await HumanMimicry.gaussian_delay(2.0, 0.8)
                try:
                    await page.reload(
                        wait_until="domcontentloaded",
                        timeout=settings.search_nav_timeout_headed,
                    )
                except Exception as exc:
                    logger.warning("challenge_reload_failed", error=str(exc))

        logger.info("challenge_resolve_timeout", attempts=settings.search_headed_max_attempts)
        return "timeout"

    @staticmethod
    async def _is_cleared(page: Page) -> bool:
        try:
            title = (await page.title() or "").lower()
            if any(m in title for m in _CHALLENGE_TITLE_MARKERS):
                return False

            cookies = await page.context.cookies()
            if any(c.get("name") == "cf_clearance" for c in cookies):
                return True

            text_len = await page.evaluate("() => (document.body?.innerText || '').length")
            if text_len and int(text_len) > 1500:
                body_sample = await page.evaluate(
                    "() => (document.body?.innerText || '').slice(0, 2000).toLowerCase()"
                )
                if not ChallengeResolver.is_challenge_page("", body_sample or ""):
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    async def _prime_human(page: Page) -> None:
        if not settings.enable_enhanced_mouse_movement:
            await HumanMimicry.gaussian_delay(0.8, 0.2)
            return
        await HumanMouseMovement.random_mouse_wiggle(page, intensity=2)
        await HumanMimicry.human_scroll(page, "down", random.randint(120, 280))
        await HumanMimicry.gaussian_delay(0.8, 0.25)
        await HumanMimicry.human_scroll(page, "up", random.randint(60, 160))

    @staticmethod
    async def _attempt_challenge_click(page: Page) -> bool:
        clicks = 0
        for selector in _TURNSTILE_IFRAME_SELECTORS:
            locator = page.locator(selector).first
            try:
                if await page.locator(selector).count() == 0:
                    continue
                box = await locator.bounding_box()
                if not box or box["width"] < 4 or box["height"] < 4:
                    continue

                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2

                await HumanMouseMovement.random_mouse_wiggle(page, intensity=1)

                for _ in range(settings.search_challenge_click_attempts):
                    off_x = cx + random.randint(-18, 18)
                    off_y = cy + random.randint(-12, 12)
                    await page.mouse.click(off_x, off_y)
                    await asyncio.sleep(random.uniform(0.25, 0.75))
                    jitter_x = cx + random.randint(-4, 4)
                    jitter_y = cy + random.randint(-4, 4)
                    await page.mouse.click(jitter_x, jitter_y)
                    clicks += 1
                    if await ChallengeResolver.wait_passive(page, 8000):
                        return True

                if clicks > 0:
                    return True
            except Exception as exc:
                logger.debug("challenge_click_selector_failed", selector=selector, error=str(exc))
        return False
