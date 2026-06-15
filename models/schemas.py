"""Consolidated Pydantic schemas for Surf Browser Service"""
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field, validator, HttpUrl
from datetime import datetime, timezone
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


class SessionMode(str, Enum):
    """Session mode enumeration"""
    BROWSER = "browser"
    FETCH_ONLY = "fetch_only"


class StealthStrategy(str, Enum):
    """Browser profile strategy enumeration"""
    NONE = "none"
    MINIMAL = "minimal"
    LEGACY = "legacy"


class FetchBackend(str, Enum):
    """HTTP fetch backend enumeration"""
    AUTO = "auto"
    HTTPX = "httpx"
    CURL_CFFI = "curl_cffi"
    CLOUDSCRAPER = "cloudscraper"
    BROWSER = "browser"


class BlockMode(str, Enum):
    """Request blocking mode enumeration"""
    OFF = "off"
    CONSERVATIVE = "conservative"
    TOKEN_SAVER = "token_saver"


class ContentMode(str, Enum):
    """Agent observation verbosity mode"""
    COMPACT = "compact"
    READER = "reader"
    DATA = "data"
    FULL = "full"


# ============================================================================
# REQUEST SCHEMAS
# ============================================================================

class SessionCreateRequest(BaseModel):
    """Request model for creating a new session"""
    config: Optional[Dict[str, Any]] = Field(default=None, description="Session configuration")
    user_agent: Optional[str] = Field(default=None, max_length=500, description="Custom user agent")
    viewport: Optional[Dict[str, int]] = Field(default=None, description="Viewport dimensions")
    silent: Optional[bool] = Field(default=None, description="Run browser in the background without opening a visible window")
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
    wait_until: WaitUntil = Field(default=WaitUntil.DOMCONTENTLOADED, description="Wait condition")
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


class ObserveRequest(BaseModel):
    """Request model for compact page observation"""
    session_id: str = Field(..., description="Session ID")
    include_screenshot: bool = Field(default=False, description="Capture a screenshot with the observation")
    max_text_length: int = Field(default=8000, ge=500, le=50000, description="Maximum visible text length")
    max_items: int = Field(default=100, ge=1, le=500, description="Maximum links/forms/actions/tables to return")
    content_mode: Optional[ContentMode] = Field(default=None, description="Observation content mode; defaults to the session config")


class WaitRequest(BaseModel):
    """Request model for explicit browser waits"""
    session_id: str = Field(..., description="Session ID")
    selector: Optional[str] = Field(default=None, description="Selector to wait for")
    text: Optional[str] = Field(default=None, description="Text to wait for")
    url_contains: Optional[str] = Field(default=None, description="URL fragment to wait for")
    load_state: Optional[WaitUntil] = Field(default=None, description="Playwright load state to wait for")
    timeout: int = Field(default=30000, ge=1000, le=300000, description="Timeout in milliseconds")


class NetworkCaptureRequest(BaseModel):
    """Request model for browser network capture"""
    session_id: str = Field(..., description="Session ID")
    url_contains: Optional[str] = Field(default=None, description="Only capture responses containing this URL fragment")
    resource_types: Optional[List[str]] = Field(default=None, description="Resource types to capture")
    status_min: Optional[int] = Field(default=None, ge=100, le=599, description="Minimum HTTP status")
    status_max: Optional[int] = Field(default=None, ge=100, le=599, description="Maximum HTTP status")
    include_body: bool = Field(default=False, description="Include small text or JSON response bodies")
    max_body_bytes: int = Field(default=65536, ge=1024, le=1048576, description="Maximum body bytes per response")


class FetchRequest(BaseModel):
    """Request model for one-off HTTP fetches"""
    method: str = Field(default="GET", max_length=16, description="HTTP method")
    url: HttpUrl = Field(..., description="URL to fetch")
    headers: Optional[Dict[str, str]] = Field(default=None, description="Request headers")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Query params")
    body: Optional[Union[str, bytes]] = Field(default=None, description="Raw request body")
    json_body: Optional[Any] = Field(default=None, alias="json", description="JSON request body")
    timeout: int = Field(default=30000, ge=1000, le=300000, description="Timeout in milliseconds")
    backend: FetchBackend = Field(default=FetchBackend.AUTO, description="Fetch backend")
    session_id: Optional[str] = Field(default=None, description="Optional browser session cookie source")
    impersonate: Optional[str] = Field(default="chrome", description="curl_cffi impersonation target")
    save_to_downloads: bool = Field(default=False, description="Save response body into SURF downloads")
    download_filename: Optional[str] = Field(default=None, max_length=255, description="Optional download filename")
    output_dir: Optional[str] = Field(default=None, max_length=1000, description="Optional caller-visible output directory")
    overwrite: bool = Field(default=False, description="Overwrite an existing file in output_dir")

    class Config:
        populate_by_name = True


class SessionTouchRequest(BaseModel):
    """Request model for explicit session heartbeat"""
    reason: Optional[str] = Field(default=None, max_length=200, description="Optional heartbeat reason")


class SessionReapRequest(BaseModel):
    """Request model for manual idle session cleanup"""
    dry_run: bool = Field(default=False, description="Report sessions that would be reaped without closing them")


class DownloadClickRequest(BaseModel):
    """Request model for click-triggered browser downloads"""
    session_id: str = Field(..., description="Session ID")
    selector: str = Field(..., max_length=1000, description="Selector that triggers a download")
    timeout: int = Field(default=60000, ge=1000, le=300000, description="Timeout in milliseconds")
    filename: Optional[str] = Field(default=None, max_length=255, description="Optional saved filename")
    output_dir: Optional[str] = Field(default=None, max_length=1000, description="Optional caller-visible output directory")
    overwrite: bool = Field(default=False, description="Overwrite an existing file in output_dir")


class BatchRequest(BaseModel):
    """Request model for batch operations"""
    operations: List[Dict[str, Any]] = Field(..., min_items=1, max_items=10, description="List of operations")
    session_id: str = Field(..., description="Session ID for batch operations")
    parallel: bool = Field(default=False, description="Whether to execute operations in parallel")
    max_concurrent: int = Field(default=3, ge=1, le=10, description="Maximum concurrent operations")
    
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


class ObserveResponse(BaseResponse):
    """Page observation response model"""
    success: bool = Field(default=True, description="Observation success status")
    data: Dict[str, Any] = Field(..., description="Observation data")


class WaitResponse(BaseResponse):
    """Explicit wait response model"""
    success: bool = Field(default=True, description="Wait success status")
    data: Dict[str, Any] = Field(..., description="Wait result")


class NetworkCaptureResponse(BaseResponse):
    """Network capture response model"""
    success: bool = Field(default=True, description="Network capture operation success status")
    data: Dict[str, Any] = Field(..., description="Network capture data")


class FetchResponse(BaseResponse):
    """Fetch response model"""
    success: bool = Field(default=True, description="Fetch success status")
    data: Dict[str, Any] = Field(..., description="Fetch data")


class DownloadResponse(BaseResponse):
    """Download operation response model"""
    success: bool = Field(default=True, description="Download operation success status")
    data: Dict[str, Any] = Field(..., description="Download data")


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
    mode: SessionMode = Field(default=SessionMode.BROWSER, description="Session mode")
    profile_id: str = Field(default="default", description="Persistent browser profile ID")
    headed: bool = Field(default=True, description="Launch a visible browser")
    silent: bool = Field(default=False, description="Run browser in the background")
    background_headed: bool = Field(default=True, description="Place headed browser windows off-screen by default")
    persist_profile: bool = Field(default=True, description="Persist browser profile data")
    viewport: Dict[str, int] = Field(default={"width": 1920, "height": 1080}, description="Viewport dimensions")
    user_agent: Optional[str] = Field(default=None, description="User agent string")
    stealth: bool = Field(default=False, description="Enable legacy stealth mode")
    stealth_strategy: StealthStrategy = Field(default=StealthStrategy.MINIMAL, description="Browser profile strategy")
    block_resources: List[str] = Field(default=[], description="Resource types to block")
    block_mode: BlockMode = Field(default=BlockMode.CONSERVATIVE, description="Ad/resource blocking mode")
    content_mode: ContentMode = Field(default=ContentMode.COMPACT, description="Default observation mode")
    timeout: int = Field(default=30000, description="Default timeout in milliseconds")
    java_script_enabled: bool = Field(default=True, description="Enable JavaScript")
    ignore_https_errors: bool = Field(default=True, description="Ignore HTTPS errors")
    browser_type: BrowserType = Field(default=BrowserType.CHROMIUM, description="Browser type")
    locale: str = Field(default="en-US", description="Browser locale")
    timezone_id: str = Field(default="Asia/Kolkata", description="Browser timezone ID")
    
    class Config:
        use_enum_values = True


class BrowserContext(BaseModel):
    """Browser context information"""
    context_id: str = Field(..., description="Browser context ID")
    page_id: str = Field(..., description="Page ID")
    url: Optional[str] = Field(default=None, description="Current URL")
    title: Optional[str] = Field(default=None, description="Page title")
    status: SessionStatus = Field(default=SessionStatus.ACTIVE, description="Session status")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Last activity timestamp")
    expires_at: Optional[datetime] = Field(default=None, description="Hard expiration timestamp")
    close_reason: Optional[str] = Field(default=None, description="Reason the session was closed or marked expired")
    
    class Config:
        use_enum_values = True


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


class SessionData(BaseModel):
    """Complete session data model"""
    session_id: str = Field(..., description="Unique session identifier")
    config: SessionConfig = Field(..., description="Session configuration")
    context: BrowserContext = Field(..., description="Browser context")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    stats: SessionStats = Field(default_factory=SessionStats, description="Session statistics")
    
    # Runtime objects (not serialized)
    page: Optional[Any] = Field(default=None, exclude=True, description="Playwright page object")
    context_obj: Optional[Any] = Field(default=None, exclude=True, description="Playwright context object")
    
    class Config:
        use_enum_values = True
        arbitrary_types_allowed = True


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

class SearchRequest(BaseModel):
    """Request model for SearXNG search"""
    query: str = Field(..., min_length=1, max_length=500)
    engines: Optional[List[str]] = Field(default=None)
    categories: Optional[List[str]] = Field(default=None)
    max_results: int = Field(default=10, ge=1, le=50)
    language: str = Field(default="en")
    time_range: Optional[str] = Field(default=None)


class SearchExtractRequest(BaseModel):
    """Request model for parallel deep content extraction"""
    urls: List[str] = Field(..., min_length=1, max_length=10)
    content_mode: str = Field(default="reader")
    max_text_length: int = Field(default=8000, ge=500, le=50000)


class SearchResponse(BaseModel):
    """Search results — minimal wrapper"""
    success: bool = True
    data: Dict[str, Any] = Field(default_factory=dict)


class SearchExtractResponse(BaseModel):
    """Deep extraction — minimal wrapper"""
    success: bool = True
    data: Dict[str, Any] = Field(default_factory=dict)


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
