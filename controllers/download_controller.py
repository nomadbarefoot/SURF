"""Download management controller for SURF."""
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
import structlog

from core.foundation import get_current_user, get_download_service
from services.download_service import DownloadService

logger = structlog.get_logger()
router = APIRouter()


@router.get("/")
async def list_downloads(
    download_service: DownloadService = Depends(get_download_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """List sandboxed downloads."""
    return {"success": True, "downloads": download_service.list_downloads()}


@router.get("/{download_id}")
async def get_download(
    download_id: str,
    download_service: DownloadService = Depends(get_download_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Return download metadata."""
    try:
        return {"success": True, "download": download_service.get_download(download_id)}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{download_id}/content")
async def get_download_content(
    download_id: str,
    download_service: DownloadService = Depends(get_download_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Return download file content."""
    try:
        record = download_service.get_download(download_id)
        return FileResponse(
            path=download_service.path_for(download_id),
            filename=record["filename"],
            media_type=record.get("content_type") or "application/octet-stream"
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{download_id}")
async def delete_download(
    download_id: str,
    download_service: DownloadService = Depends(get_download_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Delete a sandboxed download."""
    try:
        return {"success": True, "data": download_service.delete_download(download_id)}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
