"""HTTP fetch controller for Surf Browser Service."""
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from core.foundation import get_current_user, get_fetch_service, get_request_guard, get_session_service, get_download_service, ValidationError
from models.schemas import FetchRequest, FetchResponse
from services.fetch_service import FetchService
from services.request_guard import RequestGuard
from services.session_service import SessionService
from services.download_service import DownloadService

logger = structlog.get_logger()
router = APIRouter()


@router.post("/request", response_model=FetchResponse)
async def fetch_request(
    request: FetchRequest,
    fetch_service: FetchService = Depends(get_fetch_service),
    session_service: SessionService = Depends(get_session_service),
    download_service: DownloadService = Depends(get_download_service),
    guard: RequestGuard = Depends(get_request_guard),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Execute a one-off HTTP request, optionally using cookies from a browser session."""
    guard.check_url(str(request.url))
    try:
        if request.session_id:
            async with session_service.session_operation(request.session_id, "fetch") as session:
                cookies = None
                browser_context = None
                if getattr(session, "context_obj", None):
                    cookies = await session.context_obj.cookies()
                    browser_context = session.context_obj
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
                    impersonate=request.impersonate,
                    browser_context=browser_context
                )
        else:
            result = await fetch_service.request(
                method=request.method,
                url=str(request.url),
                headers=request.headers,
                params=request.params,
                body=request.body,
                json_body=request.json_body,
                timeout=request.timeout,
                backend=request.backend,
                cookies=None,
                impersonate=request.impersonate,
                browser_context=None
            )
        content_bytes = result.pop("_content_bytes", b"")
        if request.save_to_downloads:
            download = await download_service.save_bytes(
                content_bytes,
                filename=request.download_filename,
                source_url=result.get("url"),
                content_type=result.get("headers", {}).get("content-type"),
                output_dir=request.output_dir,
                overwrite=request.overwrite
            )
            result["download"] = download
            result["text"] = ""
            result["text_preview"] = ""
        return FetchResponse(success=True, data=result)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": type(e).__name__, "code": e.error_code, "message": e.message, "details": e.details}
        )
    except Exception as e:
        logger.error("Fetch request failed", error=str(e), url=str(request.url))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fetch request failed: {str(e)}"
        )
