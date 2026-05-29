"""Local auth introspection for SURF."""
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status

from core.foundation import get_current_user
from config.settings import settings

router = APIRouter()


@router.get("/me")
async def get_current_user_info(
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Return the current local principal."""
    return {
        "success": True,
        "user": user,
        "auth_mode": settings.auth_mode
    }


@router.post("/login")
async def login_disabled():
    """Demo login was removed from the supported local contract."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Demo login is disabled. Use loopback mode locally or SURF_AUTH_MODE=token with SURF_API_TOKEN."
    )


@router.post("/api-key")
async def api_key_disabled():
    """Runtime API-key creation is not supported."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Runtime API-key creation is not supported. Configure SURF_API_TOKEN instead."
    )


@router.post("/refresh")
async def refresh_disabled():
    """JWT refresh is not part of the local auth contract."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="JWT refresh is not supported. Configure SURF_API_TOKEN for bearer auth."
    )


@router.post("/logout")
async def logout_disabled():
    """Stateless local auth has no logout operation."""
    return {"success": True, "message": "No local auth session to revoke"}
