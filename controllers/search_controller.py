"""Search controller for SearXNG queries and parallel deep extraction."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from core.foundation import get_current_user, get_search_service
from models.schemas import SearchRequest, SearchExtractRequest
from services.search_service import SearchService

logger = structlog.get_logger()
router = APIRouter()


@router.post("/query")
async def search_query(
    request: SearchRequest,
    search_service: SearchService = Depends(get_search_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return await search_service.search(
            query=request.query,
            max_results=request.max_results,
            engines=request.engines,
            categories=request.categories,
            language=request.language,
            time_range=request.time_range,
            provider=request.provider,
            fallback=request.fallback,
            min_relevance=request.min_relevance,
        )
    except Exception as exc:
        logger.error("search_query_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.get("/stats")
async def search_stats(
    search_service: SearchService = Depends(get_search_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return search_service.get_stats()


@router.post("/extract")
async def search_extract(
    request: SearchExtractRequest,
    search_service: SearchService = Depends(get_search_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return await search_service.deep_extract(
            urls=request.urls,
            content_mode=request.content_mode,
            max_text_length=request.max_text_length,
            relevance=request.relevance,
            refine_query=request.refine_query,
        )
    except Exception as exc:
        logger.error("search_extract_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )
