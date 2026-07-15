"""Health check controller for Surf Browser Service"""
import psutil
import time
from typing import Dict, Any
from fastapi import APIRouter, Depends, Response, status
import structlog

from core.foundation import (
    get_finance_service,
    get_session_service_if_initialized,
    require_full_access,
)
from models.schemas import HealthResponse
from services.finance_service import FinanceService
from services.searxng_runtime import ensure_searxng, probe_searxng
from config.settings import get_settings

logger = structlog.get_logger()
router = APIRouter()
settings = get_settings()

# Track service start time
_start_time = time.time()


def _process_memory_tree() -> Dict[str, Any]:
    try:
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
            "available": True,
            "pid": process.pid,
            "rss": process_memory.rss,
            "vms": process_memory.vms,
            "child_count": child_count,
            "child_rss": child_rss,
            "tree_rss": process_memory.rss + child_rss,
            "num_threads": process.num_threads(),
            "create_time": process.create_time(),
        }
    except (OSError, psutil.Error):
        return {
            "available": False,
            "pid": None,
            "rss": None,
            "vms": None,
            "child_count": None,
            "child_rss": None,
            "tree_rss": None,
            "num_threads": None,
            "create_time": None,
        }


@router.get("/", response_model=HealthResponse)
async def health_check(
    response: Response,
    _user: Dict[str, Any] = Depends(require_full_access),
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
        
        # Get service uptime
        uptime = time.time() - _start_time
        
        session_service = get_session_service_if_initialized()
        active_sessions = session_service.active_session_count if session_service else 0
        
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
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
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
    response: Response,
    _user: Dict[str, Any] = Depends(require_full_access),
):
    """Readiness check for load balancers"""
    
    try:
        session_service = get_session_service_if_initialized()
        active_sessions = session_service.active_session_count if session_service else 0
        if active_sessions >= settings.max_sessions:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready", "reason": "Maximum sessions reached"}
        
        return {
            "status": "ready",
            "active_sessions": active_sessions,
            "max_sessions": settings.max_sessions,
            "browser_runtime": (
                session_service.browser_runtime_state()
                if session_service
                else {"status": "not_started"}
            ),
        }
        
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
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
    response: Response,
    _user: Dict[str, Any] = Depends(require_full_access),
):
    """Get detailed service metrics for monitoring"""
    
    try:
        # System metrics
        memory_info = psutil.virtual_memory()
        cpu_usage = psutil.cpu_percent(interval=None)
        disk_usage = psutil.disk_usage('/')
        
        # Service metrics
        uptime = time.time() - _start_time
        session_service = get_session_service_if_initialized()
        active_sessions = session_service.active_session_count if session_service else 0
        
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
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"success": False, "error": str(e)}


@router.get("/searxng")
async def searxng_health(
    response: Response,
    _user: Dict[str, Any] = Depends(require_full_access),
):
    """Probe SearXNG reachability without mutating runtime state."""
    probe = await probe_searxng()
    result = {"status": "ready" if probe.get("reachable") else "down", "probe": probe}
    if result["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"success": result.get("status") == "ready", **result}


@router.post("/searxng/autowake")
async def searxng_autowake(
    response: Response,
    _user: Dict[str, Any] = Depends(require_full_access),
):
    """Explicitly start the configured SearXNG runtime when autowake is enabled."""
    result = await ensure_searxng()
    if result.get("status") != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"success": result.get("status") == "ready", **result}


@router.get("/finance")
async def finance_ladder_probe(
    response: Response,
    _user: Dict[str, Any] = Depends(require_full_access),
    finance_service: FinanceService = Depends(get_finance_service),
):
    """Probe all finance ladders on one known symbol per market.

    Intended for nightly monitoring — each rung gets a real HTTP request.
    Do not call on hot paths.
    """
    probes = [
        ("consensus", "RELIANCE", "IN"),
        ("consensus", "AAPL", "US"),
        ("insider", "RELIANCE", "IN"),
        ("corp_actions", "RELIANCE", "IN"),
        ("macro", "IN", "IN"),
        ("erp", "IN", "IN"),
        ("snapshot_us", "AAPL", "US"),
    ]
    results = []
    for endpoint, symbol, market in probes:
        try:
            probe = await finance_service.probe_ladder(endpoint, symbol, market)
            results.append(probe)
        except Exception as exc:
            results.append({"endpoint": endpoint, "symbol": symbol, "market": market,
                            "error": str(exc)})
    all_ok = len(results) == len(probes) and all(
        "rungs" in probe
        and all(rung.get("status") in ("ok", "skipped") for rung in probe["rungs"])
        for probe in results
    )
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"success": all_ok, "healthy": all_ok, "probes": results}


@router.get("/runtime")
async def runtime_check(
    response: Response,
    _user: Dict[str, Any] = Depends(require_full_access),
):
    """Cheap runtime state for agents and local supervisors."""
    try:
        session_service = get_session_service_if_initialized()
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
                "active": session_service.active_session_count if session_service else 0,
            },
            "browser_runtime": (
                session_service.browser_runtime_state()
                if session_service
                else {"status": "not_started"}
            ),
            "process": _process_memory_tree(),
        }
    except Exception as e:
        logger.error("Runtime check failed", error=str(e))
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"success": False, "error": str(e)}
