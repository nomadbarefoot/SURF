"""Session management controller for Surf Browser Service"""
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
import structlog

from core.foundation import get_current_user, get_session_service
from core.foundation import SessionNotFoundError, ResourceLimitError
from models.schemas import SessionCreateRequest, SessionResponse
from services.session_service import SessionService

logger = structlog.get_logger()
router = APIRouter()


@router.post("/", response_model=SessionResponse)
async def create_session(
    request: SessionCreateRequest = SessionCreateRequest(),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Create new browser session with smart defaults"""
    
    try:
        # Create session
        session_data = await session_service.create_session(
            user_config=request.config,
            user_id=user.get("username")
        )
        
        return SessionResponse(
            success=True,
            session_id=session_data.session_id,
            config=session_data.config.dict(),
            expires_at=session_data.context.created_at
        )
        
    except ResourceLimitExceededError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Session creation failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session creation failed"
        )


@router.delete("/{session_id}")
async def close_session(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Close browser session and cleanup resources"""
    
    try:
        await session_service.close_session(session_id)
        return {"success": True, "message": f"Session {session_id} closed"}
        
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Session closure failed", error=str(e), session_id=session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session closure failed"
        )


@router.get("/{session_id}")
async def get_session_info(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Get session information and statistics"""
    
    try:
        session = await session_service.get_session(session_id)
        stats = await session_service.get_session_stats(session_id)
        
        return {
            "success": True,
            "session": {
                "session_id": session.session_id,
                "status": session.context.status,
                "created_at": session.context.created_at,
                "last_activity": session.context.last_activity,
                "url": session.context.url,
                "title": session.context.title,
                "config": session.config.dict(),
                "stats": stats
            }
        }
        
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Failed to get session info", error=str(e), session_id=session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get session info"
        )


@router.get("/", response_model=List[Dict[str, Any]])
async def list_sessions(
    user_id: str = Query(None, description="Filter by user ID"),
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """List all active sessions"""
    
    try:
        sessions = await session_service.list_sessions(user_id=user_id)
        return sessions
        
    except Exception as e:
        logger.error("Failed to list sessions", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list sessions"
        )


@router.get("/{session_id}/stats")
async def get_session_stats(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Get detailed session statistics"""
    
    try:
        stats = await session_service.get_session_stats(session_id)
        return {"success": True, "stats": stats}
        
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Failed to get session stats", error=str(e), session_id=session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get session stats"
        )
