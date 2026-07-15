"""Browser operations controller for Surf Browser Service"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from core.foundation import get_current_user, get_browser_service, get_session_service
from core.foundation import BrowserOperationError, SessionNotFoundError, SessionBusyError, ValidationError
from services.outbound_policy import OutboundPolicyError
from models.schemas import (
    NavigateRequest, ExtractRequest, InteractRequest, ScreenshotRequest,
    NavigationResponse, ExtractResponse, InteractResponse, ScreenshotResponse,
    ObserveRequest, ObserveResponse, WaitRequest, WaitResponse,
    NetworkCaptureRequest, NetworkCaptureResponse,
    DownloadClickRequest, DownloadResponse,
    StructuredDataRequest, StructuredDataResponse, 
    CaptchaDetectionRequest, CaptchaDetectionResponse,
    BatchRequest, BatchOperationResponse, ExtractType, InteractionAction,
)
from services.browser_service import BrowserService
from services.session_service import SessionService

logger = structlog.get_logger()
router = APIRouter()


@router.post("/navigate", response_model=NavigationResponse)
async def navigate(
    request: NavigateRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Navigate to a URL with intelligent waiting"""
    
    try:
        async with session_service.session_operation(request.session_id, "navigate") as session:
            session_service.start_navigation_snapshot(session)
            result = await browser_service.navigate_to_url(
                session=session,
                url=str(request.url),
                wait_until=request.wait_until,
                timeout=request.timeout
            )
            result["blocker_delta"] = session_service.finish_navigation_snapshot(session)
        
        # Update session stats
        await session_service.update_session_stats(
            request.session_id,
            {"operation": "navigate", "duration": result.get("duration_ms", 0) / 1000}
        )
        
        return NavigationResponse(
            success=True,
            data=result
        )
        
    except HTTPException:
        raise
    except OutboundPolicyError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message,
        )
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except BrowserOperationError as e:
        logger.error("Navigation failed", error=str(e), error_code=e.error_code, details=e.details, session_id=request.session_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Navigation failed: {e.message}"
        )
    except Exception as e:
        logger.error("Navigation failed", error=str(e), error_type=type(e).__name__, session_id=request.session_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Navigation failed: {str(e)}"
        )


@router.post("/extract", response_model=ExtractResponse)
async def extract_content(
    request: ExtractRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Extract content with smart fallback strategies"""
    
    try:
        async with session_service.session_operation(request.session_id, "extract") as session:
            result = await browser_service.extract_content(
                session=session,
                extract_type=request.extract_type,
                selector=request.selector,
                timeout=request.timeout
            )
        
        # Update session stats
        await session_service.update_session_stats(
            request.session_id,
            {"operation": "extract"}
        )
        
        return ExtractResponse(
            success=True,
            data=result
        )
        
    except HTTPException:
        raise
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except BrowserOperationError as e:
        logger.error("Content extraction failed", error=str(e), error_code=e.error_code, details=e.details, session_id=request.session_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Content extraction failed: {e.message}"
        )
    except Exception as e:
        logger.error("Content extraction failed", error=str(e), error_type=type(e).__name__, session_id=request.session_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Content extraction failed: {str(e)}"
        )


@router.post("/interact", response_model=InteractResponse)
async def interact_with_element(
    request: InteractRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Perform element interactions with human-like behavior"""
    
    try:
        async with session_service.session_operation(request.session_id, "interact") as session:
            result = await browser_service.interact_with_element(
                session=session,
                action=request.action,
                selector=request.selector,
                value=request.value,
                options=request.options,
                timeout=request.timeout
            )
        
        # Update session stats
        await session_service.update_session_stats(
            request.session_id,
            {"operation": "interact"}
        )
        
        return InteractResponse(
            success=True,
            data=result
        )
        
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Element interaction failed", error=str(e), session_id=request.session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Element interaction failed"
        )


@router.post("/screenshot", response_model=ScreenshotResponse)
async def take_screenshot(
    request: ScreenshotRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Capture page or element screenshots"""
    
    try:
        async with session_service.session_operation(request.session_id, "screenshot") as session:
            result = await browser_service.take_screenshot(
                session=session,
                selector=request.selector,
                full_page=request.full_page,
                path=request.path,
                quality=request.quality,
                timeout=request.timeout
            )
        
        # Update session stats
        await session_service.update_session_stats(
            request.session_id,
            {"operation": "screenshot"}
        )
        
        return ScreenshotResponse(
            success=True,
            data=result
        )
        
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Screenshot failed", error=str(e), session_id=request.session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Screenshot failed"
        )


@router.post("/observe", response_model=ObserveResponse)
async def observe_page(
    request: ObserveRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Return a compact agent-friendly observation of the current page"""
    try:
        async with session_service.session_operation(request.session_id, "observe") as session:
            result = await browser_service.observe_page(
                session=session,
                include_screenshot=request.include_screenshot,
                max_text_length=request.max_text_length,
                max_items=request.max_items,
                content_mode=request.content_mode or session.config.content_mode
            )
        return ObserveResponse(success=True, data=result)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Page observation failed", error=str(e), session_id=request.session_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Page observation failed")


@router.post("/wait", response_model=WaitResponse)
async def wait_for_condition(
    request: WaitRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Wait for an explicit browser condition"""
    try:
        async with session_service.session_operation(request.session_id, "wait") as session:
            result = await browser_service.wait_for_condition(
                session=session,
                selector=request.selector,
                text=request.text,
                url_contains=request.url_contains,
                load_state=request.load_state,
                timeout=request.timeout
            )
        return WaitResponse(success=True, data=result)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Wait failed", error=str(e), session_id=request.session_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Wait failed")


@router.post("/network/start", response_model=NetworkCaptureResponse)
async def start_network_capture(
    request: NetworkCaptureRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Start bounded response capture for a session"""
    try:
        async with session_service.session_operation(request.session_id, "network_start") as session:
            result = await browser_service.start_network_capture(
                session=session,
                filters=request.dict(exclude={"session_id"})
            )
        return NetworkCaptureResponse(success=True, data=result)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Network capture start failed", error=str(e), session_id=request.session_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Network capture start failed")


@router.post("/network/stop", response_model=NetworkCaptureResponse)
async def stop_network_capture(
    request: NetworkCaptureRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Stop response capture for a session"""
    try:
        async with session_service.session_operation(request.session_id, "network_stop") as session:
            result = await browser_service.stop_network_capture(session=session)
        return NetworkCaptureResponse(success=True, data=result)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Network capture stop failed", error=str(e), session_id=request.session_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Network capture stop failed")


@router.get("/network/events/{session_id}", response_model=NetworkCaptureResponse)
async def get_network_events(
    session_id: str,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Return captured response events for a session"""
    try:
        async with session_service.session_operation(session_id, "network_events") as session:
            result = await browser_service.get_network_events(session=session)
        return NetworkCaptureResponse(success=True, data=result)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Network capture read failed", error=str(e), session_id=session_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Network capture read failed")


@router.post("/download/click", response_model=DownloadResponse)
async def click_download(
    request: DownloadClickRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Click an element that triggers a download and save it in the SURF sandbox."""
    try:
        async with session_service.session_operation(request.session_id, "download") as session:
            result = await browser_service.click_and_download(
                session=session,
                selector=request.selector,
                timeout=request.timeout,
                filename=request.filename,
                output_dir=request.output_dir,
                overwrite=request.overwrite
            )
        return DownloadResponse(success=True, data=result)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": type(e).__name__, "code": e.error_code, "message": e.message, "details": e.details}
        )
    except Exception as e:
        logger.error("Download click failed", error=str(e), session_id=request.session_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Download failed: {str(e)}")


@router.post("/batch", response_model=BatchOperationResponse)
async def batch_operations(
    request: BatchRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Perform multiple operations in parallel or sequence"""
    
    try:
        if request.parallel:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Parallel batch operations on one page are disabled; send sequential operations or separate sessions."
            )

        async with session_service.session_operation(request.session_id, "batch") as session:
            results = await _execute_sequential_operations(
                request.operations, session, browser_service
            )
        
        successful_operations = sum(1 for r in results if r.get("success", False))
        
        return BatchOperationResponse(
            success=successful_operations == len(request.operations),
            results=results,
            total_operations=len(request.operations),
            successful_operations=successful_operations,
            failed_operations=len(request.operations) - successful_operations,
            parallel=False,
            max_concurrent=1,
        )
        
    except HTTPException:
        raise
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except SessionBusyError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Batch operations failed", error=str(e), session_id=request.session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Batch operations failed"
        )


@router.post("/extract-structured", response_model=StructuredDataResponse)
async def extract_structured_data(
    request: StructuredDataRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Extract structured data from page content"""
    
    try:
        async with session_service.session_operation(
            request.session_id, "extract_structured"
        ) as session:
            result = await browser_service.extract_structured_data(
                session=session,
                content_type=request.content_type,
                selector=request.selector,
                timeout=request.timeout,
            )
        
        # Update session stats
        await session_service.update_session_stats(
            request.session_id,
            {"operation": "extract_structured"}
        )
        
        return StructuredDataResponse(
            success=True,
            data=result
        )
        
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Structured data extraction failed", error=str(e), session_id=request.session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Structured data extraction failed"
        )


@router.post("/detect-captcha", response_model=CaptchaDetectionResponse)
async def detect_captcha(
    request: CaptchaDetectionRequest,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Detect CAPTCHA on the current page"""
    
    try:
        async with session_service.session_operation(
            request.session_id, "detect_captcha"
        ) as session:
            result = await browser_service.detect_captcha(
                session=session,
                selector=request.selector,
                timeout=request.timeout,
            )
        
        # Update session stats
        await session_service.update_session_stats(
            request.session_id,
            {"operation": "detect_captcha"}
        )
        
        return CaptchaDetectionResponse(
            success=True,
            data=result
        )
        
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("CAPTCHA detection failed", error=str(e), session_id=request.session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CAPTCHA detection failed"
        )


# Helper functions for batch operations
async def _execute_operation(operation: dict, session, browser_service) -> dict:
    """Execute a single operation"""
    try:
        op_type = operation.get("type")
        
        if op_type == "navigate":
            wait_until = operation.get("wait_until", "domcontentloaded")
            if isinstance(wait_until, str):
                from models.schemas import WaitUntil
                wait_until = WaitUntil(wait_until)
            result = await browser_service.navigate_to_url(
                session=session,
                url=operation["url"],
                wait_until=wait_until,
                timeout=operation.get("timeout")
            )
        elif op_type == "extract":
            extract_type = ExtractType(operation.get("extract_type", "text"))
            result = await browser_service.extract_content(
                session=session,
                extract_type=extract_type,
                selector=operation.get("selector"),
                timeout=operation.get("timeout")
            )
        elif op_type == "extract_structured":
            result = await browser_service.extract_structured_data(
                session=session,
                content_type=operation.get("content_type", "general"),
                selector=operation.get("selector"),
                timeout=operation.get("timeout")
            )
        elif op_type == "detect_captcha":
            result = await browser_service.detect_captcha(
                session=session,
                selector=operation.get("selector"),
                timeout=operation.get("timeout")
            )
        elif op_type == "interact":
            action = InteractionAction(operation["action"])
            result = await browser_service.interact_with_element(
                session=session,
                action=action,
                selector=operation["selector"],
                value=operation.get("value"),
                options=operation.get("options"),
                timeout=operation.get("timeout")
            )
        elif op_type == "screenshot":
            result = await browser_service.take_screenshot(
                session=session,
                selector=operation.get("selector"),
                full_page=operation.get("full_page", False),
                path=operation.get("path"),
                quality=operation.get("quality"),
                timeout=operation.get("timeout")
            )
        else:
            result = {"error": f"Unknown operation type: {op_type}"}
        
        return {
            "operation": op_type,
            "success": "error" not in result,
            "data": result
        }
        
    except Exception as e:
        return {
            "operation": operation.get("type", "unknown"),
            "success": False,
            "error": str(e)
        }


async def _execute_parallel_operations(operations: list, session, browser_service, max_concurrent: int) -> list:
    """Execute operations in parallel with concurrency control"""
    import asyncio
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute_with_semaphore(operation):
        async with semaphore:
            return await _execute_operation(operation, session, browser_service)
    
    # Execute all operations in parallel
    tasks = [execute_with_semaphore(op) for op in operations]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Handle any exceptions that occurred
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed_results.append({
                "operation": operations[i].get("type", "unknown"),
                "success": False,
                "error": str(result)
            })
        else:
            processed_results.append(result)
    
    return processed_results


async def _execute_sequential_operations(operations: list, session, browser_service) -> list:
    """Execute operations sequentially (original behavior)"""
    results = []
    
    for operation in operations:
        result = await _execute_operation(operation, session, browser_service)
        results.append(result)
    
    return results
