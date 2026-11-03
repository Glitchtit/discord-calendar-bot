from datetime import date
from ics import Calendar
from events import _extract_ics_events
from tasks import detect_event_changes

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:wilma-123
DTSTART:20261103T{start}00Z
DTEND:20261103T{end}00Z
SUMMARY:Mini Exam
LOCATION:A223
END:VEVENT
END:VCALENDAR
"""


def _events(start, end):
    cal = Calendar(ICS.format(start=start, end=end))
    return _extract_ics_events(cal, "test", date(2026, 11, 1), date(2026, 11, 30))


def test_rescheduled_ics_event_is_changed_not_added_removed():
    before, after = _events("1000", "1100"), _events("0815", "0915")
    added, removed, changed = detect_event_changes(before, after, date(2026, 11, 3))
    assert (added, removed, len(changed)) == ([], [], 1)


NO_UID_ICS = ICS.replace("UID:wilma-123\n", "")


def test_uidless_ics_ids_are_stable_across_fetches():
    ids = []
    for _ in range(2):
        cal = Calendar(NO_UID_ICS.format(start="1000", end="1100"))
        ids.append(_extract_ics_events(cal, "test", date(2026, 11, 1), date(2026, 11, 30), has_uids=False)[0]["id"])
    assert ids[0] == ids[1]


# --- watch loop / snapshot logic -------------------------------------------
import asyncio
from datetime import datetime, timedelta
from dateutil import tz
from utils import get_local_timezone

import pytest

import tasks
from events import compute_event_fingerprint
from utils import get_today


def _ev(eid, title, day, hour=10):
    start = datetime.combine(day, datetime.min.time()).replace(hour=hour).isoformat() + "+00:00"
    end = datetime.combine(day, datetime.min.time()).replace(hour=hour + 1).isoformat() + "+00:00"
    return {"id": eid, "summary": title, "original_summary": title,
            "start": {"dateTime": start}, "end": {"dateTime": end}, "location": "", "description": ""}


@pytest.fixture
def watch_env(monkeypatch):
    today = get_today()
    ev_a, ev_b = _ev("a", "Alpha", today), _ev("b", "Beta", today)
    saved = []
    monkeypatch.setattr(tasks, "GROUPED_CALENDARS", {"T": [{"id": "A", "type": "ics", "name": "A"},
                                                           {"id": "B", "type": "ics", "name": "B"}]})
    monkeypatch.setattr(tasks, "save_current_events_for_key", lambda k, evs: saved.append((k, evs)))
    monkeypatch.setattr(tasks, "_watch_tag_cursor", 0)
    tasks._pending_changes.clear()
    tasks._task_locks.clear()
    yield ev_a, ev_b, saved
    tasks._pending_changes.clear()


def _run_watch():
    asyncio.run(tasks.watch_for_event_changes.coro(object()))


def test_failed_source_does_not_report_removals(watch_env, monkeypatch):
    ev_a, ev_b, saved = watch_env
    monkeypatch.setattr(tasks, "get_events", lambda meta, s, e: None if meta["id"] == "B" else [ev_a])
    monkeypatch.setattr(tasks, "load_previous_events", lambda: {"T_full": [ev_a, ev_b]})
    _run_watch()
    assert tasks._pending_changes == {} and saved == []


def test_missing_snapshot_is_saved_silently(watch_env, monkeypatch):
    ev_a, ev_b, saved = watch_env
    monkeypatch.setattr(tasks, "get_events", lambda meta, s, e: [ev_a] if meta["id"] == "A" else [ev_b])
    monkeypatch.setattr(tasks, "load_previous_events", lambda: {})
    _run_watch()
    assert tasks._pending_changes == {}
    assert [k for k, _ in saved] == ["T_full"]


def test_event_moved_out_of_week_is_reported():
    today = get_today()
    old = _ev("x", "Exam", today)
    new = _ev("x", "Exam", today + timedelta(days=14))
    added, removed, changed = detect_event_changes([old], [new], today)
    assert (added, removed, len(changed)) == ([], [], 1)


def test_fingerprint_ignores_ai_simplified_title():
    a = _ev("x", "Kvantmekanik", get_today())
    b = dict(a, summary="Something Else Entirely")
    assert compute_event_fingerprint(a) == compute_event_fingerprint(b)


def test_apply_changes_only_applies_posted_changes():
    today = get_today()
    keep, gone, old = _ev("k", "Keep", today), _ev("g", "Gone", today), _ev("c", "Chg", today)
    new, add = _ev("c", "Chg", today, hour=14), _ev("n", "New", today, hour=16)
    result = tasks.apply_changes([keep, gone, old], [add], [gone], [(old, new)])
    assert [e["summary"] for e in result] == ["Keep", "Chg", "New"]


# --- second-audit fixes -------------------------------------------------------
import events


def _verification_env(monkeypatch, send_result):
    today = get_today()
    ev = _ev("n", "New", today)
    sends, saved = [], []

    async def fake_verify(*a, **k):
        await asyncio.sleep(0.01)  # let the second verifier start while the first is "fetching"
        return [ev], [], []

    async def fake_send(*a, **k):
        sends.append(1)
        return send_result

    monkeypatch.setattr(tasks, "GROUPED_CALENDARS", {"T": [{"id": "A"}]})
    monkeypatch.setattr(tasks, "verify_changes", fake_verify)
    monkeypatch.setattr(tasks, "send_embed", fake_send)
    monkeypatch.setattr(tasks, "load_previous_events", lambda: {"T_full": []})
    monkeypatch.setattr(tasks, "save_current_events_for_key", lambda k, evs: saved.append(k))
    tasks._pending_changes.clear()
    tasks._pending_changes["T"] = {"timestamp": datetime.now(), "added_events": [ev],
                                   "removed_events": [], "changed_events": [], "verification_count": 0}
    return sends, saved


def test_concurrent_verifications_post_once(monkeypatch):
    sends, saved = _verification_env(monkeypatch, send_result=object())

    async def both():
        await asyncio.gather(tasks.process_single_verification(None, "T"),
                             tasks.process_single_verification(None, "T"))
    asyncio.run(both())
    assert len(sends) == 1 and saved == ["T_full"]


def test_failed_send_leaves_snapshot_untouched(monkeypatch):
    sends, saved = _verification_env(monkeypatch, send_result=None)
    asyncio.run(tasks.process_single_verification(None, "T"))
    assert len(sends) == 1 and saved == []


def test_utc_ics_event_is_shown_in_local_time_and_still_matches_old_snapshot():
    ev = _events("0600", "0700")[0]
    local_offset = datetime(2026, 11, 3, 6, tzinfo=tz.UTC).astimezone(get_local_timezone()).utcoffset()
    assert datetime.fromisoformat(ev["start"]["dateTime"]).utcoffset() == local_offset
    old = dict(ev, start={"dateTime": "2026-11-03T06:00:00+00:00"}, end={"dateTime": "2026-11-03T07:00:00+00:00"})
    assert compute_event_fingerprint(old) == compute_event_fingerprint(ev)


def test_all_day_ics_event_uses_date_and_matches_old_snapshot():
    allday = ICS.replace("DTSTART:20261103T{start}00Z", "DTSTART;VALUE=DATE:20261103") \
                .replace("DTEND:20261103T{end}00Z", "DTEND;VALUE=DATE:20261104")
    ev = _extract_ics_events(Calendar(allday), "test", date(2026, 11, 1), date(2026, 11, 30))[0]
    assert ev["start"] == {"date": "2026-11-03"}
    old = dict(ev, start={"dateTime": "2026-11-03T00:00:00+00:00"}, end={"dateTime": "2026-11-04T00:00:00+00:00"})
    assert compute_event_fingerprint(old) == compute_event_fingerprint(ev)


def test_errored_ics_source_is_revalidated(monkeypatch):
    meta = {"type": "ics", "id": "https://x/cal.ics", "name": "ICS Calendar (Access Denied)",
            "error": True, "error_type": "forbidden", "tag": "T"}
    monkeypatch.setattr(events, "fetch_ics_calendar_metadata",
                        lambda url: {"type": "ics", "id": url, "name": "cal.ics"})
    monkeypatch.setattr(events, "get_ics_events", lambda s, e, url: ["ok"])
    assert events.get_events(meta, date(2026, 11, 1), date(2026, 11, 2)) == ["ok"]
    assert meta == {"type": "ics", "id": "https://x/cal.ics", "name": "cal.ics", "tag": "T"}
