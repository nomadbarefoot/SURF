"""Enhanced session management service for Surf Browser Service"""
import asyncio
import time
import uuid
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import structlog

from config import get_settings
from core.foundation import (
    SessionNotFoundError,
    InvalidSessionError,
    ResourceLimitError,
    ConfigurationError
)
from models.schemas import (
    SessionData,
    SessionConfig,
    BrowserContext as BrowserContextModel,
    SessionStatus,
    SessionStats,
    SessionLimits,
    SessionMode,
    StealthStrategy
)
from utils.stealth import setup_stealth_mode
from utils.helpers import get_random_user_agent
from utils.anti_detection import get_enhanced_stealth_config, user_agent_pool

logger = structlog.get_logger()
settings = get_settings()


class SessionService:
    """Enhanced session management with connection pooling and monitoring"""
    
    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.active_sessions: Dict[str, SessionData] = {}
        self.session_lock = asyncio.Lock()
        self.cleanup_task: Optional[asyncio.Task] = None
        self.start_time = time.time()
        self.session_limits = SessionLimits()
    
    async def initialize(self) -> None:
        """Initialize Playwright and browser instance"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = None
            
            # Start cleanup task
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())
            
            logger.info("Session service initialized successfully")
            
        except Exception as e:
            logger.error("Failed to initialize session service", error=str(e))
            raise ConfigurationError("browser_initialization", str(e))
    
    async def cleanup(self) -> None:
        """Cleanup all sessions and browser instance"""
        try:
            # Cancel cleanup task
            if self.cleanup_task:
                self.cleanup_task.cancel()
                try:
                    await self.cleanup_task
                except asyncio.CancelledError:
                    pass
            
            # Close all active sessions
            async with self.session_lock:
                for session_id in list(self.active_sessions.keys()):
                    await self._close_session_internal(session_id)
            
            # Close browser and playwright
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            logger.info("Session service cleanup completed")
            
        except Exception as e:
            logger.error("Error during session service cleanup", error=str(e))
    
    async def create_session(
        self, 
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> SessionData:
        """Create new browser session with enhanced configuration"""
        
        async with self.session_lock:
            # Check session limit
            if len(self.active_sessions) >= settings.max_sessions:
                raise ResourceLimitError(
                    "sessions", 
                    settings.max_sessions, 
                    len(self.active_sessions)
                )
            
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            
            try:
                # Build session configuration
                config = self._build_session_config(user_config)
                
                context = await self._create_browser_context(config, session_id)
                
                # Block resources if enabled
                if config.block_resources:
                    await context.route("**/*", lambda route: self._handle_route(route, config.block_resources))
                
                # Create page
                page = context.pages[0] if context.pages else await context.new_page()
                
                stealth_strategy = self._enum_value(config.stealth_strategy)
                if stealth_strategy == StealthStrategy.LEGACY.value or config.stealth:
                    stealth_config = get_enhanced_stealth_config()
                    await setup_stealth_mode(page, stealth_config["device_info"])
                elif stealth_strategy == StealthStrategy.MINIMAL.value:
                    await self._setup_minimal_profile(page)
                
                # Create browser context model
                browser_context = BrowserContextModel(
                    context_id=str(id(context)),
                    page_id=str(id(page)),
                    status=SessionStatus.ACTIVE
                )
                
                # Create session data
                session_data = SessionData(
                    session_id=session_id,
                    config=config,
                    context=browser_context,
                    metadata={
                        "user_id": user_id,
                        "created_by": "api",
                        "browser_type": config.browser_type
                    },
                    stats=SessionStats()
                )
                
                # Store session with page and context references
                session_data.page = page
                session_data.context_obj = context
                self.active_sessions[session_id] = session_data
                
                logger.info(
                    "Session created",
                    session_id=session_id,
                    user_id=user_id,
                    config=config.dict()
                )
                
                return session_data
                
            except Exception as e:
                logger.error("Failed to create session", session_id=session_id, error=str(e))
                raise
    
    async def close_session(self, session_id: str) -> None:
        """Close specific session and cleanup resources"""
        async with self.session_lock:
            await self._close_session_internal(session_id)
    
    async def _close_session_internal(self, session_id: str) -> None:
        """Internal method to close session without lock"""
        if session_id not in self.active_sessions:
            raise SessionNotFoundError(session_id)
        
        session = self.active_sessions[session_id]
        
        try:
            if getattr(session, "context_obj", None):
                await session.context_obj.close()
            elif self.browser:
                context_id = session.context.context_id
                for context in self.browser.contexts:
                    if str(id(context)) == context_id:
                        await context.close()
                        break
            
            # Remove from active sessions
            del self.active_sessions[session_id]
            
            logger.info("Session closed", session_id=session_id)
            
        except Exception as e:
            logger.error("Error closing session", session_id=session_id, error=str(e))
            # Still remove from active sessions even if close fails
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]
    
    async def get_session(self, session_id: str) -> SessionData:
        """Get session by ID with activity tracking and validation"""
        
        if session_id not in self.active_sessions:
            raise SessionNotFoundError(session_id)
        
        session = self.active_sessions[session_id]
        
        # Check TTL
        if time.time() - session.context.created_at.timestamp() > settings.session_ttl:
            await self._close_session_internal(session_id)
            raise InvalidSessionError(session_id, "Session expired")
        
        # Check session limits
        violations = self.session_limits.check_limits(session.stats)
        if violations:
            await self._close_session_internal(session_id)
            raise InvalidSessionError(session_id, f"Session limits exceeded: {', '.join(violations)}")
        
        # Update last activity
        from datetime import timezone
        session.context.last_activity = datetime.now(timezone.utc)
        
        return session
    
    async def update_session_stats(self, session_id: str, stats_update: Dict[str, Any]) -> None:
        """Update session statistics"""
        if session_id not in self.active_sessions:
            return
        
        session = self.active_sessions[session_id]
        
        # Update stats based on operation type
        if stats_update.get("operation") == "navigate":
            session.stats.increment_pages()
        elif stats_update.get("operation") == "screenshot":
            session.stats.increment_screenshots()
        elif stats_update.get("operation") == "interact":
            session.stats.increment_interactions()
        elif stats_update.get("operation") == "request":
            session.stats.increment_requests()
        
        # Update duration
        if "duration" in stats_update:
            session.stats.update_duration(stats_update["duration"])
        
        # Update error count
        if "error" in stats_update:
            session.stats.increment_errors(stats_update["error"])
    
    async def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get session statistics"""
        session = await self.get_session(session_id)
        return {
            "session_id": session_id,
            "stats": session.stats.dict(),
            "context": session.context.dict(),
            "uptime": time.time() - session.context.created_at.timestamp()
        }
    
    async def list_sessions(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all active sessions"""
        sessions = []
        
        for session_id, session in self.active_sessions.items():
            if user_id and session.metadata.get("user_id") != user_id:
                continue
            
            sessions.append({
                "session_id": session_id,
                "status": session.context.status,
                "created_at": session.context.created_at,
                "last_activity": session.context.last_activity,
                "url": session.context.url,
                "title": session.context.title,
                "stats": session.stats.dict()
            })
        
        return sessions
    
    def _build_session_config(self, user_config: Optional[Dict[str, Any]]) -> SessionConfig:
        """Build session configuration with smart defaults"""
        
        default_config = {
            "mode": SessionMode.BROWSER,
            "profile_id": settings.default_profile_id,
            "headed": not settings.headless,
            "persist_profile": settings.persist_profiles,
            "viewport": settings.default_viewport,
            "user_agent": settings.user_agents[0],
            "stealth": settings.enable_stealth,
            "stealth_strategy": settings.stealth_strategy,
            "block_resources": settings.block_resources,
            "timeout": settings.default_timeout,
            "java_script_enabled": True,
            "ignore_https_errors": True,
            "browser_type": "chromium",
            "locale": settings.default_locale,
            "timezone_id": settings.default_timezone_id
        }
        
        if user_config:
            default_config.update(user_config)
        
        return SessionConfig(**default_config)

    async def _create_browser_context(self, config: SessionConfig, session_id: str) -> BrowserContext:
        """Create a browser context using a persistent headed profile by default."""
        if self._enum_value(config.mode) == SessionMode.FETCH_ONLY.value:
            raise ConfigurationError("session_mode", "fetch_only sessions do not create browser contexts yet")

        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage"
        ]

        context_options = {
            "headless": not config.headed,
            "viewport": config.viewport,
            "user_agent": config.user_agent,
            "java_script_enabled": config.java_script_enabled,
            "ignore_https_errors": config.ignore_https_errors,
            "locale": config.locale,
            "timezone_id": config.timezone_id,
            "args": launch_args
        }

        if config.persist_profile:
            profile_id = self._safe_profile_id(config.profile_id)
            profile_dir = Path(settings.profiles_dir)
            if not profile_dir.is_absolute():
                profile_dir = Path(__file__).parent.parent / profile_dir
            user_data_dir = profile_dir / profile_id
            user_data_dir.mkdir(parents=True, exist_ok=True)
            return await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                **context_options
            )

        if self.browser is None:
            self.browser = await self.playwright.chromium.launch(
                headless=not config.headed,
                args=launch_args
            )
        return await self.browser.new_context(
            viewport=config.viewport,
            user_agent=config.user_agent,
            java_script_enabled=config.java_script_enabled,
            ignore_https_errors=config.ignore_https_errors,
            locale=config.locale,
            timezone_id=config.timezone_id
        )

    async def _setup_minimal_profile(self, page: Page) -> None:
        """Apply only low-risk automation cleanup without broad fingerprint spoofing."""
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
        """)

    def _safe_profile_id(self, profile_id: str) -> str:
        """Return a filesystem-safe profile id."""
        allowed = [c if c.isalnum() or c in ("-", "_") else "_" for c in profile_id]
        safe = "".join(allowed).strip("_")
        return safe or "default"

    def _enum_value(self, value: Any) -> str:
        """Return enum value or string value for Pydantic v1/v2 compatibility."""
        return value.value if hasattr(value, "value") else str(value)
    
    async def _handle_route(self, route, blocked_resources: Optional[List[str]] = None) -> None:
        """Handle resource blocking"""
        resource_type = route.request.resource_type
        
        if resource_type in (blocked_resources or []):
            await route.abort()
        else:
            await route.continue_()
    
    async def _cleanup_loop(self) -> None:
        """Background task to cleanup expired sessions"""
        while True:
            try:
                await asyncio.sleep(settings.session_cleanup_interval)
                
                current_time = time.time()
                expired_sessions = []
                
                async with self.session_lock:
                    for session_id, session in self.active_sessions.items():
                        if current_time - session.context.created_at.timestamp() > settings.session_ttl:
                            expired_sessions.append(session_id)
                
                # Close expired sessions
                for session_id in expired_sessions:
                    try:
                        await self._close_session_internal(session_id)
                        logger.info("Expired session cleaned up", session_id=session_id)
                    except Exception as e:
                        logger.error("Error cleaning up expired session", session_id=session_id, error=str(e))
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in cleanup loop", error=str(e))
                await asyncio.sleep(60)  # Wait before retrying
    
    @property
    def active_session_count(self) -> int:
        """Get number of active sessions"""
        return len(self.active_sessions)
    
    @property
    def uptime(self) -> float:
        """Get service uptime in seconds"""
        return time.time() - self.start_time
