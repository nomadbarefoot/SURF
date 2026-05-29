"""Security configuration and utilities for Surf Browser Service"""
import secrets
import hashlib

from .settings import get_settings

settings = get_settings()


class SecurityConfig:
    """Security configuration and utilities"""
    
    @staticmethod
    def generate_secret_key() -> str:
        """Generate a secure secret key"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def generate_api_key() -> str:
        """Generate a secure API key"""
        return f"surf_{secrets.token_urlsafe(24)}"
    
    @staticmethod
    def hash_api_key(api_key: str) -> str:
        """Hash an API key for storage"""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL format and length"""
        if not url or len(url) > settings.max_url_length:
            return False
        
        # Basic URL validation
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return all([parsed.scheme, parsed.netloc])
        except Exception:
            return False
    
    @staticmethod
    def sanitize_input(input_str: str, max_length: int = 1000) -> str:
        """Sanitize user input"""
        if not input_str:
            return ""
        
        # Remove potentially dangerous characters
        sanitized = input_str.strip()[:max_length]
        
        # Remove null bytes and control characters
        sanitized = ''.join(char for char in sanitized if ord(char) >= 32 or char in '\t\n\r')
        
        return sanitized
