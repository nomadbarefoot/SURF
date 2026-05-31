"""Enhanced browser operations service for Surf Browser Service"""
import asyncio
import random
import time
from collections import deque
from typing import Optional, Dict, Any, List
from playwright.async_api import Page
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

logger = structlog.get_logger()


class BrowserService:
    """Enhanced browser operations service with improved error handling and performance"""
    
    def __init__(self):
        self.initialized = False
        self.site_memory_manager = create_site_memory_manager(ttl=settings.site_memory_ttl)
        self.network_captures: Dict[str, Dict[str, Any]] = {}
    
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
        
        logger.info("Browser service cleaned up")
    
    async def navigate_to_url(
        self,
        session: SessionData,
        url: str,
        wait_until: WaitUntil = WaitUntil.NETWORKIDLE,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Navigate to URL with intelligent waiting and error handling"""
        
        if not self.initialized:
            raise BrowserOperationError("navigate", "Browser service not initialized")
        
        start_time = time.time()
        try:
            # Get page from session
            page = self._get_page_from_session(session)
            
            # Apply adaptive rate limiting if enabled
            if settings.enable_adaptive_rate_limiting:
                await adaptive_rate_limiter.wait_if_needed(success=True)
            
            # Load site memory if enabled
            site_memory = None
            if settings.enable_site_memory:
                site_memory = self.site_memory_manager.get_site_memory(url)
                if site_memory:
                    logger.debug("Loaded site memory", site_url=url, access_count=site_memory.access_count)
            
            # Set timeout
            actual_timeout = timeout or session.config.timeout
            
            # Navigate with retry logic
            response = await self._navigate_with_retry(
                page, url, wait_until, actual_timeout
            )
            
            # Wait for content to fully load
            # Quick content load check (reduced wait time)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except:
                pass  # Continue even if timeout
            
            # Enhanced human behavior simulation with Gaussian delays
            if settings.enable_enhanced_mouse_movement:
                await HumanMouseMovement.random_mouse_wiggle(page, intensity=2)
                # Enhanced reading simulation based on content length
                await HumanMimicry.simulate_reading_behavior_enhanced(page)
            else:
                await HumanMimicry.gaussian_delay(1.0, 0.3)
            
            duration = time.time() - start_time
            
            # Update session context
            session.context.url = page.url
            session.context.title = await page.title()
            
            # Update site memory with success
            if settings.enable_site_memory:
                self.site_memory_manager.update_access_stats(url, success=True)
            
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
                "warnings": self._navigation_warnings(response.status if response else None, page.url)
            }
            
            logger.info("Navigation completed", session_id=session.session_id, **result)
            return result
            
        except Exception as e:
            # Update site memory with failure
            if settings.enable_site_memory:
                self.site_memory_manager.update_access_stats(url, success=False)
            
            # Update resource monitoring with failure
            resource_monitor.update_session_metrics(
                session_id=session.session_id,
                success=False,
                response_time=time.time() - start_time
            )
            
            logger.error("Navigation failed", session_id=session.session_id, url=url, error=str(e))
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
        content_mode: str = "compact"
    ) -> Dict[str, Any]:
        """Return a compact agent-friendly observation of the current page."""
        if not self.initialized:
            raise BrowserOperationError("observe", "Browser service not initialized")

        try:
            page = self._get_page_from_session(session)
            observation = await page.evaluate(
                """
                ({maxTextLength, maxItems, contentMode}) => {
                    const noiseSelector = [
                        '[class*="ad-"]', '[class*="ads"]', '[id*="ad-"]', '[id*="ads"]',
                        '[class*="cookie"]', '[id*="cookie"]', '[class*="newsletter"]',
                        '[class*="subscribe"]', '[aria-label*="advertisement" i]',
                        'aside', 'footer'
                    ].join(',');
                    const visible = (el) => {
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style && style.visibility !== 'hidden' &&
                            style.display !== 'none' && rect.width > 0 && rect.height > 0;
                    };
                    const noisy = (el) => contentMode !== 'full' && !!el.closest(noiseSelector);
                    const text = (el) => (el.innerText || el.textContent || '').trim();
                    const attr = (el, name) => el.getAttribute(name) || '';
                    const clip = (value, length = 300) => (value || '').replace(/\\s+/g, ' ').trim().slice(0, length);
                    const sourceText = () => document.body ? (document.body.innerText || document.body.textContent || '') : '';
                    const readableText = () => {
                        if (!document.body) return '';
                        if (contentMode === 'full') return document.body.innerText || '';
                        const clone = document.body.cloneNode(true);
                        clone.querySelectorAll(noiseSelector + ', script, style, noscript, svg').forEach((el) => el.remove());
                        if (contentMode === 'reader') {
                            const article = clone.querySelector('main, article, [role=main], .article, .story, .post, .content');
                            if (article) {
                                article.querySelectorAll('nav, header, footer, aside, form, button, input, textarea, select').forEach((el) => el.remove());
                                return article.innerText || article.textContent || '';
                            }
                            clone.querySelectorAll('nav, header, footer, aside, form, button, input, textarea, select').forEach((el) => el.remove());
                        }
                        if (contentMode === 'data') {
                            clone.querySelectorAll('nav, header, footer, aside, form, button').forEach((el) => el.remove());
                        }
                        return clone.innerText || clone.textContent || '';
                    };

                    const links = Array.from(document.querySelectorAll('a[href]')).filter((el) => visible(el) && !noisy(el)).slice(0, maxItems).map((a) => ({
                        text: clip(text(a), 160),
                        href: a.href
                    }));

                    const forms = Array.from(document.querySelectorAll('form')).filter((el) => !noisy(el)).slice(0, maxItems).map((form, index) => ({
                        index,
                        action: form.action || '',
                        method: (form.method || 'get').toUpperCase(),
                        fields: Array.from(form.querySelectorAll('input, textarea, select')).slice(0, 50).map((field) => ({
                            tag: field.tagName.toLowerCase(),
                            type: attr(field, 'type'),
                            name: attr(field, 'name'),
                            id: field.id || '',
                            placeholder: attr(field, 'placeholder'),
                            label: clip(field.labels && field.labels[0] ? text(field.labels[0]) : '', 120)
                        }))
                    }));

                    const actions = Array.from(document.querySelectorAll('button, input[type=button], input[type=submit], [role=button], [onclick]'))
                        .filter((el) => visible(el) && !noisy(el)).slice(0, maxItems).map((el) => ({
                            tag: el.tagName.toLowerCase(),
                            text: clip(text(el) || attr(el, 'value') || attr(el, 'aria-label'), 160),
                            id: el.id || '',
                            name: attr(el, 'name'),
                            selector_hint: el.id ? `#${CSS.escape(el.id)}` : ''
                        }));

                    const tables = Array.from(document.querySelectorAll('table')).filter((el) => !noisy(el)).slice(0, Math.min(maxItems, 20)).map((table, index) => ({
                        index,
                        rows: table.rows.length,
                        columns: table.rows[0] ? table.rows[0].cells.length : 0,
                        preview: Array.from(table.rows).slice(0, 5).map((row) =>
                            Array.from(row.cells).slice(0, 8).map((cell) => clip(text(cell), 120))
                        )
                    }));

                    const rawText = sourceText();
                    const selectedText = readableText();
                    const visibleText = clip(selectedText, maxTextLength);
                    return {
                        visible_text: visibleText,
                        visible_text_length: visibleText.length,
                        token_estimate: Math.ceil(visibleText.length / 4),
                        source_text_length: rawText.length,
                        selected_text_length: selectedText.length,
                        truncated: selectedText.length > visibleText.length,
                        reduction_ratio: rawText.length ? Math.round((1 - (visibleText.length / rawText.length)) * 10000) / 10000 : 0,
                        links,
                        forms,
                        actions,
                        tables
                    };
                }
                """,
                {"maxTextLength": max_text_length, "maxItems": max_items, "contentMode": content_mode}
            )

            screenshot_path = None
            if include_screenshot:
                screenshot = await self.take_screenshot(session=session, full_page=False, wait_for_dynamic=False)
                screenshot_path = screenshot.get("path")

            return {
                "url": page.url,
                "title": await page.title(),
                "screenshot": screenshot_path,
                "content_mode": content_mode,
                "blocker": session.metadata.get("blocker", {}),
                "blocker_delta": session.metadata.get("last_navigation_blocker", {}),
                "warnings": self._page_warnings(await page.title(), observation.get("visible_text", "")),
                **observation
            }
        except Exception as e:
            logger.error("Page observation failed", session_id=session.session_id, error=str(e))
            raise BrowserOperationError("observe", str(e))

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
        load_state: Optional[WaitUntil] = None,
        timeout: int = 30000
    ) -> Dict[str, Any]:
        """Wait for an explicit browser condition."""
        page = self._get_page_from_session(session)
        started = time.time()
        try:
            if load_state:
                state_value = load_state.value if hasattr(load_state, "value") else str(load_state)
                await page.wait_for_load_state(state_value, timeout=timeout)
            if selector:
                await page.wait_for_selector(selector, timeout=timeout)
            if text:
                await page.get_by_text(text).first.wait_for(timeout=timeout)
            if url_contains:
                await page.wait_for_function(
                    "(fragment) => window.location.href.includes(fragment)",
                    url_contains,
                    timeout=timeout
                )
            return {
                "success": True,
                "url": page.url,
                "duration_ms": int((time.time() - started) * 1000)
            }
        except Exception as e:
            raise BrowserOperationError("wait", str(e))

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
        selector: str,
        value: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Perform element interactions with human-like behavior"""
        
        if not self.initialized:
            raise BrowserOperationError("interact", "Browser service not initialized")
        
        try:
            page = self._get_page_from_session(session)
            actual_timeout = timeout or session.config.timeout
            options = options or {}
            
            # Wait for element to be actionable
            element = page.locator(selector)
            await element.wait_for(state="visible", timeout=actual_timeout)
            
            # Enhanced mouse movement and element-specific timing
            if settings.enable_enhanced_mouse_movement and action in [InteractionAction.CLICK, InteractionAction.DOUBLE_CLICK, InteractionAction.RIGHT_CLICK]:
                await HumanMouseMovement.human_like_move(
                    page, 
                    selector,
                    bezier_points=settings.mouse_movement_bezier_points,
                    min_delay=settings.mouse_movement_min_delay,
                    max_delay=settings.mouse_movement_max_delay,
                    reaction_delay_min=settings.mouse_movement_reaction_delay_min,
                    reaction_delay_max=settings.mouse_movement_reaction_delay_max
                )
            
            # Element-specific timing for all interactions
            await HumanMimicry.element_specific_timing(page, selector, action.value)
            
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
    
    async def take_screenshot(
        self,
        session: SessionData,
        selector: Optional[str] = None,
        full_page: bool = False,
        path: Optional[str] = None,
        quality: Optional[int] = None,
        timeout: Optional[int] = None,
        wait_for_dynamic: bool = True
    ) -> Dict[str, Any]:
        """Capture page or element screenshots with enhanced options and smart waiting for dynamic content"""
        
        if not self.initialized:
            raise BrowserOperationError("screenshot", "Browser service not initialized")
        
        try:
            page = self._get_page_from_session(session)
            actual_timeout = timeout or session.config.timeout
            
            # Quick wait for dynamic content if requested
            if wait_for_dynamic:
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass  # Continue even if timeout
                
                # Quick check for images (reduced wait)
                try:
                    await page.wait_for_function("""
                        () => {
                            const images = document.querySelectorAll('img');
                            let loadedCount = 0;
                            images.forEach(img => {
                                if (img.complete && img.naturalHeight > 0) loadedCount++;
                            });
                            return images.length === 0 || loadedCount / images.length > 0.5;
                        }
                    """, timeout=3000)
                except:
                    pass  # Continue even if images not fully loaded

            # Quick delay before screenshot
            await asyncio.sleep(random.uniform(0.2, 0.8))
            
            # Generate path if not provided
            if not path:
                timestamp = int(time.time())
                path = f"screenshots/{session.session_id}_{timestamp}.png"
            
            # Ensure directory exists
            import os
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            # Take screenshot
            if selector:
                element = page.locator(selector)
                await element.wait_for(state="visible", timeout=actual_timeout)
                await element.screenshot(path=path)
            else:
                await page.screenshot(path=path, full_page=full_page)
            
            # Get file size
            file_size = os.path.getsize(path)
            
            result = {
                "path": path,
                "selector": selector,
                "full_page": full_page,
                "size_bytes": file_size,
                "success": True,
                "dynamic_content_waited": wait_for_dynamic
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
            
            # Extract content first
            if selector:
                text = await ContentProcessor.extract_smart_content(page, selector)
            else:
                text = await ContentProcessor.extract_smart_content(page, 'body')
            
            # Extract structured data
            structured_data = ContentProcessor.extract_structured_data(text, content_type)
            
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
