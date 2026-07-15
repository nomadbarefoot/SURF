"""Consolidated core foundation for Surf Browser Service"""
import time
import asyncio
import secrets
import uuid
from typing import Callable, Optional, Dict, Any
from fastapi import Request, Response, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware as StarletteCORSMiddleware
import structlog

from config import get_settings, SecurityConfig
from config.settings import FREE_TIER_ROUTES

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


class SessionBusyError(SurfException):
    """Raised when an operation conflicts with active session work"""

    def __init__(self, session_id: str, operation: str = "operation"):
        super().__init__(
            message=f"Session {session_id} is busy; retry after the active operation completes",
            error_code="SESSION_BUSY",
            details={"session_id": session_id, "operation": operation}
        )


class ProfileInUseError(SurfException):
    """Raised when a persistent browser profile is already leased"""

    def __init__(self, profile_id: str):
        super().__init__(
            message=f"Persistent profile '{profile_id}' is already active",
            error_code="PROFILE_IN_USE",
            details={"profile_id": profile_id}
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
            path=request.url.path,
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
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=int(duration * 1000)
        )
        
        return response


class SecurityMiddleware(BaseHTTPMiddleware):
    """Security middleware for request validation and protection"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Route-tier gate: when running in loopback mode without a bearer token,
        # restrict access to FREE_TIER_ROUTES (mirrors FREE_TIER_TOOLS on the MCP layer).
        if settings.auth_mode == "loopback":
            auth_header = request.headers.get("authorization", "")
            provided_token = ""
            if auth_header.lower().startswith("bearer "):
                provided_token = auth_header[len("bearer "):].strip()
            has_valid_token = bool(
                provided_token
                and settings.api_token
                and secrets.compare_digest(provided_token, settings.api_token)
            )
            if not has_valid_token:
                path = request.url.path
                # Always allow the root endpoint
                if path != "/" and not any(path.startswith(prefix) for prefix in FREE_TIER_ROUTES):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "success": False,
                            "error": {
                                "code": "FORBIDDEN",
                                "message": "This route requires an API token. Set SURF_API_TOKEN and pass it as a Bearer token."
                            }
                        }
                    )

        # Add security headers
        response = await call_next(request)
        
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response


class RequestSizeLimitMiddleware:
    """Bound declared and chunked request bodies before route parsing."""

    def __init__(self, app, max_body_size: int):
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.lower(): value for key, value in scope.get("headers", [])
        }
        declared = headers.get(b"content-length")
        if declared:
            try:
                declared_size = int(declared)
            except ValueError:
                await JSONResponse(
                    status_code=400,
                    content={"success": False, "error": {"code": "INVALID_CONTENT_LENGTH", "message": "Invalid Content-Length header"}},
                )(scope, receive, send)
                return
            if declared_size > self.max_body_size:
                await self._reject(scope, receive, send, declared_size)
                return

        buffered = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            buffered.append(message)
            if message["type"] != "http.request":
                continue
            total += len(message.get("body", b""))
            if total > self.max_body_size:
                await self._reject(scope, receive, send, total)
                return
            if not message.get("more_body", False):
                break

        index = 0

        async def replay():
            nonlocal index
            if index < len(buffered):
                message = buffered[index]
                index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)

    async def _reject(self, scope, receive, send, current_size: int) -> None:
        await JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={
                "success": False,
                "error": {
                    "code": "REQUEST_TOO_LARGE",
                    "message": "Request body exceeds the configured limit",
                    "details": {
                        "limit": self.max_body_size,
                        "current": current_size,
                    },
                },
            },
        )(scope, receive, send)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using in-memory storage"""
    
    def __init__(self, app, requests_per_window: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = {}
        self._request_count = 0
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()
        
        if request.url.path == "/health/live":
            return await call_next(request)

        cutoff = current_time - self.window_seconds
        self._request_count += 1
        if self._request_count % 100 == 0:
            self.requests = {
                key: [timestamp for timestamp in timestamps if timestamp >= cutoff]
                for key, timestamps in self.requests.items()
                if any(timestamp >= cutoff for timestamp in timestamps)
            }

        self.requests[client_ip] = [
            timestamp
            for timestamp in self.requests.get(client_ip, [])
            if timestamp >= cutoff
        ]
        
        # Check rate limit
        if len(self.requests[client_ip]) >= self.requests_per_window:
            retry_after = max(
                1,
                int(self.window_seconds - (current_time - min(self.requests[client_ip]))),
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "success": False,
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Rate limit exceeded",
                        "details": {"retry_after": retry_after},
                    },
                },
                headers={"Retry-After": str(retry_after)},
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
                path=request.url.path,
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
                path=request.url.path,
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
                path=request.url.path,
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
    """Return a local principal for loopback mode or validate the static bearer token."""

    scopes = ["browser:read", "browser:write", "sessions:manage", "downloads:manage"]
    if settings.auth_mode == "loopback":
        if (
            credentials
            and settings.api_token
            and secrets.compare_digest(credentials.credentials, settings.api_token)
        ):
            return {
                "username": "local-token",
                "scopes": scopes,
                "auth_type": "local_token",
            }
        return {
            "username": "local-loopback",
            "scopes": [],
            "auth_type": "loopback"
        }

    if (
        not credentials
        or not settings.api_token
        or not secrets.compare_digest(credentials.credentials, settings.api_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return {
        "username": "local-token",
        "scopes": scopes,
        "auth_type": "local_token"
    }


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """Get current user if authenticated, otherwise return None"""
    
    try:
        return await get_current_user(credentials)
    except (AuthenticationError, HTTPException):
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


async def require_full_access(
    user: Dict[str, Any] = Depends(require_auth),
) -> Dict[str, Any]:
    """Require a validated bearer token, including in loopback mode."""
    if user.get("auth_type") != "local_token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A configured API token is required",
        )
    return user


def require_scope(required_scope: str):
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
_fetch_service: Optional[Any] = None
_download_service: Optional[Any] = None
_adblock_service: Optional[Any] = None
_search_service: Optional[Any] = None
_finance_service: Optional[Any] = None


async def get_session_service():
    """Get session service instance"""
    global _session_service
    
    if _session_service is None:
        from services.session_service import SessionService
        _session_service = SessionService()
        await _session_service.initialize()
    
    return _session_service


def get_session_service_if_initialized() -> Optional[Any]:
    """Return runtime state without starting background services from a probe."""
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


async def get_fetch_service():
    """Get fetch service instance"""
    global _fetch_service

    if _fetch_service is None:
        from services.fetch_service import FetchService
        _fetch_service = FetchService()

    return _fetch_service


async def get_download_service():
    """Get download service instance"""
    global _download_service

    if _download_service is None:
        from services.download_service import DownloadService
        _download_service = DownloadService()

    return _download_service


async def get_adblock_service():
    """Get adblock service instance"""
    global _adblock_service

    if _adblock_service is None:
        from services.adblock_service import AdblockService
        _adblock_service = AdblockService()
        await _adblock_service.initialize()

    return _adblock_service


async def get_search_service():
    """Get search service instance"""
    global _search_service

    if _search_service is None:
        from services.search_service import SearchService
        _search_service = SearchService()

    return _search_service


async def get_finance_service():
    """Get finance service instance"""
    global _finance_service

    if _finance_service is None:
        from services.finance_service import FinanceService
        fetch = await get_fetch_service()
        search = await get_search_service()
        cache = await get_cache_service()
        _finance_service = FinanceService(fetch, search, cache)

    return _finance_service


async def get_session_manager():
    """Alias for get_session_service for backward compatibility"""
    return await get_session_service()


def get_request_guard():
    """Return the module-level RequestGuard singleton."""
    from services.request_guard import get_guard
    return get_guard()


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
    global _session_service, _browser_service, _cache_service, _fetch_service, _download_service, _adblock_service, _search_service, _finance_service
    
    if _session_service:
        await _session_service.cleanup()
        _session_service = None
    
    if _browser_service:
        await _browser_service.cleanup()
        _browser_service = None
    
    if _cache_service:
        await _cache_service.cleanup()
        _cache_service = None

    _fetch_service = None
    _download_service = None
    _adblock_service = None
    _search_service = None
    _finance_service = None
