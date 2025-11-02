"""Caching service for Surf Browser Service"""
import json
import time
from typing import Optional, Dict, Any, Union
import structlog

from config import get_settings
from core.foundation import CacheError

logger = structlog.get_logger()
settings = get_settings()


class CacheService:
    """Caching service with Redis support and fallback to in-memory cache"""
    
    def __init__(self):
        self.redis_client = None
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        self.initialized = False
    
    async def initialize(self) -> None:
        """Initialize cache service"""
        
        if settings.enable_cache and settings.redis_url:
            try:
                import redis.asyncio as redis
                self.redis_client = redis.from_url(settings.redis_url)
                await self.redis_client.ping()
                logger.info("Redis cache initialized")
            except Exception as e:
                logger.warning("Redis initialization failed, using memory cache", error=str(e))
                self.redis_client = None
        
        self.initialized = True
        logger.info("Cache service initialized")
    
    async def cleanup(self) -> None:
        """Cleanup cache service"""
        
        if self.redis_client:
            try:
                await self.redis_client.close()
            except Exception as e:
                logger.error("Redis cleanup failed", error=str(e))
        
        self.initialized = False
        logger.info("Cache service cleaned up")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        
        if not self.initialized:
            raise CacheError("get", "Cache service not initialized")
        
        try:
            if self.redis_client:
                value = await self.redis_client.get(key)
                if value:
                    return json.loads(value)
            else:
                # Use memory cache
                if key in self.memory_cache:
                    cache_data = self.memory_cache[key]
                    if time.time() < cache_data["expires_at"]:
                        return cache_data["value"]
                    else:
                        del self.memory_cache[key]
            
            return None
            
        except Exception as e:
            logger.error("Cache get failed", key=key, error=str(e))
            raise CacheError("get", str(e))
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in cache with TTL"""
        
        if not self.initialized:
            raise CacheError("set", "Cache service not initialized")
        
        try:
            actual_ttl = ttl or settings.cache_ttl
            
            if self.redis_client:
                await self.redis_client.setex(
                    key, 
                    actual_ttl, 
                    json.dumps(value, default=str)
                )
            else:
                # Use memory cache
                self.memory_cache[key] = {
                    "value": value,
                    "expires_at": time.time() + actual_ttl
                }
            
            return True
            
        except Exception as e:
            logger.error("Cache set failed", key=key, error=str(e))
            raise CacheError("set", str(e))
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        
        if not self.initialized:
            raise CacheError("delete", "Cache service not initialized")
        
        try:
            if self.redis_client:
                result = await self.redis_client.delete(key)
                return result > 0
            else:
                # Use memory cache
                if key in self.memory_cache:
                    del self.memory_cache[key]
                    return True
                return False
                
        except Exception as e:
            logger.error("Cache delete failed", key=key, error=str(e))
            raise CacheError("delete", str(e))
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        
        if not self.initialized:
            raise CacheError("exists", "Cache service not initialized")
        
        try:
            if self.redis_client:
                return await self.redis_client.exists(key) > 0
            else:
                # Use memory cache
                if key in self.memory_cache:
                    cache_data = self.memory_cache[key]
                    if time.time() < cache_data["expires_at"]:
                        return True
                    else:
                        del self.memory_cache[key]
                return False
                
        except Exception as e:
            logger.error("Cache exists check failed", key=key, error=str(e))
            raise CacheError("exists", str(e))
    
    async def clear(self) -> bool:
        """Clear all cache entries"""
        
        if not self.initialized:
            raise CacheError("clear", "Cache service not initialized")
        
        try:
            if self.redis_client:
                await self.redis_client.flushdb()
            else:
                # Use memory cache
                self.memory_cache.clear()
            
            return True
            
        except Exception as e:
            logger.error("Cache clear failed", error=str(e))
            raise CacheError("clear", str(e))
    
    async def get_or_set(
        self, 
        key: str, 
        factory_func, 
        ttl: Optional[int] = None
    ) -> Any:
        """Get value from cache or set it using factory function"""
        
        value = await self.get(key)
        if value is not None:
            return value
        
        # Value not in cache, generate it
        value = await factory_func()
        await self.set(key, value, ttl)
        return value
    
    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment numeric value in cache"""
        
        if not self.initialized:
            raise CacheError("increment", "Cache service not initialized")
        
        try:
            if self.redis_client:
                return await self.redis_client.incrby(key, amount)
            else:
                # Use memory cache
                current_value = await self.get(key) or 0
                new_value = current_value + amount
                await self.set(key, new_value)
                return new_value
                
        except Exception as e:
            logger.error("Cache increment failed", key=key, error=str(e))
            raise CacheError("increment", str(e))
    
    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration for existing key"""
        
        if not self.initialized:
            raise CacheError("expire", "Cache service not initialized")
        
        try:
            if self.redis_client:
                return await self.redis_client.expire(key, ttl)
            else:
                # Use memory cache
                if key in self.memory_cache:
                    self.memory_cache[key]["expires_at"] = time.time() + ttl
                    return True
                return False
                
        except Exception as e:
            logger.error("Cache expire failed", key=key, error=str(e))
            raise CacheError("expire", str(e))
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        
        if not self.initialized:
            raise CacheError("stats", "Cache service not initialized")
        
        try:
            if self.redis_client:
                info = await self.redis_client.info()
                return {
                    "type": "redis",
                    "connected_clients": info.get("connected_clients", 0),
                    "used_memory": info.get("used_memory", 0),
                    "keyspace_hits": info.get("keyspace_hits", 0),
                    "keyspace_misses": info.get("keyspace_misses", 0)
                }
            else:
                # Memory cache stats
                current_time = time.time()
                active_keys = sum(
                    1 for data in self.memory_cache.values()
                    if time.time() < data["expires_at"]
                )
                
                return {
                    "type": "memory",
                    "total_keys": len(self.memory_cache),
                    "active_keys": active_keys,
                    "expired_keys": len(self.memory_cache) - active_keys
                }
                
        except Exception as e:
            logger.error("Cache stats failed", error=str(e))
            raise CacheError("stats", str(e))
    
    def _cleanup_expired_memory_cache(self) -> None:
        """Clean up expired entries from memory cache"""
        
        current_time = time.time()
        expired_keys = [
            key for key, data in self.memory_cache.items()
            if current_time >= data["expires_at"]
        ]
        
        for key in expired_keys:
            del self.memory_cache[key]
        
        if expired_keys:
            logger.debug("Cleaned up expired cache entries", count=len(expired_keys))
