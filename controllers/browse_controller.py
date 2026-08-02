"""One-shot browse controller for Surf Browser Service."""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from core.foundation import (
    get_browse_service,
    get_current_user,
    BrowserOperationError,
)
from models.schemas import BrowseRequest, BrowseResponse
from services.browse_service import BrowseService
from services.outbound_policy import OutboundPolicyError

logger = structlog.get_logger()
router = APIRouter()


@router.post("/browse", response_model=BrowseResponse)
async def browse(
    request: BrowseRequest,
    browse_service: BrowseService = Depends(get_browse_service),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """One-shot browse: create session, navigate, settle, extract, close."""
    try:
        result = await browse_service.browse(
            url=str(request.url),
            mode=request.mode,
            content_mode=request.content_mode,
            readiness=request.readiness.dict() if request.readiness else None,
            include_screenshot=request.include_screenshot,
            keep_session=request.keep_session,
            extract_download=request.extract_download,
            max_text_length=request.max_text_length,
            max_items=request.max_items,
            timeout=request.timeout,
            allow_aggressive=user.get("profile") == "ui",
        )
        return BrowseResponse(
            success=result["success"],
            url=result["url"],
            title=result.get("title"),
            content=result.get("content"),
            content_mode=result["content_mode"],
            transition=result["transition"],
            challenge=result.get("challenge"),
            screenshot_artifact=result.get("screenshot_artifact"),
            session_id=result.get("session_id"),
            warnings=result.get("warnings", []),
        )
    except OutboundPolicyError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message,
        )
    except BrowserOperationError as e:
        logger.error("Browse failed", error=str(e), error_code=e.error_code)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Browse failed: {e.message}",
        )
    except Exception as e:
        logger.error("Browse failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Browse failed: {str(e)}",
        )
