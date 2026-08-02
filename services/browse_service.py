"""One-shot browse workflow for arbitrary sites.

Creates an ephemeral browser session, navigates, settles the page, classifies
and attempts to resolve challenges, extracts content, optionally captures a
screenshot, and closes the session unless the caller asks to keep it alive.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import structlog

from core.foundation import (
    BrowserOperationError,
    ResourceLimitError,
    get_browser_profile_service,
    get_session_service,
    get_browser_service,
)
from models.schemas import ContentMode, WaitUntil
from services.challenge_resolver import ChallengeResolver, LadderConfig
from services.document_extract_service import (
    DocumentExtractService,
    ExtractResult,
    get_document_extract_service,
)
from services.outbound_policy import OutboundPolicyError
from utils.stealth import apply_human_behavior
from utils.url_security import safe_url_for_log

logger = structlog.get_logger()


class BrowseService:
    """Shared one-shot browse ladder for MCP, CLI, and search extraction."""

    def __init__(
        self,
        session_service: Any = None,
        browser_service: Any = None,
        profile_service: Any = None,
    ):
        self.initialized = False
        self._injected_session_service = session_service
        self._injected_browser_service = browser_service
        self._injected_profile_service = profile_service

    async def initialize(self) -> None:
        self.initialized = True
        logger.info("Browse service initialized")

    async def cleanup(self) -> None:
        self.initialized = False
        logger.info("Browse service cleaned up")

    async def _session_service(self) -> Any:
        if self._injected_session_service is not None:
            return self._injected_session_service
        return await get_session_service()

    async def _browser_service(self) -> Any:
        if self._injected_browser_service is not None:
            return self._injected_browser_service
        return await get_browser_service()

    async def _profile_service(self) -> Any:
        if self._injected_profile_service is not None:
            return self._injected_profile_service
        return await get_browser_profile_service()

    async def _document_extract_service(self) -> DocumentExtractService:
        return get_document_extract_service()

    async def browse(
        self,
        url: str,
        mode: str = "standard",
        content_mode: ContentMode = ContentMode.COMPACT,
        readiness: Optional[Dict[str, Any]] = None,
        include_screenshot: bool = False,
        keep_session: bool = False,
        extract_download: bool = True,
        max_text_length: int = 8000,
        max_items: int = 100,
        timeout: int = 30000,
        allow_aggressive: bool = False,
    ) -> Dict[str, Any]:
        """Execute a one-shot browse workflow using a resolved profile."""
        if not self.initialized:
            raise BrowserOperationError("browse", "Browse service not initialized")

        started = time.time()
        # Resolve the profile before touching the browser services: a rejected
        # mode must not boot a Playwright runtime it will never use.
        profile_service = await self._profile_service()
        profile = profile_service.resolve(
            requested_mode=mode, url=url, allow_aggressive=allow_aggressive
        )

        session_service = await self._session_service()
        browser_service = await self._browser_service()
        session_overrides = dict(profile.session_overrides)
        session_overrides.setdefault("content_mode", content_mode.value)
        if profile.proxy_mode == "sticky" and profile.proxy_entry:
            session_overrides["proxy"] = {
                "server": profile.proxy_entry["server"],
                "username": profile.proxy_entry.get("username"),
                "password": profile.proxy_entry.get("password"),
            }

        session_id: Optional[str] = None
        session = None
        try:
            session_data = await session_service.create_session(
                user_config=session_overrides,
                pool="default",
            )
            session = session_data
            session_id = session_data.session_id

            # Let the challenge resolver retrieve the session for screenshots.
            # Single underscore: a dunder prefix would be name-mangled to
            # _BrowseService__surf_session and the resolver would never find it.
            page = browser_service._get_page_from_session(session)
            page._surf_session = session

            # Use the readiness load_state for the initial navigation wait if
            # provided; otherwise avoid hanging on networkidle for one-off browses.
            nav_wait = WaitUntil.DOMCONTENTLOADED
            if readiness:
                load_state = readiness.get("load_state")
                if load_state:
                    nav_wait = (
                        load_state.value
                        if hasattr(load_state, "value")
                        else load_state
                    )

            nav_result = await browser_service.navigate_to_url(
                session=session,
                url=url,
                wait_until=nav_wait,
                timeout=timeout,
                readiness=readiness,
            )

            transition = nav_result.get("transition", {})

            # If the server returned a downloadable document, extract it instead
            # of observing the page.
            document_body = nav_result.get("document_body")
            if document_body:
                if extract_download:
                    extract_service = await self._document_extract_service()
                    extract = extract_service.extract_from_bytes(
                        document_body,
                        filename=url.rsplit("/", 1)[-1].split("?")[0] or "download.bin",
                        content_type=nav_result.get("content_type"),
                    )
                else:
                    extract = ExtractResult(
                        success=False,
                        content="",
                        content_type=nav_result.get("content_type"),
                        format=None,
                        error="Document extraction disabled (extract_download=false)",
                    )
                elapsed_ms = int((time.time() - started) * 1000)
                result = {
                    "success": extract.success,
                    "url": nav_result.get("url", url),
                    "title": nav_result.get("title"),
                    "content": extract.content,
                    "content_mode": content_mode.value,
                    "transition": {
                        "initial_url": transition.get("initial_url", url),
                        "final_url": transition.get("final_url", nav_result.get("url", url)),
                        "route_changed": transition.get("route_changed", False),
                        "response_status": transition.get("response_status"),
                        "elapsed_ms": transition.get("elapsed_ms", elapsed_ms),
                        "readiness_reason": "document_extract",
                        "timeout_stage": transition.get("timeout_stage"),
                        "challenge_state": None,
                    },
                    "challenge": None,
                    "document_extract": extract.to_dict(),
                    "screenshot_artifact": None,
                    "warnings": nav_result.get("warnings", []) + profile.warnings,
                    "session_id": session_id if keep_session else None,
                }
                if not keep_session:
                    await session_service.close_session(session_id)
                    session_id = None
                    session = None
                logger.info(
                    "Browse document extracted",
                    url=safe_url_for_log(url),
                    mode=profile.mode,
                    format=extract.format,
                    elapsed_ms=elapsed_ms,
                )
                return result

            # Apply scoped human behavior only when the profile enables it.
            hb = profile.human_behavior
            if hb.get("enabled"):
                await apply_human_behavior(
                    page,
                    scroll_pauses=hb.get("scroll_pauses", 2),
                    mouse_movements=hb.get("mouse_movements", True),
                )

            # Run bounded challenge ladder.
            ladder = LadderConfig.from_dict(profile.challenge_ladder)
            resolver = ChallengeResolver(
                page,
                ladder=ladder,
                browser_service=browser_service,
                session_service=session_service,
            )
            challenge = (await resolver.run()).to_dict()

            # Observe / extract content.
            observe = await browser_service.observe_page(
                session=session,
                include_screenshot=False,
                max_text_length=max_text_length,
                max_items=max_items,
                content_mode=content_mode.value,
            )

            screenshot_artifact = None
            if include_screenshot:
                screenshot = await browser_service.take_screenshot(
                    session=session,
                    full_page=False,
                    wait_for_dynamic=False,
                )
                screenshot_artifact = {
                    "artifact_id": screenshot.get("artifact_id"),
                    "content_url": screenshot.get("content_url"),
                    "path": screenshot.get("path"),
                    "size_bytes": screenshot.get("size_bytes"),
                }

            elapsed_ms = int((time.time() - started) * 1000)

            result = {
                "success": not challenge.get("blocked", False),
                "url": observe.get("url", nav_result.get("url", url)),
                "title": observe.get("title"),
                "content": observe.get("visible_text"),
                "content_mode": content_mode.value,
                "transition": {
                    "initial_url": transition.get("initial_url", url),
                    "final_url": transition.get("final_url", observe.get("url", url)),
                    "route_changed": transition.get("route_changed", False),
                    "response_status": transition.get("response_status"),
                    "elapsed_ms": transition.get("elapsed_ms", elapsed_ms),
                    "readiness_reason": transition.get("readiness_reason", "unknown"),
                    "timeout_stage": transition.get("timeout_stage"),
                    "challenge_state": challenge.get("state"),
                },
                "challenge": challenge,
                "screenshot_artifact": screenshot_artifact,
                "warnings": observe.get("warnings", []) + profile.warnings,
                "session_id": session_id if keep_session else None,
            }

            if not keep_session:
                await session_service.close_session(session_id)
                session_id = None
                session = None

            logger.info(
                "Browse completed",
                url=safe_url_for_log(url),
                mode=profile.mode,
                elapsed_ms=elapsed_ms,
                readiness_reason=result["transition"]["readiness_reason"],
                challenge_state=challenge.get("state"),
            )
            return result

        except (ResourceLimitError, OutboundPolicyError):
            # Surface egress denials as themselves so the controller can map
            # them to 403 instead of a generic 500.
            if session_id:
                try:
                    await session_service.close_session(session_id)
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.error("Browse failed", url=safe_url_for_log(url), error=str(e))
            if session_id:
                try:
                    await session_service.close_session(session_id)
                except Exception:
                    pass
            raise BrowserOperationError("browse", str(e))
