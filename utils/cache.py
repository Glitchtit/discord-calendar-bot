"""
cache.py: Provides timed caching for calendar events and metadata

This module implements a simple expiring cache system to reduce API calls
and improve performance for frequently accessed calendar data.
"""

import time
import threading
from typing import Dict, Any, Optional, Tuple, Set
from datetime import datetime, timedelta
from utils.logging import logger

class TimedCache:
    """
    A thread-safe cache with expiration for items.
    
    Items stored in the cache will expire after the specified ttl (time-to-live)
    and will be removed on the next access after expiration.
    """
    
    def __init__(self, name: str, ttl_seconds: int = 300):
        """
        Initialize a new cache.
        
        Args:
            name: Name of the cache for logging and reference
            ttl_seconds: Default time-to-live in seconds for cached items
        """
        self.name = name
        self.default_ttl = ttl_seconds
        self.cache: Dict[str, Tuple[Any, float]] = {}  # value, expiry
        self.lock = threading.RLock()
        
        # Stats
        self.hits = 0
        self.misses = 0
        self.size = 0
        
        logger.debug(f"Initialized {name} cache with {ttl_seconds}s TTL")
        
    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache.
        
        Args:
            key: The cache key to lookup
            
        Returns:
            The cached value, or None if not found or expired
        """
        with self.lock:
            if key not in self.cache:
                self.misses += 1
                return None
                
            value, expiry = self.cache[key]
            
            # Check if expired
            if time.time() > expiry:
                del self.cache[key]
                self.size = len(self.cache)
                self.misses += 1
                return None
                
            self.hits += 1
            return value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Store a value in the cache.
        
        Args:
            key: The cache key
            value: The value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        if ttl is None:
            ttl = self.default_ttl
            
        expiry = time.time() + ttl
        
        with self.lock:
            self.cache[key] = (value, expiry)
            self.size = len(self.cache)
    
    def invalidate(self, key: str) -> bool:
        """
        Remove a specific key from the cache.
        
        Args:
            key: The cache key to invalidate
            
        Returns:
            True if key was found and removed, False otherwise
        """
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                self.size = len(self.cache)
                return True
            return False
    
    def invalidate_pattern(self, pattern: str) -> int:
        """
        Remove all keys containing the specified pattern.
        
        Args:
            pattern: String pattern to match in keys
            
        Returns:
            Number of keys removed
        """
        count = 0
        with self.lock:
            keys_to_remove = [k for k in self.cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self.cache[key]
                count += 1
                
            self.size = len(self.cache)
            return count
    
    def clear(self) -> None:
        """Clear the entire cache."""
        with self.lock:
            self.cache.clear()
            self.size = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary containing hit/miss counts and ratios
        """
        with self.lock:
            total = self.hits + self.misses
            hit_ratio = self.hits / total if total > 0 else 0
            
            return {
                "name": self.name,
                "size": self.size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio": hit_ratio
            }

# Create shared cache instances with appropriate TTLs
event_cache = TimedCache("event", ttl_seconds=180)  # 3 minutes for events
metadata_cache = TimedCache("metadata", ttl_seconds=3600)  # 1 hour for metadata

def clear_all_caches() -> Dict[str, int]:
    """
    Clear all cache instances and return stats.
    
    Returns:
        Dictionary with counts of items cleared from each cache
    """
    results = {}
    
    event_count = event_cache.size
    event_cache.clear()
    results["event"] = event_count
    
    metadata_count = metadata_cache.size
    metadata_cache.clear()
    results["metadata"] = metadata_count
    
    logger.info(f"Cleared all caches: {results}")
    return results