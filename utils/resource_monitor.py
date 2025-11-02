"""
Basic Resource Monitoring System
Monitors system resources and session metrics for optimization
"""

import psutil
import time
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import structlog

logger = structlog.get_logger()

@dataclass
class SystemMetrics:
    """System resource metrics"""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_available_gb: float
    disk_usage_percent: float
    active_sessions: int
    max_sessions: int

@dataclass
class SessionMetrics:
    """Individual session metrics"""
    session_id: str
    memory_usage_mb: float
    cpu_usage_percent: float
    last_activity: float
    request_count: int
    success_count: int
    failure_count: int
    avg_response_time: float

class ResourceMonitor:
    """Basic resource monitoring for SURF system"""
    
    def __init__(self):
        self.session_metrics: Dict[str, SessionMetrics] = {}
        self.system_metrics_history: list = []
        self.max_history_size = 1000
        self.monitoring_active = False
        self.monitor_task: Optional[asyncio.Task] = None
    
    def start_monitoring(self, interval: int = 30) -> None:
        """Start background resource monitoring"""
        if self.monitoring_active:
            logger.warning("Resource monitoring already active")
            return
        
        self.monitoring_active = True
        self.monitor_task = asyncio.create_task(self._monitor_loop(interval))
        logger.info("Resource monitoring started", interval=interval)
    
    def stop_monitoring(self) -> None:
        """Stop background resource monitoring"""
        if not self.monitoring_active:
            return
        
        self.monitoring_active = False
        if self.monitor_task:
            self.monitor_task.cancel()
        logger.info("Resource monitoring stopped")
    
    async def _monitor_loop(self, interval: int) -> None:
        """Background monitoring loop"""
        while self.monitoring_active:
            try:
                await self._collect_metrics()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Resource monitoring error", error=str(e))
                await asyncio.sleep(interval)
    
    async def _collect_metrics(self) -> None:
        """Collect current system and session metrics"""
        try:
            # System metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            system_metrics = SystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_available_gb=memory.available / (1024**3),
                disk_usage_percent=disk.percent,
                active_sessions=len(self.session_metrics),
                max_sessions=self._calculate_max_sessions()
            )
            
            # Store metrics
            self.system_metrics_history.append(system_metrics)
            if len(self.system_metrics_history) > self.max_history_size:
                self.system_metrics_history.pop(0)
            
            # Log critical metrics
            if cpu_percent > 80 or memory.percent > 80:
                logger.warning("High resource usage detected", 
                             cpu_percent=cpu_percent, 
                             memory_percent=memory.percent)
            
        except Exception as e:
            logger.error("Failed to collect system metrics", error=str(e))
    
    def _calculate_max_sessions(self) -> int:
        """Calculate maximum sessions based on system resources"""
        try:
            available_ram = psutil.virtual_memory().available / (1024**3)  # GB
            cpu_count = psutil.cpu_count()
            
            # Conservative calculation: 2 sessions per GB RAM, max 20
            max_sessions = max(5, min(20, int(available_ram * 2)))
            return max_sessions
        except Exception:
            return 10  # Default fallback
    
    def update_session_metrics(self, session_id: str, 
                             memory_usage_mb: float = 0,
                             cpu_usage_percent: float = 0,
                             success: bool = True,
                             response_time: float = 0) -> None:
        """Update metrics for a specific session"""
        try:
            if session_id not in self.session_metrics:
                self.session_metrics[session_id] = SessionMetrics(
                    session_id=session_id,
                    memory_usage_mb=memory_usage_mb,
                    cpu_usage_percent=cpu_usage_percent,
                    last_activity=time.time(),
                    request_count=0,
                    success_count=0,
                    failure_count=0,
                    avg_response_time=0
                )
            
            metrics = self.session_metrics[session_id]
            metrics.last_activity = time.time()
            metrics.request_count += 1
            metrics.memory_usage_mb = memory_usage_mb
            metrics.cpu_usage_percent = cpu_usage_percent
            
            if success:
                metrics.success_count += 1
            else:
                metrics.failure_count += 1
            
            # Update average response time
            if response_time > 0:
                if metrics.avg_response_time == 0:
                    metrics.avg_response_time = response_time
                else:
                    # Exponential moving average
                    metrics.avg_response_time = (metrics.avg_response_time * 0.9) + (response_time * 0.1)
            
        except Exception as e:
            logger.error("Failed to update session metrics", 
                        session_id=session_id, error=str(e))
    
    def get_session_metrics(self, session_id: str) -> Optional[SessionMetrics]:
        """Get metrics for a specific session"""
        return self.session_metrics.get(session_id)
    
    def get_system_metrics(self) -> Optional[SystemMetrics]:
        """Get latest system metrics"""
        if not self.system_metrics_history:
            return None
        return self.system_metrics_history[-1]
    
    def get_system_summary(self) -> Dict[str, Any]:
        """Get system summary for monitoring"""
        try:
            current_metrics = self.get_system_metrics()
            if not current_metrics:
                return {"error": "No metrics available"}
            
            # Calculate success rates
            total_requests = sum(m.request_count for m in self.session_metrics.values())
            total_successes = sum(m.success_count for m in self.session_metrics.values())
            success_rate = (total_successes / total_requests) if total_requests > 0 else 0
            
            # Find top resource-consuming sessions
            top_sessions = sorted(
                self.session_metrics.values(),
                key=lambda x: x.memory_usage_mb,
                reverse=True
            )[:5]
            
            return {
                "timestamp": datetime.now().isoformat(),
                "system": {
                    "cpu_percent": current_metrics.cpu_percent,
                    "memory_percent": current_metrics.memory_percent,
                    "memory_available_gb": current_metrics.memory_available_gb,
                    "active_sessions": current_metrics.active_sessions,
                    "max_sessions": current_metrics.max_sessions
                },
                "performance": {
                    "total_requests": total_requests,
                    "success_rate": success_rate,
                    "avg_response_time": sum(m.avg_response_time for m in self.session_metrics.values()) / len(self.session_metrics) if self.session_metrics else 0
                },
                "top_sessions": [
                    {
                        "session_id": s.session_id,
                        "memory_mb": s.memory_usage_mb,
                        "cpu_percent": s.cpu_usage_percent,
                        "success_rate": s.success_count / s.request_count if s.request_count > 0 else 0
                    }
                    for s in top_sessions
                ]
            }
        except Exception as e:
            logger.error("Failed to generate system summary", error=str(e))
            return {"error": str(e)}
    
    def cleanup_old_sessions(self, max_idle_time: int = 300) -> int:
        """Clean up sessions that have been idle too long"""
        current_time = time.time()
        cleaned_count = 0
        
        sessions_to_remove = []
        for session_id, metrics in self.session_metrics.items():
            if current_time - metrics.last_activity > max_idle_time:
                sessions_to_remove.append(session_id)
        
        for session_id in sessions_to_remove:
            del self.session_metrics[session_id]
            cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info("Cleaned up idle sessions", count=cleaned_count)
        
        return cleaned_count

# Global instance
resource_monitor = ResourceMonitor()
