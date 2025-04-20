# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                           RATE LIMITER MODULE                              ║
# ║    Token bucket implementation for controlling API request frequency       ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Standard library imports
import time
import threading
from typing import Dict, Optional, List

# Local application imports
from utils.logging import logger

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ TOKEN BUCKET IMPLEMENTATION                                                ║
# ╚════════════════════════════════════════════════════════════════════════════╝

class TokenBucketRateLimiter:
    # --- TokenBucketRateLimiter ---
    # Implements the token bucket algorithm for rate limiting API requests.
    # 
    # The algorithm works by:
    # 1. Adding tokens to a bucket at a fixed rate (token_refill_rate)
    # 2. Allowing requests to consume tokens from the bucket
    # 3. Blocking requests when the bucket is empty
    #
    # This allows for bursts of activity (up to max_tokens) while
    # maintaining a sustainable long-term average rate.
    
    # --- __init__ ---
    # Initialize a new token bucket rate limiter.
    # Args:
    #     name: Name of the rate limiter for logging
    #     max_tokens: Maximum number of tokens the bucket can hold
    #     token_refill_rate: Rate at which tokens are added (tokens per second)
    #     refill_interval: How often to refill tokens (in seconds)
    def __init__(
        self, 
        name: str,
        max_tokens: float,
        token_refill_rate: float,
        refill_interval: float = 1.0
    ):
        self.name = name
        self.max_tokens = max_tokens
        self.token_refill_rate = token_refill_rate
        self.refill_interval = refill_interval
        
        self.tokens = max_tokens  # Start with a full bucket
        self.last_refill = time.time()
        
        self.lock = threading.RLock()
        self.request_count = 0
        self.throttled_count = 0
        
        logger.info(f"Initialized rate limiter '{name}' with {max_tokens} max tokens, "
                  f"refill rate of {token_refill_rate} tokens/sec")
    
    # --- _refill ---
    # Refill tokens based on elapsed time since last refill.
    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        
        # Calculate how many tokens to add based on elapsed time
        new_tokens = elapsed * self.token_refill_rate
        
        # Update token count, ensuring it doesn't exceed max_tokens
        self.tokens = min(self.tokens + new_tokens, self.max_tokens)
        self.last_refill = now
    
    # --- consume ---
    # Attempt to consume tokens from the bucket.
    # Args:
    #     tokens: Number of tokens to consume (default 1.0)
    #     wait: If True, wait until tokens are available
    # Returns: True if tokens were consumed, False otherwise
    def consume(self, tokens: float = 1.0, wait: bool = False) -> bool:
        with self.lock:
            self.request_count += 1
            
            # Always refill before checking available tokens
            self._refill()
            
            # If we have enough tokens, consume them immediately
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
                
            # If we shouldn't wait, fail fast
            if not wait:
                self.throttled_count += 1
                return False
            
            # Calculate how long we need to wait
            tokens_needed = tokens - self.tokens
            wait_time = tokens_needed / self.token_refill_rate
            
            # Release the lock while waiting
            self.lock.release()
            try:
                logger.debug(f"Rate limiter '{self.name}' waiting for {wait_time:.2f}s to get {tokens_needed:.2f} tokens")
                time.sleep(wait_time)
            finally:
                # Re-acquire the lock
                self.lock.acquire()
            
            # Refill and try again (should succeed unless another thread took tokens)
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            else:
                self.throttled_count += 1
                return False
    
    # --- get_stats ---
    # Get current statistics for this rate limiter.
    # Returns: Dictionary with rate limiter statistics
    def get_stats(self) -> Dict[str, float]:
        with self.lock:
            self._refill()  # Make sure token count is current
            return {
                "name": self.name,
                "tokens": self.tokens,
                "max_tokens": self.max_tokens,
                "request_count": self.request_count,
                "throttled_count": self.throttled_count,
                "throttle_ratio": self.throttled_count / self.request_count if self.request_count else 0
            }
    
    # --- get_token_count ---
    # Get the current number of tokens in the bucket.
    # Returns: Current token count as a float
    def get_token_count(self) -> float:
        with self.lock:
            self._refill()  # Make sure token count is current
            return self.tokens

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ PREDEFINED RATE LIMITERS                                                   ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# General Calendar API operations (excluding expensive list operations)
# Allow bursts of up to 10 operations, long-term average of 2 per second
CALENDAR_API_LIMITER = TokenBucketRateLimiter(
    "calendar_api", 
    max_tokens=10.0, 
    token_refill_rate=2.0
)

# List operations are more expensive, so limit them more strictly
# Allow bursts of up to 5 list operations, long-term average of 1 per 2 seconds
EVENT_LIST_LIMITER = TokenBucketRateLimiter(
    "event_list",
    max_tokens=5.0,
    token_refill_rate=0.5  # 1 every 2 seconds
)

# Map of API endpoints to their appropriate rate limiters
ENDPOINT_RATE_LIMITERS = {
    "default": CALENDAR_API_LIMITER,
    "events.list": EVENT_LIST_LIMITER,
    "events.get": CALENDAR_API_LIMITER,
    "calendars.get": CALENDAR_API_LIMITER
}

# --- get_rate_limiter_for_endpoint ---
# Get the appropriate rate limiter for a specific API endpoint.
# Args:
#     endpoint: The API endpoint name
# Returns: The appropriate TokenBucketRateLimiter instance
def get_rate_limiter_for_endpoint(endpoint: str) -> TokenBucketRateLimiter:
    return ENDPOINT_RATE_LIMITERS.get(endpoint, ENDPOINT_RATE_LIMITERS["default"])