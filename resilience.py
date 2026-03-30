"""Shared resilience primitives: circuit breakers and retry logic.

Replaces duplicate implementations across ai.py, events.py, and commands.py
with a unified module. Uses tenacity for retry mechanics.
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any, Callable, TypeVar

from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from log import logger

T = TypeVar("T")


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔌 CircuitBreaker                                                  ║
# ║ Opens after N consecutive failures, auto-resets after timeout      ║
# ╚════════════════════════════════════════════════════════════════════╝
class CircuitBreaker:
    """Circuit breaker for a single external service (e.g., OpenAI API).

    Opens after `threshold` consecutive failures, blocking further calls
    until `reset_after` seconds have elapsed.
    """

    def __init__(
        self,
        name: str,
        threshold: int = 3,
        reset_after: float = 300.0,
    ):
        self.name = name
        self.threshold = threshold
        self.reset_after = timedelta(seconds=reset_after)

        self._error_count = 0
        self._last_error_time: datetime | None = None

    @property
    def is_open(self) -> bool:
        """True if circuit is open (calls should be blocked)."""
        if self._error_count < self.threshold:
            return False
        if self._last_error_time and datetime.now() - self._last_error_time > self.reset_after:
            self.reset()
            return False
        return True

    def record_failure(self) -> None:
        self._error_count += 1
        self._last_error_time = datetime.now()
        if self._error_count >= self.threshold:
            logger.warning(
                f"Circuit breaker '{self.name}' opened after {self._error_count} errors. "
                f"Will retry after {self.reset_after}"
            )

    def record_success(self) -> None:
        if self._error_count > 0:
            logger.debug(f"Circuit breaker '{self.name}' cleared after success")
            self._error_count = 0
            self._last_error_time = None

    def reset(self) -> None:
        logger.info(f"Circuit breaker '{self.name}' reset")
        self._error_count = 0
        self._last_error_time = None

    @property
    def error_count(self) -> int:
        return self._error_count


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📡 CalendarCircuitBreakers                                         ║
# ║ Per-calendar circuit breakers with exponential backoff             ║
# ╚════════════════════════════════════════════════════════════════════╝
class CalendarCircuitBreakers:
    """Manages per-key circuit breakers for calendar sources.

    Each calendar source gets its own failure counter with exponential
    backoff: base_backoff * 2^(failures-1), capped at max_backoff.
    """

    def __init__(
        self,
        threshold: int = 5,
        base_backoff: float = 60.0,
        max_backoff: float = 3600.0,
        auto_reset_after: float = 3600.0,
    ):
        self.threshold = threshold
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.auto_reset_after = timedelta(seconds=auto_reset_after)
        self._breakers: dict[str, dict[str, Any]] = {}

    def is_open(self, calendar_id: str) -> bool:
        if calendar_id not in self._breakers:
            return False
        info = self._breakers[calendar_id]
        if info.get("backoff_until", datetime.min) > datetime.now():
            return True
        if datetime.now() - info.get("last_failure", datetime.min) > self.auto_reset_after:
            logger.debug(f"Auto-resetting circuit breaker for calendar {calendar_id}")
            del self._breakers[calendar_id]
            return False
        return False

    def record_failure(self, calendar_id: str) -> None:
        now = datetime.now()
        if calendar_id not in self._breakers:
            self._breakers[calendar_id] = {"count": 0, "last_failure": now}
        info = self._breakers[calendar_id]
        info["count"] += 1
        info["last_failure"] = now
        backoff_seconds = min(
            self.base_backoff * (2 ** (info["count"] - 1)),
            self.max_backoff,
        )
        info["backoff_until"] = now + timedelta(seconds=backoff_seconds)
        logger.warning(
            f"Calendar {calendar_id} failed {info['count']} times, "
            f"backing off for {backoff_seconds}s"
        )

    def record_success(self, calendar_id: str) -> None:
        if calendar_id in self._breakers:
            logger.debug(f"Clearing failure record for calendar {calendar_id}")
            del self._breakers[calendar_id]

    def clear_all(self) -> int:
        count = len(self._breakers)
        self._breakers.clear()
        return count

    def get_failure_info(self, calendar_id: str) -> dict[str, Any] | None:
        """Get raw failure info for a calendar (used by health monitoring)."""
        return self._breakers.get(calendar_id)

    def get_status(self) -> dict[str, Any]:
        """Get status of all active breakers for monitoring."""
        result = {}
        for cal_id, info in self._breakers.items():
            backoff_remaining = 0
            if info.get("backoff_until", datetime.min) > datetime.now():
                backoff_remaining = (info["backoff_until"] - datetime.now()).total_seconds()
            result[cal_id] = {
                "failure_count": info["count"],
                "last_failure": info["last_failure"].isoformat(),
                "backoff_remaining_seconds": max(0, int(backoff_remaining)),
            }
        return result

    def items(self):
        """Iterate over (calendar_id, failure_info) pairs."""
        return self._breakers.items()

    def __len__(self) -> int:
        return len(self._breakers)

    def __contains__(self, key: str) -> bool:
        return key in self._breakers


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔁 Retry helpers                                                   ║
# ║ Centralized retry logic with exponential backoff                   ║
# ╚════════════════════════════════════════════════════════════════════╝
def retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
) -> T:
    """Retry a synchronous function with exponential backoff and jitter.

    Retries on all exceptions except KeyboardInterrupt.
    """
    @retry(
        stop=stop_after_attempt(max_retries + 1),
        wait=wait_exponential_jitter(initial=initial_delay, max=max_delay, jitter=1),
        retry=retry_if_exception(lambda e: not isinstance(e, KeyboardInterrupt)),
        reraise=True,
    )
    def _wrapped():
        return func()

    return _wrapped()


async def async_retry_with_backoff(
    operation: Callable,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    non_retryable: tuple[type[Exception], ...] = (),
) -> Any:
    """Retry an async operation with exponential backoff and jitter.

    Args:
        operation: Async callable to retry.
        max_retries: Maximum retry attempts.
        initial_delay: Initial backoff delay in seconds.
        max_delay: Maximum backoff delay cap.
        non_retryable: Exception types that should not be retried.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return await operation()
        except non_retryable:
            raise
        except Exception as e:
            backoff = min((2 ** attempt) * initial_delay + random.uniform(0, 1), max_delay)
            logger.warning(f"Async retry {attempt + 1}/{max_retries} failed: {e}")
            logger.info(f"Retrying in {backoff:.2f} seconds...")
            last_error = e
            await asyncio.sleep(backoff)

    if last_error:
        raise last_error
