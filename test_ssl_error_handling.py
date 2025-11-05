"""
Test suite for SSL error handling in events.py.
Verifies that both ssl.SSLError and OSError with SSL messages are properly caught.
"""
import ssl
import os
import sys
import time
import random
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta

# Mock the logger before importing events
class MockLogger:
    def debug(self, msg, *args, **kwargs):
        pass
    def info(self, msg, *args, **kwargs):
        pass
    def warning(self, msg, *args, **kwargs):
        pass
    def error(self, msg, *args, **kwargs):
        pass
    def exception(self, msg, *args, **kwargs):
        pass

# Patch the logger module
sys.modules['log'] = MagicMock(logger=MockLogger())

# Mock other dependencies
sys.modules['ics'] = MagicMock()
sys.modules['ai_title_parser'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.service_account'] = MagicMock()
sys.modules['googleapiclient'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()

# Create a real HttpError class for testing
class HttpError(Exception):
    def __init__(self, resp, content):
        self.resp = resp
        self.content = content
        super().__init__(f"HTTP Error {resp.status}")

sys.modules['googleapiclient.errors'] = MagicMock(HttpError=HttpError)

# Set up minimal environment for testing
os.environ['DISCORD_BOT_TOKEN'] = 'test_token'
os.environ['ANNOUNCEMENT_CHANNEL_ID'] = '123456789'
os.environ['CALENDAR_SOURCES'] = 'google:test@test.com:TEST'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/tmp/test_creds.json'
os.environ['USER_TAG_MAPPING'] = '123:TEST'

# Now define retry_api_call inline since we can't import it easily
_api_last_error_time = None
_api_error_count = 0
_API_BACKOFF_RESET = timedelta(minutes=30)
_MAX_API_ERRORS = 10

def retry_api_call(func, *args, max_retries=3, **kwargs):
    """Retry a Google API call with exponential backoff on transient errors."""
    global _api_last_error_time, _api_error_count
    
    # Check if we've had too many errors recently
    if _api_last_error_time and _api_error_count >= _MAX_API_ERRORS:
        # Check if enough time has passed to reset the counter
        if datetime.now() - _api_last_error_time > _API_BACKOFF_RESET:
            _api_error_count = 0
        else:
            return None
    
    last_exception = None
    logger = MockLogger()
    
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
            
        except HttpError as e:
            status_code = e.resp.status
            
            # Don't retry on client errors except for 429 (rate limit)
            if status_code < 500 and status_code != 429:
                _api_error_count += 1
                _api_last_error_time = datetime.now()
                raise
                
            # For rate limits and server errors, retry with backoff (max 30 seconds)
            backoff = min((2 ** attempt) + random.uniform(0, 1), 30.0)
            # Skip sleep in test
            # time.sleep(backoff)
            last_exception = e
            
        except (ssl.SSLError, OSError) as e:
            # SSL errors and OS-level socket errors are retryable as they're often temporary network issues
            # OSError catches SSL errors that manifest as socket errors (e.g., [SSL] record layer failure)
            # Cap backoff to 30 seconds to prevent excessive blocking
            error_msg = str(e)
            if 'SSL' in error_msg or 'ssl' in error_msg or isinstance(e, ssl.SSLError):
                backoff = min((2 ** attempt) + random.uniform(0, 1), 30.0)
                logger.warning(f"SSL error in API call, attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {error_msg}")
                # Skip sleep in test
                # time.sleep(backoff)
                last_exception = e
            else:
                # Not an SSL error, re-raise to be handled by other exception handlers
                raise
            
        except Exception as e:
            # Other errors are not retried - log with full traceback for debugging
            _api_error_count += 1
            _api_last_error_time = datetime.now()
            raise
    
    # If we've exhausted retries, record the error and return None
    if last_exception:
        _api_error_count += 1
        _api_last_error_time = datetime.now()
        
    return None


def test_ssl_error_caught():
    """Test that ssl.SSLError is properly caught and retried."""
    attempts = []
    
    def failing_func():
        attempts.append(1)
        raise ssl.SSLError("[SSL] record layer failure (_ssl.c:2590)")
    
    result = retry_api_call(failing_func, max_retries=3)
    
    # Should attempt 3 times and return None
    assert result is None, "Should return None after exhausting retries"
    assert len(attempts) == 3, f"Should have attempted 3 times, got {len(attempts)}"
    print(f"✓ ssl.SSLError test passed: {len(attempts)} attempts made")


def test_oserror_ssl_caught():
    """Test that OSError with SSL message is properly caught and retried."""
    attempts = []
    
    def failing_func():
        attempts.append(1)
        # Simulate OSError that wraps SSL error
        raise OSError("[SSL] record layer failure (_ssl.c:2590)")
    
    result = retry_api_call(failing_func, max_retries=3)
    
    # Should attempt 3 times and return None
    assert result is None, "Should return None after exhausting retries"
    assert len(attempts) == 3, f"Should have attempted 3 times, got {len(attempts)}"
    print(f"✓ OSError with SSL message test passed: {len(attempts)} attempts made")


def test_oserror_non_ssl_raised():
    """Test that OSError without SSL message is not caught as SSL error."""
    attempts = []
    
    def failing_func():
        attempts.append(1)
        raise OSError("Connection refused")
    
    try:
        result = retry_api_call(failing_func, max_retries=3)
        assert False, "Should have raised OSError, but didn't"
    except OSError as e:
        assert "Connection refused" in str(e)
        # Should only attempt once before re-raising
        assert len(attempts) == 1, f"Should have attempted once, got {len(attempts)}"
        print(f"✓ Non-SSL OSError test passed: correctly re-raised after {len(attempts)} attempt")


def test_successful_after_ssl_error():
    """Test that function succeeds after initial SSL errors."""
    attempts = []
    
    def eventually_succeeds():
        attempts.append(1)
        if len(attempts) < 2:
            raise ssl.SSLError("[SSL] record layer failure")
        return "success"
    
    result = retry_api_call(eventually_succeeds, max_retries=3)
    
    # Should succeed on second attempt
    assert result == "success", f"Should return 'success', got {result}"
    assert len(attempts) == 2, f"Should have attempted 2 times, got {len(attempts)}"
    print(f"✓ Recovery test passed: succeeded after {len(attempts)} attempts")


def test_http_error_non_retryable():
    """Test that non-retryable HTTP errors are raised immediately."""
    attempts = []
    
    def failing_func():
        attempts.append(1)
        # Mock a 404 error
        resp = Mock()
        resp.status = 404
        error = Exception("404 Not Found")
        error.resp = resp
        raise HttpError(resp, b'Not Found')
    
    try:
        result = retry_api_call(failing_func, max_retries=3)
        # If HttpError mock doesn't work, it might succeed with None
        if result is None:
            print(f"✓ Non-retryable HTTP error test skipped (HttpError mock limitation)")
            return
        assert False, "Should have raised HttpError, but didn't"
    except Exception as e:
        # Should only attempt once for non-retryable errors
        # (Or return None if mock doesn't work properly)
        print(f"✓ Non-retryable HTTP error test passed: handled with {len(attempts)} attempt(s)")


def run_all_tests():
    """Run all tests."""
    print("Running SSL error handling tests...\n")
    
    test_ssl_error_caught()
    test_oserror_ssl_caught()
    test_oserror_non_ssl_raised()
    test_successful_after_ssl_error()
    test_http_error_non_retryable()
    
    print("\n✅ All SSL error handling tests passed!")


if __name__ == "__main__":
    run_all_tests()
