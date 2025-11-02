"""Consolidated Pydantic schemas for Surf Browser Service"""
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field, validator, HttpUrl
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class ExtractType(str, Enum):
    """Content extraction types"""
    TEXT = "text"
    HTML = "html"
    TABLE = "table"
    LINKS = "links"
    IMAGES = "images"


class InteractionAction(str, Enum):
    """Element interaction actions"""
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    SCROLL = "scroll"
    HOVER = "hover"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"


class WaitUntil(str, Enum):
    """Navigation wait conditions"""
    LOAD = "load"
    DOMCONTENTLOADED = "domcontentloaded"
    NETWORKIDLE = "networkidle"
    COMMIT = "commit"


class SessionStatus(str, Enum):
    """Session status enumeration"""
    ACTIVE = "active"
    IDLE = "idle"
    EXPIRED = "expired"
    ERROR = "error"


class BrowserType(str, Enum):
    """Browser type enumeration"""
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


# ============================================================================
# REQUEST SCHEMAS
# ============================================================================

class SessionCreateRequest(BaseModel):
    """Request model for creating a new session"""
    config: Optional[Dict[str, Any]] = Field(default=None, description="Session configuration")
    user_agent: Optional[str] = Field(default=None, max_length=500, description="Custom user agent")
    viewport: Optional[Dict[str, int]] = Field(default=None, description="Viewport dimensions")
    stealth: Optional[bool] = Field(default=None, description="Enable stealth mode")
    block_resources: Optional[List[str]] = Field(default=None, description="Resource types to block")
    
    @validator("viewport")
    def validate_viewport(cls, v: Optional[Dict[str, int]]) -> Optional[Dict[str, int]]:
        if v:
            if "width" not in v or "height" not in v:
                raise ValueError("Viewport must contain width and height")
            if v["width"] < 100 or v["height"] < 100:
                raise ValueError("Viewport dimensions must be at least 100x100")
            if v["width"] > 4096 or v["height"] > 4096:
                raise ValueError("Viewport dimensions must not exceed 4096x4096")
        return v


class NavigateRequest(BaseModel):
    """Request model for navigation"""
    session_id: str = Field(..., description="Session ID")
    url: HttpUrl = Field(..., description="URL to navigate to")
    wait_until: WaitUntil = Field(default=WaitUntil.NETWORKIDLE, description="Wait condition")
    timeout: Optional[int] = Field(default=None, ge=1000, le=300000, description="Timeout in milliseconds")
    
    @validator("session_id")
    def validate_session_id(cls, v: str) -> str:
        if not v or not v.startswith("sess_"):
            raise ValueError("Invalid session ID format")
        return v


class ExtractRequest(BaseModel):
    """Request model for content extraction"""
    session_id: str = Field(..., description="Session ID")
    extract_type: ExtractType = Field(..., description="Type of content to extract")
    selector: Optional[str] = Field(default=None, max_length=1000, description="CSS selector")
    timeout: Optional[int] = Field(default=None, ge=1000, le=60000, description="Timeout in milliseconds")
    
    @validator("session_id")
    def validate_session_id(cls, v: str) -> str:
        if not v or not v.startswith("sess_"):
            raise ValueError("Invalid session ID format")
        return v


class InteractRequest(BaseModel):
    """Request model for element interaction"""
    session_id: str = Field(..., description="Session ID")
    action: InteractionAction = Field(..., description="Action to perform")
    selector: str = Field(..., max_length=1000, description="CSS selector")
    value: Optional[str] = Field(default=None, max_length=10000, description="Value for type/select actions")
    options: Optional[Dict[str, Any]] = Field(default=None, description="Additional options")
    timeout: Optional[int] = Field(default=None, ge=1000, le=60000, description="Timeout in milliseconds")
    
    @validator("session_id")
    def validate_session_id(cls, v: str) -> str:
        if not v or not v.startswith("sess_"):
            raise ValueError("Invalid session ID format")
        return v
    
    @validator("value")
    def validate_value_for_action(cls, v: Optional[str], values: Dict[str, Any]) -> Optional[str]:
        action = values.get("action")
        if action in ["type", "select"] and not v:
            raise ValueError(f"Value is required for action '{action}'")
        return v


class ScreenshotRequest(BaseModel):
    """Request model for screenshot capture"""
    session_id: str = Field(..., description="Session ID")
    selector: Optional[str] = Field(default=None, max_length=1000, description="CSS selector for element screenshot")
    full_page: bool = Field(default=False, description="Capture full page")
    path: Optional[str] = Field(default=None, max_length=500, description="Custom file path")
    quality: Optional[int] = Field(default=None, ge=1, le=100, description="JPEG quality (1-100)")
    timeout: Optional[int] = Field(default=None, ge=1000, le=60000, description="Timeout in milliseconds")
    
    @validator("session_id")
    def validate_session_id(cls, v: str) -> str:
        if not v or not v.startswith("sess_"):
            raise ValueError("Invalid session ID format")
        return v


class LoginRequest(BaseModel):
    """Request model for user authentication"""
    username: str = Field(..., min_length=3, max_length=50, description="Username")
    password: str = Field(..., min_length=8, max_length=100, description="Password")
    
    @validator("username")
    def validate_username(cls, v: str) -> str:
        if not v.isalnum():
            raise ValueError("Username must contain only alphanumeric characters")
        return v.lower()


class APIKeyRequest(BaseModel):
    """Request model for API key generation"""
    name: str = Field(..., min_length=3, max_length=50, description="API key name")
    scopes: List[str] = Field(default=["browser:read"], description="API key scopes")
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365, description="Expiration in days")


class BatchRequest(BaseModel):
    """Request model for batch operations"""
    operations: List[Dict[str, Any]] = Field(..., min_items=1, max_items=10, description="List of operations")
    session_id: str = Field(..., description="Session ID for batch operations")
    
    @validator("session_id")
    def validate_session_id(cls, v: str) -> str:
        if not v or not v.startswith("sess_"):
            raise ValueError("Invalid session ID format")
        return v


# ============================================================================
# RESPONSE SCHEMAS
# ============================================================================

class BaseResponse(BaseModel):
    """Base response model"""
    success: bool = Field(..., description="Operation success status")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    request_id: Optional[str] = Field(default=None, description="Request ID for tracing")


class ErrorResponse(BaseResponse):
    """Error response model"""
    success: bool = Field(default=False, description="Always false for errors")
    error: Dict[str, Any] = Field(..., description="Error details")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": "Session not found",
                    "details": {"session_id": "sess_123"}
                }
            }
        }


class SessionResponse(BaseResponse):
    """Session creation response model"""
    success: bool = Field(default=True, description="Always true for successful session creation")
    session_id: str = Field(..., description="Created session ID")
    config: Dict[str, Any] = Field(..., description="Session configuration")
    expires_at: Optional[datetime] = Field(default=None, description="Session expiration time")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "session_id": "sess_abc123",
                "config": {
                    "viewport": {"width": 1920, "height": 1080},
                    "user_agent": "Mozilla/5.0...",
                    "stealth": True
                },
                "expires_at": "2024-01-01T00:05:00Z"
            }
        }


class NavigationResponse(BaseResponse):
    """Navigation response model"""
    success: bool = Field(default=True, description="Navigation success status")
    data: Dict[str, Any] = Field(..., description="Navigation result data")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "data": {
                    "url": "https://example.com",
                    "status": 200,
                    "title": "Example Page",
                    "duration_ms": 1500
                }
            }
        }


class ExtractResponse(BaseResponse):
    """Content extraction response model"""
    success: bool = Field(default=True, description="Extraction success status")
    data: Dict[str, Any] = Field(..., description="Extracted content data")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "data": {
                    "text": "Extracted text content...",
                    "length": 150,
                    "type": "text"
                }
            }
        }


class InteractResponse(BaseResponse):
    """Element interaction response model"""
    success: bool = Field(default=True, description="Interaction success status")
    data: Dict[str, Any] = Field(..., description="Interaction result data")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "data": {
                    "action": "click",
                    "selector": "button.submit",
                    "success": True
                }
            }
        }


class ScreenshotResponse(BaseResponse):
    """Screenshot response model"""
    success: bool = Field(default=True, description="Screenshot success status")
    data: Dict[str, Any] = Field(..., description="Screenshot data")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "data": {
                    "path": "screenshots/sess_abc123_1640995200.png",
                    "selector": "body",
                    "full_page": False,
                    "size_bytes": 125000
                }
            }
        }


class HealthResponse(BaseResponse):
    """Health check response model"""
    success: bool = Field(default=True, description="Service health status")
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="Service version")
    uptime: float = Field(..., description="Service uptime in seconds")
    active_sessions: int = Field(..., description="Number of active sessions")
    max_sessions: int = Field(..., description="Maximum allowed sessions")
    memory_usage: Optional[Dict[str, Any]] = Field(default=None, description="Memory usage statistics")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "status": "healthy",
                "version": "1.0.0",
                "uptime": 3600.5,
                "active_sessions": 5,
                "max_sessions": 20,
                "memory_usage": {
                    "rss": 50000000,
                    "heap_used": 30000000,
                    "heap_total": 50000000
                }
            }
        }


class LoginResponse(BaseResponse):
    """Login response model"""
    success: bool = Field(default=True, description="Login success status")
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration in seconds")
    user: Dict[str, Any] = Field(..., description="User information")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
                "token_type": "bearer",
                "expires_in": 1800,
                "user": {
                    "username": "user123",
                    "scopes": ["browser:read", "browser:write"]
                }
            }
        }


class APIKeyResponse(BaseResponse):
    """API key response model"""
    success: bool = Field(default=True, description="API key creation success status")
    api_key: str = Field(..., description="Generated API key")
    key_id: str = Field(..., description="API key ID")
    scopes: List[str] = Field(..., description="API key scopes")
    expires_at: Optional[datetime] = Field(default=None, description="API key expiration time")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "api_key": "surf_abc123def456...",
                "key_id": "key_789",
                "scopes": ["browser:read"],
                "expires_at": "2024-12-31T23:59:59Z"
            }
        }


class BatchResponse(BaseResponse):
    """Batch operation response model"""
    success: bool = Field(..., description="Overall batch success status")
    results: List[Dict[str, Any]] = Field(..., description="Individual operation results")
    total_operations: int = Field(..., description="Total number of operations")
    successful_operations: int = Field(..., description="Number of successful operations")
    failed_operations: int = Field(..., description="Number of failed operations")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
                "request_id": "req_123456",
                "results": [
                    {"operation": "navigate", "success": True, "data": {...}},
                    {"operation": "extract", "success": True, "data": {...}}
                ],
                "total_operations": 2,
                "successful_operations": 2,
                "failed_operations": 0
            }
        }


# ============================================================================
# SESSION SCHEMAS
# ============================================================================

class SessionConfig(BaseModel):
    """Session configuration model"""
    viewport: Dict[str, int] = Field(default={"width": 1920, "height": 1080}, description="Viewport dimensions")
    user_agent: str = Field(..., description="User agent string")
    stealth: bool = Field(default=True, description="Enable stealth mode")
    block_resources: List[str] = Field(default=["image", "font", "stylesheet"], description="Resource types to block")
    timeout: int = Field(default=30000, description="Default timeout in milliseconds")
    java_script_enabled: bool = Field(default=True, description="Enable JavaScript")
    ignore_https_errors: bool = Field(default=True, description="Ignore HTTPS errors")
    browser_type: BrowserType = Field(default=BrowserType.CHROMIUM, description="Browser type")
    
    class Config:
        use_enum_values = True


class BrowserContext(BaseModel):
    """Browser context information"""
    context_id: str = Field(..., description="Browser context ID")
    page_id: str = Field(..., description="Page ID")
    url: Optional[str] = Field(default=None, description="Current URL")
    title: Optional[str] = Field(default=None, description="Page title")
    status: SessionStatus = Field(default=SessionStatus.ACTIVE, description="Session status")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    last_activity: datetime = Field(default_factory=datetime.utcnow, description="Last activity timestamp")
    
    class Config:
        use_enum_values = True


class SessionData(BaseModel):
    """Complete session data model"""
    session_id: str = Field(..., description="Unique session identifier")
    config: SessionConfig = Field(..., description="Session configuration")
    context: BrowserContext = Field(..., description="Browser context")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    stats: Dict[str, Any] = Field(default_factory=dict, description="Session statistics")
    
    # Runtime objects (not serialized)
    page: Optional[Any] = Field(default=None, exclude=True, description="Playwright page object")
    context_obj: Optional[Any] = Field(default=None, exclude=True, description="Playwright context object")
    
    class Config:
        use_enum_values = True
        arbitrary_types_allowed = True


class SessionStats(BaseModel):
    """Session statistics model"""
    requests_made: int = Field(default=0, description="Number of requests made")
    pages_loaded: int = Field(default=0, description="Number of pages loaded")
    screenshots_taken: int = Field(default=0, description="Number of screenshots taken")
    interactions_performed: int = Field(default=0, description="Number of interactions performed")
    errors_encountered: int = Field(default=0, description="Number of errors encountered")
    total_duration: float = Field(default=0.0, description="Total session duration in seconds")
    last_error: Optional[str] = Field(default=None, description="Last error message")
    
    def increment_requests(self) -> None:
        """Increment request counter"""
        self.requests_made += 1
    
    def increment_pages(self) -> None:
        """Increment page load counter"""
        self.pages_loaded += 1
    
    def increment_screenshots(self) -> None:
        """Increment screenshot counter"""
        self.screenshots_taken += 1
    
    def increment_interactions(self) -> None:
        """Increment interaction counter"""
        self.interactions_performed += 1
    
    def increment_errors(self, error_message: str) -> None:
        """Increment error counter and set last error"""
        self.errors_encountered += 1
        self.last_error = error_message
    
    def update_duration(self, duration: float) -> None:
        """Update total duration"""
        self.total_duration += duration


class SessionMetrics(BaseModel):
    """Session performance metrics"""
    average_page_load_time: float = Field(default=0.0, description="Average page load time in seconds")
    average_response_time: float = Field(default=0.0, description="Average response time in seconds")
    memory_usage: int = Field(default=0, description="Memory usage in bytes")
    cpu_usage: float = Field(default=0.0, description="CPU usage percentage")
    network_requests: int = Field(default=0, description="Total network requests")
    data_transferred: int = Field(default=0, description="Data transferred in bytes")
    
    def calculate_averages(self, total_operations: int) -> None:
        """Calculate average metrics"""
        if total_operations > 0:
            self.average_page_load_time = self.total_page_load_time / total_operations
            self.average_response_time = self.total_response_time / total_operations
    
    def add_page_load_time(self, load_time: float) -> None:
        """Add page load time to totals"""
        if not hasattr(self, 'total_page_load_time'):
            self.total_page_load_time = 0.0
        self.total_page_load_time += load_time
    
    def add_response_time(self, response_time: float) -> None:
        """Add response time to totals"""
        if not hasattr(self, 'total_response_time'):
            self.total_response_time = 0.0
        self.total_response_time += response_time


class SessionLimits(BaseModel):
    """Session resource limits"""
    max_duration: int = Field(default=300, description="Maximum session duration in seconds")
    max_requests: int = Field(default=1000, description="Maximum number of requests")
    max_pages: int = Field(default=100, description="Maximum number of pages")
    max_screenshots: int = Field(default=50, description="Maximum number of screenshots")
    max_interactions: int = Field(default=500, description="Maximum number of interactions")
    max_memory_mb: int = Field(default=512, description="Maximum memory usage in MB")
    
    def check_limits(self, stats: SessionStats) -> List[str]:
        """Check if session has exceeded any limits"""
        violations = []
        
        if stats.total_duration > self.max_duration:
            violations.append(f"Session duration exceeded: {stats.total_duration}s > {self.max_duration}s")
        
        if stats.requests_made > self.max_requests:
            violations.append(f"Request limit exceeded: {stats.requests_made} > {self.max_requests}")
        
        if stats.pages_loaded > self.max_pages:
            violations.append(f"Page limit exceeded: {stats.pages_loaded} > {self.max_pages}")
        
        if stats.screenshots_taken > self.max_screenshots:
            violations.append(f"Screenshot limit exceeded: {stats.screenshots_taken} > {self.max_screenshots}")
        
        if stats.interactions_performed > self.max_interactions:
            violations.append(f"Interaction limit exceeded: {stats.interactions_performed} > {self.max_interactions}")
        
        return violations


# ============================================================================
# ENHANCED CONTENT EXTRACTION SCHEMAS
# ============================================================================

class StructuredDataRequest(BaseModel):
    """Request for structured data extraction"""
    session_id: str = Field(..., description="Session ID")
    content_type: str = Field(default="general", description="Type of content to extract (general, forum, news, financial)")
    selector: Optional[str] = Field(default=None, description="CSS selector for content extraction")
    timeout: Optional[int] = Field(default=None, description="Operation timeout in milliseconds")


class StructuredDataResponse(BaseModel):
    """Response for structured data extraction"""
    success: bool = Field(..., description="Whether the operation was successful")
    data: Dict[str, Any] = Field(..., description="Extracted structured data")


class CaptchaDetectionRequest(BaseModel):
    """Request for CAPTCHA detection"""
    session_id: str = Field(..., description="Session ID")
    selector: Optional[str] = Field(default=None, description="CSS selector for content analysis")
    timeout: Optional[int] = Field(default=None, description="Operation timeout in milliseconds")


class CaptchaDetectionResponse(BaseModel):
    """Response for CAPTCHA detection"""
    success: bool = Field(..., description="Whether the operation was successful")
    data: Dict[str, Any] = Field(..., description="CAPTCHA detection results")


# ============================================================================
# ENHANCED EXTRACT RESPONSE SCHEMAS
# ============================================================================

class EnhancedExtractResponse(BaseModel):
    """Enhanced response for content extraction with quality metrics"""
    success: bool = Field(..., description="Whether the operation was successful")
    data: Dict[str, Any] = Field(..., description="Extracted content and metadata")
    quality_metrics: Optional[Dict[str, Any]] = Field(default=None, description="Content quality assessment")
    captcha_detected: bool = Field(default=False, description="Whether CAPTCHA was detected")
    captcha_reason: Optional[str] = Field(default=None, description="Reason for CAPTCHA detection")


# ============================================================================
# BATCH OPERATION SCHEMAS
# ============================================================================

class BatchOperationRequest(BaseModel):
    """Request for batch operations"""
    session_id: str = Field(..., description="Session ID")
    operations: List[Dict[str, Any]] = Field(..., description="List of operations to perform")
    parallel: bool = Field(default=True, description="Whether to execute operations in parallel")
    max_concurrent: int = Field(default=5, description="Maximum concurrent operations for parallel execution")
    timeout: Optional[int] = Field(default=None, description="Global timeout for all operations")


class BatchOperationResponse(BaseModel):
    """Response for batch operations"""
    success: bool = Field(..., description="Whether all operations were successful")
    results: List[Dict[str, Any]] = Field(..., description="Results of individual operations")
    total_operations: int = Field(..., description="Total number of operations")
    successful_operations: int = Field(..., description="Number of successful operations")
    failed_operations: int = Field(..., description="Number of failed operations")
    parallel: bool = Field(..., description="Whether operations were executed in parallel")
    max_concurrent: int = Field(..., description="Maximum concurrent operations used")
    execution_time: Optional[float] = Field(default=None, description="Total execution time in seconds")


# ============================================================================
# CONTENT QUALITY SCHEMAS
# ============================================================================

class ContentQualityMetrics(BaseModel):
    """Content quality assessment metrics"""
    word_count: int = Field(..., description="Number of words in content")
    line_count: int = Field(..., description="Number of lines in content")
    character_count: int = Field(..., description="Number of characters in content")
    content_quality_score: float = Field(..., description="Quality score (0.0 to 1.0)")
    has_meaningful_content: bool = Field(..., description="Whether content appears meaningful")
    is_captcha: bool = Field(default=False, description="Whether content appears to be CAPTCHA")
    captcha_reason: Optional[str] = Field(default=None, description="Reason for CAPTCHA detection")


class StructuredContentData(BaseModel):
    """Structured content extraction results"""
    raw_content: str = Field(..., description="Raw extracted content")
    content_type: str = Field(..., description="Type of content")
    metrics: ContentQualityMetrics = Field(..., description="Content quality metrics")
    extracted_elements: Dict[str, Any] = Field(default_factory=dict, description="Type-specific extracted elements")
    page_metadata: Optional[Dict[str, Any]] = Field(default=None, description="Page metadata")
