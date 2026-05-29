"""Health check controller for Surf Browser Service"""
import psutil
import time
from typing import Dict, Any
from fastapi import APIRouter, Depends
import structlog

from core.foundation import get_session_service
from models.schemas import HealthResponse
from services.session_service import SessionService
from config.settings import get_settings

logger = structlog.get_logger()
router = APIRouter()
settings = get_settings()

# Track service start time
_start_time = time.time()


def _process_memory_tree() -> Dict[str, Any]:
    process = psutil.Process()
    children = process.children(recursive=True)
    process_memory = process.memory_info()
    child_rss = 0
    child_count = 0
    for child in children:
        try:
            child_rss += child.memory_info().rss
            child_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {
        "pid": process.pid,
        "rss": process_memory.rss,
        "vms": process_memory.vms,
        "child_count": child_count,
        "child_rss": child_rss,
        "tree_rss": process_memory.rss + child_rss,
        "num_threads": process.num_threads(),
        "create_time": process.create_time(),
    }


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
            max_sessions=settings.max_sessions,
            memory_usage=memory_usage
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
        if session_service.active_session_count >= settings.max_sessions:
            return {"status": "not_ready", "reason": "Maximum sessions reached"}
        
        return {
            "status": "ready",
            "active_sessions": session_service.active_session_count,
            "max_sessions": settings.max_sessions,
            "browser_runtime": session_service.browser_runtime_state(),
        }
        
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
        
        process_memory = _process_memory_tree()
        
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
                "max_sessions": settings.max_sessions,
                "session_utilization": (active_sessions / settings.max_sessions) * 100 if settings.max_sessions > 0 else 0
            },
            "process": {
                "memory_rss": process_memory["rss"],
                "memory_vms": process_memory["vms"],
                "child_count": process_memory["child_count"],
                "child_memory_rss": process_memory["child_rss"],
                "tree_memory_rss": process_memory["tree_rss"],
                "cpu_percent": psutil.Process().cpu_percent(),
                "num_threads": process_memory["num_threads"],
                "create_time": process_memory["create_time"]
            }
        }
        
        return {"success": True, "metrics": metrics}
        
    except Exception as e:
        logger.error("Failed to get metrics", error=str(e))
        return {"success": False, "error": str(e)}


@router.get("/runtime")
async def runtime_check(
    session_service: SessionService = Depends(get_session_service)
):
    """Cheap runtime state for agents and local supervisors."""
    try:
        return {
            "success": True,
            "service": {
                "status": "running",
                "version": "1.0.0",
                "uptime_seconds": time.time() - _start_time,
            },
            "limits": {
                "max_sessions": settings.max_sessions,
                "max_headed_sessions": settings.max_headed_sessions,
                "session_idle_timeout_seconds": settings.idle_timeout_seconds,
                "browser_idle_timeout_seconds": settings.browser_idle_timeout_seconds,
            },
            "sessions": {
                "active": session_service.active_session_count,
            },
            "browser_runtime": session_service.browser_runtime_state(),
            "process": _process_memory_tree(),
        }
    except Exception as e:
        logger.error("Runtime check failed", error=str(e))
        return {"success": False, "error": str(e)}
