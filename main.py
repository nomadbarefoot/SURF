"""Main FastAPI application for Surf Browser Service"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from config.settings import get_settings
from core.foundation import (
    LoggingMiddleware,
    SecurityMiddleware,
    RateLimitMiddleware,
    ErrorHandlingMiddleware,
    RequestIDMiddleware,
    cleanup_services
)
from controllers import browser_controller, session_controller, health_controller, auth_controller
from utils.logging import configure_logging

# Configure logging
settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting Surf Browser Service", version="1.0.0")
    yield
    # Shutdown
    logger.info("Shutting down Surf Browser Service")
    await cleanup_services()


# Create FastAPI application
app = FastAPI(
    title="Surf Browser Service",
    version="1.0.0",
    description="Headless browser automation service for VoidOS MCP",
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
    requests_per_minute=settings.rate_limit_requests
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
app.include_router(auth_controller.router, prefix="/auth", tags=["Authentication"])
app.include_router(session_controller.router, prefix="/sessions", tags=["Sessions"])
app.include_router(browser_controller.router, prefix="/browser", tags=["Browser Operations"])
app.include_router(health_controller.router, prefix="/health", tags=["Health"])

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


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.debug
    )
