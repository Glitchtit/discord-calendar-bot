"""
Tests for fetch_ics_calendar_metadata() resilience.

Covers two fixes:
  (a) The validation probe uses the same browser User-Agent/Accept headers as
      the real content fetch, and is retried with backoff so a transient
      Cloudflare blip does not flip the calendar's name.
  (c) A non-classified HTTP status (anything that is not 401/403/404/405) falls
      back to the URL-derived name instead of "ICS Calendar (HTTP Error)", is
      not flagged as a persistent error, and is not written to the long error
      cache (so it self-heals on the next load).

Uses pytest and imports directly from the source modules.
"""
import os
import sys
import time

import pytest
from unittest.mock import MagicMock

# Mock heavy dependencies before importing events
sys.modules.setdefault('ics', MagicMock())
sys.modules.setdefault('google.oauth2', MagicMock())
sys.modules.setdefault('google.oauth2.service_account', MagicMock())
sys.modules.setdefault('googleapiclient', MagicMock())
sys.modules.setdefault('googleapiclient.discovery', MagicMock())


# events.py does `except HttpError`, so the mocked HttpError must be a real
# exception class. Match test_ssl_error_handling.py so collection order between
# the two test modules doesn't matter (sys.modules.setdefault is shared).
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

import requests  # noqa: E402
import events  # noqa: E402

URL = "https://example.test/schedule/export/teachers/720/Wilma.ics?token=abc&p=1"
CACHE_KEY = f"ics_{URL}"


class FakeResp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.url = URL
        self.text = "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
        self.encoding = None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"HTTP {self.status_code}", response=self
            )


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    events._calendar_metadata_cache.clear()
    # Make tenacity's exponential backoff instant so retry tests stay fast.
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
    yield
    events._calendar_metadata_cache.clear()


def test_validation_probe_sends_browser_headers(monkeypatch):
    """(a) The HEAD probe must carry the browser UA + Accept headers."""
    captured = {}

    def fake_head(url, **kwargs):
        captured["headers"] = kwargs.get("headers") or {}
        return FakeResp(200)

    monkeypatch.setattr(requests, "head", fake_head)

    events.fetch_ics_calendar_metadata(URL)

    assert "Mozilla" in captured["headers"].get("User-Agent", "")
    assert "text/calendar" in captured["headers"].get("Accept", "")


def test_validation_retries_transient_server_error(monkeypatch):
    """(a) A transient 5xx on the probe is retried, then resolves cleanly."""
    calls = []

    def fake_head(url, **kwargs):
        calls.append(1)
        return FakeResp(503) if len(calls) == 1 else FakeResp(200)

    monkeypatch.setattr(requests, "head", fake_head)

    meta = events.fetch_ics_calendar_metadata(URL)

    assert len(calls) == 2, "expected one retry after the transient 503"
    assert not meta.get("error")
    assert meta["name"] == "Wilma.ics"


def test_persistent_transient_error_falls_back_to_url_name(monkeypatch):
    """(c) A persistent non-classified status uses the URL-derived name, is not
    flagged as an error, and is not stored as a sticky error in the cache."""

    def fake_head(url, **kwargs):
        return FakeResp(500)

    monkeypatch.setattr(requests, "head", fake_head)

    meta = events.fetch_ics_calendar_metadata(URL)

    assert meta["name"] == "Wilma.ics"
    assert "HTTP Error" not in meta["name"]
    assert not meta.get("error")
    cached = events._calendar_metadata_cache.get(CACHE_KEY)
    assert cached is None or not cached.get("error")


def test_not_found_still_classified(monkeypatch):
    """(c) Genuine 404 must still be classified (not swallowed by the fallback)."""

    def fake_head(url, **kwargs):
        return FakeResp(404)

    monkeypatch.setattr(requests, "head", fake_head)

    meta = events.fetch_ics_calendar_metadata(URL)

    assert meta.get("error") is True
    assert meta.get("error_type") == "not_found"


def test_head_405_uses_ranged_get_with_browser_headers(monkeypatch):
    """(a) When HEAD is 405, the ranged-GET fallback also carries browser headers."""
    get_calls = []

    def fake_head(url, **kwargs):
        return FakeResp(405)

    def fake_get(url, **kwargs):
        get_calls.append(kwargs.get("headers") or {})
        return FakeResp(200)

    monkeypatch.setattr(requests, "head", fake_head)
    monkeypatch.setattr(requests, "get", fake_get)

    meta = events.fetch_ics_calendar_metadata(URL)

    assert not meta.get("error")
    assert meta["name"] == "Wilma.ics"
    assert meta.get("validation_method") == "GET-partial"
    assert "Mozilla" in get_calls[0].get("User-Agent", "")
    assert get_calls[0].get("Range") == "bytes=0-1023"
