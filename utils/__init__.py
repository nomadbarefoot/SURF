"""Utility functions for Surf Browser Service"""

from .logging import configure_logging, get_logger
from .validators import validate_url, validate_session_id, sanitize_input
from .helpers import (
    get_random_user_agent,
    random_delay,
    safe_click_with_retry,
    wait_for_network_idle,
    calculate_file_size,
    format_duration
)
from .stealth import setup_stealth_mode, enhance_stealth_mode, simulate_human_behavior
from .anti_detection import (
    SmartWaiter, CAPTCHADetector, HumanMimicry, 
    get_enhanced_stealth_config, user_agent_pool
)
from .proxy_manager import initialize_proxies, get_proxy_for_request
from .content_processor import ContentProcessor, ContentMetrics

__all__ = [
    "configure_logging",
    "get_logger",
    "validate_url",
    "validate_session_id", 
    "sanitize_input",
    "get_random_user_agent",
    "random_delay",
    "safe_click_with_retry",
    "wait_for_network_idle",
    "calculate_file_size",
    "format_duration",
    "setup_stealth_mode",
    "enhance_stealth_mode",
    "simulate_human_behavior",
    "SmartWaiter",
    "CAPTCHADetector", 
    "HumanMimicry",
    "get_enhanced_stealth_config",
    "user_agent_pool",
    "initialize_proxies",
    "get_proxy_for_request",
    "ContentProcessor",
    "ContentMetrics"
]
