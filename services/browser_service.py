"""Enhanced browser operations service for Surf Browser Service"""
import asyncio
import os
import random
import time
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
import structlog

from core.foundation import BrowserOperationError, ValidationError
from models.schemas import SessionData, ExtractType, InteractionAction, WaitUntil
from utils.helpers import random_delay, safe_click_with_retry, wait_for_network_idle
from utils.stealth import get_random_headers, simulate_human_behavior, get_realistic_headers
from utils.anti_detection import (
    SmartWaiter, HumanMimicry, HumanMouseMovement, AdaptiveRateLimiter,
    get_enhanced_stealth_config, proxy_rotator, adaptive_rate_limiter
)
from utils.resource_monitor import resource_monitor
from utils.content_processor import (
    ContentProcessor, ContentMetrics, ContentDeduplicator, 
    ContentTypeDetector, content_deduplicator
)
from utils.site_memory import create_site_memory_manager
from utils.semantic_chunker import SemanticChunker
from config.settings import settings
from services.outbound_policy import get_outbound_policy
from services.element_registry import element_registry
from services.observation_script import (
    OBSERVATION_SCRIPT,
    ROLE_OF_ELEMENT,
    SENSITIVE_ELEMENT_PREDICATE,
)
from services.page_readiness_service import PageReadinessService, ReadinessTimeoutError
from utils.path_policy import resolve_export_file
from utils.url_security import safe_url_for_log

logger = structlog.get_logger()


class BrowserService:
    """Enhanced browser operations service with improved error handling and performance"""
    
    def __init__(self):
        self.initialized = False
        from services.download_service import DownloadService
        self.artifact_service = DownloadService()
        self.site_memory_manager = (
            create_site_memory_manager(ttl=settings.site_memory_ttl)
            if settings.enable_site_memory
            else None
        )
        self.network_captures: Dict[str, Dict[str, Any]] = {}
        self.console_captures: Dict[str, Dict[str, Any]] = {}
    
    async def initialize(self) -> None:
        """Initialize browser service"""
        self.initialized = True
        
        # Start resource monitoring
        resource_monitor.start_monitoring(interval=30)
        
        logger.info("Browser service initialized with resource monitoring")
    
    async def cleanup(self) -> None:
        """Cleanup browser service"""
        self.initialized = False
        
        # Stop resource monitoring
        resource_monitor.stop_monitoring()
        for capture in list(self.console_captures.values()):
            capture["page"].remove_listener("console", capture["listener"])
            capture["page"].remove_listener("close", capture["close_listener"])
        self.console_captures.clear()
        
        logger.info("Browser service cleaned up")

    def _console_key(self, session: SessionData) -> str:
        return f"{session.session_id}:{session.active_page_id or 'page_0'}"

    async def manage_console_capture(
        self, session: SessionData, action: str = "read", limit: int = 100,
        clear_after_read: bool = False,
    ) -> Dict[str, Any]:
        """Start/read/clear/stop a page-scoped, bounded console message buffer."""
        page = self._get_page_from_session(session)
        key = self._console_key(session)
        capture = self.console_captures.get(key)
        if action == "start":
            if capture:
                capture["page"].remove_listener("console", capture["listener"])
                capture["page"].remove_listener("close", capture["close_listener"])
            buffer = deque(maxlen=limit)
            def listener(message):
                buffer.append({
                    "type": message.type,
                    "text": message.text[:10000],
                    "location": dict(message.location or {}),
                    "timestamp_ms": int(time.time() * 1000),
                })
            def close_listener():
                self.console_captures.pop(key, None)
            page.on("console", listener)
            page.on("close", close_listener)
            capture = {"page": page, "listener": listener, "close_listener": close_listener, "entries": buffer, "capacity": limit}
            self.console_captures[key] = capture
        elif action in {"clear", "stop"} and capture:
            capture["entries"].clear()
            if action == "stop":
                capture["page"].remove_listener("console", capture["listener"])
                capture["page"].remove_listener("close", capture["close_listener"])
                self.console_captures.pop(key, None)
                capture = None

        entries = list(capture["entries"])[-limit:] if capture else []
        result = {
            "active": capture is not None,
            "entries": entries,
            "count": len(entries),
            "capacity": capture["capacity"] if capture else 0,
            "action": action,
        }
        if action == "read" and clear_after_read and capture:
            capture["entries"].clear()
        return result

    async def press_key(
        self, session: SessionData, key: str, selector: Optional[str] = None,
        handle: Optional[str] = None, timeout: int = 30000,
    ) -> Dict[str, Any]:
        """Press a raw key, preserving focus unless an exact target is supplied."""
        page = self._get_page_from_session(session)
        async with asyncio.timeout(timeout / 1000):
            target = None
            target_kind = "active_element"
            if handle:
                page_id = session.active_page_id or "page_0"
                record = element_registry.get(handle, session.session_id, page_id)
                frame = self._frame_by_identity(page, record.frame_id)
                if frame is None:
                    raise BrowserOperationError("press_key", "Target frame unavailable")
                locator = frame.locator(record.locator)
                if await locator.count() != 1:
                    raise BrowserOperationError("press_key", "Verified target is stale")
                target = await locator.first.element_handle()
                actual = await self._interaction_fingerprint(target) if target else {}
                if target is None or any(actual.get(k, "") != v for k, v in record.fingerprint.items()):
                    raise BrowserOperationError("press_key", "Verified target is stale")
                target_kind = "handle"
            elif selector:
                locator = page.locator(selector)
                count = await locator.count()
                if count != 1:
                    raise BrowserOperationError("press_key", f"Target matched {count} elements")
                target = await locator.first.element_handle()
                target_kind = "selector"
            if target is not None:
                await target.focus()
            await page.keyboard.press(key)
        return {"key": key, "target": target_kind, "focus_behavior": "target_focused" if target else "preserved", "timeout_ms": timeout}

    async def resize_viewport(
        self, session: SessionData, width: int, height: int, timeout: int = 30000,
    ) -> Dict[str, Any]:
        """Resize the active page in place and report browser-observed dimensions."""
        page = self._get_page_from_session(session)
        async with asyncio.timeout(timeout / 1000):
            await page.set_viewport_size({"width": width, "height": height})
            actual = await page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
        return {"requested": {"width": width, "height": height}, "actual": actual, "page_id": session.active_page_id or "page_0"}

    @staticmethod
    def _frame_identity(frame) -> str:
        """Return Playwright's stable identity for a live frame object."""
        if isinstance(frame, Page):
            frame = frame.main_frame
        return str(frame._impl_obj._guid)

    @classmethod
    def _frame_by_identity(cls, page, frame_id: str):
        return next(
            (frame for frame in page.frames if cls._frame_identity(frame) == str(frame_id)),
            None,
        )
    
    async def navigate_to_url(
        self,
        session: SessionData,
        url: str,
        wait_until: WaitUntil = WaitUntil.NETWORKIDLE,
        timeout: Optional[int] = None,
        readiness: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Navigate to URL with intelligent waiting and error handling"""

        if not self.initialized:
            raise BrowserOperationError("navigate", "Browser service not initialized")

        await get_outbound_policy().validate(url)

        start_time = time.time()
        initial_url = session.context.url
        try:
            # Get page from session
            page = self._get_page_from_session(session)
            element_registry.evict_page(session.session_id, session.active_page_id or "page_0")

            # Apply adaptive rate limiting if enabled
            if settings.enable_adaptive_rate_limiting:
                await adaptive_rate_limiter.wait_if_needed(success=True)

            # Load site memory if enabled
            site_memory = None
            if self.site_memory_manager is not None:
                site_memory = await asyncio.to_thread(
                    self.site_memory_manager.get_site_memory, url
                )
                if site_memory:
                    logger.debug(
                        "Loaded site memory",
                        site_url=safe_url_for_log(url),
                        access_count=site_memory.access_count,
                    )

            # Set timeout
            actual_timeout = timeout or session.config.timeout

            # Navigate with retry logic
            response = await self._navigate_with_retry(
                page, url, wait_until, actual_timeout
            )

            # SPA / dynamic settlement
            # Copy: the caller's dict must not gain a timeout as a side effect.
            readiness_spec = dict(readiness or {})
            if not readiness_spec.get("timeout"):
                readiness_spec["timeout"] = actual_timeout
            try:
                settle = await PageReadinessService.wait(
                    page, readiness_spec, start_url=initial_url
                )
            except ReadinessTimeoutError as rte:
                settle = {
                    "success": False,
                    "initial_url": initial_url or url,
                    "final_url": page.url,
                    "route_changed": (initial_url or url) != page.url,
                    "readiness_reason": "timeout",
                    "elapsed_ms": rte.elapsed_ms,
                    "timeout_stage": rte.stage,
                }

            duration = time.time() - start_time

            # Update session context
            session.context.url = page.url
            session.context.title = await page.title()

            # Update site memory with success
            if self.site_memory_manager is not None:
                await asyncio.to_thread(
                    self.site_memory_manager.update_access_stats, url, True
                )

            # Update resource monitoring
            resource_monitor.update_session_metrics(
                session_id=session.session_id,
                success=True,
                response_time=duration
            )

            result = {
                "url": page.url,
                "status": response.status if response else None,
                "title": session.context.title,
                "duration_ms": int(duration * 1000),
                "success": True,
                "site_memory_loaded": site_memory is not None,
                "warnings": self._navigation_warnings(response.status if response else None, page.url),
                "transition": {
                    "initial_url": settle.get("initial_url", initial_url or url),
                    "final_url": settle.get("final_url", page.url),
                    "route_changed": settle.get("route_changed", False),
                    "response_status": response.status if response else None,
                    "elapsed_ms": settle.get("elapsed_ms", int(duration * 1000)),
                    "readiness_reason": settle.get("readiness_reason", "unknown"),
                    "timeout_stage": settle.get("timeout_stage"),
                },
                "content_type": response.headers.get("content-type", "").split(";")[0].strip() if response else None,
                "document_body": None,
            }

            # If the navigation landed on a downloadable document, capture the
            # response body so the caller can route it to DocumentExtractService.
            if response and self._is_document_content_type(result["content_type"]):
                try:
                    body = await response.body()
                    if body and len(body) <= settings.max_download_size_bytes:
                        result["document_body"] = body
                        result["warnings"].append(
                            f"Document response detected ({result['content_type']}); use document extraction."
                        )
                    elif body:
                        result["warnings"].append("Document response exceeds download size limit; not captured.")
                except Exception as exc:
                    logger.debug("Failed to capture document response body", error=str(exc))

            logger.info(
                "Navigation completed",
                session_id=session.session_id,
                url=safe_url_for_log(result["url"]),
                status=result["status"],
                duration_ms=result["duration_ms"],
                readiness_reason=result["transition"]["readiness_reason"],
            )
            return result

        except Exception as e:
            # Update site memory with failure
            if self.site_memory_manager is not None:
                await asyncio.to_thread(
                    self.site_memory_manager.update_access_stats, url, False
                )

            # Update resource monitoring with failure
            resource_monitor.update_session_metrics(
                session_id=session.session_id,
                success=False,
                response_time=time.time() - start_time
            )

            logger.error(
                "Navigation failed",
                session_id=session.session_id,
                url=safe_url_for_log(url),
                error=str(e),
            )
            raise BrowserOperationError("navigate", str(e))
    
    async def extract_content(
        self,
        session: SessionData,
        extract_type: ExtractType,
        selector: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Extract content with intelligent fallback strategies"""
        
        if not self.initialized:
            raise BrowserOperationError("extract", "Browser service not initialized")
        
        try:
            page = self._get_page_from_session(session)
            actual_timeout = timeout or session.config.timeout
            
            if extract_type == ExtractType.TEXT:
                result = await self._extract_text(page, selector, actual_timeout)
            elif extract_type == ExtractType.HTML:
                result = await self._extract_html(page, selector, actual_timeout)
            elif extract_type == ExtractType.TABLE:
                result = await self._extract_table(page, selector, actual_timeout)
            elif extract_type == ExtractType.LINKS:
                result = await self._extract_links(page, selector, actual_timeout)
            elif extract_type == ExtractType.IMAGES:
                result = await self._extract_images(page, selector, actual_timeout)
            else:
                raise ValidationError("extract_type", f"Unsupported extract type: {extract_type}")
            
            # Enhanced content processing
            enhanced_result = await self._enhance_extracted_content(result, extract_type)
            
            # Flatten response for better accessibility - extract the actual content to top level
            final_result = {
                "success": True,
                "extract_type": extract_type.value,
                "selector": selector
            }
            
            # Add the actual content based on extract type for easy access
            if extract_type == ExtractType.TEXT:
                if "raw_content" in enhanced_result and "text" in enhanced_result["raw_content"]:
                    final_result["content"] = enhanced_result["raw_content"]["text"]
                elif "text" in enhanced_result:
                    final_result["content"] = enhanced_result["text"]
            elif extract_type == ExtractType.HTML:
                if "raw_content" in enhanced_result and "html" in enhanced_result["raw_content"]:
                    final_result["content"] = enhanced_result["raw_content"]["html"]
                elif "html" in enhanced_result:
                    final_result["content"] = enhanced_result["html"]
            elif extract_type == ExtractType.LINKS:
                if "raw_content" in enhanced_result and "links" in enhanced_result["raw_content"]:
                    final_result["content"] = enhanced_result["raw_content"]["links"]
                elif "links" in enhanced_result:
                    final_result["content"] = enhanced_result["links"]
            elif extract_type == ExtractType.IMAGES:
                if "raw_content" in enhanced_result and "images" in enhanced_result["raw_content"]:
                    final_result["content"] = enhanced_result["raw_content"]["images"]
                elif "images" in enhanced_result:
                    final_result["content"] = enhanced_result["images"]
            elif extract_type == ExtractType.TABLE:
                if "raw_content" in enhanced_result and "table" in enhanced_result["raw_content"]:
                    final_result["content"] = enhanced_result["raw_content"]["table"]
                elif "table" in enhanced_result:
                    final_result["content"] = enhanced_result["table"]
            
            # Keep the full enhanced result for detailed info
            final_result["data"] = enhanced_result
            
            return final_result
                
        except Exception as e:
            logger.error("Content extraction failed", session_id=session.session_id, extract_type=extract_type, error=str(e))
            raise BrowserOperationError("extract", str(e))

    async def observe_page(
        self,
        session: SessionData,
        include_screenshot: bool = False,
        max_text_length: int = 8000,
        max_items: int = 100,
        content_mode: str = "compact",
        cursor: Optional[str] = None,
        limit: Optional[Any] = None,
        role: Optional[str] = None,
        action: Optional[str] = None,
        visibility: Optional[str] = None,
        name_contains: Optional[str] = None,
        scope_handle: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a compact agent-friendly observation of the current page."""
        if not self.initialized:
            raise BrowserOperationError("observe", "Browser service not initialized")

        try:
            page = self._get_page_from_session(session)
            page_id = session.active_page_id or "page_0"
            scope_record = None
            scope_element = None
            if scope_handle:
                try:
                    scope_record = element_registry.get(scope_handle, session.session_id, page_id)
                    scope_frame = self._frame_by_identity(page, scope_record.frame_id)
                    if scope_frame is None:
                        raise ValueError("Scope frame is unavailable")
                    scope_locator = scope_frame.locator(scope_record.locator)
                    if await scope_locator.count() != 1:
                        raise ValueError("Scope locator is stale or ambiguous")
                    scope_element = await scope_locator.element_handle()
                    if scope_element is None:
                        raise ValueError("Scope element is detached")
                    actual = await self._interaction_fingerprint(scope_element)
                    if any(
                        actual.get(key, "") != scope_record.fingerprint.get(key, "")
                        for key in scope_record.fingerprint
                    ):
                        raise ValueError("Scope fingerprint mismatch")
                except ValueError as exc:
                    return {
                        "outcome": "failure", "reason": "stale_handle",
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                    }

            extracted = []
            for frame_index, frame in enumerate(page.frames):
                frame_id = self._frame_identity(frame)
                if scope_record and frame_id != scope_record.frame_id:
                    continue
                payload = await frame.evaluate(
                    OBSERVATION_SCRIPT,
                    {
                        "maxTextLength": max_text_length,
                        "contentMode": content_mode,
                        "scopeElement": scope_element if scope_record else None,
                    },
                )
                for raw in payload.pop("elements", []):
                    candidates = raw.pop("locator_candidates", [])
                    locator = candidates[0] if candidates else ""
                    if not locator:
                        continue
                    fingerprint = raw.pop("fingerprint")
                    raw["locator"] = locator
                    raw["_fingerprint"] = fingerprint
                    raw["_frame_id"] = frame_id
                    if frame_index:
                        raw["context"] = {"frame_index": frame_index}
                    raw["_legacy"] = raw.pop("legacy")
                    extracted.append(raw)
                extracted.append({"_frame_payload": payload, "_frame_index": frame_index})

            frame_payloads = [item["_frame_payload"] for item in extracted if "_frame_payload" in item]
            all_elements = [item for item in extracted if "_frame_payload" not in item]
            filtered = all_elements
            if role:
                filtered = [item for item in filtered if item["role"] == role]
            if action:
                filtered = [item for item in filtered if action in item["actions"]]
            if visibility and visibility != "all":
                wanted = visibility == "visible"
                filtered = [item for item in filtered if item["state"]["visible"] is wanted]
            if name_contains:
                needle = name_contains.casefold()
                filtered = [item for item in filtered if needle in item["name"].casefold()]

            counts_by_role: Dict[str, int] = {}
            counts_by_action: Dict[str, int] = {}
            for item in filtered:
                counts_by_role[item["role"]] = counts_by_role.get(item["role"], 0) + 1
                for item_action in item["actions"]:
                    counts_by_action[item_action] = counts_by_action.get(item_action, 0) + 1
            inventory_limit = {"slim": 25, "verbose": 100}.get(limit, limit)
            inventory_limit = inventory_limit or settings.observe_inventory_default_limit
            offset = int(cursor or 0)
            page_elements = filtered[offset:offset + inventory_limit]
            for index, item in enumerate(page_elements, start=offset):
                item["handle"] = element_registry.register(
                    session.session_id,
                    page_id,
                    item.pop("_frame_id"),
                    item["locator"],
                    item.pop("_fingerprint"),
                )
                item["index"] = index
            next_cursor = str(offset + inventory_limit) if offset + inventory_limit < len(filtered) else None

            links = []
            actions = []
            form_groups: Dict[str, Dict[str, Any]] = {}
            for item in all_elements:
                legacy = item["_legacy"]
                if item.get("link") and item["state"]["visible"]:
                    links.append({
                        "index": len(links), "text": item["name"],
                        "href": item["link"]["resolved"], "resolved": item["link"]["resolved"],
                        "visible": item["link"]["visible"],
                    })
                if "click" in item["actions"] and item["state"]["visible"]:
                    actions.append({
                        "tag": item["tag"], "text": item["name"], "id": legacy["id"],
                        "name": legacy["name"], "selector_hint": item["locator"],
                    })
                if item.get("form"):
                    form = item["form"]
                    key = f"{form['id']}|{form['action']}|{form['method']}"
                    group = form_groups.setdefault(key, {"action": form["action"], "method": form["method"], "fields": []})
                    group["fields"].append({
                        "tag": item["tag"], "type": item.get("input_type", ""), "name": legacy["name"],
                        "id": legacy["id"], "placeholder": item.get("placeholder", ""), "label": item["name"],
                    })
            forms = [
                {"index": index, **form, "fields": form["fields"][:50]}
                for index, form in enumerate(form_groups.values())
            ][:max_items]
            links = links[:max_items]
            actions = actions[:max_items]
            for item in page_elements:
                item.pop("_legacy", None)
            main_payload = frame_payloads[0] if frame_payloads else {
                "visible_text": "", "visible_text_length": 0, "token_estimate": 0,
                "source_text_length": 0, "selected_text_length": 0, "truncated": False,
                "reduction_ratio": 0, "tables": [],
            }
            observation = {
                **main_payload,
                "elements": page_elements,
                "total": len(filtered),
                "next_cursor": next_cursor,
                "counts_by_role": counts_by_role,
                "counts_by_action": counts_by_action,
                "visible_count": sum(1 for item in filtered if item["state"]["visible"]),
                "hidden_count": sum(1 for item in filtered if not item["state"]["visible"]),
                "links": links,
                "forms": forms,
                "actions": actions,
                "tables": main_payload.get("tables", [])[:min(max_items, 20)],
            }

            screenshot_artifact = {}
            if include_screenshot:
                screenshot = await self.take_screenshot(session=session, full_page=False, wait_for_dynamic=False)
                screenshot_artifact = {
                    "screenshot_artifact_id": screenshot.get("artifact_id"),
                    "screenshot_content_url": screenshot.get("content_url"),
                }

            return {
                "url": page.url,
                "title": await page.title(),
                **screenshot_artifact,
                "content_mode": content_mode,
                "blocker": session.metadata.get("blocker", {}),
                "blocker_delta": session.metadata.get("last_navigation_blocker", {}),
                "warnings": self._page_warnings(await page.title(), observation.get("visible_text", "")),
                **observation
            }
        except Exception as e:
            logger.error("Page observation failed", session_id=session.session_id, error=str(e))
            raise BrowserOperationError("observe", str(e))

    async def observe_structured(
        self,
        session: SessionData,
        *,
        max_blocks: int = 200,
        max_table_rows: int = 30,
    ) -> Dict[str, Any]:
        """Extract ordered DOM blocks (headings, paragraphs, lists, tables) from article root."""
        if not self.initialized:
            raise BrowserOperationError("observe_structured", "Browser service not initialized")

        try:
            page = self._get_page_from_session(session)
            payload = await page.evaluate(
                """
                ({ maxBlocks, maxTableRows }) => {
                    const noiseSelector = [
                        '[class*="ad-"]', '[class*="ads"]', '[id*="ad-"]', '[id*="ads"]',
                        '[class*="cookie"]', '[id*="cookie"]', '[class*="newsletter"]',
                        '[class*="subscribe"]', '[aria-label*="advertisement" i]',
                        '.comments', '#comments', '.comment-respond', '.related-posts',
                        '.post-navigation', '.related-posts-wrapper', '.you-may-like',
                        'nav', 'header', 'footer', 'aside', 'form'
                    ].join(',');

                    const articleSelectors = [
                        '.entry-content', '.post-content', '.article-content', '.article-body',
                        '.story-body', 'article .content', 'main article', 'article', 'main',
                        '[role=main]', '.article', '.story', '.post'
                    ];

                    const visible = (el) => {
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style && style.visibility !== 'hidden' &&
                            style.display !== 'none' && rect.width > 0 && rect.height > 0;
                    };

                    const text = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();

                    let root = document.body;
                    let bestLength = 0;
                    for (const sel of articleSelectors) {
                        const candidate = document.querySelector(sel);
                        if (!candidate) continue;
                        const t = text(candidate);
                        // Largest candidate wins: a small nested element (nav,
                        // breadcrumbs) must not claim the article root.
                        if (t.length >= 200 && t.length > bestLength) {
                            root = candidate;
                            bestLength = t.length;
                        }
                    }

                    const blocks = [];
                    const seen = new Set();
                    const pushBlock = (block) => {
                        if (blocks.length >= maxBlocks) return;
                        const key = block.type + ':' + (block.text || JSON.stringify(block.rows || block.items || '')).slice(0, 120);
                        if (seen.has(key)) return;
                        seen.add(key);
                        blocks.push(block);
                    };

                    const walk = (node) => {
                        if (!node || blocks.length >= maxBlocks) return;
                        if (node.nodeType !== 1) return;
                        const isRoot = node === root;
                        if (!isRoot && node.matches && node.matches(noiseSelector)) return;

                        const tag = node.tagName ? node.tagName.toLowerCase() : '';
                        if (/^h[1-6]$/.test(tag) && visible(node)) {
                            const level = parseInt(tag[1], 10);
                            const t = text(node).slice(0, 500);
                            if (t.length >= 3) pushBlock({ type: 'heading', level, text: t });
                            return;
                        }
                        if (tag === 'p' && visible(node)) {
                            const t = text(node).slice(0, 5000);
                            if (t.length >= 20) pushBlock({ type: 'paragraph', text: t });
                            return;
                        }
                        if ((tag === 'ul' || tag === 'ol') && visible(node)) {
                            const items = Array.from(node.querySelectorAll(':scope > li'))
                                .map((li) => text(li).slice(0, 1000)).filter((t) => t.length >= 8).slice(0, 40);
                            if (items.length) pushBlock({ type: 'list', ordered: tag === 'ol', items });
                            return;
                        }
                        if (tag === 'table' && visible(node)) {
                            const rows = Array.from(node.querySelectorAll('tr')).slice(0, maxTableRows).map((row) =>
                                Array.from(row.cells).slice(0, 20).map((cell) => text(cell).slice(0, 200))
                            ).filter((row) => row.some((c) => c.length > 0));
                            if (rows.length) pushBlock({ type: 'table', rows });
                            return;
                        }
                        if (tag === 'blockquote' && visible(node)) {
                            const t = text(node).slice(0, 5000);
                            if (t.length >= 20) pushBlock({ type: 'quote', text: t });
                            return;
                        }
                        if (tag === 'div' && visible(node)) {
                            const blockChildren = Array.from(node.children).filter((c) =>
                                /^(p|h[1-6]|ul|ol|table|blockquote|div)$/i.test(c.tagName || '')
                            );
                            if (blockChildren.length === 0) {
                                const t = text(node);
                                if (t.length >= 40 && t.length <= 5000) {
                                    pushBlock({ type: 'paragraph', text: t });
                                    return;
                                }
                            }
                        }

                        for (const child of node.children || []) {
                            walk(child);
                        }
                    };

                    walk(root);
                    return { blocks, root_selector: root === document.body ? 'body' : (root.tagName || 'body').toLowerCase() };
                }
                """,
                {"maxBlocks": max_blocks, "maxTableRows": max_table_rows},
            )

            return {
                "url": page.url,
                "title": await page.title(),
                "blocks": payload.get("blocks") or [],
                "root_selector": payload.get("root_selector", "body"),
            }
        except Exception as e:
            logger.error("Structured observation failed", session_id=session.session_id, error=str(e))
            raise BrowserOperationError("observe_structured", str(e))

    async def click_and_download(
        self,
        session: SessionData,
        selector: str,
        timeout: int = 60000,
        filename: Optional[str] = None,
        output_dir: Optional[str] = None,
        overwrite: bool = False
    ) -> Dict[str, Any]:
        """Click an element and save the resulting browser download."""
        page = self._get_page_from_session(session)
        try:
            from core.foundation import get_download_service

            download_service = await get_download_service()
            async with page.expect_download(timeout=timeout) as download_info:
                await page.locator(selector).click(timeout=timeout)
            download = await download_info.value
            result = await download_service.save_playwright_download(
                download,
                filename=filename,
                output_dir=output_dir,
                overwrite=overwrite,
            )
            logger.info("Browser download saved", session_id=session.session_id, download_id=result.get("download_id"))
            return result
        except ValidationError:
            raise
        except Exception as e:
            logger.error("Browser download failed", session_id=session.session_id, selector=selector, error=str(e))
            raise BrowserOperationError("download", str(e))

    async def wait_for_condition(
        self,
        session: SessionData,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        url_contains: Optional[str] = None,
        url_regex: Optional[str] = None,
        js_predicate: Optional[str] = None,
        load_state: Optional[WaitUntil] = None,
        dom_stable_ms: Optional[int] = None,
        network_quiet_ms: Optional[int] = None,
        timeout: int = 30000
    ) -> Dict[str, Any]:
        """Wait for an explicit browser condition."""
        page = self._get_page_from_session(session)
        started = time.time()
        initial_url = page.url
        spec = {
            "selector": selector,
            "text": text,
            "url_contains": url_contains,
            "url_regex": url_regex,
            "js_predicate": js_predicate,
            "load_state": load_state,
            "dom_stable_ms": dom_stable_ms,
            "network_quiet_ms": network_quiet_ms,
            "timeout": timeout,
        }
        # Remove None values so the service uses sensible defaults.
        spec = {k: v for k, v in spec.items() if v is not None}
        try:
            settle = await PageReadinessService.wait(page, spec, start_url=initial_url)
            return {
                "success": True,
                "url": page.url,
                "duration_ms": int((time.time() - started) * 1000),
                "transition": settle,
            }
        except ReadinessTimeoutError as rte:
            raise BrowserOperationError(
                "wait",
                f"Timeout waiting for condition ({rte.stage}) after {rte.elapsed_ms}ms",
            )

    async def start_network_capture(
        self,
        session: SessionData,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Start bounded network response capture for a session."""
        page = self._get_page_from_session(session)
        filters = filters or {}
        capture = {
            "enabled": True,
            "filters": filters,
            "events": deque(maxlen=500)
        }
        async def capture_response(response):
            try:
                if not capture.get("enabled"):
                    return
                if not self._network_response_matches(response, filters):
                    return
                event = {
                    "url": response.url,
                    "status": response.status,
                    "method": response.request.method,
                    "resource_type": response.request.resource_type,
                    "content_type": response.headers.get("content-type", ""),
                    "timestamp": time.time()
                }
                if filters.get("include_body"):
                    event["body"] = await self._safe_response_body(response, filters.get("max_body_bytes", 65536))
                capture["events"].append(event)
            except Exception as e:
                logger.debug("Network capture event skipped", error=str(e))

        def handler(response):
            asyncio.create_task(capture_response(response))

        old_capture = self.network_captures.get(session.session_id)
        if old_capture:
            self._remove_network_listener(session, old_capture)
        capture["handler"] = handler
        self.network_captures[session.session_id] = capture
        page.on("response", handler)
        return {"capturing": True, "session_id": session.session_id, "filters": filters}

    async def stop_network_capture(self, session: SessionData) -> Dict[str, Any]:
        """Stop network capture for a session."""
        capture = self.network_captures.get(session.session_id)
        if capture:
            capture["enabled"] = False
            self._remove_network_listener(session, capture)
            self.network_captures.pop(session.session_id, None)
        return {"capturing": False, "session_id": session.session_id}

    async def get_network_events(self, session: SessionData) -> Dict[str, Any]:
        """Return captured network events for a session."""
        capture = self.network_captures.get(session.session_id)
        events = list(capture["events"]) if capture else []
        return {
            "session_id": session.session_id,
            "capturing": bool(capture and capture.get("enabled")),
            "count": len(events),
            "events": events
        }

    def cleanup_session(self, session_id: str) -> None:
        """Drop browser-service state tied to a closed session."""
        capture = self.network_captures.pop(session_id, None)
        if capture:
            capture["enabled"] = False

    def _remove_network_listener(self, session: SessionData, capture: Dict[str, Any]) -> None:
        handler = capture.get("handler")
        if not handler:
            return
        try:
            page = self._get_page_from_session(session)
            page.remove_listener("response", handler)
        except Exception as e:
            logger.debug("Network listener cleanup skipped", session_id=session.session_id, error=str(e))
    
    async def _enhance_extracted_content(self, content: Dict[str, Any], extract_type: ExtractType) -> Dict[str, Any]:
        """Enhance extracted content with deduplication, type detection, and chunking"""
        # Extract text content for processing
        text_content = ""
        if "text" in content:
            text_content = content["text"]
        elif "html" in content:
            text_content = content["html"]
        elif "raw_content" in content:
            text_content = str(content["raw_content"])
        
        enhanced_result = {
            "raw_content": content,
            "extract_type": extract_type.value
        }
        
        # Content deduplication
        if settings.enable_content_deduplication and text_content:
            is_duplicate = content_deduplicator.is_duplicate(text_content)
            enhanced_result["is_duplicate"] = is_duplicate
            
            if is_duplicate:
                logger.debug("Duplicate content detected", content_length=len(text_content))
                return enhanced_result
        
        # Content type detection
        if settings.enable_semantic_chunking and text_content:
            content_type = ContentTypeDetector.detect_content_type(text_content)
            confidence = ContentTypeDetector.get_content_confidence(text_content, content_type)
            
            enhanced_result["content_type"] = content_type
            enhanced_result["type_confidence"] = confidence
            
            # Semantic chunking for text content
            if extract_type == ExtractType.TEXT and confidence > settings.semantic_chunking_confidence_threshold:
                chunks = SemanticChunker.chunk_content(text_content, content_type, settings.semantic_chunking_confidence_threshold)
                enhanced_result["chunks"] = [
                    {
                        "content": chunk.content,
                        "chunk_type": chunk.chunk_type,
                        "confidence": chunk.confidence,
                        "metadata": chunk.metadata
                    }
                    for chunk in chunks
                ]
                enhanced_result["chunk_summary"] = SemanticChunker.get_chunk_summary(chunks)
        
        # Content quality assessment
        if text_content:
            metrics = ContentProcessor.assess_content_quality(text_content)
            enhanced_result["quality_metrics"] = {
                "word_count": metrics.word_count,
                "character_count": metrics.character_count,
                "quality_score": metrics.content_quality_score,
                "has_meaningful_content": metrics.has_meaningful_content
            }
        
        return enhanced_result
    
    async def interact_with_element(
        self,
        session: SessionData,
        action: InteractionAction,
        selector: Optional[str] = None,
        handle: Optional[str] = None,
        value: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        contract_version: Optional[str] = None,
        structured_outcomes: bool = False,
    ) -> Dict[str, Any]:
        """Perform an interaction, preserving the legacy path unless explicitly opted in."""
        if contract_version == "interaction.v1" or structured_outcomes:
            return await self._interact_structured(
                session=session, action=action, selector=selector, handle=handle,
                value=value, options=options, timeout=timeout,
            )
        # The new explicit handle is additive; legacy selectors and errors retain
        # their original implementation and controller boundary unchanged.
        return await self._interact_legacy(
            session=session, action=action, selector=handle or selector or "",
            value=value, options=options, timeout=timeout,
        )

    async def _interact_legacy(
        self,
        session: SessionData,
        action: InteractionAction,
        selector: str,
        value: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Perform element interactions with human-like behavior"""
        
        if not self.initialized:
            raise BrowserOperationError("interact", "Browser service not initialized")
        
        try:
            page = self._get_page_from_session(session)
            actual_timeout = timeout or session.config.timeout
            options = options or {}
            
            # Handles use the same legacy selector field during the additive migration.
            target_page = page
            target_selector = selector
            if selector.startswith("surf:e1:"):
                page_id = session.active_page_id or "page_0"
                record = element_registry.get(selector, session.session_id, page_id)
                target_page = self._frame_by_identity(page, record.frame_id)
                if target_page is None:
                    raise ValidationError("selector", "Element handle frame is unavailable")
                target_selector = record.locator
                matches = target_page.locator(target_selector)
                if await matches.count() != 1:
                    raise ValidationError("selector", "Element handle is stale or ambiguous")
                element = await matches.first.element_handle()
                if element is None:
                    raise ValidationError("selector", "Element handle is stale")
                actual = await element.evaluate("""el => {
                    const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || (tag === 'input' ? 'text' : '')).toLowerCase();
                    let role = el.getAttribute('role') || '';
                    if (!role && tag === 'a' && el.hasAttribute('href')) role = 'link';
                    else if (!role && (tag === 'button' || (tag === 'input' && ['button','submit','reset','image'].includes(type)))) role = 'button';
                    else if (!role && tag === 'textarea') role = 'textbox';
                    else if (!role && tag === 'select') role = el.multiple ? 'listbox' : 'combobox';
                    else if (!role && tag === 'input') role = type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : type === 'range' ? 'slider' : 'textbox';
                    else if (!role && tag === 'summary') role = 'button';
                    else if (!role) role = 'generic';
                    const labelledby = el.getAttribute('aria-labelledby') || '';
                    const referenced = labelledby ? labelledby.split(/\\s+/).map(id => document.getElementById(id)).filter(Boolean).map(x => x.innerText || '').join(' ') : '';
                    const controlValue = tag === 'input' && ['button','submit','reset','image'].includes(type) ? el.getAttribute('value') : '';
                    let name = referenced || el.getAttribute('aria-label') || (el.labels && el.labels.length ? Array.from(el.labels).map(x => x.innerText || '').join(' ') : '') || el.innerText || controlValue || el.getAttribute('placeholder') || el.getAttribute('title') || '';
                    const contextNode = el.closest('li,label,[role=listitem],tr,form') || el.parentElement;
                    const context = contextNode ? (contextNode.innerText || '').replace(/\\s+/g,' ').trim().slice(0,160) : '';
                    return {tag, role, type, name: name.replace(/\\s+/g,' ').trim().slice(0,160), id: el.id || '', testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || '', context};
                }""")
                expected = record.fingerprint
                if any(actual.get(key, "") != expected.get(key, "") for key in expected):
                    raise ValidationError("selector", "Element handle fingerprint mismatch")

            # Wait for element to be actionable
            if not selector.startswith("surf:e1:"):
                element = target_page.locator(target_selector)
            await element.wait_for(state="visible", timeout=actual_timeout)
            
            # Enhanced mouse movement and element-specific timing
            if settings.enable_enhanced_mouse_movement and action in [InteractionAction.CLICK, InteractionAction.DOUBLE_CLICK, InteractionAction.RIGHT_CLICK]:
                await HumanMouseMovement.human_like_move(
                    target_page,
                    target_selector,
                    bezier_points=settings.mouse_movement_bezier_points,
                    min_delay=settings.mouse_movement_min_delay,
                    max_delay=settings.mouse_movement_max_delay,
                    reaction_delay_min=settings.mouse_movement_reaction_delay_min,
                    reaction_delay_max=settings.mouse_movement_reaction_delay_max
                )
            
            # Element-specific timing for all interactions
            await HumanMimicry.element_specific_timing(target_page, target_selector, action.value)
            
            # Perform action based on type
            if action == InteractionAction.CLICK:
                await self._perform_click(element, options)
            elif action == InteractionAction.DOUBLE_CLICK:
                await self._perform_double_click(element, options)
            elif action == InteractionAction.RIGHT_CLICK:
                await self._perform_right_click(element, options)
            elif action == InteractionAction.TYPE:
                await self._perform_type(element, value, options)
            elif action == InteractionAction.SELECT:
                await self._perform_select(element, value, options)
            elif action == InteractionAction.SCROLL:
                await self._perform_scroll(element, value, options)
            elif action == InteractionAction.HOVER:
                await self._perform_hover(element, options)
            else:
                raise ValidationError("action", f"Unsupported action: {action}")
            
            result = {
                "action": action,
                "selector": selector,
                "success": True
            }
            
            logger.info("Interaction completed", session_id=session.session_id, **result)
            return result
            
        except Exception as e:
            logger.error("Interaction failed", session_id=session.session_id, action=action, selector=selector, error=str(e))
            raise BrowserOperationError("interact", str(e))

    async def _interact_structured(
        self,
        session: SessionData,
        action: InteractionAction,
        selector: Optional[str],
        handle: Optional[str],
        value: Optional[str],
        options: Optional[Dict[str, Any]],
        timeout: Optional[int],
    ) -> Dict[str, Any]:
        """Execute interaction.v1 within one caller-owned deadline."""
        started = time.monotonic()
        timeout_ms = timeout or session.config.timeout
        deadline = started + timeout_ms / 1000
        recoveries: List[Dict[str, Any]] = []
        input_kind = "handle" if handle else "selector"
        target: Dict[str, Any] = {
            "input_kind": input_kind,
            "handle": handle,
            "locator": selector,
            "match_count": None,
        }
        before = None
        page = None
        locator = None

        def remaining() -> int:
            return max(1, int((deadline - time.monotonic()) * 1000))

        async def bounded(awaitable):
            """Cancel any interaction await when the caller-owned deadline expires."""
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                close = getattr(awaitable, "close", None)
                if close:
                    close()
                raise asyncio.TimeoutError()
            async with asyncio.timeout(seconds):
                return await awaitable

        def outcome(
            reason: str,
            *,
            error: Optional[Exception] = None,
            candidates: Optional[List[Dict[str, Any]]] = None,
            after: Optional[Dict[str, Any]] = None,
            effect: Optional[Dict[str, Any]] = None,
            extra_error: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            elapsed = int((time.monotonic() - started) * 1000)
            error_data = None
            if error is not None:
                error_data = {
                    "type": type(error).__name__,
                    "message": str(error)[:1000],
                }
            if extra_error:
                error_data = {**(error_data or {}), **extra_error}
            return {
                "outcome": "success" if reason == "completed" else "failure",
                "reason": reason,
                "action": action.value,
                "target": target,
                "timing": {
                    "timeout_ms": timeout_ms,
                    "elapsed_ms": elapsed,
                    "deadline_exhausted": time.monotonic() >= deadline,
                },
                "recoveries": recoveries,
                "element_before": before,
                "element_after": after,
                "effect": effect or {},
                "error": error_data,
                "candidates": (candidates or [])[:10],
            }

        if not self.initialized:
            return outcome("browser_error", error=BrowserOperationError("interact", "Browser service not initialized"))
        if bool(handle) == bool(selector):
            return outcome("invalid_target", extra_error={"message": "Provide exactly one of handle or selector"})
        if action not in {
            InteractionAction.CLICK, InteractionAction.TYPE,
            InteractionAction.SELECT, InteractionAction.HOVER,
        }:
            return outcome("action_not_supported")
        if action in {InteractionAction.TYPE, InteractionAction.SELECT} and value is None:
            return outcome("invalid_target", extra_error={"message": f"Value is required for {action.value}"})

        try:
            browser_page = self._get_page_from_session(session)
            page = browser_page
            resolved_selector = selector
            record = None
            if handle:
                page_id = session.active_page_id or "page_0"
                try:
                    record = element_registry.get(handle, session.session_id, page_id)
                except ValueError as exc:
                    return outcome("stale_handle", error=exc, extra_error={"stale_cause": "registry_unavailable"})
                target["locator"] = record.locator
                page = self._frame_by_identity(browser_page, record.frame_id)
                if page is None:
                    return outcome("stale_handle", extra_error={"stale_cause": "frame_unavailable"})
                resolved_selector = record.locator

            locator = page.locator(resolved_selector)
            count = await bounded(locator.count())
            target["match_count"] = count
            if handle:
                if count != 1:
                    cause = "not_found" if count == 0 else "ambiguous"
                    return outcome("stale_handle", extra_error={"stale_cause": cause})
                locator = await bounded(locator.first.element_handle())
                if locator is None:
                    return outcome("stale_handle", extra_error={"stale_cause": "detached"})
                actual = await bounded(self._interaction_fingerprint(locator))
                if any(actual.get(key, "") != record.fingerprint.get(key, "") for key in record.fingerprint):
                    return outcome("stale_handle", extra_error={"stale_cause": "fingerprint_mismatch"})
            elif count == 0:
                try:
                    await bounded(locator.first.wait_for(state="attached", timeout=remaining()))
                    count = await bounded(locator.count())
                    target["match_count"] = count
                except Exception as exc:
                    return outcome("not_found", error=exc)

            if count > 1:
                candidate_data = await bounded(self._interaction_candidates(
                    session, page, resolved_selector, locator, count
                ))
                if time.monotonic() >= deadline:
                    return outcome("timeout")
                actionable = [item for item in candidate_data if item.get("_actionable", False)]
                if len(actionable) == 1:
                    chosen = actionable[0]
                    locator = await bounded(locator.nth(chosen["match_index"]).element_handle())
                    if locator is None:
                        return outcome("detached")
                    actual = await bounded(self._interaction_fingerprint(locator))
                    if any(
                        actual.get(key, "") != chosen["_fingerprint"].get(key, "")
                        for key in chosen["_fingerprint"]
                    ):
                        return outcome("detached")
                    target["handle"] = chosen["handle"]
                    target["locator"] = chosen["locator"]
                    recoveries.append({"reason": "ambiguous", "resolution": "single_actionable_match"})
                else:
                    for item in candidate_data:
                        item.pop("_actionable", None)
                        item.pop("_fingerprint", None)
                    target["match_count"] = count
                    return outcome("ambiguous", candidates=candidate_data)
            elif not handle:
                locator = await bounded(locator.first.element_handle())
                if locator is None:
                    return outcome("detached")

            if time.monotonic() >= deadline:
                return outcome("timeout")
            before = await bounded(self._interaction_snapshot(locator))
            if action == InteractionAction.TYPE:
                if before.get("readonly"):
                    return outcome("readonly")
                if not before.get("editable", False):
                    return outcome("not_editable")
            if action == InteractionAction.SELECT:
                option_matches = await bounded(locator.evaluate(
                    """(el, value) => Array.from(el.options || []).filter(
                        option => option.value === value || option.label === value
                    ).map(option => ({value: option.value, label: option.label}))""",
                    value,
                ))
                if len(option_matches) == 0:
                    return outcome("option_not_found")
                if len(option_matches) > 1:
                    return outcome("option_ambiguous")
                select_by = "value" if option_matches[0]["value"] == value else "label"
            old_url = browser_page.url
            blocker_stats = session.metadata.get("blocker", {})
            blocker_watermark = blocker_stats.get("blocked_navigation_sequence", 0)
            interaction_frame_id = self._frame_identity(page)
            try:
                if not before.get("visible", False):
                    if action in {InteractionAction.CLICK, InteractionAction.HOVER}:
                        recoveries.append({
                            "reason": "not_visible",
                            "resolution": "hover_then_recheck",
                        })
                        try:
                            await bounded(self._hover_to_reveal(
                                locator, min(remaining(), 100)
                            ))
                            revealed = await bounded(self._interaction_snapshot(locator))
                            if revealed.get("visible", False):
                                before = revealed
                        except Exception:
                            pass
                    if not before.get("visible", False):
                        recoveries.append({"reason": "not_visible", "resolution": "wait_visible"})
                        try:
                            await bounded(self._wait_element_visible(
                                locator, max(1, remaining() - 10)
                            ))
                        except Exception as exc:
                            return outcome("not_visible", error=exc)
                if time.monotonic() >= deadline:
                    return outcome("timeout")
                recoveries.append({"reason": "actionability", "resolution": "scroll_and_recheck"})
                await bounded(locator.scroll_into_view_if_needed(timeout=remaining()))
                if time.monotonic() >= deadline:
                    return outcome("timeout")
                dispatch_options = dict(options or {})
                if action == InteractionAction.SELECT:
                    dispatch_options["_select_by"] = select_by
                # Let Playwright's action timeout surface its specific
                # actionability diagnosis before our caller-owned deadline.
                # Without this reporting margin, a permanently covered target
                # races the outer asyncio timeout and degrades to opaque
                # ``timeout`` instead of ``covered_by``.
                action_timeout = max(1, remaining() - 10)
                await bounded(self._perform_structured_action(
                    locator, action, value, dispatch_options, action_timeout
                ))
            except Exception as exc:
                reason = self._normalize_interaction_error(exc, action, before)
                if handle and reason == "detached":
                    return outcome(
                        "stale_handle", error=exc,
                        extra_error={"stale_cause": "detached_after_verification"},
                    )
                return outcome(reason, error=exc)

            new_blocked_navigations = [
                entry
                for entry in session.metadata.get("blocker", {}).get("blocked_navigations", [])
                if entry.get("sequence", 0) > blocker_watermark
                and entry.get("frame_id") == interaction_frame_id
            ]
            if new_blocked_navigations:
                blocked = new_blocked_navigations[0]
                return outcome(
                    "navigation_blocked",
                    effect={
                        "blocker_delta": {
                            "blocked_navigations": new_blocked_navigations,
                            "requests_blocked": len(new_blocked_navigations),
                        },
                        "url_before": old_url,
                        "attempted_url": blocked.get("url"),
                        "block_reason": blocked.get("reason"),
                        "filter": blocked.get("filter"),
                    },
                )

            after = None
            try:
                after = await bounded(self._interaction_snapshot(
                    locator,
                    expected_value=value,
                    check_value=action in {InteractionAction.TYPE, InteractionAction.SELECT},
                ))
            except Exception:
                pass
            if action in {InteractionAction.TYPE, InteractionAction.SELECT} and (
                after is None or (
                    after.get("value_applied") is not True
                    if after.get("value_redacted")
                    else after.get("value") != value
                )
            ):
                return outcome("value_not_applied", after=after)
            effect = self._interaction_effect(before, after, old_url, browser_page.url)
            return outcome("completed", after=after, effect=effect)
        except Exception as exc:
            return outcome(self._normalize_interaction_error(exc, action, before), error=exc)

    @staticmethod
    async def _interaction_fingerprint(locator) -> Dict[str, str]:
        script = """el => {
            const tag = el.tagName.toLowerCase();
            const type = (el.getAttribute('type') || (tag === 'input' ? 'text' : '')).toLowerCase();
            const role = (__SURF_ROLE_OF_ELEMENT__)(el);
            const labelledby = el.getAttribute('aria-labelledby') || '';
            const referenced = labelledby ? labelledby.split(/\\s+/).map(id => document.getElementById(id)).filter(Boolean).map(x => x.innerText || '').join(' ') : '';
            const controlValue = tag === 'input' && ['button','submit','reset','image'].includes(type) ? el.getAttribute('value') : '';
            const name = (referenced || el.getAttribute('aria-label') || (el.labels && el.labels.length ? Array.from(el.labels).map(x => x.innerText || '').join(' ') : '') || el.innerText || controlValue || el.getAttribute('placeholder') || el.getAttribute('title') || '').replace(/\\s+/g,' ').trim().slice(0,160);
            const contextNode = el.closest('li,label,[role=listitem],tr,form') || el.parentElement;
            const context = contextNode ? (contextNode.innerText || '').replace(/\\s+/g,' ').trim().slice(0,160) : '';
            return {tag, role, type, name, id: el.id || '', testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || '', context};
        }""".replace("__SURF_ROLE_OF_ELEMENT__", ROLE_OF_ELEMENT)
        return await locator.evaluate(script)

    @staticmethod
    async def _interaction_snapshot(
        locator, expected_value: Optional[str] = None, check_value: bool = False
    ) -> Dict[str, Any]:
        script = """(el, expected) => {
            const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
            const visible = style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            const contextNode = el.closest('li,label,[role=listitem],tr,form') || el.parentElement;
            const result = {tag: el.tagName.toLowerCase(), role: (__SURF_ROLE_OF_ELEMENT__)(el), name: (el.getAttribute('aria-label') || el.innerText || el.getAttribute('placeholder') || '').replace(/\\s+/g,' ').trim().slice(0,160), context_text: contextNode ? (contextNode.innerText || '').replace(/\\s+/g,' ').trim().slice(0,160) : '', visible, enabled: !(el.disabled || el.getAttribute('aria-disabled') === 'true'), readonly: Boolean(el.readOnly || el.getAttribute('aria-readonly') === 'true'), editable: Boolean(el.isContentEditable || ['input','textarea'].includes(el.tagName.toLowerCase()))};
            const sensitive = (__SURF_SENSITIVE_ELEMENT_PREDICATE__)(el);
            if ('value' in el) {
              if (sensitive) {
                result.value_redacted = true;
                if (expected.check) result.value_applied = String(el.value ?? '') === expected.value;
              } else result.value = String(el.value ?? '').slice(0,500);
            }
            if ((el.type === 'checkbox' || el.type === 'radio') || ['checkbox','radio','switch'].includes(result.role)) result.checked = el.getAttribute('aria-checked') ? el.getAttribute('aria-checked') === 'true' : Boolean(el.checked);
            if (el.hasAttribute('aria-expanded')) result.expanded = el.getAttribute('aria-expanded') === 'true';
            return result;
        }""".replace(
            "__SURF_SENSITIVE_ELEMENT_PREDICATE__", SENSITIVE_ELEMENT_PREDICATE
        ).replace("__SURF_ROLE_OF_ELEMENT__", ROLE_OF_ELEMENT)
        return await locator.evaluate(
            script, {"value": expected_value, "check": check_value}
        )

    async def _interaction_candidates(self, session, page, selector, locator, count):
        page_id = session.active_page_id or "page_0"
        frame_id = self._frame_identity(page)
        candidates = []
        for index in range(min(count, 10)):
            item = locator.nth(index)
            fingerprint = await self._interaction_fingerprint(item)
            snapshot = await self._interaction_snapshot(item)
            candidate_locator = f"{selector} >> nth={index}"
            candidate_handle = element_registry.register(
                session.session_id, page_id, frame_id, candidate_locator, fingerprint
            )
            candidates.append({
                "match_index": index, "handle": candidate_handle,
                "locator": candidate_locator, "role": fingerprint["role"],
                "name": fingerprint["name"],
                "context": {"text": snapshot["context_text"]}, "state": {
                    "visible": snapshot["visible"], "enabled": snapshot["enabled"],
                },
                "_actionable": snapshot["visible"] and snapshot["enabled"],
                "_fingerprint": fingerprint,
            })
        return candidates

    @staticmethod
    async def _wait_element_visible(locator, timeout):
        """Wait on the already-resolved node without consulting its selector."""
        visible = await locator.evaluate(
            """(el, timeout) => new Promise((resolve, reject) => {
              const started = performance.now();
              const check = () => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                if (style.display !== 'none' && style.visibility !== 'hidden' &&
                    rect.width > 0 && rect.height > 0) return resolve(true);
                if (performance.now() - started >= timeout) {
                  return resolve(false);
                }
                requestAnimationFrame(check);
              };
              check();
            })""",
            timeout,
        )
        if not visible:
            raise TimeoutError("Timeout waiting for element to become visible")

    @staticmethod
    async def _hover_to_reveal(locator, timeout):
        """Hover a stable containing affordance so CSS :hover can reveal target."""
        handle = await locator.evaluate_handle(
            "el => el.closest('li,tr,[role=row],[role=menuitem]') || el.parentElement || el"
        )
        try:
            element = handle.as_element()
            if element is not None:
                await element.hover(timeout=timeout)
        finally:
            await handle.dispose()

    @staticmethod
    async def _perform_structured_action(locator, action, value, options, timeout):
        force = options.get("force", False)
        if not isinstance(force, bool):
            raise ValidationError("options.force", "force must be a boolean")
        if action == InteractionAction.CLICK:
            await locator.click(timeout=timeout, force=force)
        elif action == InteractionAction.TYPE:
            await locator.fill(value, timeout=timeout, force=force)
        elif action == InteractionAction.SELECT:
            if options.get("_select_by") == "label":
                await locator.select_option(label=value, timeout=timeout, force=force)
            else:
                await locator.select_option(value=value, timeout=timeout, force=force)
        elif action == InteractionAction.HOVER:
            await locator.hover(timeout=timeout, force=force)

    @staticmethod
    def _normalize_interaction_error(error: Exception, action: InteractionAction, before=None) -> str:
        message = str(error).lower()
        if "strict mode violation" in message:
            return "ambiguous"
        if "page, context or browser has been closed" in message or "target page" in message and "closed" in message:
            return "page_closed"
        if "frame was detached" in message or "frame has been detached" in message:
            return "frame_unavailable"
        if "element is not attached" in message or "detached" in message:
            return "detached"
        if "intercepts pointer events" in message or "another element" in message and "receives" in message:
            return "covered_by"
        if "not visible" in message or "hidden" in message:
            return "not_visible"
        if "not enabled" in message or "disabled" in message or before and not before.get("enabled", True):
            return "disabled"
        if "not editable" in message:
            return "not_editable"
        if "not writable" in message or "read only" in message or "readonly" in message:
            return "readonly"
        if action == InteractionAction.SELECT and "did not find" in message:
            return "option_not_found"
        if "element is not stable" in message:
            return "unstable"
        if "navigation" in message and "interrupted" in message:
            return "navigation_interrupted"
        if "timeout" in message or isinstance(error, (PlaywrightTimeoutError, asyncio.TimeoutError)):
            return "timeout"
        return "browser_error"

    @staticmethod
    def _interaction_effect(before, after, old_url, new_url):
        changed = {}
        if before and after:
            for key in sorted(set(before) | set(after)):
                if before.get(key) != after.get(key):
                    changed[key] = {"before": before.get(key), "after": after.get(key)}
        return {
            "element_changed": bool(changed), "changed_fields": changed,
            "url_changed": old_url != new_url, "url_before": old_url,
            "url_after": new_url, "element_detached": after is None,
        }
    
    async def scroll_page(
        self,
        session: SessionData,
        selector: Optional[str] = None,
        direction: str = "down",
        amount: Optional[int] = None,
        until_selector: Optional[str] = None,
        until_text: Optional[str] = None,
        max_steps: int = 50,
        dwell_ms: int = 300,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Scroll the page or an element with bounded steps and stop conditions."""
        if not self.initialized:
            raise BrowserOperationError("scroll", "Browser service not initialized")

        page = self._get_page_from_session(session)
        actual_timeout = timeout or session.config.timeout
        deadline = time.time() + (actual_timeout / 1000.0)
        started = time.time()
        steps = 0
        last_hash = ""

        async def page_state_hash() -> str:
            return await page.evaluate(
                "() => document.documentElement.scrollHeight + '|' + document.documentElement.scrollTop"
            )

        while steps < max_steps and time.time() < deadline:
            if selector:
                element = page.locator(selector).first
                await element.scroll_into_view_if_needed(timeout=5000)
            else:
                viewport_h = await page.evaluate("() => window.innerHeight")
                scroll_by = amount or int(viewport_h * 0.8)
                if direction == "up":
                    scroll_by = -scroll_by
                await page.evaluate(f"window.scrollBy(0, {scroll_by})")

            steps += 1
            await asyncio.sleep(dwell_ms / 1000.0)

            if until_selector:
                try:
                    await page.wait_for_selector(until_selector, timeout=1000)
                    break
                except PlaywrightTimeoutError:
                    pass
            if until_text:
                try:
                    await page.get_by_text(until_text).first.wait_for(timeout=1000)
                    break
                except PlaywrightTimeoutError:
                    pass

            current_hash = await page_state_hash()
            if current_hash == last_hash:
                break
            last_hash = current_hash

        return {
            "success": True,
            "steps": steps,
            "url": page.url,
            "duration_ms": int((time.time() - started) * 1000),
        }

    async def take_screenshot(
        self,
        session: SessionData,
        selector: Optional[str] = None,
        full_page: bool = False,
        wait_for_dynamic: bool = False,
        timeout: Optional[int] = None,
        path: Optional[str] = None,
        quality: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Capture a viewport, full-page, or element screenshot and register it as an artifact."""

        if not self.initialized:
            raise BrowserOperationError("screenshot", "Browser service not initialized")

        try:
            page = self._get_page_from_session(session)
            actual_timeout = timeout or session.config.timeout

            # Quick wait for dynamic content if requested
            if wait_for_dynamic:
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass  # Continue even if timeout

                # Quick check for images (reduced wait)
                try:
                    await page.wait_for_function(
                        """
                        () => {
                            const images = document.querySelectorAll('img');
                            let loadedCount = 0;
                            images.forEach(img => {
                                if (img.complete && img.naturalHeight > 0) loadedCount++;
                            });
                            return images.length === 0 || loadedCount / images.length > 0.5;
                        }
                        """,
                        timeout=3000,
                    )
                except Exception:
                    pass  # Continue even if images not fully loaded

            # Quick delay before screenshot
            await asyncio.sleep(random.uniform(0.2, 0.8))

            # Generate path if not provided
            if not path:
                timestamp = int(time.time())
                path = f"{session.session_id}_{timestamp}.png"
            path = str(resolve_export_file(path, default_root="screenshots_dir"))

            screenshot_options: Dict[str, Any] = {"path": path, "full_page": full_page}
            if quality is not None:
                # Playwright requires jpeg type when quality is set.
                screenshot_options["type"] = "jpeg"
                screenshot_options["quality"] = quality
                if Path(path).suffix.lower() not in {".jpg", ".jpeg"}:
                    path = str(Path(path).with_suffix(".jpg"))
                    screenshot_options["path"] = path

            # Take screenshot
            if selector:
                element = page.locator(selector)
                await element.wait_for(state="visible", timeout=actual_timeout)
                await element.screenshot(**screenshot_options)
            else:
                await page.screenshot(**screenshot_options)

            # Get file size
            file_size = os.path.getsize(path)
            content_type = "image/jpeg" if Path(path).suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            artifact = self.artifact_service.register_artifact(
                path, content_type=content_type, filename=os.path.basename(path)
            )

            result = {
                **artifact,
                "selector": selector,
                "full_page": full_page,
                "size_bytes": file_size,
                "success": True,
                "dynamic_content_waited": wait_for_dynamic,
            }

            logger.info("Screenshot captured", session_id=session.session_id, **result)
            return result

        except Exception as e:
            logger.error("Screenshot failed", session_id=session.session_id, error=str(e))
            raise BrowserOperationError("screenshot", str(e))

    def _get_page_from_session(self, session: SessionData) -> Page:
        """Get page object from session data"""
        if not hasattr(session, 'page') or session.page is None:
            raise BrowserOperationError("get_page", "Page not available in session")
        
        return session.page

    def _navigation_warnings(self, status: Optional[int], url: str) -> List[str]:
        """Return permissive-local warnings for suspicious navigation outcomes."""
        warnings = []
        if status in (401, 403):
            warnings.append("Authentication or access challenge likely; continue only with permission.")
        elif status == 429:
            warnings.append("Rate limit response detected; back off before retrying.")
        elif status and status >= 500:
            warnings.append("Server error response detected; retry conservatively.")
        return warnings

    @staticmethod
    def _is_document_content_type(content_type: Optional[str]) -> bool:
        """Return True if the content-type indicates a downloadable document."""
        if not content_type:
            return False
        ct = content_type.lower().split(";")[0].strip()
        document_types = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
            "text/plain",
            "application/json",
            "application/xml",
            "text/xml",
        }
        if ct in document_types:
            return True
        # application/*+xml (e.g., atom+xml) are XML documents.
        if ct.endswith("+xml"):
            return True
        return False

    def _page_warnings(self, title: str, visible_text: str) -> List[str]:
        """Detect common challenge/login-wall indicators without bypassing them."""
        haystack = f"{title}\n{visible_text}".lower()
        indicators = [
            "captcha", "recaptcha", "hcaptcha", "verify you are human",
            "access denied", "too many requests", "login required", "sign in"
        ]
        return [
            f"Page contains possible challenge or gated-flow indicator: {indicator}"
            for indicator in indicators
            if indicator in haystack
        ]

    def _network_response_matches(self, response, filters: Dict[str, Any]) -> bool:
        """Apply lightweight response capture filters."""
        if not filters:
            return True
        url_contains = filters.get("url_contains")
        if url_contains and url_contains not in response.url:
            return False
        resource_types = filters.get("resource_types")
        if resource_types and response.request.resource_type not in resource_types:
            return False
        status_min = filters.get("status_min")
        if status_min and response.status < status_min:
            return False
        status_max = filters.get("status_max")
        if status_max and response.status > status_max:
            return False
        return True

    async def _safe_response_body(self, response, max_body_bytes: int) -> Optional[str]:
        """Capture only bounded text-like response bodies."""
        content_type = response.headers.get("content-type", "").lower()
        if not any(kind in content_type for kind in ("json", "text", "xml", "html", "javascript")):
            return None
        body = await response.body()
        if len(body) > max_body_bytes:
            body = body[:max_body_bytes]
        try:
            return body.decode("utf-8", errors="replace")
        except Exception:
            return None
    
    async def _navigate_with_retry(
        self, 
        page: Page, 
        url: str, 
        wait_until: WaitUntil, 
        timeout: int,
        max_retries: int = 3
    ) -> Any:
        """Navigate with retry logic for network issues"""
        
        for attempt in range(max_retries):
            try:
                response = await page.goto(
                    url,
                    wait_until=wait_until.value,
                    timeout=timeout
                )
                return response
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                
                logger.warning("Navigation attempt failed, retrying", attempt=attempt + 1, error=str(e))
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
    
    async def _extract_text(self, page: Page, selector: Optional[str], timeout: int) -> Dict[str, Any]:
        """Extract text content with smart extraction and cleaning"""
        
        try:
            # Use smart content extraction
            if selector:
                text = await ContentProcessor.extract_smart_content(page, selector)
            else:
                text = await ContentProcessor.extract_smart_content(page, 'body')
            
            # Assess content quality
            content_metrics = ContentProcessor.assess_content_quality(text)
            
            # Detect CAPTCHA
            is_captcha, captcha_reason = await ContentProcessor.detect_captcha_content(page, text)
            
            return {
                "text": text,
                "length": content_metrics.character_count,
                "word_count": content_metrics.word_count,
                "line_count": content_metrics.line_count,
                "quality_score": content_metrics.content_quality_score,
                "has_meaningful_content": content_metrics.has_meaningful_content,
                "is_captcha": is_captcha,
                "captcha_reason": captcha_reason if is_captcha else None,
                "type": "text"
            }
            
        except Exception as e:
            logger.error("Smart text extraction failed, using fallback", error=str(e))
            # Fallback to basic extraction
            return await self._extract_text_fallback(page, selector, timeout)
    
    async def _extract_text_fallback(self, page: Page, selector: Optional[str], timeout: int) -> Dict[str, Any]:
        """Fallback text extraction method"""
        
        if selector:
            element = page.locator(selector)
            await element.wait_for(state="visible", timeout=timeout)
            text = await element.text_content()
        else:
            # Smart main content detection - try body first as it's most reliable
            main_selectors = ["body", "main", "article", ".content", "#content", ".post-content"]
            text = None
            
            for sel in main_selectors:
                try:
                    element = page.locator(sel).first
                    # Use shorter timeout for each selector attempt
                    await element.wait_for(state="visible", timeout=min(timeout, 5000))
                    text = await element.text_content()
                    if text and len(text.strip()) > 10:  # Lower threshold for better results
                        break
                except Exception as e:
                    logger.debug(f"Selector {sel} failed: {e}")
                    continue
        
        # Fallback to page content if no selector worked
        if not text or len(text.strip()) < 10:
            try:
                text = await page.locator('body').text_content()
            except Exception as e:
                logger.warning(f"Fallback text extraction failed: {e}")
                text = ""
        
        return {
            "text": text.strip() if text else "",
            "length": len(text.strip()) if text else 0,
            "word_count": len(text.split()) if text else 0,
            "line_count": len(text.split('\n')) if text else 0,
            "quality_score": 0.0,
            "has_meaningful_content": len(text.strip()) > 100 if text else False,
            "is_captcha": False,
            "captcha_reason": None,
            "type": "text"
        }
    
    async def _extract_html(self, page: Page, selector: Optional[str], timeout: int) -> Dict[str, Any]:
        """Extract HTML content"""
        
        if selector:
            element = page.locator(selector)
            await element.wait_for(state="visible", timeout=timeout)
            html = await element.inner_html()
        else:
            html = await page.content()
        
        return {
            "html": html,
            "length": len(html),
            "type": "html"
        }
    
    async def _extract_table(self, page: Page, selector: Optional[str], timeout: int) -> Dict[str, Any]:
        """Extract table data to structured format"""
        
        table_selectors = [selector] if selector else ["table", ".table", ".data-table"]
        
        for table_sel in table_selectors:
            try:
                rows = await page.locator(f"{table_sel} tr").all()
                if not rows:
                    continue
                
                table_data = []
                for row in rows:
                    cells = await row.locator("td, th").all()
                    row_data = []
                    for cell in cells:
                        text = await cell.text_content()
                        row_data.append(text.strip() if text else "")
                    table_data.append(row_data)
                
                if table_data:
                    return {
                        "table": table_data,
                        "rows": len(table_data),
                        "columns": len(table_data[0]) if table_data else 0,
                        "type": "table"
                    }
                    
            except Exception:
                continue
        
        raise BrowserOperationError("extract_table", "No tables found")
    
    async def _extract_links(self, page: Page, selector: Optional[str], timeout: int) -> Dict[str, Any]:
        """Extract all links from page or specific container"""

        root_selector = selector or "body"
        await page.locator(root_selector).first.wait_for(state="attached", timeout=timeout)
        link_data = await page.evaluate(
            """
            ({rootSelector}) => {
                const root = document.querySelector(rootSelector) || document;
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.visibility !== 'hidden' &&
                        style.display !== 'none' && rect.width > 0 && rect.height > 0;
                };
                const clip = (value, length = 300) => (value || '').replace(/\\s+/g, ' ').trim().slice(0, length);
                return Array.from(root.querySelectorAll('a[href]')).map((a, index) => ({
                    index,
                    text: clip(a.innerText || a.textContent || a.getAttribute('aria-label') || a.title || ''),
                    href: a.getAttribute('href') || '',
                    url: a.href,
                    title: a.title || '',
                    visible: visible(a)
                })).filter((link) => link.url);
            }
            """,
            {"rootSelector": root_selector}
        )

        return {
            "links": link_data,
            "count": len(link_data),
            "type": "links"
        }
    
    async def _extract_images(self, page: Page, selector: Optional[str], timeout: int) -> Dict[str, Any]:
        """Extract image information from page or specific container"""
        
        img_selector = f"{selector} img" if selector else "img"
        images = await page.locator(img_selector).all()
        
        image_data = []
        for img in images:
            src = await img.get_attribute("src")
            alt = await img.get_attribute("alt")
            width = await img.get_attribute("width")
            height = await img.get_attribute("height")
            
            if src:  # Only include images with src
                image_data.append({
                    "src": src,
                    "alt": alt or "",
                    "width": width or "",
                    "height": height or ""
                })
        
        return {
            "images": image_data,
            "count": len(image_data),
            "type": "images"
        }
    
    async def _perform_click(self, element, options: Dict[str, Any]) -> None:
        """Perform click action with human-like behavior"""
        if options.get("hover_first", True):
            await element.hover()
            await random_delay(100, 300)
        
        await element.click()
        await random_delay(50, 150)
    
    async def _perform_double_click(self, element, options: Dict[str, Any]) -> None:
        """Perform double click action"""
        if options.get("hover_first", True):
            await element.hover()
            await random_delay(100, 300)
        
        await element.dblclick()
        await random_delay(100, 200)
    
    async def _perform_right_click(self, element, options: Dict[str, Any]) -> None:
        """Perform right click action"""
        if options.get("hover_first", True):
            await element.hover()
            await random_delay(100, 300)
        
        await element.click(button="right")
        await random_delay(100, 200)
    
    async def _perform_type(self, element, value: Optional[str], options: Dict[str, Any]) -> None:
        """Perform type action with human-like behavior"""
        if not value:
            raise ValidationError("value", "Value required for type action")
        
        await element.clear()
        
        # Human-like typing with random delays
        for char in value:
            await element.type(char)
            await random_delay(50, 150)
    
    async def _perform_select(self, element, value: Optional[str], options: Dict[str, Any]) -> None:
        """Perform select action"""
        if not value:
            raise ValidationError("value", "Value required for select action")
        
        await element.select_option(value)
        await random_delay(100, 200)
    
    async def _perform_scroll(self, element, value: Optional[str], options: Dict[str, Any]) -> None:
        """Perform scroll action"""
        await element.scroll_into_view_if_needed()
        
        if value:  # Additional scroll offset
            await element.page.evaluate(f"window.scrollBy(0, {value})")
        
        await random_delay(100, 300)
    
    async def _perform_hover(self, element, options: Dict[str, Any]) -> None:
        """Perform hover action"""
        await element.hover()
        await random_delay(200, 500)
    
    async def extract_structured_data(
        self,
        session: SessionData,
        content_type: str = "general",
        selector: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Extract structured data from page content"""
        
        if not self.initialized:
            raise BrowserOperationError("extract_structured", "Browser service not initialized")
        
        try:
            page = self._get_page_from_session(session)
            actual_timeout = timeout or session.config.timeout
            
            # Extract content first. General extraction retains a bounded raw-text
            # projection for compatibility and adds deterministic DOM structure.
            if selector:
                text = await ContentProcessor.extract_smart_content(page, selector)
            else:
                text = await ContentProcessor.extract_smart_content(page, 'body')
            if content_type == "general":
                text = text[:50000]
            
            # Extract structured data
            structured_data = ContentProcessor.extract_structured_data(text, content_type)
            if content_type == "general":
                root = page.locator(selector or "body")
                if await root.count() != 1:
                    raise ValueError("General structured extraction selector must match exactly one element")
                structured_data["extracted_elements"] = await root.evaluate(
                    """(root) => {
                      const clean = (value, limit) => (value || '').replace(/\\s+/g, ' ').trim().slice(0, limit);
                      const visible = (el) => {
                        const style = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' &&
                          rect.width > 0 && rect.height > 0 && !el.hidden && el.getAttribute('aria-hidden') !== 'true';
                      };
                      const take = (query, limit) => Array.from(root.querySelectorAll(query)).filter(visible).slice(0, limit);
                      const headings = take('h1,h2,h3,h4,h5,h6', 50).map((el) => ({
                        level: Number(el.tagName.slice(1)), text: clean(el.innerText, 500)
                      })).filter((item) => item.text);
                      const paragraphs = take('p', 100).map((el) => clean(el.innerText, 2000)).filter(Boolean);
                      const lists = take('ul,ol', 30).map((el) => ({
                        ordered: el.tagName === 'OL',
                        items: Array.from(el.children).filter((child) => child.tagName === 'LI' && visible(child))
                          .slice(0, 40).map((child) => clean(child.innerText, 500)).filter(Boolean)
                      })).filter((item) => item.items.length);
                      const tables = take('table', 20).map((table) => ({
                        rows: Array.from(table.rows).slice(0, 30).map((row) =>
                          Array.from(row.cells).slice(0, 20).map((cell) => clean(cell.innerText, 300))
                        ).filter((row) => row.some(Boolean))
                      })).filter((item) => item.rows.length);
                      const links = take('a[href]', 100).map((el) => ({
                        text: clean(el.innerText || el.getAttribute('aria-label'), 500),
                        url: el.href
                      }));
                      return {
                        schema: 'general.dom.v1', headings, paragraphs, lists, tables, links,
                        limits: {headings: 50, paragraphs: 100, lists: 30, list_items: 40,
                          tables: 20, table_rows: 30, table_columns: 20, links: 100,
                          raw_content_characters: 50000}
                      };
                    }"""
                )
            
            # Add page metadata
            structured_data["page_metadata"] = {
                "url": page.url,
                "title": await page.title(),
                "extraction_timestamp": time.time()
            }
            
            return {
                "data": structured_data,
                "success": True,
                "content_type": content_type,
                "selector": selector
            }
                
        except Exception as e:
            logger.error("Structured data extraction failed", session_id=session.session_id, content_type=content_type, error=str(e))
            raise BrowserOperationError("extract_structured", str(e))
    
    async def detect_captcha(
        self,
        session: SessionData,
        selector: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Detect CAPTCHA on the current page"""
        
        if not self.initialized:
            raise BrowserOperationError("detect_captcha", "Browser service not initialized")
        
        try:
            page = self._get_page_from_session(session)
            actual_timeout = timeout or session.config.timeout
            
            # Extract content for analysis
            if selector:
                text = await ContentProcessor.extract_smart_content(page, selector)
            else:
                text = await ContentProcessor.extract_smart_content(page, 'body')
            
            # Detect CAPTCHA
            is_captcha, reason = await ContentProcessor.detect_captcha_content(page, text)
            
            return {
                "data": {
                    "is_captcha": is_captcha,
                    "reason": reason,
                    "content_length": len(text),
                    "url": page.url
                },
                "success": True,
                "selector": selector
            }
                
        except Exception as e:
            logger.error("CAPTCHA detection failed", session_id=session.session_id, error=str(e))
            raise BrowserOperationError("detect_captcha", str(e))
