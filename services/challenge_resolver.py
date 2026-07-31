"""Bounded challenge / CAPTCHA / bot-gate state machine.

Used by BrowseService in standard mode and by SearchService headed retry path.
Never calls paid CAPTCHA-solving services. Terminal states return sanitized
diagnostics and optional protected screenshots.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import structlog
from playwright.async_api import Page

from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "checking your browser",
    "performing security verification",
    "attention required",
    "robot challenge",
    "verify you are human",
)

# High-precision phrases. These appear on interstitials and effectively never in
# ordinary prose, so any one of them is sufficient to declare a challenge.
_STRONG_TYPE_MARKERS: Dict[str, List[str]] = {
    "cloudflare": [
        "just a moment",
        "checking your browser",
        "cf-browser-verification",
        "enable javascript and cookies to continue",
        "needs to review the security of your connection",
    ],
    "turnstile": ["verify you are human", "cf-turnstile"],
    "recaptcha": ["i'm not a robot", "recaptcha challenge"],
    "rate_limit": ["too many requests", "rate limit exceeded", "retry after"],
    "access_denied": [
        "access denied",
        "access forbidden",
        "you have been blocked",
        "you don't have permission to access",
    ],
    "login_wall": ["login required", "sign in to continue", "please log in"],
    "generic": [
        "attention required",
        "robot challenge",
        "performing security verification",
        "additional security check",
    ],
}

# Ambiguous mentions. A news article about Cloudflare or a page containing the
# word "blocked" is not a challenge, so these only count as corroboration when a
# structural signal (interstitial-length body, challenge widget) is also present.
_WEAK_TYPE_MARKERS: Dict[str, List[str]] = {
    "cloudflare": ["cloudflare"],
    "turnstile": ["turnstile"],
    "recaptcha": ["recaptcha"],
    "hcaptcha": ["hcaptcha"],
    "access_denied": ["blocked"],
}

# Real interstitials carry very little copy; genuine articles carry a lot.
_INTERSTITIAL_MAX_TEXT_LENGTH = 1500

_CHALLENGE_WIDGET_SELECTORS = (
    'iframe[src*="challenges.cloudflare.com"]',
    'iframe[src*="turnstile"]',
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    ".cf-turnstile",
    "#challenge-form",
    "#cf-challenge-running",
)

_TURNSTILE_IFRAME_SELECTORS = (
    'iframe[src*="challenges.cloudflare.com"]',
    'iframe[src*="turnstile"]',
    'iframe[title*="Cloudflare"]',
    'iframe[title*="challenge"]',
)

_CHECKBOX_SELECTORS = (
    'input[type="checkbox"]',
    '.cf-turnstile',
    '[data-action*="challenge"]',
    'iframe[src*="turnstile"]',
)


@dataclass
class LadderConfig:
    """Challenge ladder parameters."""

    passive_wait_ms: int = 12000
    max_passive_attempts: int = 2
    allow_reload: bool = False
    allow_headed_retry: bool = False
    allow_checkbox_assist: bool = False
    max_total_attempts: int = 2
    screenshot_on_detection: bool = True

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LadderConfig":
        if not data:
            return cls()
        return cls(
            passive_wait_ms=int(data.get("passive_wait_ms", cls.passive_wait_ms)),
            max_passive_attempts=int(data.get("max_passive_attempts", cls.max_passive_attempts)),
            allow_reload=bool(data.get("allow_reload", cls.allow_reload)),
            allow_headed_retry=bool(data.get("allow_headed_retry", cls.allow_headed_retry)),
            allow_checkbox_assist=bool(data.get("allow_checkbox_assist", cls.allow_checkbox_assist)),
            max_total_attempts=int(data.get("max_total_attempts", cls.max_total_attempts)),
            screenshot_on_detection=bool(data.get("screenshot_on_detection", cls.screenshot_on_detection)),
        )


@dataclass
class ChallengeResult:
    """Outcome of a challenge resolution attempt."""

    # cleared, passive, clicked, reload, headed_retry, manual_required, failed, unknown
    state: str
    blocked: bool
    type: Optional[str] = None
    indicators: List[str] = field(default_factory=list)
    recommendation: Optional[str] = None
    attempts: int = 0
    elapsed_ms: int = 0
    screenshot_artifact: Optional[Dict[str, Any]] = None
    detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "blocked": self.blocked,
            "type": self.type,
            "indicators": self.indicators,
            "recommendation": self.recommendation,
            "attempts": self.attempts,
            "elapsed_ms": self.elapsed_ms,
            "screenshot_artifact": self.screenshot_artifact,
            "detail": self.detail,
        }


class ChallengeResolver:
    """Resolve passive and interactive challenge pages with bounded attempts."""

    def __init__(
        self,
        page: Page,
        ladder: Optional[LadderConfig] = None,
        browser_service: Any = None,
        session_service: Any = None,
    ):
        self.page = page
        self.ladder = ladder or LadderConfig()
        self.browser_service = browser_service
        self.session_service = session_service
        self.attempts = 0
        self.started = time.monotonic()
        self._headless_context = None

    # -----------------------------------------------------------------------
    # Legacy static API used by SearchService
    # -----------------------------------------------------------------------
    @staticmethod
    def is_challenge_page(title: str, text: str) -> bool:
        challenge_type, _ = ChallengeResolver.classify(title, text)
        return challenge_type is not None

    @staticmethod
    def classify(
        title: str,
        text: str,
        has_challenge_widget: bool = False,
    ) -> Tuple[Optional[str], List[str]]:
        """Return (type, indicators) for the given page text.

        A strong marker alone is decisive. Weak markers (bare vendor names, the
        word "blocked") only classify when corroborated by a structural signal:
        an interstitial-length body or a challenge widget in the DOM. Without
        that, an article discussing Cloudflare would be mistaken for a gate.
        """
        haystack = f"{title}\n{text}".lower()

        strong_types: List[str] = []
        indicators: List[str] = []
        for kind, phrases in _STRONG_TYPE_MARKERS.items():
            matched = [p for p in phrases if p in haystack]
            if matched:
                strong_types.append(kind)
                indicators.extend(matched)

        weak_types: List[str] = []
        weak_indicators: List[str] = []
        for kind, phrases in _WEAK_TYPE_MARKERS.items():
            matched = [p for p in phrases if p in haystack]
            if matched:
                weak_types.append(kind)
                weak_indicators.extend(matched)

        structural = has_challenge_widget or len(text) <= _INTERSTITIAL_MAX_TEXT_LENGTH

        if strong_types:
            resolved_type = strong_types[0]
        elif weak_types and structural:
            resolved_type = weak_types[0]
        else:
            return None, []

        # Weak matches are still useful diagnostics once a challenge is declared.
        indicators.extend(weak_indicators)

        seen = set()
        unique_indicators = []
        for ind in indicators:
            if ind not in seen:
                seen.add(ind)
                unique_indicators.append(ind)
        return resolved_type, unique_indicators

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
    async def resolve_headed(page: Page) -> str:
        """Backwards-compatible wrapper around the bounded state machine."""
        resolver = ChallengeResolver(
            page,
            ladder=LadderConfig(
                passive_wait_ms=settings.search_challenge_wait_headed,
                max_passive_attempts=settings.search_headed_max_attempts,
                allow_reload=True,
                allow_headed_retry=False,
                allow_checkbox_assist=True,
                max_total_attempts=settings.search_headed_max_attempts + 1,
            ),
        )
        result = await resolver.run()
        if result.state in ("cleared", "passive"):
            return "passive"
        if result.state in ("clicked", "reload"):
            return "clicked"
        return "timeout"

    # -----------------------------------------------------------------------
    # State machine
    # -----------------------------------------------------------------------
    async def run(self) -> ChallengeResult:
        """Run the full challenge ladder."""
        title, text = await self._snapshot()
        challenge_type, indicators = self.classify(
            title, text, has_challenge_widget=await self._has_challenge_widget()
        )

        if not challenge_type:
            return ChallengeResult(
                state="cleared",
                blocked=False,
                type=None,
                indicators=[],
                recommendation=None,
                elapsed_ms=self._elapsed_ms(),
            )

        logger.info(
            "challenge_detected",
            challenge_type=challenge_type,
            indicators=indicators,
        )

        # Stage 1: passive wait.
        for attempt in range(1, self.ladder.max_passive_attempts + 1):
            self.attempts += 1
            if await self._wait_passive(self.ladder.passive_wait_ms):
                return self._success("passive", challenge_type, indicators)
            logger.debug("challenge_passive_wait_exhausted", attempt=attempt)

        # Stage 2: re-observe and classify.
        title, text = await self._snapshot()
        current_type, current_indicators = self.classify(
            title, text, has_challenge_widget=await self._has_challenge_widget()
        )
        if not current_type:
            return self._success("cleared", challenge_type, indicators)

        # Stage 3: optional checkbox assist (headed or headless-safe click).
        if self.ladder.allow_checkbox_assist:
            self.attempts += 1
            if await self._attempt_checkbox_click():
                if await self._wait_passive(min(self.ladder.passive_wait_ms, 30000)):
                    return self._success("clicked", challenge_type, indicators)

        # Stage 4: relax blocker policy and reload once.
        if self.ladder.allow_reload:
            self.attempts += 1
            if await self._reload_with_relaxed_blocker():
                return self._success("reload", challenge_type, indicators)

        # Stage 5: optional headed retry with a fresh session.
        if self.ladder.allow_headed_retry:
            self.attempts += 1
            headed_result = await self._headed_retry(challenge_type, indicators)
            if headed_result:
                return headed_result

        # Terminal: manual required.
        screenshot = await self._maybe_screenshot()
        return ChallengeResult(
            state="manual_required",
            blocked=True,
            type=challenge_type,
            indicators=indicators,
            recommendation="Retry with a headed session or manual action.",
            attempts=self.attempts,
            elapsed_ms=self._elapsed_ms(),
            screenshot_artifact=screenshot,
            detail="Challenge ladder exhausted without clearing the gate.",
        )

    async def _has_challenge_widget(self) -> bool:
        """True when a known challenge widget is present in the DOM."""
        for selector in _CHALLENGE_WIDGET_SELECTORS:
            try:
                if await self.page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    async def _snapshot(self) -> Tuple[str, str]:
        try:
            title = await self.page.title()
        except Exception:
            title = ""
        try:
            text = await self.page.evaluate(
                "() => (document.body?.innerText || '').slice(0, 3000)"
            )
        except Exception:
            text = ""
        return title or "", text or ""

    async def _wait_passive(self, timeout_ms: int) -> bool:
        deadline = time.monotonic() + (timeout_ms / 1000)
        while time.monotonic() < deadline:
            if await self._is_cleared():
                return True
            await asyncio.sleep(0.5)
        return await self._is_cleared()

    async def _is_cleared(self) -> bool:
        try:
            title = (await self.page.title() or "").lower()
            if any(m in title for m in _CHALLENGE_TITLE_MARKERS):
                return False

            cookies = await self.page.context.cookies()
            if any(c.get("name") == "cf_clearance" for c in cookies):
                return True

            text_len = await self.page.evaluate("() => (document.body?.innerText || '').length")
            if text_len and int(text_len) > 1500:
                body_sample = await self.page.evaluate(
                    "() => (document.body?.innerText || '').slice(0, 2000).toLowerCase()"
                )
                if not self.is_challenge_page("", body_sample or ""):
                    return True
            return False
        except Exception:
            return False

    async def _attempt_checkbox_click(self) -> bool:
        for selector in _CHECKBOX_SELECTORS:
            try:
                locator = self.page.locator(selector).first
                if await self.page.locator(selector).count() == 0:
                    continue
                box = await locator.bounding_box()
                if box and box.get("width", 0) > 4 and box.get("height", 0) > 4:
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    await self.page.mouse.move(cx, cy)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                    await self.page.mouse.click(cx, cy)
                    logger.debug("challenge_checkbox_clicked", selector=selector)
                    return True
            except Exception as exc:
                logger.debug("challenge_checkbox_click_failed", selector=selector, error=str(exc))
        return False

    async def _reload_with_relaxed_blocker(self) -> bool:
        try:
            session = self._session_for_page()
            if session:
                original_mode = session.config.block_mode
                # Temporarily relax blocker to token_saver/off.
                session.config.block_mode = "off"
                try:
                    await self.page.reload(wait_until="domcontentloaded", timeout=30000)
                    return await self._wait_passive(self.ladder.passive_wait_ms)
                finally:
                    session.config.block_mode = original_mode
            else:
                await self.page.reload(wait_until="domcontentloaded", timeout=30000)
                return await self._wait_passive(self.ladder.passive_wait_ms)
        except Exception as exc:
            logger.warning("challenge_reload_failed", error=str(exc))
        return False

    async def _headed_retry(
        self,
        challenge_type: Optional[str],
        indicators: List[str],
    ) -> Optional[ChallengeResult]:
        if not self.session_service or not self.browser_service:
            return None
        try:
            url = self.page.url
            # Create a fresh headed session.
            headed_session = await self.session_service.create_session(
                user_config={
                    "headed": True,
                    "background_headed": True,
                    "stealth_strategy": "balanced",
                    "block_mode": "conservative",
                    "persist_profile": False,
                },
                pool="default",
            )
            headed_page = headed_session.page
            try:
                await self.browser_service.navigate_to_url(
                    session=headed_session,
                    url=url,
                    timeout=60000,
                )
                resolver = ChallengeResolver(
                    headed_page,
                    ladder=LadderConfig(
                        passive_wait_ms=30000,
                        max_passive_attempts=3,
                        allow_reload=False,
                        allow_headed_retry=False,
                        allow_checkbox_assist=True,
                        max_total_attempts=4,
                    ),
                    browser_service=self.browser_service,
                    session_service=self.session_service,
                )
                sub = await resolver.run()
                if not sub.blocked:
                    # Copy cookies back to original context if possible.
                    try:
                        cookies = await headed_page.context.cookies()
                        await self.page.context.add_cookies(cookies)
                    except Exception:
                        pass
                    return ChallengeResult(
                        state="headed_retry",
                        blocked=False,
                        type=challenge_type,
                        indicators=indicators,
                        recommendation=None,
                        attempts=self.attempts + sub.attempts,
                        elapsed_ms=self._elapsed_ms(),
                    )
            finally:
                # Always reclaim the headed session; it owns a real browser
                # window and leaks for the process lifetime otherwise.
                try:
                    await self.session_service.close_session(headed_session.session_id)
                except Exception as exc:
                    logger.warning(
                        "challenge_headed_session_close_failed",
                        session_id=headed_session.session_id,
                        error=str(exc),
                    )
        except Exception as exc:
            logger.warning("challenge_headed_retry_failed", error=str(exc))
        return None

    async def _maybe_screenshot(self) -> Optional[Dict[str, Any]]:
        if not self.ladder.screenshot_on_detection or not self.browser_service:
            return None
        try:
            result = await self.browser_service.take_screenshot(
                session=self._session_for_page(),
                full_page=False,
                wait_for_dynamic=False,
            )
            return {
                "artifact_id": result.get("artifact_id"),
                "content_url": result.get("content_url"),
                "path": result.get("path"),
                "size_bytes": result.get("size_bytes"),
            }
        except Exception as exc:
            logger.debug("challenge_screenshot_failed", error=str(exc))
            return None

    def _session_for_page(self) -> Optional[Any]:
        # BrowseService stores the session on page._surf_session.
        return getattr(self.page, "_surf_session", None)

    def _elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def _success(
        self,
        state: str,
        challenge_type: Optional[str],
        indicators: List[str],
    ) -> ChallengeResult:
        return ChallengeResult(
            state=state,
            blocked=False,
            type=challenge_type,
            indicators=indicators,
            recommendation=None,
            attempts=self.attempts,
            elapsed_ms=self._elapsed_ms(),
        )
