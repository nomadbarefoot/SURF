"""Enhanced configuration management for Surf Browser Service"""
import os
from typing import List, Dict, Any, Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Centralized configuration with environment variable support"""
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", env="SURF_HOST")
    port: int = Field(default=8000, env="SURF_PORT")
    debug: bool = Field(default=False, env="SURF_DEBUG")
    log_level: str = Field(default="INFO", env="SURF_LOG_LEVEL")
    
    # Security Configuration
    secret_key: str = Field(default="your-secret-key-change-this", env="SURF_SECRET_KEY")
    access_token_expire_minutes: int = Field(default=30, env="SURF_ACCESS_TOKEN_EXPIRE_MINUTES")
    algorithm: str = Field(default="HS256", env="SURF_ALGORITHM")
    
    # Rate Limiting
    rate_limit_requests: int = Field(default=100, env="SURF_RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(default=60, env="SURF_RATE_LIMIT_WINDOW")  # seconds
    
    # Session Management
    max_sessions: int = Field(default=20, env="SURF_MAX_SESSIONS")
    session_ttl: int = Field(default=300, env="SURF_SESSION_TTL")  # 5 minutes
    session_cleanup_interval: int = Field(default=60, env="SURF_SESSION_CLEANUP_INTERVAL")  # seconds
    
    # Browser Configuration
    headless: bool = Field(default=True, env="SURF_HEADLESS")
    default_timeout: int = Field(default=30000, env="SURF_DEFAULT_TIMEOUT")  # 30 seconds
    max_page_load_timeout: int = Field(default=60000, env="SURF_MAX_PAGE_LOAD_TIMEOUT")  # 60 seconds
    
    # Performance & Stealth
    enable_stealth: bool = Field(default=True, env="SURF_ENABLE_STEALTH")
    block_resources: List[str] = Field(default=["image", "font", "stylesheet"], env="SURF_BLOCK_RESOURCES")
    default_viewport: Dict[str, int] = Field(default={"width": 1920, "height": 1080})
    
    # User Agents Pool
    user_agents: List[str] = Field(default=[
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15"
    ])
    
    # Caching Configuration
    enable_cache: bool = Field(default=True, env="SURF_ENABLE_CACHE")
    cache_ttl: int = Field(default=300, env="SURF_CACHE_TTL")  # 5 minutes
    redis_url: Optional[str] = Field(default=None, env="SURF_REDIS_URL")
    
    # Request Limits
    max_request_size: int = Field(default=10485760, env="SURF_MAX_REQUEST_SIZE")  # 10MB
    max_url_length: int = Field(default=2048, env="SURF_MAX_URL_LENGTH")
    
    # Monitoring
    enable_metrics: bool = Field(default=True, env="SURF_ENABLE_METRICS")
    metrics_port: int = Field(default=9090, env="SURF_METRICS_PORT")
    
    # CORS Configuration
    cors_origins: List[str] = Field(default=["*"], env="SURF_CORS_ORIGINS")
    cors_methods: List[str] = Field(default=["GET", "POST", "PUT", "DELETE"], env="SURF_CORS_METHODS")
    cors_headers: List[str] = Field(default=["*"], env="SURF_CORS_HEADERS")
    
    # Enhanced Features Configuration
    enable_adaptive_rate_limiting: bool = Field(default=True, env="SURF_ENABLE_ADAPTIVE_RATE_LIMITING")
    enable_site_memory: bool = Field(default=True, env="SURF_ENABLE_SITE_MEMORY")
    enable_semantic_chunking: bool = Field(default=True, env="SURF_ENABLE_SEMANTIC_CHUNKING")
    enable_content_deduplication: bool = Field(default=True, env="SURF_ENABLE_CONTENT_DEDUPLICATION")
    enable_enhanced_mouse_movement: bool = Field(default=True, env="SURF_ENABLE_ENHANCED_MOUSE_MOVEMENT")
    
    # Site Memory Configuration
    site_memory_ttl: int = Field(default=86400, env="SURF_SITE_MEMORY_TTL")  # 24 hours
    
    # Adaptive Rate Limiting Configuration
    adaptive_rate_base_delay: float = Field(default=2.0, env="SURF_ADAPTIVE_RATE_BASE_DELAY")
    adaptive_rate_min_delay: float = Field(default=0.5, env="SURF_ADAPTIVE_RATE_MIN_DELAY")
    adaptive_rate_max_delay: float = Field(default=10.0, env="SURF_ADAPTIVE_RATE_MAX_DELAY")
    adaptive_rate_success_increment: float = Field(default=0.1, env="SURF_ADAPTIVE_RATE_SUCCESS_INCREMENT")
    adaptive_rate_failure_decrement: float = Field(default=0.2, env="SURF_ADAPTIVE_RATE_FAILURE_DECREMENT")
    
    # Content Processing Configuration
    content_deduplication_ttl: int = Field(default=3600, env="SURF_CONTENT_DEDUPLICATION_TTL")  # 1 hour
    semantic_chunking_confidence_threshold: float = Field(default=0.7, env="SURF_SEMANTIC_CHUNKING_CONFIDENCE_THRESHOLD")
    
    # Mouse Movement Configuration
    mouse_movement_bezier_points: int = Field(default=20, env="SURF_MOUSE_MOVEMENT_BEZIER_POINTS")
    mouse_movement_min_delay: float = Field(default=0.01, env="SURF_MOUSE_MOVEMENT_MIN_DELAY")
    mouse_movement_max_delay: float = Field(default=0.03, env="SURF_MOUSE_MOVEMENT_MAX_DELAY")
    mouse_movement_reaction_delay_min: float = Field(default=0.1, env="SURF_MOUSE_MOVEMENT_REACTION_DELAY_MIN")
    mouse_movement_reaction_delay_max: float = Field(default=0.3, env="SURF_MOUSE_MOVEMENT_REACTION_DELAY_MAX")
    
    @validator("log_level")
    def validate_log_level(cls, v: str) -> str:
        """Validate log level"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()
    
    @validator("block_resources", pre=True)
    def parse_block_resources(cls, v: Any) -> List[str]:
        """Parse block resources from string or list"""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",")]
        return v
    
    @validator("cors_origins", pre=True)
    def parse_cors_origins(cls, v: Any) -> List[str]:
        """Parse CORS origins from string or list"""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",")]
        return v
    
    @validator("cors_methods", pre=True)
    def parse_cors_methods(cls, v: Any) -> List[str]:
        """Parse CORS methods from string or list"""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",")]
        return v
    
    @validator("cors_headers", pre=True)
    def parse_cors_headers(cls, v: Any) -> List[str]:
        """Parse CORS headers from string or list"""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",")]
        return v
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Global settings instance
settings = get_settings()
