"""Enhanced configuration management for Surf Browser Service"""

from typing import List, Dict, Any, Optional
from ipaddress import ip_address
from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Centralized configuration with environment variable support"""

    model_config = SettingsConfigDict(
        env_prefix="SURF_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    # Server Configuration
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=17777)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # Security Configuration
    secret_key: str = Field(default="your-secret-key-change-this")
    access_token_expire_minutes: int = Field(default=30)
    algorithm: str = Field(default="HS256")
    api_token: Optional[str] = Field(default=None)
    auth_mode: str = Field(default="loopback")

    # Rate Limiting
    rate_limit_requests: int = Field(default=100)
    rate_limit_window: int = Field(default=60)  # seconds

    # Session Management
    max_sessions: int = Field(default=3)
    max_headed_sessions: int = Field(default=1)
    session_ttl: int = Field(default=7200)
    idle_timeout_seconds: int = Field(default=600)
    hard_ttl_seconds: int = Field(default=7200)
    session_cleanup_interval: int = Field(default=30)
    browser_idle_timeout_seconds: int = Field(default=60)

    # Browser Configuration
    headless: bool = Field(default=True)
    default_silent: bool = Field(default=True)
    default_timeout: int = Field(default=30000)  # 30 seconds
    max_page_load_timeout: int = Field(default=60000)  # 60 seconds
    profiles_dir: str = Field(default="data/profiles")
    default_profile_id: str = Field(default="default")
    persist_profiles: bool = Field(default=True)
    downloads_dir: str = Field(default="data/downloads")
    screenshots_dir: str = Field(default="data/screenshots")
    export_roots: List[str] = Field(default=[])
    max_download_size_bytes: int = Field(default=104857600)
    download_retention_seconds: int = Field(default=86400)

    # Search Configuration
    search_provider: str = Field(default="exa")
    search_fallback_provider: str = Field(default="searxng")

    # Exa Configuration
    exa_api_key: Optional[str] = Field(default=None)
    exa_base_url: str = Field(default="https://api.exa.ai")
    exa_timeout: int = Field(default=30)
    # Exa search mode is hardcoded to "auto" in search_providers.py; not configurable.
    exa_num_results: int = Field(default=10)
    exa_contents_highlights: bool = Field(default=True)
    exa_contents_text: bool = Field(default=False)
    exa_contents_summary: bool = Field(default=False)
    exa_fallback_enabled: bool = Field(default=True)

    # SearXNG Configuration
    searxng_base_url: str = Field(default="http://localhost:8888")
    searxng_engines: List[str] = Field(default=[])
    searxng_timeout: int = Field(default=10)
    searxng_autowake_enabled: bool = Field(default=True)
    searxng_container_name: str = Field(default="searxng")
    searxng_docker_image: str = Field(default="docker.io/searxng/searxng:latest")
    searxng_config_dir: str = Field(default="~/searxng/config")
    searxng_host_port: int = Field(default=8888)
    searxng_health_timeout: float = Field(default=3.0)
    searxng_autowake_wait_seconds: int = Field(default=30)
    searxng_autowake_settle_seconds: float = Field(default=1.5)
    searxng_autowake_cmd_timeout: int = Field(default=60)
    searxng_autowake_cooldown_seconds: int = Field(default=60)
    search_max_results: int = Field(default=20)
    max_search_sessions: int = Field(default=5)
    search_extract_timeout: int = Field(default=60)
    search_extract_timeout_headed: int = Field(default=180)
    search_nav_timeout_headless: int = Field(default=20000)
    search_nav_timeout_headed: int = Field(default=60000)
    search_challenge_wait_headless: int = Field(default=12000)
    search_challenge_wait_headed: int = Field(default=45000)
    search_headed_relevance_threshold: float = Field(default=0.7)
    search_relevance_threshold: float = Field(default=0.5)
    search_below_threshold_results: int = Field(default=3)
    max_search_headed_sessions: int = Field(default=1)
    search_headed_max_attempts: int = Field(default=2)
    search_challenge_click_attempts: int = Field(default=2)
    search_min_content_chars: int = Field(default=200)
    search_refine_embed_enabled: bool = Field(default=True)
    search_refine_embed_threshold: float = Field(default=0.32)
    search_refine_min_block_chars: int = Field(default=40)
    embedding_base_url: str = Field(default="http://127.0.0.1:4000/v1")
    embedding_api_key: Optional[str] = Field(default=None)
    embedding_model: str = Field(default="embedding")
    embedding_timeout: float = Field(default=15.0)

    # Performance & Stealth
    enable_stealth: bool = Field(default=False)
    stealth_strategy: str = Field(default="minimal")
    block_resources: List[str] = Field(default=[])
    block_mode: str = Field(default="conservative")
    content_mode: str = Field(default="compact")
    adblock_enabled: bool = Field(default=True)
    adblock_filter_urls: List[str] = Field(
        default=[
            "https://easylist.to/easylist/easylist.txt",
            "https://easylist.to/easylist/easyprivacy.txt",
        ]
    )
    adblock_cache_dir: str = Field(default="data/filterlists")
    adblock_cache_ttl_seconds: int = Field(default=86400)
    default_viewport: Dict[str, int] = Field(default={"width": 1920, "height": 1080})
    default_locale: str = Field(default="en-US")
    default_timezone_id: str = Field(default="Asia/Kolkata")

    # User Agents Pool
    user_agents: List[str] = Field(
        default=[
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        ]
    )

    # Caching Configuration
    enable_cache: bool = Field(default=True)
    cache_ttl: int = Field(default=300)  # 5 minutes
    redis_url: Optional[str] = Field(default=None)

    # Request Limits
    max_request_size: int = Field(default=10485760)  # 10MB
    max_url_length: int = Field(default=2048)
    max_response_size: int = Field(default=52428800)  # 50MB
    max_json_parse_size: int = Field(default=1048576)  # 1MB

    # Outbound Network Policy
    outbound_allow_private_networks: bool = Field(default=False)
    outbound_allowed_hosts: List[str] = Field(default=[])
    outbound_dns_timeout_seconds: float = Field(default=3.0)
    outbound_dns_cache_ttl_seconds: float = Field(default=30.0)
    outbound_max_redirects: int = Field(default=5)

    # Monitoring
    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=9090)

    # CORS Configuration
    cors_origins: List[str] = Field(
        default=[
            "http://127.0.0.1",
            "http://localhost",
            "http://127.0.0.1:17777",
            "http://localhost:17777",
        ]
    )
    cors_methods: List[str] = Field(default=["GET", "POST", "PUT", "DELETE"])
    cors_headers: List[str] = Field(default=["*"])

    # Enhanced Features Configuration
    enable_adaptive_rate_limiting: bool = Field(default=True)
    enable_site_memory: bool = Field(default=False)
    enable_semantic_chunking: bool = Field(default=True)
    enable_content_deduplication: bool = Field(default=True)
    enable_enhanced_mouse_movement: bool = Field(default=True)
    policy_mode: str = Field(default="permissive")
    per_domain_delay_seconds: float = Field(default=2.0)

    # Site Memory Configuration
    site_memory_ttl: int = Field(default=86400)  # 24 hours

    # Adaptive Rate Limiting Configuration
    adaptive_rate_base_delay: float = Field(default=2.0)
    adaptive_rate_min_delay: float = Field(default=0.5)
    adaptive_rate_max_delay: float = Field(default=10.0)
    adaptive_rate_success_increment: float = Field(default=0.1)
    adaptive_rate_failure_decrement: float = Field(default=0.2)

    # Content Processing Configuration
    content_deduplication_ttl: int = Field(default=3600)  # 1 hour
    semantic_chunking_confidence_threshold: float = Field(default=0.7)

    # Mouse Movement Configuration
    mouse_movement_bezier_points: int = Field(default=20)
    mouse_movement_min_delay: float = Field(default=0.01)
    mouse_movement_max_delay: float = Field(default=0.03)
    mouse_movement_reaction_delay_min: float = Field(default=0.1)
    mouse_movement_reaction_delay_max: float = Field(default=0.3)

    @validator("log_level")
    def validate_log_level(cls, v: str) -> str:
        """Validate log level"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()

    @validator("auth_mode")
    def validate_auth_mode(cls, v: str) -> str:
        value = v.lower()
        if value not in {"loopback", "token"}:
            raise ValueError("auth_mode must be 'loopback' or 'token'")
        return value

    def is_loopback_host(self) -> bool:
        """Return True when SURF is bound only to a local loopback host."""
        host = self.host.lower()
        if host in {"localhost"}:
            return True
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False

    def validate_runtime_security(self) -> None:
        """Refuse unsafe local-browser control exposure."""
        if self.auth_mode == "token" and not self.api_token:
            raise ValueError("SURF_AUTH_MODE=token requires SURF_API_TOKEN")
        if self.auth_mode == "loopback" and not self.is_loopback_host():
            raise ValueError(
                "SURF_AUTH_MODE=loopback is only allowed on loopback hosts"
            )

    @validator("block_resources", pre=True)
    def parse_block_resources(cls, v: Any) -> List[str]:
        """Parse block resources from string or list"""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @validator("adblock_filter_urls", pre=True)
    def parse_adblock_filter_urls(cls, v: Any) -> List[str]:
        """Parse adblock filter URLs from string or list"""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
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

    @validator("outbound_allowed_hosts", pre=True)
    def parse_outbound_allowed_hosts(cls, v: Any) -> List[str]:
        """Parse exact or wildcard host exceptions from a comma-separated value."""
        if isinstance(v, str):
            return [item.strip().lower().rstrip(".") for item in v.split(",") if item.strip()]
        return v

    @validator("export_roots", pre=True)
    def parse_export_roots(cls, v: Any) -> List[str]:
        """Parse explicitly writable artifact roots from a comma-separated value."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Global settings instance
settings = get_settings()

# Route prefixes accessible without a bearer token when auth_mode == "loopback".
# Mirrors the MCP-level FREE_TIER_TOOLS gate for the HTTP layer.
FREE_TIER_ROUTES: frozenset = frozenset({"/search/", "/fetch/", "/health/"})
