"""HTTP fetch controller for Surf Browser Service."""
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from core.foundation import get_current_user, get_fetch_service, get_request_guard, get_session_service, get_download_service, ResourceLimitError, ValidationError
from models.schemas import FetchRequest, FetchResponse
from services.fetch_service import FetchService
from services.request_guard import RequestGuard
from services.session_service import SessionService
from services.download_service import DownloadService
from services.outbound_policy import OutboundPolicyError
from utils.url_security import safe_url_for_log

logger = structlog.get_logger()
router = APIRouter()

# Public text budget for agent-facing fetch responses. JSON bodies are already
# bounded by the service parse budget; raw text gets a fixed preview cap.
_PUBLIC_TEXT_CHARS = 50_000


def _public_fetch_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """Project an internal fetch result to the minimal agent-facing shape.

    Keeps only what an agent needs: status, final URL, content type, the body
    exactly once (parsed JSON when available, otherwise text), a truncation
    flag, and actionable warnings. Drops header dumps, duplicated body
    representations, and transport telemetry.
    """
    data: Dict[str, Any] = {
        "status": result.get("status"),
        "url": result.get("url"),
    }
    content_type = (result.get("headers") or {}).get("content-type")
    if content_type:
        data["content_type"] = content_type
    if result.get("download"):
        data["download"] = result["download"]
    elif result.get("json") is not None:
        data["json"] = result["json"]
    else:
        text = result.get("text") or ""
        if len(text) > _PUBLIC_TEXT_CHARS:
            data["text"] = text[:_PUBLIC_TEXT_CHARS]
            data["truncated"] = True
        elif text:
            data["text"] = text
    if result.get("warnings"):
        data["warnings"] = result["warnings"]
    return data


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
    if user.get("profile") == "web":
        unsafe = (
            request.method.upper() != "GET"
            or request.headers is not None
            or request.body is not None
            or request.json_body is not None
            or request.session_id is not None
            or request.backend.value != "auto"
            or request.save_to_downloads
            or request.download_filename is not None
            or request.output_dir is not None
            or request.overwrite
            or request.timeout > 30000
        )
        if unsafe:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="surf/web permits only a bounded public GET",
            )
    guard.check_url(str(request.url))
    try:
        if request.session_id:
            async with session_service.session_operation(request.session_id, "fetch") as session:
                cookies = None
                browser_context = None
                if getattr(session, "context_obj", None):
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
        return FetchResponse(success=True, data=_public_fetch_data(result))
    except OutboundPolicyError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": e.error_code, "message": e.message},
        )
    except ResourceLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": e.error_code, "message": e.message, "details": e.details},
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": type(e).__name__, "code": e.error_code, "message": e.message, "details": e.details}
        )
    except Exception as e:
        logger.error(
            "Fetch request failed",
            error=str(e),
            url=safe_url_for_log(request.url),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fetch request failed: {str(e)}"
        )
