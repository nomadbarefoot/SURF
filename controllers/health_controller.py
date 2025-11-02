"""Health check controller for Surf Browser Service"""
import psutil
import time
from typing import Dict, Any
from fastapi import APIRouter, Depends
import structlog

from core.foundation import get_session_service
from models.schemas import HealthResponse
from services.session_service import SessionService

logger = structlog.get_logger()
router = APIRouter()

# Track service start time
_start_time = time.time()


@router.get("/", response_model=HealthResponse)
async def health_check(
    session_service: SessionService = Depends(get_session_service)
):
    """Service health check with detailed metrics"""
    
    try:
        # Get memory usage
        memory_info = psutil.virtual_memory()
        memory_usage = {
            "total": memory_info.total,
            "available": memory_info.available,
            "used": memory_info.used,
            "percentage": memory_info.percent
        }
        
        # Get CPU usage
        cpu_usage = psutil.cpu_percent(interval=1)
        
        # Get service uptime
        uptime = time.time() - _start_time
        
        # Get session statistics
        active_sessions = session_service.active_session_count
        
        return HealthResponse(
            success=True,
            status="healthy",
            version="1.0.0",
            uptime=uptime,
            active_sessions=active_sessions,
            max_sessions=session_service.session_limits.max_sessions,
            memory_usage=memory_usage,
            cpu_usage=cpu_usage
        )
        
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return HealthResponse(
            success=False,
            status="unhealthy",
            version="1.0.0",
            uptime=time.time() - _start_time,
            active_sessions=0,
            max_sessions=0
        )


@router.get("/ready")
async def readiness_check(
    session_service: SessionService = Depends(get_session_service)
):
    """Readiness check for load balancers"""
    
    try:
        # Check if service is ready to accept requests
        if session_service.browser is None:
            return {"status": "not_ready", "reason": "Browser not initialized"}
        
        if session_service.active_session_count >= session_service.session_limits.max_sessions:
            return {"status": "not_ready", "reason": "Maximum sessions reached"}
        
        return {"status": "ready"}
        
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        return {"status": "not_ready", "reason": str(e)}


@router.get("/live")
async def liveness_check():
    """Liveness check for container orchestration"""
    
    try:
        # Simple check to see if the service is alive
        return {"status": "alive", "timestamp": time.time()}
        
    except Exception as e:
        logger.error("Liveness check failed", error=str(e))
        return {"status": "dead", "error": str(e)}


@router.get("/metrics")
async def get_metrics(
    session_service: SessionService = Depends(get_session_service)
):
    """Get detailed service metrics for monitoring"""
    
    try:
        # System metrics
        memory_info = psutil.virtual_memory()
        cpu_usage = psutil.cpu_percent(interval=1)
        disk_usage = psutil.disk_usage('/')
        
        # Service metrics
        uptime = time.time() - _start_time
        active_sessions = session_service.active_session_count
        
        # Process metrics
        process = psutil.Process()
        process_memory = process.memory_info()
        
        metrics = {
            "system": {
                "memory": {
                    "total": memory_info.total,
                    "available": memory_info.available,
                    "used": memory_info.used,
                    "percentage": memory_info.percent
                },
                "cpu": {
                    "usage_percent": cpu_usage,
                    "count": psutil.cpu_count()
                },
                "disk": {
                    "total": disk_usage.total,
                    "used": disk_usage.used,
                    "free": disk_usage.free,
                    "percentage": (disk_usage.used / disk_usage.total) * 100
                }
            },
            "service": {
                "uptime_seconds": uptime,
                "active_sessions": active_sessions,
                "max_sessions": session_service.session_limits.max_sessions,
                "session_utilization": (active_sessions / session_service.session_limits.max_sessions) * 100
            },
            "process": {
                "memory_rss": process_memory.rss,
                "memory_vms": process_memory.vms,
                "cpu_percent": process.cpu_percent(),
                "num_threads": process.num_threads(),
                "create_time": process.create_time()
            }
        }
        
        return {"success": True, "metrics": metrics}
        
    except Exception as e:
        logger.error("Failed to get metrics", error=str(e))
        return {"success": False, "error": str(e)}
