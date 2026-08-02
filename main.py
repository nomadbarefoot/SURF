"""Main FastAPI application for Surf Browser Service"""
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.routing import Route
import structlog

from config.settings import get_settings
from core.foundation import (
    LoggingMiddleware,
    SecurityMiddleware,
    RequestSizeLimitMiddleware,
    RateLimitMiddleware,
    ErrorHandlingMiddleware,
    RequestIDMiddleware,
    cleanup_services
)
from controllers import browser_controller, session_controller, health_controller, fetch_controller, download_controller, artifact_controller, search_controller, finance_controller, youtube_controller, browse_controller
from utils.logging import configure_logging
from surfctl import PROFILE_TOOLS, build_mcp_server

# Configure logging
settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger()


class ProfileMCPEndpoint:
    """Dispatch to the MCP server instance created for this app lifespan."""

    def __init__(self, profile: str):
        self.profile = profile

    async def __call__(self, scope, receive, send):
        endpoint = scope["app"].state.mcp_endpoints[self.profile]
        await endpoint(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    settings.validate_runtime_security()
    loop = asyncio.get_running_loop()
    previous_exception_handler = loop.get_exception_handler()

    def handle_loop_exception(loop, context):
        exception = context.get("exception")
        message = str(exception or context.get("message", ""))
        if (
            "Connection closed while reading from the driver" in message
            or "Target page, context or browser has been closed" in message
            or "handler is closed" in message
        ):
            logger.debug("Suppressed closed Playwright transport during shutdown", error=message)
            return
        if previous_exception_handler:
            previous_exception_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handle_loop_exception)
    logger.info("Starting Surf Browser Service", version="1.0.0")
    try:
        async with AsyncExitStack() as stack:
            servers = {
                profile: build_mcp_server(profile, embedded=True)
                for profile in PROFILE_TOOLS
            }
            endpoints = {}
            for profile, server in servers.items():
                mcp_app = server.streamable_http_app()
                endpoints[profile] = next(
                    route.endpoint
                    for route in mcp_app.routes
                    if isinstance(route, Route)
                )
                await stack.enter_async_context(server.session_manager.run())
            app.state.mcp_servers = servers
            app.state.mcp_endpoints = endpoints
            yield
    finally:
        # Shutdown
        logger.info("Shutting down Surf Browser Service")
        await cleanup_services()


# Create FastAPI application
app = FastAPI(
    title="Surf Browser Service",
    version="1.0.0",
    description="Local browser substrate for agents and one-off scripts",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan
)

# Add middleware
app.add_middleware(RequestIDMiddleware)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_window=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window,
)
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_body_size=settings.max_request_size,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
    expose_headers=["X-Request-ID", "X-Response-Time"]
)

# Include routers
app.include_router(session_controller.router, prefix="/sessions", tags=["Sessions"])
app.include_router(browser_controller.router, prefix="/browser", tags=["Browser Operations"])
app.include_router(fetch_controller.router, prefix="/fetch", tags=["HTTP Fetch"])
app.include_router(download_controller.router, prefix="/downloads", tags=["Downloads"])
app.include_router(artifact_controller.router, prefix="/artifacts", tags=["Artifacts"])
app.include_router(health_controller.router, prefix="/health", tags=["Health"])
app.include_router(search_controller.router, prefix="/search", tags=["Search"])
app.include_router(youtube_controller.router, prefix="/youtube", tags=["YouTube"])
app.include_router(finance_controller.router, prefix="/finance", tags=["Finance"])
app.include_router(browse_controller.router, prefix="/browse", tags=["Browse"])

# Profile-scoped Streamable HTTP MCP. The outer FastAPI middleware owns
# authentication; each lifespan gets fresh, restartable MCP session managers.
for profile in PROFILE_TOOLS:
    app.router.routes.append(
        Route(f"/mcp/{profile}", endpoint=ProfileMCPEndpoint(profile))
    )

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": "Surf Browser Service",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs" if settings.debug else "disabled"
    }


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors"""
    logger.error(
        "Unhandled exception",
        error=str(exc),
        error_type=type(exc).__name__,
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


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.debug
    )
