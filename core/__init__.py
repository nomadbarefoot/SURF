"""Core module for Surf Browser Service"""

from .foundation import (
    # Exceptions
    SurfException,
    SessionNotFoundError,
    InvalidSessionError,
    BrowserOperationError,
    AuthenticationError,
    RateLimitExceededError,
    ValidationError,
    ConfigurationError,
    CacheError,
    ResourceLimitError,
    # Middleware
    LoggingMiddleware,
    SecurityMiddleware,
    RateLimitMiddleware,
    ErrorHandlingMiddleware,
    CORSMiddleware,
    RequestIDMiddleware,
    # Dependencies
    get_current_user,
    get_optional_user,
    require_auth,
    require_scope,
    get_session_service,
    get_browser_service,
    get_cache_service,
    get_session_manager,
    get_request_id,
    get_client_ip,
    validate_session_id,
    validate_url,
    cleanup_services
)

__all__ = [
    # Exceptions
    "SurfException",
    "SessionNotFoundError",
    "InvalidSessionError", 
    "BrowserOperationError",
    "AuthenticationError",
    "RateLimitExceededError",
    "ValidationError",
    "ConfigurationError",
    "CacheError",
    "ResourceLimitError",
    # Middleware
    "LoggingMiddleware",
    "SecurityMiddleware",
    "RateLimitMiddleware",
    "ErrorHandlingMiddleware",
    "CORSMiddleware",
    "RequestIDMiddleware",
    # Dependencies
    "get_current_user",
    "get_optional_user",
    "require_auth",
    "require_scope",
    "get_session_service",
    "get_browser_service",
    "get_cache_service",
    "get_session_manager",
    "get_request_id",
    "get_client_ip",
    "validate_session_id",
    "validate_url",
    "cleanup_services"
]
