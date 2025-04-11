"""
error_handling.py: Standardized error handling utilities for the calendar bot.

This module provides consistent error handling patterns to be used throughout
the application, ensuring errors are properly logged, tracked, and reported.
"""

import functools
import logging
import traceback
from typing import Callable, TypeVar, Any, Optional
import asyncio

# Configure logger
logger = logging.getLogger("calendarbot")

# Type variable for function return types
T = TypeVar('T')

def with_error_handling(
    default_value: Any = None, 
    error_message: str = "An error occurred", 
    notify_admin: bool = False
) -> Callable:
    """
    Decorator for standardized error handling in synchronous functions.
    
    Args:
        default_value: Value to return if an exception occurs
        error_message: Message prefix to log with the error
        notify_admin: Whether to notify admins about this error
        
    Returns:
        Decorated function with standardized error handling
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Log the error with contextual information
                logger.exception(f"{error_message}: {str(e)}")
                
                # Notify admins if requested
                if notify_admin:
                    try:
                        from utils.notifications import notify_error
                        asyncio.create_task(
                            notify_error(
                                title=f"Error in {func.__name__}",
                                error=e,
                                context=f"Args: {args}, Kwargs: {kwargs}"
                            )
                        )
                    except Exception as notify_error:
                        logger.error(f"Failed to send admin notification: {notify_error}")
                
                # Return default value on error
                return default_value
        return wrapper
    return decorator


async def with_async_error_handling(
    coro_func, 
    *args, 
    default_value: Any = None,
    error_message: str = "An async error occurred",
    notify_admin: bool = False,
    **kwargs
) -> Any:
    """
    Helper function for standardized error handling in async code.
    
    Args:
        coro_func: Async function to execute
        *args: Arguments to pass to the function
        default_value: Value to return if an exception occurs
        error_message: Message prefix to log with the error
        notify_admin: Whether to notify admins about this error
        **kwargs: Keyword arguments to pass to the function
        
    Returns:
        Result of the function or default_value on error
    """
    try:
        return await coro_func(*args, **kwargs)
    except Exception as e:
        # Log the error with contextual information
        logger.exception(f"{error_message}: {str(e)}")
        
        # Notify admins if requested
        if notify_admin:
            try:
                from utils.notifications import notify_error
                await notify_error(
                    title=f"Error in {coro_func.__name__}",
                    error=e,
                    context=f"Args: {args}, Kwargs: {kwargs}"
                )
            except Exception as notify_error:
                logger.error(f"Failed to send admin notification: {notify_error}")
        
        # Return default value on error
        return default_value


def async_error_handler(
    default_value: Any = None, 
    error_message: str = "An async error occurred", 
    notify_admin: bool = False
) -> Callable:
    """
    Decorator for standardized error handling in async functions.
    
    Args:
        default_value: Value to return if an exception occurs
        error_message: Message prefix to log with the error
        notify_admin: Whether to notify admins about this error
        
    Returns:
        Decorated async function with standardized error handling
    """
    def decorator(coro_func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(coro_func)
        async def wrapper(*args, **kwargs):
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


class ErrorTracker:
    """
    Tracks error occurrences and provides circuit-breaker functionality.
    
    This class can be used to track error rates and automatically implement
    circuit breaker patterns for external services or operations.
    """
    
    def __init__(self, name: str, threshold: int = 5, reset_after_seconds: int = 300):
        """
        Initialize an error tracker.
        
        Args:
            name: Identifier for this tracker
            threshold: Number of errors before circuit opens
            reset_after_seconds: Seconds after which to attempt reset
        """
        self.name = name
        self.threshold = threshold
        self.reset_after_seconds = reset_after_seconds
        self.error_count = 0
        self.circuit_open = False
        self.last_error_time = None
        self._recovery_task = None
    
    def record_error(self, error: Exception) -> bool:
        """
        Record an error occurrence and update circuit state.
        
        Args:
            error: The exception that occurred
            
        Returns:
            True if circuit is now open, False otherwise
        """
        import time
        
        self.error_count += 1
        self.last_error_time = time.time()
        
        if self.error_count >= self.threshold:
            if not self.circuit_open:
                logger.warning(
                    f"Circuit breaker opened for {self.name} after {self.error_count} errors"
                )
                self.circuit_open = True
                self._schedule_recovery()
                
        return self.circuit_open
    
    def is_available(self) -> bool:
        """Check if the service is available (circuit closed)"""
        import time
        
        # If circuit is open but enough time has passed, reset
        if self.circuit_open and self.last_error_time:
            elapsed = time.time() - self.last_error_time
            if elapsed > self.reset_after_seconds:
                logger.info(f"Circuit breaker for {self.name} reset after {elapsed:.1f}s")
                self.reset()
                return True
                
        return not self.circuit_open
    
    def reset(self):
        """Reset the circuit breaker state"""
        self.circuit_open = False
        self.error_count = 0
    
    def _schedule_recovery(self):
        """Schedule a recovery check after the timeout period"""
        import threading
        
        def check_and_reset():
            if self.is_available():  # This will reset if enough time has passed
                logger.info(f"Recovery check successful for {self.name}")
            else:
                logger.info(f"Recovery check scheduled in {self.reset_after_seconds}s for {self.name}")
                self._recovery_task = threading.Timer(
                    self.reset_after_seconds, check_and_reset
                )
                self._recovery_task.daemon = True
                self._recovery_task.start()
        
        # Cancel any existing timer
        if self._recovery_task:
            self._recovery_task.cancel()
        
        # Schedule the recovery check
        self._recovery_task = threading.Timer(
            self.reset_after_seconds, check_and_reset
        )
        self._recovery_task.daemon = True
        self._recovery_task.start()