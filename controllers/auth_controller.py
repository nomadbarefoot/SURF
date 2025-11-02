"""Authentication controller for Surf Browser Service"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
import structlog

from core.foundation import get_current_user, AuthenticationError
from models.schemas import LoginRequest, APIKeyRequest, LoginResponse, APIKeyResponse
from config import SecurityConfig

logger = structlog.get_logger()
router = APIRouter()
security = HTTPBearer()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate user and return JWT token"""
    
    try:
        # In a real implementation, you would:
        # 1. Validate credentials against a database
        # 2. Check user permissions
        # 3. Generate appropriate scopes
        
        # For demo purposes, accept any valid username/password
        if len(request.username) < 3 or len(request.password) < 8:
            raise AuthenticationError("Invalid credentials")
        
        # Generate token with user info and scopes
        token_data = {
            "sub": request.username,
            "scopes": ["browser:read", "browser:write", "sessions:manage"]
        }
        
        access_token = SecurityConfig.create_access_token(token_data)
        
        return LoginResponse(
            success=True,
            access_token=access_token,
            expires_in=1800,  # 30 minutes
            user={
                "username": request.username,
                "scopes": token_data["scopes"]
            }
        )
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Login failed", error=str(e), username=request.username)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )


@router.post("/api-key", response_model=APIKeyResponse)
async def create_api_key(
    request: APIKeyRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Create API key for programmatic access"""
    
    try:
        # Generate API key
        api_key = SecurityConfig.generate_api_key()
        key_id = f"key_{api_key[:8]}"
        
        # In a real implementation, you would:
        # 1. Store the hashed API key in database
        # 2. Associate it with the user
        # 3. Set expiration date
        
        return APIKeyResponse(
            success=True,
            api_key=api_key,
            key_id=key_id,
            scopes=request.scopes
        )
        
    except Exception as e:
        logger.error("API key creation failed", error=str(e), user=user.get("username"))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key creation failed"
        )


@router.get("/me")
async def get_current_user_info(
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Get current user information"""
    
    return {
        "success": True,
        "user": user
    }


@router.post("/refresh")
async def refresh_token(
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Refresh JWT token"""
    
    try:
        # Generate new token with same user info
        token_data = {
            "sub": user["username"],
            "scopes": user.get("scopes", [])
        }
        
        access_token = SecurityConfig.create_access_token(token_data)
        
        return LoginResponse(
            success=True,
            access_token=access_token,
            expires_in=1800,
            user=user
        )
        
    except Exception as e:
        logger.error("Token refresh failed", error=str(e), user=user.get("username"))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed"
        )


@router.post("/logout")
async def logout(
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Logout user (invalidate token)"""
    
    # In a real implementation, you would:
    # 1. Add token to blacklist
    # 2. Remove from active sessions
    # 3. Log the logout event
    
    logger.info("User logged out", username=user.get("username"))
    
    return {
        "success": True,
        "message": "Logged out successfully"
    }
