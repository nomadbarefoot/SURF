"""YouTube transcript HTTP controller."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
import structlog

from core.foundation import get_current_user, get_youtube_transcript_service
from models.schemas import YoutubeTranscriptRequest, YoutubeTranscriptResponse
from services.youtube_transcript_service import (
    TranscriptServiceError,
    YoutubeTranscriptService,
)
from utils.url_security import safe_url_for_log

logger = structlog.get_logger()
router = APIRouter()


@router.post("/transcript", response_model=YoutubeTranscriptResponse)
async def youtube_transcript(
    request: YoutubeTranscriptRequest,
    service: YoutubeTranscriptService = Depends(get_youtube_transcript_service),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Download and normalize one public YouTube caption track."""
    try:
        return await service.get_transcript(
            url=str(request.url),
            languages=request.languages,
            allow_auto_captions=request.allow_auto_captions,
            max_text_length=request.max_text_length,
        )
    except TranscriptServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        ) from exc
    except Exception as exc:
        logger.error(
            "youtube_transcript_failed",
            url=safe_url_for_log(str(request.url)),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "TRANSCRIPT_EXTRACTION_FAILED",
                "message": "YouTube transcript extraction failed",
            },
        ) from exc
