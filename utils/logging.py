"""Logging configuration for Surf Browser Service"""
import logging
import sys
from typing import Optional
import structlog
from structlog.stdlib import LoggerFactory


def configure_logging(level: str = "INFO") -> None:
    """Configure structured logging with JSON output"""
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(message)s",
        stream=sys.stdout
    )
    
    # Set specific logger levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)


def get_logger(name: Optional[str] = None) -> structlog.BoundLogger:
    """Get a structured logger instance"""
    return structlog.get_logger(name)


class RequestLogger:
    """Request-specific logger for tracking operations"""
    
    def __init__(self, request_id: str, session_id: Optional[str] = None):
        self.request_id = request_id
        self.session_id = session_id
        self.logger = get_logger("request")
    
    def info(self, message: str, **kwargs) -> None:
        """Log info message with request context"""
        self.logger.info(
            message,
            request_id=self.request_id,
            session_id=self.session_id,
            **kwargs
        )
    
    def error(self, message: str, **kwargs) -> None:
        """Log error message with request context"""
        self.logger.error(
            message,
            request_id=self.request_id,
            session_id=self.session_id,
            **kwargs
        )
    
    def warning(self, message: str, **kwargs) -> None:
        """Log warning message with request context"""
        self.logger.warning(
            message,
            request_id=self.request_id,
            session_id=self.session_id,
            **kwargs
        )
    
    def debug(self, message: str, **kwargs) -> None:
        """Log debug message with request context"""
        self.logger.debug(
            message,
            request_id=self.request_id,
            session_id=self.session_id,
            **kwargs
        )
