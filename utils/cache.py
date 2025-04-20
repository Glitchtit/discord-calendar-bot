# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                            TIMED CACHE UTILITIES                           ║
# ║         Provides a thread-safe cache with time-based expiration            ║
# ║                  and basic statistics tracking.                            ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Standard library imports
import time
import threading
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timedelta

# Local application imports
from utils.logging import logger

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CLASS DEFINITION: TimedCache                                               ║
# ╚════════════════════════════════════════════════════════════════════════════╝

class TimedCache:
    # --- __init__ ---
    # Initializes the TimedCache instance.
    # Args:
    #     name: A string name for the cache, used for logging.
    #     ttl_seconds: Default time-to-live for cache entries in seconds.
    def __init__(self, name: str, ttl_seconds: int = 300):
        self.name = name
        self.default_ttl = ttl_seconds
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.size = 0
        logger.debug(f"Initialized {name} cache with {ttl_seconds}s TTL")

    # --- get ---
    # Retrieves an item from the cache if it exists and hasn't expired.
    # Increments hit or miss counters.
    # Args:
    #     key: The key of the item to retrieve.
    # Returns:
    #     The cached value, or None if the key is not found or the item has expired.
    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            entry = self.cache.get(key)
            if not entry:
                self.misses += 1
                return None
            value, expiry = entry
            if time.time() > expiry:
                del self.cache[key]
                self.size = len(self.cache)
                self.misses += 1
                return None
            self.hits += 1
            return value

    # --- set ---
    # Adds or updates an item in the cache.
    # Args:
    #     key: The key of the item to store.
    #     value: The value to store.
    #     ttl: Optional custom time-to-live in seconds for this item.
    #          If None, the cache's default TTL is used.
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expiry = time.time() + (ttl or self.default_ttl)
        with self.lock:
            self.cache[key] = (value, expiry)
            self.size = len(self.cache)

    # --- invalidate ---
    # Removes a specific item from the cache.
    # Args:
    #     key: The key of the item to remove.
    # Returns:
    #     True if the item was found and removed, False otherwise.
    def invalidate(self, key: str) -> bool:
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                self.size = len(self.cache)
                return True
            return False

    # --- invalidate_pattern ---
    # Removes all items from the cache whose keys contain the specified pattern.
    # Args:
    #     pattern: The substring pattern to match against cache keys.
    # Returns:
    #     The number of items removed from the cache.
    def invalidate_pattern(self, pattern: str) -> int:
        count = 0
        with self.lock:
            keys_to_remove = [k for k in self.cache if pattern in k]
            for key in keys_to_remove:
                del self.cache[key]
                count += 1
            self.size = len(self.cache)
        return count

    # --- clear ---
    # Removes all items from the cache.
    def clear(self) -> None:
        with self.lock:
            self.cache.clear()
            self.size = 0

    # --- get_stats ---
    # Returns statistics about the cache's performance.
    # Returns:
    #     A dictionary containing 'name', 'size', 'hits', 'misses', and 'hit_ratio'.
    def get_stats(self) -> Dict[str, Any]:
        with self.lock:
            total = self.hits + self.misses
            hit_ratio = self.hits / total if total else 0
            return {
                "name": self.name,
                "size": self.size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio": hit_ratio
            }

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SHARED CACHE INSTANCES                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Cache for calendar event data (short TTL: 3 minutes)
event_cache = TimedCache("event", ttl_seconds=180)

# Cache for calendar metadata (longer TTL: 1 hour)
metadata_cache = TimedCache("metadata", ttl_seconds=3600)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CACHE MANAGEMENT FUNCTIONS                                                 ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- clear_all_caches ---
# Clears all defined shared cache instances.
# Logs the number of items cleared from each cache.
# Returns:
#     A dictionary mapping cache names to the number of items cleared.
def clear_all_caches() -> Dict[str, int]:
    event_count = event_cache.size
    event_cache.clear()
    metadata_count = metadata_cache.size
    metadata_cache.clear()
    logger.info(f"Cleared all caches: {{'event': {event_count}, 'metadata': {metadata_count}}}")
    return {"event": event_count, "metadata": metadata_count}