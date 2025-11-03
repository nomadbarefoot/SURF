"""Browser operations controller for Surf Browser Service"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from core.foundation import get_current_user, get_browser_service, get_session_service
from core.foundation import BrowserOperationError, SessionNotFoundError
from models.schemas import (
    NavigateRequest, ExtractRequest, InteractRequest, ScreenshotRequest,
    NavigationResponse, ExtractResponse, InteractResponse, ScreenshotResponse,
    StructuredDataRequest, StructuredDataResponse, 
    CaptchaDetectionRequest, CaptchaDetectionResponse
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
        # Get session
        session = await session_service.get_session(request.session_id)
        
        # Perform navigation
        result = await browser_service.navigate_to_url(
            session=session,
            url=str(request.url),
            wait_until=request.wait_until,
            timeout=request.timeout
        )
        
        # Update session stats
        await session_service.update_session_stats(
            request.session_id,
            {"operation": "navigate", "duration": result.get("duration_ms", 0) / 1000}
        )
        
        return NavigationResponse(
            success=True,
            data=result
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
        # Get session
        session = await session_service.get_session(request.session_id)
        
        # Perform extraction
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
        # Get session
        session = await session_service.get_session(request.session_id)
        
        # Perform interaction
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
        # Get session
        session = await session_service.get_session(request.session_id)
        
        # Take screenshot
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


@router.post("/batch")
async def batch_operations(
    operations: list,
    session_id: str,
    parallel: bool = True,
    max_concurrent: int = 5,
    browser_service: BrowserService = Depends(get_browser_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Perform multiple operations in parallel or sequence"""
    
    try:
        # Get session
        session = await session_service.get_session(session_id)
        
        if parallel:
            # Parallel processing
            results = await _execute_parallel_operations(
                operations, session, browser_service, max_concurrent
            )
        else:
            # Sequential processing (original behavior)
            results = await _execute_sequential_operations(
                operations, session, browser_service
            )
        
        successful_operations = sum(1 for r in results if r.get("success", False))
        
        return {
            "success": successful_operations == len(operations),
            "results": results,
            "total_operations": len(operations),
            "successful_operations": successful_operations,
            "failed_operations": len(operations) - successful_operations,
            "parallel": parallel,
            "max_concurrent": max_concurrent if parallel else 1
        }
        
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Batch operations failed", error=str(e), session_id=session_id)
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
        # Get session
        session = await session_service.get_session(request.session_id)
        
        # Perform structured data extraction
        result = await browser_service.extract_structured_data(
            session=session,
            content_type=request.content_type,
            selector=request.selector,
            timeout=request.timeout
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
        # Get session
        session = await session_service.get_session(request.session_id)
        
        # Perform CAPTCHA detection
        result = await browser_service.detect_captcha(
            session=session,
            selector=request.selector,
            timeout=request.timeout
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
            result = await browser_service.navigate_to_url(
                session=session,
                url=operation["url"],
                wait_until=operation.get("wait_until", "networkidle"),
                timeout=operation.get("timeout")
            )
        elif op_type == "extract":
            result = await browser_service.extract_content(
                session=session,
                extract_type=operation["extract_type"],
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
            result = await browser_service.interact_with_element(
                session=session,
                action=operation["action"],
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
