# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                   CALENDAR BOT ERROR HANDLING UTILITIES                     ║
# ║ Provides standardized error handling decorators and a circuit breaker      ║
# ║      pattern implementation for robust application operation.              ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Standard library imports
import functools
import logging
import traceback
from typing import Callable, TypeVar, Any, Optional
import asyncio
import time # Added for ErrorTracker
import threading # Added for ErrorTracker

# Local application imports
# (utils.notifications is imported conditionally within functions to avoid circular deps)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CONFIGURATION AND GLOBALS                                                  ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Logger for this module
logger = logging.getLogger("calendarbot")

# Type variable for generic function return types
T = TypeVar('T')

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SYNCHRONOUS ERROR HANDLING DECORATOR                                       ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- with_error_handling ---
# Decorator factory for standardized error handling in synchronous functions.
# Catches exceptions, logs them, optionally notifies admins, and returns a default value.
# Args:
#     default_value: The value to return if an exception occurs.
#     error_message: A prefix for the log message when an error occurs.
#     notify_admin: If True, attempts to send an error notification to admins.
# Returns: A decorator function.
def with_error_handling(
    default_value: Any = None,
    error_message: str = "An error occurred",
    notify_admin: bool = False
) -> Callable:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # --- Log Error ---
                logger.exception(f"{error_message} in {func.__name__}: {str(e)}")

                # --- Notify Admin (Optional) ---
                if notify_admin:
                    try:
                        # Import locally to prevent circular dependency
                        from utils.notifications import notify_critical_error
                        # Use asyncio.create_task for fire-and-forget notification
                        asyncio.create_task(
                            notify_critical_error(
                                error_context=f"Function {func.__name__}",
                                exception=e
                            )
                        )
                    except Exception as notify_err:
                        logger.error(f"Failed to send admin notification: {notify_err}")

                # --- Return Default Value ---
                return default_value
        return wrapper
    return decorator

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ ASYNCHRONOUS ERROR HANDLING                                                ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- with_async_error_handling ---
# Helper function to wrap an awaitable call with standardized error handling.
# Catches exceptions, logs them, optionally notifies admins, and returns a default value.
# Args:
#     coro_func: The awaitable (async function) to execute.
#     *args: Positional arguments for the awaitable.
#     default_value: The value to return if an exception occurs.
#     error_message: A prefix for the log message when an error occurs.
#     notify_admin: If True, attempts to send an error notification to admins.
#     **kwargs: Keyword arguments for the awaitable.
# Returns: The result of the awaitable or the default value on error.
async def with_async_error_handling(
    coro_func, # The async function itself
    *args,
    default_value: Any = None,
    error_message: str = "An async error occurred",
    notify_admin: bool = False,
    **kwargs
) -> Any:
    try:
        return await coro_func(*args, **kwargs)
    except Exception as e:
        # --- Log Error ---
        logger.exception(f"{error_message} in {coro_func.__name__}: {str(e)}")

        # --- Notify Admin (Optional) ---
        if notify_admin:
            try:
                # Import locally to prevent circular dependency
                from utils.notifications import notify_critical_error
                # Await notification directly in async context
                await notify_critical_error(
                    error_context=f"Async function {coro_func.__name__}",
                    exception=e
                )
            except Exception as notify_err:
                logger.error(f"Failed to send admin notification: {notify_err}")

        # --- Return Default Value ---
        return default_value

# --- async_error_handler ---
# Decorator factory for standardized error handling in asynchronous functions.
# Uses the `with_async_error_handling` helper.
# Args:
#     default_value: The value to return if an exception occurs.
#     error_message: A prefix for the log message when an error occurs.
#     notify_admin: If True, attempts to send an error notification to admins.
# Returns: An async decorator function.
def async_error_handler(
    default_value: Any = None,
    error_message: str = "An async error occurred",
    notify_admin: bool = False
) -> Callable:
    def decorator(coro_func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(coro_func)
        async def wrapper(*args, **kwargs):
            # --- Delegate to Helper ---
            return await with_async_error_handling(
                coro_func,
                *args,
                default_value=default_value,
                error_message=error_message,
                notify_admin=notify_admin,
                **kwargs
            )
        return wrapper
    return decorator

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CIRCUIT BREAKER PATTERN IMPLEMENTATION                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

class ErrorTracker:
    # --- __init__ ---
    # Initializes the ErrorTracker for circuit breaking.
    # Args:
    #     name: A unique name identifying the service or operation being tracked.
    #     threshold: The number of consecutive errors required to open the circuit.
    #     reset_after_seconds: The duration (in seconds) the circuit stays open
    #                          before attempting a recovery check.
    def __init__(self, name: str, threshold: int = 5, reset_after_seconds: int = 300):
        self.name = name
        self.threshold = threshold
        self.reset_after_seconds = reset_after_seconds
        self.error_count = 0
        self.circuit_open = False
        self.last_error_time = None
        self._recovery_task: Optional[threading.Timer] = None # Timer for recovery check
        self._lock = threading.Lock() # Lock for thread safety

    # --- record_error ---
    # Records an error occurrence and updates the circuit breaker state.
    # If the error threshold is reached, opens the circuit and schedules a recovery check.
    # Args:
    #     error: The exception object that occurred (used for logging context if needed).
    # Returns: True if the circuit is now open, False otherwise.
    def record_error(self, error: Exception) -> bool:
        with self._lock:
            self.error_count += 1
            self.last_error_time = time.time()

            if self.error_count >= self.threshold and not self.circuit_open:
                logger.warning(
                    f"Circuit breaker opened for '{self.name}' after {self.error_count} errors. "
                    f"Will attempt recovery in {self.reset_after_seconds}s."
                )
                self.circuit_open = True
                self._schedule_recovery()

            return self.circuit_open

    # --- is_available ---
    # Checks if the tracked service/operation should be considered available.
    # Returns False if the circuit is open.
    # If the circuit is open but the reset timeout has passed, it attempts to reset.
    # Returns: True if the service is considered available (circuit closed), False otherwise.
    def is_available(self) -> bool:
        with self._lock:
            if self.circuit_open:
                if self.last_error_time:
                    elapsed = time.time() - self.last_error_time
                    if elapsed > self.reset_after_seconds:
                        logger.info(f"Attempting to reset circuit breaker for '{self.name}' after {elapsed:.1f}s")
                        # Attempt to reset (could also involve a test call here)
                        self.reset()
                        # Assuming reset means available for the next try
                        return True
                # Circuit is open and reset time hasn't passed
                return False
            # Circuit is closed
            return True

    # --- reset ---
    # Resets the circuit breaker to the closed state.
    # Called automatically by `is_available` after timeout or can be called manually.
    def reset(self):
        with self._lock:
            if self.circuit_open:
                 logger.info(f"Circuit breaker for '{self.name}' has been reset.")
            self.circuit_open = False
            self.error_count = 0
            self.last_error_time = None # Clear last error time on explicit reset
            # Cancel any pending recovery task as we are resetting now
            if self._recovery_task:
                self._recovery_task.cancel()
                self._recovery_task = None

    # --- _schedule_recovery ---
    # Internal method to schedule a background task (Timer thread) that will
    # check if the service might be available again after the reset timeout.
    def _schedule_recovery(self):
        # --- Recovery Check Function ---
        def check_and_log_status():
            # This function runs in a separate thread via Timer
            # It calls is_available which might reset the circuit
            if self.is_available():
                # Logging is handled within is_available/reset
                pass
            else:
                # If still not available, schedule another check (optional, depends on strategy)
                # logger.debug(f"Recovery check for '{self.name}' failed, circuit remains open.")
                # Re-scheduling might lead to continuous checks; often manual reset or
                # relying on the next `is_available` call is preferred.
                pass
            # Ensure the task reference is cleared after execution
            with self._lock:
                self._recovery_task = None

        # --- Cancel Existing Timer ---
        if self._recovery_task:
            self._recovery_task.cancel()

        # --- Schedule New Timer ---
        self._recovery_task = threading.Timer(
            self.reset_after_seconds,
            check_and_log_status
        )
        self._recovery_task.daemon = True # Allow program exit even if timer is active
        self._recovery_task.start()
        logger.debug(f"Recovery check scheduled for '{self.name}' in {self.reset_after_seconds}s")