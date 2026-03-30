"""
Test suite for SSL error handling in events.py.
Verifies that both ssl.SSLError and OSError with SSL messages are properly caught.

Uses pytest and imports directly from the source modules instead of
duplicating production code.
"""
import ssl
import os
import sys

import pytest
from unittest.mock import Mock, MagicMock

# Mock heavy dependencies before importing events
sys.modules.setdefault('ics', MagicMock())
sys.modules.setdefault('google.oauth2', MagicMock())
sys.modules.setdefault('google.oauth2.service_account', MagicMock())
sys.modules.setdefault('googleapiclient', MagicMock())
sys.modules.setdefault('googleapiclient.discovery', MagicMock())

# Create a real HttpError class for testing
class _HttpError(Exception):
    def __init__(self, resp, content):
        self.resp = resp
        self.content = content
        super().__init__(f"HTTP Error {resp.status}")

sys.modules.setdefault('googleapiclient.errors', MagicMock(HttpError=_HttpError))

# Minimal env vars needed by events.py at import time
os.environ.setdefault('DISCORD_BOT_TOKEN', 'test_token')
os.environ.setdefault('ANNOUNCEMENT_CHANNEL_ID', '123456789')
os.environ.setdefault('CALENDAR_SOURCES', 'google:test@test.com:TEST')
os.environ.setdefault('GOOGLE_APPLICATION_CREDENTIALS', '/tmp/test_creds.json')
os.environ.setdefault('USER_TAG_MAPPING', '123:TEST')

from events import is_ssl_error, retry_api_call  # noqa: E402


class TestIsSSLError:
    """Tests for the is_ssl_error() helper function."""

    def test_direct_ssl_error(self):
        assert is_ssl_error(ssl.SSLError("[SSL] record layer failure"))

    @pytest.mark.parametrize("msg", [
        "[SSL] record layer failure (_ssl.c:2590)",
        "SSL error occurred",
        "ssl: bad handshake",
        "Error from _ssl.c:2590",
        "TLS record layer failure",
        "[ssl] RECORD LAYER failure",  # case-insensitive
    ])
    def test_oserror_with_ssl_patterns(self, msg):
        assert is_ssl_error(OSError(msg))

    @pytest.mark.parametrize("msg", [
        "Connection refused",
        "File not found",
    ])
    def test_non_ssl_oserror(self, msg):
        assert not is_ssl_error(OSError(msg))

    def test_non_oserror_exceptions(self):
        assert not is_ssl_error(ValueError("Invalid value"))
        assert not is_ssl_error(RuntimeError("Something went wrong"))


class TestRetryApiCall:
    """Tests for retry_api_call() with SSL error handling."""

    def test_ssl_error_retried(self):
        attempts = []

        def failing_func():
            attempts.append(1)
            raise ssl.SSLError("[SSL] record layer failure (_ssl.c:2590)")

        result = retry_api_call(failing_func, max_retries=3)
        assert result is None, "Should return None after exhausting retries"
        assert len(attempts) == 3

    def test_oserror_ssl_retried(self):
        attempts = []

        def failing_func():
            attempts.append(1)
            raise OSError("[SSL] record layer failure (_ssl.c:2590)")

        result = retry_api_call(failing_func, max_retries=3)
        assert result is None
        assert len(attempts) == 3

    def test_non_ssl_oserror_raised_immediately(self):
        attempts = []

        def failing_func():
            attempts.append(1)
            raise OSError("Connection refused")

        with pytest.raises(OSError, match="Connection refused"):
            retry_api_call(failing_func, max_retries=3)
        assert len(attempts) == 1

    def test_recovery_after_ssl_error(self):
        attempts = []

        def eventually_succeeds():
            attempts.append(1)
            if len(attempts) < 2:
                raise ssl.SSLError("[SSL] record layer failure")
            return "success"

        result = retry_api_call(eventually_succeeds, max_retries=3)
        assert result == "success"
        assert len(attempts) == 2

    def test_non_retryable_http_error(self):
        attempts = []

        def failing_func():
            attempts.append(1)
            resp = Mock(status=404)
            raise _HttpError(resp, b'Not Found')

        with pytest.raises(_HttpError):
            retry_api_call(failing_func, max_retries=3)
        assert len(attempts) == 1

