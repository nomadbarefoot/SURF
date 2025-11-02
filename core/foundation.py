"""Consolidated core foundation for Surf Browser Service"""
import time
import asyncio
import uuid
from typing import Callable, Optional, Dict, Any
from fastapi import Request, Response, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware as StarletteCORSMiddleware
import structlog

from config import get_settings, SecurityConfig

logger = structlog.get_logger()
settings = get_settings()
security = HTTPBearer(auto_error=False)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class SurfException(Exception):
    """Base exception for Surf Browser Service"""
    
    def __init__(self, message: str, error_code: str = "SURF_ERROR", details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class SessionNotFoundError(SurfException):
    """Raised when session is not found"""
    
    def __init__(self, session_id: str):
        super().__init__(
            message=f"Session {session_id} not found",
            error_code="SESSION_NOT_FOUND",
            details={"session_id": session_id}
        )


class InvalidSessionError(SurfException):
    """Raised when session is invalid or expired"""
    
    def __init__(self, session_id: str, reason: str = "Session expired"):
        super().__init__(
            message=f"Invalid session {session_id}: {reason}",
            error_code="INVALID_SESSION",
            details={"session_id": session_id, "reason": reason}
        )


class BrowserOperationError(SurfException):
    """Raised when browser operation fails"""
    
    def __init__(self, operation: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Browser operation '{operation}' failed: {message}",
            error_code="BROWSER_OPERATION_ERROR",
            details={"operation": operation, **(details or {})}
        )


class AuthenticationError(SurfException):
    """Raised when authentication fails"""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR"
        )


class RateLimitExceededError(SurfException):
    """Raised when rate limit is exceeded"""
    
    def __init__(self, limit: int, window: int, retry_after: int):
        super().__init__(
            message=f"Rate limit exceeded: {limit} requests per {window} seconds",
            error_code="RATE_LIMIT_EXCEEDED",
            details={
                "limit": limit,
                "window": window,
                "retry_after": retry_after
            }
        )


class ValidationError(SurfException):
    """Raised when input validation fails"""
    
    def __init__(self, field: str, message: str, value: Any = None):
        super().__init__(
            message=f"Validation error for field '{field}': {message}",
            error_code="VALIDATION_ERROR",
            details={"field": field, "value": value}
        )


class ConfigurationError(SurfException):
    """Raised when configuration is invalid"""
    
    def __init__(self, setting: str, message: str):
        super().__init__(
            message=f"Configuration error for '{setting}': {message}",
            error_code="CONFIGURATION_ERROR",
            details={"setting": setting}
        )


class CacheError(SurfException):
    """Raised when cache operation fails"""
    
    def __init__(self, operation: str, message: str):
        super().__init__(
            message=f"Cache operation '{operation}' failed: {message}",
            error_code="CACHE_ERROR",
            details={"operation": operation}
        )


class ResourceLimitError(SurfException):
    """Raised when resource limits are exceeded"""
    
    def __init__(self, resource: str, limit: int, current: int):
        super().__init__(
            message=f"Resource limit exceeded for '{resource}': {current}/{limit}",
            error_code="RESOURCE_LIMIT_ERROR",
            details={"resource": resource, "limit": limit, "current": current}
        )


# ============================================================================
# MIDDLEWARE
# ============================================================================

class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for request/response logging"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # Log request
        logger.info(
            "Request started",
            method=request.method,
            url=str(request.url),
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Log response
        logger.info(
            "Request completed",
            method=request.method,
            url=str(request.url),
            status_code=response.status_code,
            duration_ms=int(duration * 1000)
        )
        
        return response


class SecurityMiddleware(BaseHTTPMiddleware):
    """Security middleware for request validation and protection"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check request size
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.max_request_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Request too large"
            )
        
        # Add security headers
        response = await call_next(request)
        
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using in-memory storage"""
    
    def __init__(self, app, requests_per_minute: int = 100):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests: Dict[str, list] = {}
        self.cleanup_task = None
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()
        
        # Clean old requests
        if client_ip in self.requests:
            self.requests[client_ip] = [
                req_time for req_time in self.requests[client_ip]
                if current_time - req_time < 60  # Keep only last minute
            ]
        else:
            self.requests[client_ip] = []
        
        # Check rate limit
        if len(self.requests[client_ip]) >= self.requests_per_minute:
            retry_after = 60 - (current_time - min(self.requests[client_ip]))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "retry_after": int(retry_after)
                },
                headers={"Retry-After": str(int(retry_after))}
            )
        
        # Add current request
        self.requests[client_ip].append(current_time)
        
        # Process request
        response = await call_next(request)
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware for consistent error handling"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            return response
        
        except SurfException as e:
            logger.error(
                "Surf exception occurred",
                error_code=e.error_code,
                message=e.message,
                details=e.details,
                url=str(request.url),
                method=request.method
            )
            
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": {
                        "code": e.error_code,
                        "message": e.message,
                        "details": e.details
                    }
                }
            )
        
        except HTTPException as e:
            logger.error(
                "HTTP exception occurred",
                status_code=e.status_code,
                detail=e.detail,
                url=str(request.url),
                method=request.method
            )
            
            return JSONResponse(
                status_code=e.status_code,
                content={
                    "success": False,
                    "error": {
                        "code": "HTTP_ERROR",
                        "message": str(e.detail)
                    }
                }
            )
        
        except Exception as e:
            logger.error(
                "Unexpected error occurred",
                error=str(e),
                error_type=type(e).__name__,
                url=str(request.url),
                method=request.method,
                exc_info=True
            )
            
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred"
                    }
                }
            )


class CORSMiddleware:
    """CORS middleware configuration"""
    
    @staticmethod
    def get_middleware():
        """Get configured CORS middleware"""
        return StarletteCORSMiddleware(
            app=None,  # Will be set by FastAPI
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=settings.cors_methods,
            allow_headers=settings.cors_headers,
            expose_headers=["X-Request-ID", "X-Response-Time"]
        )


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID for tracing"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        
        # Add request ID to request state
        request.state.request_id = request_id
        
        # Process request
        response = await call_next(request)
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response


# ============================================================================
# DEPENDENCIES
# ============================================================================

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """Get current authenticated user from JWT token"""
    
    if not credentials:
        return None
    
    try:
        payload = SecurityConfig.verify_token(credentials.credentials)
        if payload is None:
            raise AuthenticationError("Invalid token")
        
        return {
            "username": payload.get("sub"),
            "scopes": payload.get("scopes", []),
            "exp": payload.get("exp")
        }
    
    except Exception as e:
        logger.error("Authentication failed", error=str(e))
        raise AuthenticationError("Authentication failed")


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """Get current user if authenticated, otherwise return None"""
    
    try:
        return await get_current_user(credentials)
    except AuthenticationError:
        return None


async def require_auth(
    user: Optional[Dict[str, Any]] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Require authentication for protected endpoints"""
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return user


async def require_scope(required_scope: str):
    """Require specific scope for endpoint access"""
    
    def scope_checker(user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
        if required_scope not in user.get("scopes", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope '{required_scope}' required"
            )
        return user
    
    return scope_checker


# Service dependencies
_session_service: Optional[Any] = None
_browser_service: Optional[Any] = None
_cache_service: Optional[Any] = None


async def get_session_service():
    """Get session service instance"""
    global _session_service
    
    if _session_service is None:
        from services.session_service import SessionService
        _session_service = SessionService()
        await _session_service.initialize()
    
    return _session_service


async def get_browser_service():
    """Get browser service instance"""
    global _browser_service
    
    if _browser_service is None:
        from services.browser_service import BrowserService
        _browser_service = BrowserService()
        await _browser_service.initialize()
    
    return _browser_service


async def get_cache_service():
    """Get cache service instance"""
    global _cache_service
    
    if _cache_service is None:
        from services.cache_service import CacheService
        _cache_service = CacheService()
        await _cache_service.initialize()
    
    return _cache_service


async def get_session_manager():
    """Alias for get_session_service for backward compatibility"""
    return await get_session_service()


# Request context dependencies
async def get_request_id(request: Request) -> str:
    """Get request ID from request state"""
    return getattr(request.state, "request_id", "unknown")


async def get_client_ip(request: Request) -> str:
    """Get client IP address"""
    if request.client:
        return request.client.host
    return "unknown"


# Validation dependencies
async def validate_session_id(session_id: str) -> str:
    """Validate session ID format"""
    if not session_id or not session_id.startswith("sess_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session ID format"
        )
    return session_id


async def validate_url(url: str) -> str:
    """Validate URL format and length"""
    if not SecurityConfig.validate_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL format or too long"
        )
    return url


# Cleanup function
async def cleanup_services():
    """Cleanup all services on shutdown"""
    global _session_service, _browser_service, _cache_service
    
    if _session_service:
        await _session_service.cleanup()
        _session_service = None
    
    if _browser_service:
        await _browser_service.cleanup()
        _browser_service = None
    
    if _cache_service:
        await _cache_service.cleanup()
        _cache_service = None
