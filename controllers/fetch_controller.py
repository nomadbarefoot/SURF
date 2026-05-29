"""HTTP fetch controller for Surf Browser Service."""
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from core.foundation import get_current_user, get_fetch_service, get_session_service
from models.schemas import FetchRequest, FetchResponse
from services.fetch_service import FetchService
from services.session_service import SessionService

logger = structlog.get_logger()
router = APIRouter()


@router.post("/request", response_model=FetchResponse)
async def fetch_request(
    request: FetchRequest,
    fetch_service: FetchService = Depends(get_fetch_service),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Execute a one-off HTTP request, optionally using cookies from a browser session."""
    try:
        cookies = None
        if request.session_id:
            session = await session_service.get_session(request.session_id)
            if getattr(session, "context_obj", None):
                cookies = await session.context_obj.cookies()

        result = await fetch_service.request(
            method=request.method,
            url=str(request.url),
            headers=request.headers,
            params=request.params,
            body=request.body,
            json_body=request.json_body,
            timeout=request.timeout,
            backend=request.backend,
            cookies=cookies,
            impersonate=request.impersonate
        )
        return FetchResponse(success=True, data=result)
    except Exception as e:
        logger.error("Fetch request failed", error=str(e), url=str(request.url))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fetch request failed: {str(e)}"
        )
