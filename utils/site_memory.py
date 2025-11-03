"""
Site Memory System
Persists session data, cookies, site-specific patterns, and extraction strategies
Uses SQLite for local storage with migration support
"""

import json
import sqlite3
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path
import structlog

logger = structlog.get_logger()

# Database schema version for migrations
DB_VERSION = 2

@dataclass
class SiteMemory:
    """Site memory data structure"""
    site_url: str
    session_data: Dict[str, Any]
    cookies: List[Dict[str, Any]]
    last_accessed: float
    access_count: int
    success_rate: float
    custom_data: Dict[str, Any]
    # Enhanced fields
    extraction_patterns: Optional[Dict[str, Any]] = None
    performance_metrics: Optional[Dict[str, Any]] = None
    timing_patterns: Optional[Dict[str, Any]] = None
    site_characteristics: Optional[Dict[str, Any]] = None
    anti_detection_rules: Optional[Dict[str, Any]] = None
    optimal_selectors: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Initialize optional fields with defaults"""
        if self.extraction_patterns is None:
            self.extraction_patterns = {}
        if self.performance_metrics is None:
            self.performance_metrics = {}
        if self.timing_patterns is None:
            self.timing_patterns = {}
        if self.site_characteristics is None:
            self.site_characteristics = {}
        if self.anti_detection_rules is None:
            self.anti_detection_rules = {}
        if self.optimal_selectors is None:
            self.optimal_selectors = {}


class SiteMemoryManager:
    """Manages site memory persistence and retrieval with SQLite storage"""
    
    def __init__(self, ttl: int = 86400):
        # Store database locally within surf module
        surf_dir = Path(__file__).parent.parent
        self.db_path = surf_dir / "data" / "site_memory.db"
        self.ttl = ttl
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        self._migrate_database()
    
    def _init_database(self) -> None:
        """Initialize the site memory database with enhanced schema"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Enable foreign keys and WAL mode for better concurrency
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA journal_mode = WAL")
                
                # Create main site_memory table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS site_memory (
                        site_url TEXT PRIMARY KEY,
                        session_data TEXT NOT NULL DEFAULT '{}',
                        cookies TEXT NOT NULL DEFAULT '[]',
                        last_accessed REAL NOT NULL DEFAULT 0,
                        access_count INTEGER NOT NULL DEFAULT 0,
                        success_rate REAL NOT NULL DEFAULT 0.0,
                        custom_data TEXT NOT NULL DEFAULT '{}',
                        extraction_patterns TEXT NOT NULL DEFAULT '{}',
                        performance_metrics TEXT NOT NULL DEFAULT '{}',
                        timing_patterns TEXT NOT NULL DEFAULT '{}',
                        site_characteristics TEXT NOT NULL DEFAULT '{}',
                        anti_detection_rules TEXT NOT NULL DEFAULT '{}',
                        optimal_selectors TEXT NOT NULL DEFAULT '{}',
                        created_at REAL NOT NULL DEFAULT 0,
                        updated_at REAL NOT NULL DEFAULT 0
                    )
                """)
                
                # Create indexes for common queries
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_site_memory_last_accessed 
                    ON site_memory(last_accessed)
                """)
                
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_site_memory_access_count 
                    ON site_memory(access_count)
                """)
                
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_site_memory_success_rate 
                    ON site_memory(success_rate)
                """)
                
                # Create schema version table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        migrated_at REAL NOT NULL DEFAULT 0
                    )
                """)
                
                conn.commit()
                logger.info("Site memory database initialized", db_path=str(self.db_path))
        except Exception as e:
            logger.error("Failed to initialize site memory database", error=str(e), exc_info=True)
            raise
    
    def _get_db_version(self) -> int:
        """Get current database schema version"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT MAX(version) FROM schema_version")
                row = cursor.fetchone()
                return row[0] if row and row[0] else 0
        except sqlite3.OperationalError:
            # Table doesn't exist yet
            return 0
        except Exception as e:
            logger.error("Failed to get database version", error=str(e))
            return 0
    
    def _migrate_database(self) -> None:
        """Migrate database schema to latest version"""
        current_version = self._get_db_version()
        
        if current_version >= DB_VERSION:
            return
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Migration from v0/v1 to v2: Add new columns if they don't exist
                if current_version < 2:
                    new_columns = [
                        ("extraction_patterns", "TEXT NOT NULL DEFAULT '{}'"),
                        ("performance_metrics", "TEXT NOT NULL DEFAULT '{}'"),
                        ("timing_patterns", "TEXT NOT NULL DEFAULT '{}'"),
                        ("site_characteristics", "TEXT NOT NULL DEFAULT '{}'"),
                        ("anti_detection_rules", "TEXT NOT NULL DEFAULT '{}'"),
                        ("optimal_selectors", "TEXT NOT NULL DEFAULT '{}'"),
                        ("updated_at", "REAL NOT NULL DEFAULT 0")
                    ]
                    
                    for column_name, column_def in new_columns:
                        try:
                            conn.execute(f"""
                                ALTER TABLE site_memory 
                                ADD COLUMN {column_name} {column_def}
                            """)
                            logger.debug(f"Added column {column_name} to site_memory table")
                        except sqlite3.OperationalError as e:
                            if "duplicate column name" not in str(e).lower():
                                raise
                            logger.debug(f"Column {column_name} already exists")
                    
                    # Update schema version
                    conn.execute("""
                        INSERT OR REPLACE INTO schema_version (version, migrated_at)
                        VALUES (?, ?)
                    """, (DB_VERSION, time.time()))
                    
                    conn.commit()
                    logger.info("Database migrated to version", version=DB_VERSION)
        except Exception as e:
            logger.error("Failed to migrate database", error=str(e), exc_info=True)
            # Don't raise - allow system to continue with existing schema
    
    def save_site_memory(self, site_memory: SiteMemory) -> bool:
        """Save site memory to database"""
        try:
            current_time = time.time()
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO site_memory 
                    (site_url, session_data, cookies, last_accessed, access_count, 
                     success_rate, custom_data, extraction_patterns, performance_metrics,
                     timing_patterns, site_characteristics, anti_detection_rules,
                     optimal_selectors, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 
                            COALESCE((SELECT created_at FROM site_memory WHERE site_url = ?), ?), ?)
                """, (
                    site_memory.site_url,
                    json.dumps(site_memory.session_data),
                    json.dumps(site_memory.cookies),
                    site_memory.last_accessed or current_time,
                    site_memory.access_count,
                    site_memory.success_rate,
                    json.dumps(site_memory.custom_data),
                    json.dumps(site_memory.extraction_patterns or {}),
                    json.dumps(site_memory.performance_metrics or {}),
                    json.dumps(site_memory.timing_patterns or {}),
                    json.dumps(site_memory.site_characteristics or {}),
                    json.dumps(site_memory.anti_detection_rules or {}),
                    json.dumps(site_memory.optimal_selectors or {}),
                    site_memory.site_url,  # For COALESCE in created_at
                    current_time,  # Default created_at
                    current_time   # updated_at
                ))
                conn.commit()
            logger.debug("Site memory saved", site_url=site_memory.site_url)
            return True
        except Exception as e:
            logger.error("Failed to save site memory", error=str(e), site_url=site_memory.site_url, exc_info=True)
            return False
    
    def get_site_memory(self, site_url: str) -> Optional[SiteMemory]:
        """Get site memory from database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT session_data, cookies, last_accessed, access_count, 
                           success_rate, custom_data, extraction_patterns,
                           performance_metrics, timing_patterns, site_characteristics,
                           anti_detection_rules, optimal_selectors
                    FROM site_memory 
                    WHERE site_url = ?
                """, (site_url,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                (session_data, cookies, last_accessed, access_count, success_rate,
                 custom_data, extraction_patterns, performance_metrics,
                 timing_patterns, site_characteristics, anti_detection_rules,
                 optimal_selectors) = row
                
                return SiteMemory(
                    site_url=site_url,
                    session_data=json.loads(session_data),
                    cookies=json.loads(cookies),
                    last_accessed=last_accessed,
                    access_count=access_count,
                    success_rate=success_rate,
                    custom_data=json.loads(custom_data),
                    extraction_patterns=json.loads(extraction_patterns) if extraction_patterns else {},
                    performance_metrics=json.loads(performance_metrics) if performance_metrics else {},
                    timing_patterns=json.loads(timing_patterns) if timing_patterns else {},
                    site_characteristics=json.loads(site_characteristics) if site_characteristics else {},
                    anti_detection_rules=json.loads(anti_detection_rules) if anti_detection_rules else {},
                    optimal_selectors=json.loads(optimal_selectors) if optimal_selectors else {}
                )
        except Exception as e:
            logger.error("Failed to get site memory", error=str(e), site_url=site_url, exc_info=True)
            return None
    
    def update_access_stats(self, site_url: str, success: bool, 
                           performance_data: Optional[Dict[str, Any]] = None) -> bool:
        """Update access statistics for a site"""
        try:
            site_memory = self.get_site_memory(site_url)
            if not site_memory:
                return False
            
            # Update statistics
            site_memory.access_count += 1
            site_memory.last_accessed = time.time()
            
            # Update success rate (exponential moving average)
            alpha = 0.1  # Smoothing factor
            if success:
                site_memory.success_rate = (1 - alpha) * site_memory.success_rate + alpha * 1.0
            else:
                site_memory.success_rate = (1 - alpha) * site_memory.success_rate + alpha * 0.0
            
            # Update performance metrics if provided
            if performance_data:
                if not site_memory.performance_metrics:
                    site_memory.performance_metrics = {}
                
                # Merge performance data
                for key, value in performance_data.items():
                    if key in ["load_time", "dom_ready_time", "response_time"]:
                        # Calculate running average for timing metrics
                        existing = site_memory.performance_metrics.get(key, [])
                        existing.append(value)
                        # Keep last 100 samples
                        if len(existing) > 100:
                            existing = existing[-100:]
                        site_memory.performance_metrics[key] = existing
                        site_memory.performance_metrics[f"{key}_avg"] = sum(existing) / len(existing)
                    else:
                        site_memory.performance_metrics[key] = value
            
            return self.save_site_memory(site_memory)
        except Exception as e:
            logger.error("Failed to update access stats", error=str(e), site_url=site_url, exc_info=True)
            return False
    
    def update_extraction_patterns(self, site_url: str, patterns: Dict[str, Any]) -> bool:
        """Update extraction patterns for a site"""
        try:
            site_memory = self.get_site_memory(site_url)
            if not site_memory:
                # Create new entry
                site_memory = SiteMemory(
                    site_url=site_url,
                    session_data={},
                    cookies=[],
                    last_accessed=time.time(),
                    access_count=0,
                    success_rate=0.0,
                    custom_data={}
                )
            
            # Merge patterns
            site_memory.extraction_patterns.update(patterns)
            return self.save_site_memory(site_memory)
        except Exception as e:
            logger.error("Failed to update extraction patterns", error=str(e), site_url=site_url, exc_info=True)
            return False
    
    def update_timing_patterns(self, site_url: str, timing_data: Dict[str, Any]) -> bool:
        """Update timing patterns for a site"""
        try:
            site_memory = self.get_site_memory(site_url)
            if not site_memory:
                site_memory = SiteMemory(
                    site_url=site_url,
                    session_data={},
                    cookies=[],
                    last_accessed=time.time(),
                    access_count=0,
                    success_rate=0.0,
                    custom_data={}
                )
            
            # Merge timing patterns
            site_memory.timing_patterns.update(timing_data)
            return self.save_site_memory(site_memory)
        except Exception as e:
            logger.error("Failed to update timing patterns", error=str(e), site_url=site_url, exc_info=True)
            return False
    
    def update_optimal_selectors(self, site_url: str, selectors: Dict[str, str]) -> bool:
        """Update optimal selectors for a site"""
        try:
            site_memory = self.get_site_memory(site_url)
            if not site_memory:
                site_memory = SiteMemory(
                    site_url=site_url,
                    session_data={},
                    cookies=[],
                    last_accessed=time.time(),
                    access_count=0,
                    success_rate=0.0,
                    custom_data={}
                )
            
            # Merge selectors (newer ones take precedence)
            site_memory.optimal_selectors.update(selectors)
            return self.save_site_memory(site_memory)
        except Exception as e:
            logger.error("Failed to update optimal selectors", error=str(e), site_url=site_url, exc_info=True)
            return False
    
    def update_site_characteristics(self, site_url: str, characteristics: Dict[str, Any]) -> bool:
        """Update site characteristics"""
        try:
            site_memory = self.get_site_memory(site_url)
            if not site_memory:
                site_memory = SiteMemory(
                    site_url=site_url,
                    session_data={},
                    cookies=[],
                    last_accessed=time.time(),
                    access_count=0,
                    success_rate=0.0,
                    custom_data={}
                )
            
            # Merge characteristics
            site_memory.site_characteristics.update(characteristics)
            return self.save_site_memory(site_memory)
        except Exception as e:
            logger.error("Failed to update site characteristics", error=str(e), site_url=site_url, exc_info=True)
            return False
    
    def cleanup_expired_memories(self) -> int:
        """Clean up expired site memories"""
        try:
            current_time = time.time()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM site_memory 
                    WHERE ? - last_accessed > ?
                """, (current_time, self.ttl))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
            if deleted_count > 0:
                logger.info("Cleaned up expired site memories", count=deleted_count)
            
            return deleted_count
        except Exception as e:
            logger.error("Failed to cleanup expired memories", error=str(e), exc_info=True)
            return 0
    
    def get_site_stats(self) -> Dict[str, Any]:
        """Get overall site memory statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total_sites,
                        AVG(success_rate) as avg_success_rate,
                        AVG(access_count) as avg_access_count,
                        MAX(last_accessed) as most_recent_access,
                        SUM(access_count) as total_accesses
                    FROM site_memory
                """)
                
                row = cursor.fetchone()
                if not row:
                    return {"total_sites": 0, "avg_success_rate": 0.0, "avg_access_count": 0.0, 
                           "most_recent_access": 0, "total_accesses": 0}
                
                total_sites, avg_success_rate, avg_access_count, most_recent_access, total_accesses = row
                
                return {
                    "total_sites": total_sites or 0,
                    "avg_success_rate": avg_success_rate or 0.0,
                    "avg_access_count": avg_access_count or 0.0,
                    "most_recent_access": most_recent_access or 0,
                    "total_accesses": total_accesses or 0,
                    "ttl": self.ttl
                }
        except Exception as e:
            logger.error("Failed to get site stats", error=str(e), exc_info=True)
            return {"error": str(e)}
    
    def get_top_sites(self, limit: int = 10, sort_by: str = "access_count") -> List[Dict[str, Any]]:
        """Get top sites by specified criteria"""
        valid_sort_fields = ["access_count", "success_rate", "last_accessed"]
        sort_field = sort_by if sort_by in valid_sort_fields else "access_count"
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(f"""
                    SELECT site_url, access_count, success_rate, last_accessed
                    FROM site_memory 
                    ORDER BY {sort_field} DESC 
                    LIMIT ?
                """, (limit,))
                
                rows = cursor.fetchall()
                return [
                    {
                        "site_url": row[0],
                        "access_count": row[1],
                        "success_rate": row[2],
                        "last_accessed": row[3]
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error("Failed to get top sites", error=str(e), exc_info=True)
            return []
    
    def search_sites_by_pattern(self, pattern_key: str, pattern_value: Any) -> List[str]:
        """Search for sites matching a specific extraction pattern"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT site_url, extraction_patterns
                    FROM site_memory
                """)
                
                matching_sites = []
                for row in cursor.fetchall():
                    site_url, patterns_json = row
                    if patterns_json:
                        patterns = json.loads(patterns_json)
                        if pattern_key in patterns and patterns[pattern_key] == pattern_value:
                            matching_sites.append(site_url)
                
                return matching_sites
        except Exception as e:
            logger.error("Failed to search sites by pattern", error=str(e), exc_info=True)
            return []


# Factory function for creating SiteMemoryManager instances
def create_site_memory_manager(ttl: int = 86400) -> SiteMemoryManager:
    """Create a new SiteMemoryManager instance with local storage"""
    return SiteMemoryManager(ttl=ttl)
