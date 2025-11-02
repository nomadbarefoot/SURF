"""
Site Memory System
Persists session data, cookies, and site-specific information for enhanced automation
Stores data locally within the surf module for independence
"""

import json
import sqlite3
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path
import structlog

logger = structlog.get_logger()

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

class SiteMemoryManager:
    """Manages site memory persistence and retrieval with local storage"""
    
    def __init__(self, ttl: int = 86400):
        # Store database locally within surf module
        surf_dir = Path(__file__).parent.parent
        self.db_path = surf_dir / "data" / "site_memory.db"
        self.ttl = ttl
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self) -> None:
        """Initialize the site memory database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS site_memory (
                        site_url TEXT PRIMARY KEY,
                        session_data TEXT,
                        cookies TEXT,
                        last_accessed REAL,
                        access_count INTEGER,
                        success_rate REAL,
                        custom_data TEXT,
                        created_at REAL
                    )
                """)
                conn.commit()
            logger.info("Site memory database initialized", db_path=str(self.db_path))
        except Exception as e:
            logger.error("Failed to initialize site memory database", error=str(e))
    
    def save_site_memory(self, site_memory: SiteMemory) -> bool:
        """Save site memory to database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO site_memory 
                    (site_url, session_data, cookies, last_accessed, access_count, 
                     success_rate, custom_data, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    site_memory.site_url,
                    json.dumps(site_memory.session_data),
                    json.dumps(site_memory.cookies),
                    site_memory.last_accessed,
                    site_memory.access_count,
                    site_memory.success_rate,
                    json.dumps(site_memory.custom_data),
                    time.time()
                ))
                conn.commit()
            logger.debug("Site memory saved", site_url=site_memory.site_url)
            return True
        except Exception as e:
            logger.error("Failed to save site memory", error=str(e), site_url=site_memory.site_url)
            return False
    
    def get_site_memory(self, site_url: str) -> Optional[SiteMemory]:
        """Get site memory from database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT session_data, cookies, last_accessed, access_count, 
                           success_rate, custom_data
                    FROM site_memory 
                    WHERE site_url = ?
                """, (site_url,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                session_data, cookies, last_accessed, access_count, success_rate, custom_data = row
                
                return SiteMemory(
                    site_url=site_url,
                    session_data=json.loads(session_data),
                    cookies=json.loads(cookies),
                    last_accessed=last_accessed,
                    access_count=access_count,
                    success_rate=success_rate,
                    custom_data=json.loads(custom_data)
                )
        except Exception as e:
            logger.error("Failed to get site memory", error=str(e), site_url=site_url)
            return None
    
    def update_access_stats(self, site_url: str, success: bool) -> bool:
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
            
            return self.save_site_memory(site_memory)
        except Exception as e:
            logger.error("Failed to update access stats", error=str(e), site_url=site_url)
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
            logger.error("Failed to cleanup expired memories", error=str(e))
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
                        MAX(last_accessed) as most_recent_access
                    FROM site_memory
                """)
                
                row = cursor.fetchone()
                if not row:
                    return {"total_sites": 0, "avg_success_rate": 0.0, "avg_access_count": 0.0, "most_recent_access": 0}
                
                total_sites, avg_success_rate, avg_access_count, most_recent_access = row
                
                return {
                    "total_sites": total_sites,
                    "avg_success_rate": avg_success_rate or 0.0,
                    "avg_access_count": avg_access_count or 0.0,
                    "most_recent_access": most_recent_access or 0,
                    "ttl": self.ttl
                }
        except Exception as e:
            logger.error("Failed to get site stats", error=str(e))
            return {"error": str(e)}
    
    def get_top_sites(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top sites by access count"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT site_url, access_count, success_rate, last_accessed
                    FROM site_memory 
                    ORDER BY access_count DESC 
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
            logger.error("Failed to get top sites", error=str(e))
            return []

# Factory function for creating SiteMemoryManager instances
def create_site_memory_manager(ttl: int = 86400) -> SiteMemoryManager:
    """Create a new SiteMemoryManager instance with local storage"""
    return SiteMemoryManager(ttl=ttl)
