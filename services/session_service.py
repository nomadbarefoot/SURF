"""Enhanced session management service for Surf Browser Service"""
import asyncio
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import structlog

from config import get_settings
from core.foundation import (
    SessionNotFoundError,
    InvalidSessionError,
    ResourceLimitError,
    ConfigurationError,
    SessionBusyError,
    ProfileInUseError
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
        self.browser_started_at: Optional[float] = None
        self.browser_last_used_at: Optional[float] = None
        self.session_limits = SessionLimits()
        self.adblock_service = None
        self.operation_locks: Dict[str, asyncio.Lock] = {}
        self.profile_leases: Dict[str, str] = {}
        self.ephemeral_profile_dirs: Dict[str, Path] = {}
    
    async def initialize(self) -> None:
        """Initialize the lightweight session manager.

        Playwright is intentionally lazy. Keeping the API daemon resident should
        not keep the browser substrate in memory until a browser session is
        requested.
        """
        try:
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Session service initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize session service", error=str(e))
            raise ConfigurationError("browser_initialization", str(e))

    async def ensure_browser_runtime(self) -> None:
        """Start Playwright and browser-adjacent services on first browser use."""
        if self.playwright is not None:
            return

        try:
            self.playwright = await async_playwright().start()
            self.browser = None
            if settings.adblock_enabled:
                from services.adblock_service import AdblockService
                self.adblock_service = AdblockService()
                await self.adblock_service.initialize()
            self.browser_started_at = time.time()
            self.browser_last_used_at = self.browser_started_at
            logger.info("Browser runtime initialized")
        except Exception as e:
            self.playwright = None
            self.browser = None
            self.adblock_service = None
            logger.error("Failed to initialize browser runtime", error=str(e))
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
                    await self._close_session_internal(session_id, reason="shutdown", force=True)
            
            await self._shutdown_browser_runtime(reason="service_cleanup")
            
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
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            
            try:
                # Build session configuration
                config = self._build_session_config(user_config)
                if len(self.active_sessions) >= settings.max_sessions:
                    raise ResourceLimitError(
                        "sessions",
                        settings.max_sessions,
                        len(self.active_sessions)
                    )
                if config.headed and self._headed_session_count() >= settings.max_headed_sessions:
                    raise ResourceLimitError(
                        "headed_sessions",
                        settings.max_headed_sessions,
                        self._headed_session_count()
                    )
                profile_id = self._safe_profile_id(config.profile_id)
                if config.persist_profile and profile_id in self.profile_leases:
                    raise ProfileInUseError(profile_id)

                await self.ensure_browser_runtime()
                
                context = await self._create_browser_context(config, session_id)
                
                # Create browser context model
                now = datetime.now(timezone.utc)
                browser_context = BrowserContextModel(
                    context_id=str(id(context)),
                    page_id="",
                    status=SessionStatus.ACTIVE,
                    created_at=now,
                    last_activity=now,
                    expires_at=now + timedelta(seconds=settings.hard_ttl_seconds) if settings.hard_ttl_seconds else None
                )
                
                # Create session data
                session_data = SessionData(
                    session_id=session_id,
                    config=config,
                    context=browser_context,
                    metadata={
                        "user_id": user_id,
                        "created_by": "api",
                        "browser_type": config.browser_type,
                        "busy_operations": 0,
                        "blocker": self._new_blocker_stats(config)
                    },
                    stats=SessionStats()
                )
                
                session_data.context_obj = context

                if self._enum_value(config.block_mode) != "off" or config.block_resources:
                    await context.route("**/*", lambda route: self._handle_route(route, session_data))

                # Create page
                page = context.pages[0] if context.pages else await context.new_page()
                session_data.page = page
                session_data.context.page_id = str(id(page))

                stealth_strategy = self._enum_value(config.stealth_strategy)
                if stealth_strategy == StealthStrategy.LEGACY.value or config.stealth:
                    stealth_config = get_enhanced_stealth_config()
                    await setup_stealth_mode(page, stealth_config["device_info"])
                elif stealth_strategy == StealthStrategy.MINIMAL.value:
                    await self._setup_minimal_profile(page)

                self.operation_locks[session_id] = asyncio.Lock()
                if config.persist_profile:
                    self.profile_leases[profile_id] = session_id
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
    
    async def close_session(self, session_id: str, force: bool = False) -> None:
        """Close specific session and cleanup resources"""
        async with self.session_lock:
            await self._close_session_internal(session_id, force=force)
    
    async def _close_session_internal(self, session_id: str, reason: str = "closed", force: bool = False) -> None:
        """Internal method to close session without lock"""
        if session_id not in self.active_sessions:
            raise SessionNotFoundError(session_id)
        
        session = self.active_sessions[session_id]
        if session.metadata.get("busy_operations", 0) > 0 and not force:
            raise SessionBusyError(session_id, "close")
        session.context.close_reason = reason
        
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
            self.operation_locks.pop(session_id, None)
            self._release_profile_lease(session)
            self._cleanup_ephemeral_profile(session_id)
            if not self.active_sessions:
                self.browser_last_used_at = time.time()
            
            logger.info("Session closed", session_id=session_id, reason=reason)
            
        except Exception as e:
            logger.error("Error closing session", session_id=session_id, error=str(e))
            # Still remove from active sessions even if close fails
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]
            self.operation_locks.pop(session_id, None)
            self._release_profile_lease(session)
            self._cleanup_ephemeral_profile(session_id)
            if not self.active_sessions:
                self.browser_last_used_at = time.time()
    
    async def get_session(self, session_id: str, touch: bool = True) -> SessionData:
        """Get session by ID with activity tracking and validation"""
        
        if session_id not in self.active_sessions:
            raise SessionNotFoundError(session_id)
        
        session = self.active_sessions[session_id]
        
        now = datetime.now(timezone.utc)
        if self._hard_expired(session, now):
            await self._close_session_internal(session_id, "hard_ttl_expired")
            raise InvalidSessionError(session_id, "Session hard TTL expired")
        
        # Check session limits
        violations = self.session_limits.check_limits(session.stats)
        if violations:
            await self._close_session_internal(session_id)
            raise InvalidSessionError(session_id, f"Session limits exceeded: {', '.join(violations)}")
        
        # Update last activity
        if touch:
            session.context.last_activity = now
            session.context.status = SessionStatus.ACTIVE
        
        return session

    @asynccontextmanager
    async def session_operation(self, session_id: str, operation: str):
        """Mark a session busy for the duration of an operation."""
        lock = self.operation_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            session = await self.get_session(session_id)
            session.metadata["busy_operations"] = session.metadata.get("busy_operations", 0) + 1
            session.metadata["last_operation"] = operation
            try:
                yield session
            finally:
                if session_id in self.active_sessions:
                    current = self.active_sessions[session_id]
                    current.metadata["busy_operations"] = max(0, current.metadata.get("busy_operations", 0) - 1)
                    current.context.last_activity = datetime.now(timezone.utc)

    async def touch_session(self, session_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Explicit heartbeat for a session."""
        session = await self.get_session(session_id)
        session.metadata["last_touch_reason"] = reason
        return self._session_monitor_entry(session, time.time())

    async def monitor_sessions(self) -> Dict[str, Any]:
        """Return active session lifecycle state without extending idle timers."""
        now = time.time()
        entries = [self._session_monitor_entry(session, now) for session in self.active_sessions.values()]
        return {
            "active_sessions": len(entries),
            "idle_timeout_seconds": settings.idle_timeout_seconds,
            "hard_ttl_seconds": settings.hard_ttl_seconds,
            "browser_runtime": self.browser_runtime_state(now),
            "sessions": entries
        }

    async def reap_idle_sessions(self, dry_run: bool = False) -> Dict[str, Any]:
        """Close idle or hard-expired sessions."""
        now = time.time()
        candidates = []
        async with self.session_lock:
            for session_id, session in list(self.active_sessions.items()):
                reason = self._expiration_reason(session, now)
                if reason:
                    candidates.append({"session_id": session_id, "reason": reason})
            if not dry_run:
                for candidate in candidates:
                    try:
                        await self._close_session_internal(candidate["session_id"], candidate["reason"])
                    except SessionBusyError:
                        continue
        return {"dry_run": dry_run, "reaped": candidates, "count": len(candidates)}
    
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
            "uptime": time.time() - session.context.created_at.timestamp(),
            "monitor": self._session_monitor_entry(session, time.time())
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
                "idle_for_seconds": self._idle_for(session, time.time()),
                "busy_operations": session.metadata.get("busy_operations", 0),
                "url": session.context.url,
                "title": session.context.title,
                "blocker": session.metadata.get("blocker", {}),
                "last_navigation_blocker": session.metadata.get("last_navigation_blocker", {}),
                "stats": session.stats.dict()
            })
        
        return sessions
    
    def _build_session_config(self, user_config: Optional[Dict[str, Any]]) -> SessionConfig:
        """Build session configuration with smart defaults"""
        
        default_config = {
            "mode": SessionMode.BROWSER,
            "profile_id": settings.default_profile_id,
            "headed": not settings.default_silent,
            "silent": settings.default_silent,
            "background_headed": True,
            "persist_profile": settings.persist_profiles,
            "viewport": settings.default_viewport,
            "user_agent": None,
            "stealth": settings.enable_stealth,
            "stealth_strategy": settings.stealth_strategy,
            "block_resources": settings.block_resources,
            "block_mode": settings.block_mode,
            "content_mode": settings.content_mode,
            "timeout": settings.default_timeout,
            "java_script_enabled": True,
            "ignore_https_errors": True,
            "browser_type": "chromium",
            "locale": settings.default_locale,
            "timezone_id": settings.default_timezone_id
        }
        
        if user_config:
            default_config.update(user_config)

        if user_config and "silent" in user_config and "headed" not in user_config:
            default_config["headed"] = not bool(user_config["silent"])
        elif user_config and "headed" in user_config:
            default_config["silent"] = not bool(user_config["headed"])
        else:
            default_config["silent"] = not bool(default_config["headed"])
        
        return SessionConfig(**default_config)

    async def _create_browser_context(self, config: SessionConfig, session_id: str) -> BrowserContext:
        """Create a browser context using a persistent headed profile by default."""
        if self._enum_value(config.mode) == SessionMode.FETCH_ONLY.value:
            raise ConfigurationError("session_mode", "fetch_only sessions do not create browser contexts yet")

        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ]
        if config.headed and config.background_headed:
            width = config.viewport.get("width", 1920)
            height = config.viewport.get("height", 1080)
            launch_args.extend([
                "--window-position=-32000,-32000",
                f"--window-size={width},{height}",
            ])

        context_options = {
            "headless": not config.headed,
            "viewport": config.viewport,
            "java_script_enabled": config.java_script_enabled,
            "ignore_https_errors": config.ignore_https_errors,
            "locale": config.locale,
            "timezone_id": config.timezone_id,
            "accept_downloads": True,
            "args": launch_args
        }
        if config.user_agent:
            context_options["user_agent"] = config.user_agent

        if config.persist_profile or config.headed:
            profile_dir = self._profile_root()
            if config.persist_profile:
                user_data_dir = profile_dir / self._safe_profile_id(config.profile_id)
            else:
                user_data_dir = profile_dir / "_ephemeral" / session_id
                self.ephemeral_profile_dirs[session_id] = user_data_dir
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
        new_context_options = {
            "viewport": config.viewport,
            "java_script_enabled": config.java_script_enabled,
            "ignore_https_errors": config.ignore_https_errors,
            "locale": config.locale,
            "timezone_id": config.timezone_id,
            "accept_downloads": True
        }
        if config.user_agent:
            new_context_options["user_agent"] = config.user_agent
        return await self.browser.new_context(**new_context_options)

    def start_navigation_snapshot(self, session: SessionData) -> Dict[str, Any]:
        """Capture blocker counters before a page load."""
        blocker = session.metadata.get("blocker", {})
        snapshot = {
            "requests_seen": blocker.get("requests_seen", 0),
            "requests_blocked": blocker.get("requests_blocked", 0),
            "blocked_by_reason": dict(blocker.get("blocked_by_reason", {})),
            "blocked_by_resource_type": dict(blocker.get("blocked_by_resource_type", {})),
            "allowed_by_reason": dict(blocker.get("allowed_by_reason", {})),
        }
        session.metadata["navigation_blocker_start"] = snapshot
        return snapshot

    def finish_navigation_snapshot(self, session: SessionData) -> Dict[str, Any]:
        """Store per-navigation blocker deltas for observe/monitor responses."""
        start = session.metadata.get("navigation_blocker_start") or self.start_navigation_snapshot(session)
        blocker = session.metadata.get("blocker", {})
        delta = {
            "requests_seen": blocker.get("requests_seen", 0) - start.get("requests_seen", 0),
            "requests_blocked": blocker.get("requests_blocked", 0) - start.get("requests_blocked", 0),
            "blocked_by_reason": self._dict_delta(blocker.get("blocked_by_reason", {}), start.get("blocked_by_reason", {})),
            "blocked_by_resource_type": self._dict_delta(
                blocker.get("blocked_by_resource_type", {}),
                start.get("blocked_by_resource_type", {})
            ),
            "allowed_by_reason": self._dict_delta(blocker.get("allowed_by_reason", {}), start.get("allowed_by_reason", {})),
        }
        seen = delta["requests_seen"]
        delta["blocked_ratio"] = round(delta["requests_blocked"] / seen, 4) if seen else 0.0
        session.metadata["last_navigation_blocker"] = delta
        return delta

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

    def _profile_root(self) -> Path:
        profile_dir = Path(settings.profiles_dir)
        if not profile_dir.is_absolute():
            profile_dir = Path(__file__).parent.parent / profile_dir
        return profile_dir

    def _cleanup_ephemeral_profile(self, session_id: str) -> None:
        profile_dir = self.ephemeral_profile_dirs.pop(session_id, None)
        if not profile_dir:
            return
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception as e:
            logger.warning("Failed to clean ephemeral profile", session_id=session_id, path=str(profile_dir), error=str(e))

    def _enum_value(self, value: Any) -> str:
        """Return enum value or string value for Pydantic v1/v2 compatibility."""
        return value.value if hasattr(value, "value") else str(value)
    
    async def _handle_route(self, route, session: SessionData) -> None:
        """Handle resource and adblock routing for a session."""
        request = route.request
        resource_type = request.resource_type
        stats = session.metadata.setdefault("blocker", self._new_blocker_stats(session.config))
        stats["requests_seen"] += 1

        decision = {"blocked": False, "reason": "allowed"}
        if resource_type in (session.config.block_resources or []):
            decision = {"blocked": True, "reason": "resource_type", "filter": resource_type}
        elif self.adblock_service:
            source_url = self._route_source_url(route)
            decision = self.adblock_service.should_block(
                request.url,
                source_url,
                resource_type,
                self._enum_value(session.config.block_mode)
            )

        if decision.get("blocked"):
            stats["requests_blocked"] += 1
            stats["blocked_by_reason"][decision.get("reason", "unknown")] = (
                stats["blocked_by_reason"].get(decision.get("reason", "unknown"), 0) + 1
            )
            stats["blocked_by_resource_type"][resource_type] = (
                stats["blocked_by_resource_type"].get(resource_type, 0) + 1
            )
            if len(stats["blocked_samples"]) < 20:
                stats["blocked_samples"].append({
                    "url": request.url,
                    "resource_type": resource_type,
                    "reason": decision.get("reason"),
                    "filter": decision.get("filter")
                })
            await route.abort()
        else:
            stats["allowed_by_reason"][decision.get("reason", "allowed")] = (
                stats["allowed_by_reason"].get(decision.get("reason", "allowed"), 0) + 1
            )
            await route.continue_()

    def _route_source_url(self, route) -> str:
        try:
            if route.request.frame:
                return route.request.frame.url
        except Exception:
            pass
        return route.request.headers.get("referer", route.request.url)

    def _new_blocker_stats(self, config: SessionConfig) -> Dict[str, Any]:
        engine = self.adblock_service.stats() if self.adblock_service else {"available": False}
        return {
            "mode": self._enum_value(config.block_mode),
            "engine": engine,
            "requests_seen": 0,
            "requests_blocked": 0,
            "blocked_by_reason": {},
            "blocked_by_resource_type": {},
            "allowed_by_reason": {},
            "blocked_samples": []
        }

    def _dict_delta(self, current: Dict[str, int], start: Dict[str, int]) -> Dict[str, int]:
        keys = set(current) | set(start)
        return {
            key: current.get(key, 0) - start.get(key, 0)
            for key in keys
            if current.get(key, 0) - start.get(key, 0)
        }

    def _release_profile_lease(self, session: SessionData) -> None:
        if not session.config.persist_profile:
            return
        profile_id = self._safe_profile_id(session.config.profile_id)
        if self.profile_leases.get(profile_id) == session.session_id:
            self.profile_leases.pop(profile_id, None)
    
    async def _cleanup_loop(self) -> None:
        """Background task to cleanup expired sessions"""
        while True:
            try:
                await asyncio.sleep(settings.session_cleanup_interval)
                
                result = await self.reap_idle_sessions(dry_run=False)
                for item in result["reaped"]:
                    logger.info("Expired session cleaned up", session_id=item["session_id"], reason=item["reason"])
                await self.reap_browser_runtime()
                
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

    @property
    def browser_runtime_loaded(self) -> bool:
        return self.playwright is not None

    def browser_runtime_state(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = now or time.time()
        idle_for = None
        if self.browser_last_used_at is not None:
            idle_for = max(0.0, now - self.browser_last_used_at)
        return {
            "loaded": self.browser_runtime_loaded,
            "started_at": self.browser_started_at,
            "idle_for_seconds": idle_for,
            "idle_timeout_seconds": settings.browser_idle_timeout_seconds,
            "active_sessions": len(self.active_sessions),
            "auto_teardown_enabled": settings.browser_idle_timeout_seconds > 0,
        }

    async def reap_browser_runtime(self, force: bool = False) -> Dict[str, Any]:
        """Stop Playwright/Chromium when no sessions are active."""
        async with self.session_lock:
            if not self.playwright:
                return {"stopped": False, "reason": "not_loaded"}
            if self.active_sessions:
                return {"stopped": False, "reason": "active_sessions"}
            if not force:
                timeout = settings.browser_idle_timeout_seconds
                if timeout <= 0:
                    return {"stopped": False, "reason": "disabled"}
                idle_for = time.time() - (self.browser_last_used_at or self.browser_started_at or time.time())
                if idle_for < timeout:
                    return {"stopped": False, "reason": "not_idle", "idle_for_seconds": idle_for}
            await self._shutdown_browser_runtime(reason="idle_timeout" if not force else "forced")
            return {"stopped": True, "reason": "forced" if force else "idle_timeout"}

    def _expiration_reason(self, session: SessionData, now: float) -> Optional[str]:
        if session.metadata.get("busy_operations", 0) > 0:
            return None
        if settings.hard_ttl_seconds and now - session.context.created_at.timestamp() > settings.hard_ttl_seconds:
            return "hard_ttl_expired"
        if settings.idle_timeout_seconds and self._idle_for(session, now) > settings.idle_timeout_seconds:
            return "idle_timeout"
        return None

    def _hard_expired(self, session: SessionData, now: datetime) -> bool:
        return bool(session.context.expires_at and now > session.context.expires_at)

    def _idle_for(self, session: SessionData, now: float) -> float:
        return max(0.0, now - session.context.last_activity.timestamp())

    def _session_monitor_entry(self, session: SessionData, now: float) -> Dict[str, Any]:
        idle_for = self._idle_for(session, now)
        busy = session.metadata.get("busy_operations", 0)
        status = SessionStatus.ACTIVE.value if busy else (
            SessionStatus.IDLE.value if idle_for >= settings.idle_timeout_seconds else SessionStatus.ACTIVE.value
        )
        return {
            "session_id": session.session_id,
            "status": status,
            "created_at": session.context.created_at,
            "last_activity": session.context.last_activity,
            "expires_at": session.context.expires_at,
            "idle_for_seconds": idle_for,
            "busy_operations": busy,
            "url": session.context.url,
            "title": session.context.title,
            "blocker": session.metadata.get("blocker", {})
        }

    def _headed_session_count(self) -> int:
        return sum(1 for session in self.active_sessions.values() if session.config.headed)

    async def _shutdown_browser_runtime(self, reason: str) -> None:
        """Close shared browser resources and stop the Playwright driver."""
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                logger.debug("Browser already closed during runtime shutdown", error=str(e))
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as e:
                logger.debug("Playwright already stopped during runtime shutdown", error=str(e))
        self.browser = None
        self.playwright = None
        self.adblock_service = None
        self.browser_started_at = None
        self.browser_last_used_at = None
        logger.info("Browser runtime stopped", reason=reason)
