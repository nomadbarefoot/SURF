"""Data models for Surf Browser Service"""

from .schemas import (
    # Enums
    ExtractType,
    InteractionAction,
    WaitUntil,
    SessionStatus,
    BrowserType,
    # Request Schemas
    SessionCreateRequest,
    NavigateRequest,
    ExtractRequest,
    InteractRequest,
    ScreenshotRequest,
    BatchRequest,
    # Response Schemas
    BaseResponse,
    ErrorResponse,
    SessionResponse,
    NavigationResponse,
    ExtractResponse,
    InteractResponse,
    ScreenshotResponse,
    HealthResponse,
    BatchResponse,
    # Session Schemas
    SessionConfig,
    BrowserContext,
    SessionData,
    SessionStats,
    SessionMetrics,
    SessionLimits
)

__all__ = [
    # Enums
    "ExtractType",
    "InteractionAction", 
    "WaitUntil",
    "SessionStatus",
    "BrowserType",
    # Request Schemas
    "SessionCreateRequest",
    "NavigateRequest",
    "ExtractRequest",
    "InteractRequest",
    "ScreenshotRequest",
    "BatchRequest",
    # Response Schemas
    "BaseResponse",
    "ErrorResponse",
    "SessionResponse",
    "NavigationResponse",
    "ExtractResponse",
    "InteractResponse",
    "ScreenshotResponse",
    "HealthResponse",
    "BatchResponse",
    # Session Schemas
    "SessionConfig",
    "BrowserContext",
    "SessionData",
    "SessionStats",
    "SessionMetrics",
    "SessionLimits"
]
