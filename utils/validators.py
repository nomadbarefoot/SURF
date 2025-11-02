"""Input validation utilities for Surf Browser Service"""
import re
from typing import Optional, List, Any
from urllib.parse import urlparse
import structlog

from config import get_settings

logger = structlog.get_logger()
settings = get_settings()


def validate_url(url: str) -> bool:
    """Validate URL format and length"""
    if not url or len(url) > settings.max_url_length:
        return False
    
    try:
        parsed = urlparse(url)
        return all([parsed.scheme, parsed.netloc])
    except Exception:
        return False


def validate_session_id(session_id: str) -> bool:
    """Validate session ID format"""
    if not session_id:
        return False
    
    # Session ID should start with "sess_" followed by 8 hex characters
    pattern = r'^sess_[a-f0-9]{8}$'
    return bool(re.match(pattern, session_id))


def sanitize_input(input_str: str, max_length: int = 1000) -> str:
    """Sanitize user input"""
    if not input_str:
        return ""
    
    # Remove potentially dangerous characters
    sanitized = input_str.strip()[:max_length]
    
    # Remove null bytes and control characters
    sanitized = ''.join(char for char in sanitized if ord(char) >= 32 or char in '\t\n\r')
    
    return sanitized


def validate_selector(selector: str) -> bool:
    """Validate CSS selector format"""
    if not selector or len(selector) > 1000:
        return False
    
    # Basic CSS selector validation
    # Allow common CSS selectors
    pattern = r'^[a-zA-Z0-9\s\.#:\[\]="\'()_-]+$'
    return bool(re.match(pattern, selector))


def validate_extract_type(extract_type: str) -> bool:
    """Validate content extraction type"""
    valid_types = ["text", "html", "table", "links", "images"]
    return extract_type in valid_types


def validate_action_type(action: str) -> bool:
    """Validate interaction action type"""
    valid_actions = ["click", "type", "select", "scroll", "hover", "double_click", "right_click"]
    return action in valid_actions


def validate_wait_until(wait_until: str) -> bool:
    """Validate navigation wait condition"""
    valid_conditions = ["load", "domcontentloaded", "networkidle", "commit"]
    return wait_until in valid_conditions


def validate_timeout(timeout: Optional[int]) -> bool:
    """Validate timeout value"""
    if timeout is None:
        return True
    
    return 1000 <= timeout <= 300000  # 1 second to 5 minutes


def validate_viewport(viewport: Optional[dict]) -> bool:
    """Validate viewport dimensions"""
    if viewport is None:
        return True
    
    if not isinstance(viewport, dict):
        return False
    
    if "width" not in viewport or "height" not in viewport:
        return False
    
    width = viewport.get("width")
    height = viewport.get("height")
    
    if not isinstance(width, int) or not isinstance(height, int):
        return False
    
    return 100 <= width <= 4096 and 100 <= height <= 4096


def validate_user_agent(user_agent: str) -> bool:
    """Validate user agent string"""
    if not user_agent or len(user_agent) > 500:
        return False
    
    # Basic validation - should contain common browser identifiers
    browser_indicators = ["Mozilla", "Chrome", "Safari", "Firefox", "Edge"]
    return any(indicator in user_agent for indicator in browser_indicators)


def validate_file_path(file_path: str) -> bool:
    """Validate file path for screenshots"""
    if not file_path or len(file_path) > 500:
        return False
    
    # Check for invalid characters
    invalid_chars = '<>:"/\\|?*'
    return not any(char in file_path for char in invalid_chars)


def validate_quality(quality: Optional[int]) -> bool:
    """Validate JPEG quality value"""
    if quality is None:
        return True
    
    return 1 <= quality <= 100


def validate_scopes(scopes: List[str]) -> bool:
    """Validate API key scopes"""
    if not isinstance(scopes, list):
        return False
    
    valid_scopes = [
        "browser:read",
        "browser:write", 
        "sessions:read",
        "sessions:write",
        "sessions:manage",
        "admin:all"
    ]
    
    return all(scope in valid_scopes for scope in scopes)


def validate_username(username: str) -> bool:
    """Validate username format"""
    if not username or len(username) < 3 or len(username) > 50:
        return False
    
    # Username should be alphanumeric
    pattern = r'^[a-zA-Z0-9_]+$'
    return bool(re.match(pattern, username))


def validate_password(password: str) -> bool:
    """Validate password strength"""
    if not password or len(password) < 8 or len(password) > 100:
        return False
    
    # Password should contain at least one letter and one number
    has_letter = bool(re.search(r'[a-zA-Z]', password))
    has_number = bool(re.search(r'\d', password))
    
    return has_letter and has_number


def validate_api_key_name(name: str) -> bool:
    """Validate API key name"""
    if not name or len(name) < 3 or len(name) > 50:
        return False
    
    # Name should be alphanumeric with spaces and hyphens
    pattern = r'^[a-zA-Z0-9\s\-_]+$'
    return bool(re.match(pattern, name))


def validate_batch_operations(operations: List[dict]) -> bool:
    """Validate batch operations list"""
    if not isinstance(operations, list):
        return False
    
    if len(operations) == 0 or len(operations) > 10:
        return False
    
    for operation in operations:
        if not isinstance(operation, dict):
            return False
        
        if "type" not in operation:
            return False
        
        op_type = operation["type"]
        if op_type not in ["navigate", "extract", "interact", "screenshot"]:
            return False
    
    return True


def validate_config_dict(config: Optional[dict]) -> bool:
    """Validate session configuration dictionary"""
    if config is None:
        return True
    
    if not isinstance(config, dict):
        return False
    
    # Check for valid configuration keys
    valid_keys = {
        "viewport", "user_agent", "stealth", "block_resources", 
        "timeout", "java_script_enabled", "ignore_https_errors", "browser_type"
    }
    
    return all(key in valid_keys for key in config.keys())


def validate_resource_types(resource_types: List[str]) -> bool:
    """Validate resource types for blocking"""
    if not isinstance(resource_types, list):
        return False
    
    valid_types = ["image", "font", "stylesheet", "script", "media", "other"]
    return all(resource_type in valid_types for resource_type in resource_types)


def validate_boolean(value: Any) -> bool:
    """Validate boolean value"""
    return isinstance(value, bool)


def validate_integer(value: Any, min_val: int = None, max_val: int = None) -> bool:
    """Validate integer value with optional min/max"""
    if not isinstance(value, int):
        return False
    
    if min_val is not None and value < min_val:
        return False
    
    if max_val is not None and value > max_val:
        return False
    
    return True


def validate_string(value: Any, min_length: int = 0, max_length: int = None) -> bool:
    """Validate string value with optional length constraints"""
    if not isinstance(value, str):
        return False
    
    if len(value) < min_length:
        return False
    
    if max_length is not None and len(value) > max_length:
        return False
    
    return True
