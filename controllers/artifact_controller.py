"""Authenticated retrieval of server-created artifacts."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from core.foundation import get_current_user, get_download_service
from services.download_service import DownloadService

router = APIRouter()


@router.get("/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: str,
    artifact_service: DownloadService = Depends(get_download_service),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Return bytes for an opaque server-created artifact."""
    if not artifact_id.startswith("art_") or not artifact_id[4:].isalnum():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    try:
        record = artifact_service.get_download(artifact_id)
        if not record.get("artifact"):
            raise ValueError("Artifact not found")
        return FileResponse(
            path=artifact_service.path_for(artifact_id),
            filename=record["filename"],
            media_type=record.get("content_type") or "application/octet-stream",
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
