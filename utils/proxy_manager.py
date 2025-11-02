"""
Proxy Manager for Surf Browser Service
Handles proxy configuration and initialization
"""

import yaml
import os
from typing import List, Dict, Any, Optional
from .anti_detection import initialize_proxy_rotator, proxy_rotator
import structlog

logger = structlog.get_logger()

def load_proxy_config(config_path: str = "config/proxy_config.yaml") -> Dict[str, Any]:
    """Load proxy configuration from YAML file"""
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                logger.info("Proxy configuration loaded", config_path=config_path)
                return config
        else:
            logger.warning("Proxy config file not found, using defaults", config_path=config_path)
            return get_default_proxy_config()
    except Exception as e:
        logger.error("Failed to load proxy config", error=str(e), config_path=config_path)
        return get_default_proxy_config()

def get_default_proxy_config() -> Dict[str, Any]:
    """Get default proxy configuration"""
    return {
        "proxies": [],
        "rotation": {
            "max_failures": 3,
            "reset_interval": 3600,
            "success_weight": 0.7,
            "recency_weight": 0.3
        },
        "captcha": {
            "detection_enabled": True,
            "backoff_min": 300,
            "backoff_max": 600,
            "screenshot_on_detection": True
        },
        "human_behavior": {
            "min_delay": 0.5,
            "max_delay": 2.0,
            "scroll_pauses": 3,
            "mouse_movements": True,
            "typing_speed": 0.1
        },
        "smart_waiting": {
            "content_load_timeout": 30000,
            "dynamic_content_timeout": 10000,
            "image_load_threshold": 0.8,
            "network_idle_timeout": 5000
        }
    }

def initialize_proxies(config_path: str = "config/proxy_config.yaml") -> bool:
    """Initialize proxy rotator with configuration"""
    try:
        config = load_proxy_config(config_path)
        proxies = config.get("proxies", [])
        
        if proxies:
            initialize_proxy_rotator(proxies)
            logger.info("Proxy rotator initialized", proxy_count=len(proxies))
            return True
        else:
            logger.info("No proxies configured, running without proxy rotation")
            return False
    except Exception as e:
        logger.error("Failed to initialize proxies", error=str(e))
        return False

def get_proxy_for_request() -> Optional[Dict[str, Any]]:
    """Get proxy for current request"""
    if proxy_rotator:
        proxy = proxy_rotator.get_next_proxy()
        if proxy:
            return {
                "server": proxy.url,
                "username": proxy.username,
                "password": proxy.password
            }
    return None

def mark_proxy_success(proxy_index: int):
    """Mark proxy as successful"""
    if proxy_rotator:
        proxy_rotator.mark_success(proxy_index)

def mark_proxy_failure(proxy_index: int):
    """Mark proxy as failed"""
    if proxy_rotator:
        proxy_rotator.mark_failure(proxy_index)

def get_proxy_stats() -> Dict[str, Any]:
    """Get proxy statistics"""
    if proxy_rotator:
        return {
            "total_proxies": len(proxy_rotator.proxies),
            "active_proxies": len(proxy_rotator.proxies) - len(proxy_rotator.failed_proxies),
            "failed_proxies": len(proxy_rotator.failed_proxies),
            "proxy_stats": proxy_rotator.proxy_stats
        }
    return {"total_proxies": 0, "active_proxies": 0, "failed_proxies": 0}
