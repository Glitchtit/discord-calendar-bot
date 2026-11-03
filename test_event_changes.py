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
    monkeypatch.setattr(tasks, "load_previous_events", lambda: {"T_full": [ev_a, ev_b], "T_sources": ["A", "B"]})
    _run_watch()
    assert tasks._pending_changes == {} and saved == []


def test_missing_snapshot_is_saved_silently(watch_env, monkeypatch):
    ev_a, ev_b, saved = watch_env
    monkeypatch.setattr(tasks, "get_events", lambda meta, s, e: [ev_a] if meta["id"] == "A" else [ev_b])
    monkeypatch.setattr(tasks, "load_previous_events", lambda: {})
    _run_watch()
    assert tasks._pending_changes == {}
    assert [k for k, _ in saved] == ["T_full", "T_sources"]


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


# --- cycle 3 ----------------------------------------------------------------------
from events import floating_times_to_utc
from utils import parse_agenda_date
from views import build_week_pages


def test_floating_ics_time_is_local_wall_clock():
    floating = ICS.replace("{start}00Z", "{start}00").replace("{end}00Z", "{end}00")
    content = floating_times_to_utc(floating.format(start="0800", end="0900"))
    ev = _extract_ics_events(Calendar(content), "test", date(2026, 11, 1), date(2026, 11, 30))[0]
    assert datetime.fromisoformat(ev["start"]["dateTime"]).hour == 8


@pytest.mark.parametrize("text,expected", [
    ("today", date(2026, 11, 3)), ("tomorrow", date(2026, 11, 4)),
    ("10.04", date(2027, 4, 10)), ("02.11", date(2026, 11, 2)), ("25.12.2027", date(2027, 12, 25)), ("31.02", None),
    ("friday", date(2026, 11, 6)), ("this friday", date(2026, 11, 6)), ("tuesday", date(2026, 11, 3)),
    ("next monday", date(2026, 11, 9)), ("next friday", date(2026, 11, 13)),
])
def test_parse_agenda_date(text, expected):
    assert parse_agenda_date(text, date(2026, 11, 3)) == expected  # a Tuesday


def test_week_pages_respect_discord_limits_and_keep_all_events():
    start = date(2026, 11, 2)
    by_day = {start + timedelta(days=d): [_ev(f"{d}-{i}", f"Lesson number {i} with a long title", start + timedelta(days=d), hour=i % 12)
                                          for i in range(25)] for d in range(30)}
    pages, epp = build_week_pages(by_day, title="t", description="d")
    for p in pages:
        assert len(p) <= 6000 and len(p.fields) <= 25 and all(len(f.value) <= 1024 for f in p.fields)
    assert sum(len(e) for e in epp) == 30 * 25


# --- cycle 4 ----------------------------------------------------------------------
import threading


def test_loop_watchdog_exits_when_loop_is_stuck(monkeypatch):
    import bot as bot_module
    exited = threading.Event()
    monkeypatch.setattr(bot_module.os, "_exit", lambda code: exited.set())
    stuck_loop = asyncio.new_event_loop()  # never run, so callbacks never fire
    bot_module.start_loop_watchdog(stuck_loop, timeout=0.05, interval=0)
    assert exited.wait(2)
    stuck_loop.close()


def test_errored_google_source_is_revalidated(monkeypatch):
    meta = {"type": "google", "id": "cal@x", "name": "cal@x", "error": True, "tag": "T"}
    monkeypatch.setattr(events, "fetch_google_calendar_metadata",
                        lambda cid: {"type": "google", "id": cid, "name": "Family"})
    monkeypatch.setattr(events, "get_google_events", lambda s, e, cid: [])
    assert events.get_events(meta, date(2026, 11, 1), date(2026, 11, 2)) == []
    assert meta["name"] == "Family" and "error" not in meta and meta["tag"] == "T"


# --- cycle 5 ----------------------------------------------------------------------
from resilience import CalendarCircuitBreakers
from utils import event_days
from events import _validate_ics_content


def test_dd_mm_in_late_december_means_next_january():
    assert parse_agenda_date("2.1", date(2026, 12, 28)) == date(2027, 1, 2)


def test_ics_source_with_failed_probe_is_still_fetched(monkeypatch):
    meta = {"type": "ics", "id": "https://x/cal.ics", "name": "ICS Calendar (Access Denied)",
            "error": True, "error_type": "forbidden", "tag": "T"}
    monkeypatch.setattr(events, "fetch_ics_calendar_metadata", lambda url: meta)  # still cached as an error
    monkeypatch.setattr(events, "get_ics_events", lambda s, e, url: None)
    assert events.get_events(meta, date(2026, 11, 1), date(2026, 11, 2)) is None  # failed, not "empty"
    monkeypatch.setattr(events, "get_ics_events", lambda s, e, url: ["ok"])
    assert events.get_events(meta, date(2026, 11, 1), date(2026, 11, 2)) == ["ok"]


def test_startup_keeps_existing_snapshots(monkeypatch):
    saved = []
    monkeypatch.setattr(tasks, "GROUPED_CALENDARS", {"OLD": [{"id": "A"}], "NEW": [{"id": "B"}]})
    monkeypatch.setattr(tasks, "load_previous_events", lambda: {"OLD_full": [{"x": 1}], "OLD_sources": ["A"]})
    monkeypatch.setattr(tasks, "get_events", lambda meta, s, e: [])
    monkeypatch.setattr(tasks, "save_current_events_for_key", lambda k, evs: saved.append(k))
    asyncio.run(tasks.initialize_event_snapshots())
    assert saved == ["NEW_full", "NEW_sources"]


ALLDAY_BREAK = ICS.replace("DTSTART:20261103T{start}00Z", "DTSTART;VALUE=DATE:20261102") \
                  .replace("DTEND:20261103T{end}00Z", "DTEND;VALUE=DATE:20261107")


def test_multi_day_event_covers_each_day():
    evs = _extract_ics_events(Calendar(ALLDAY_BREAK), "t", date(2026, 11, 4), date(2026, 11, 4))
    assert len(evs) == 1 and event_days(evs[0]) == (date(2026, 11, 2), date(2026, 11, 6))
    timed = _ev("t", "Late", date(2026, 11, 3), hour=1)
    timed["end"] = {"dateTime": "2026-11-04T00:00:00+02:00"}  # ends exactly at midnight
    assert event_days(timed)[1] == date(2026, 11, 3)


def test_shared_uid_events_get_distinct_ids():
    two = ICS.replace("END:VCALENDAR", "BEGIN:VEVENT\nUID:wilma-123\nDTSTART:20261105T100000Z\n"
                      "DTEND:20261105T110000Z\nSUMMARY:Mini Exam\nEND:VEVENT\nEND:VCALENDAR")
    evs = _extract_ics_events(Calendar(two.format(start="1000", end="1100")), "t", date(2026, 11, 1), date(2026, 11, 30))
    assert len({e["id"] for e in evs}) == 2


def test_bom_feed_is_accepted():
    content = "﻿" + ICS.format(start="1000", end="1100")
    assert _validate_ics_content(content, "t") is not None


def test_circuit_breaker_opens_only_at_threshold():
    cb = CalendarCircuitBreakers(threshold=5)
    for _ in range(4):
        cb.record_failure("x")
    assert not cb.is_open("x") and len(cb) == 0
    cb.record_failure("x")
    assert cb.is_open("x") and "x" in cb


def test_daily_retry_only_reposts_failed_tags(monkeypatch):
    calls = []
    fail_once = {"B"}

    async def fake_post(bot, tag, day, allow_partial=True, send=True):
        calls.append(tag)
        if tag in fail_once:
            fail_once.discard(tag)
            return None
        return [{"summary": tag}]

    monkeypatch.setattr(tasks, "GROUPED_CALENDARS", {"A": [], "B": []})
    monkeypatch.setattr(tasks, "post_tagged_events", fake_post)
    monkeypatch.setattr(tasks, "AI_TOGGLE", False)
    state = {"daily": set(), "events": []}
    assert asyncio.run(tasks.post_todays_happenings(None, True, state, allow_partial=False)) is False
    assert asyncio.run(tasks.post_todays_happenings(None, True, state, allow_partial=False)) is True
    assert calls == ["A", "B", "B"]


# --- review follow-ups ------------------------------------------------------------
def test_adding_a_calendar_to_a_tag_rebaselines_instead_of_announcing(watch_env, monkeypatch):
    ev_a, ev_b, saved = watch_env
    monkeypatch.setattr(tasks, "get_events", lambda meta, s, e: [ev_a] if meta["id"] == "A" else [ev_b])
    # snapshot taken when the tag only had calendar A
    monkeypatch.setattr(tasks, "load_previous_events", lambda: {"T_full": [ev_a], "T_sources": ["A"]})
    _run_watch()
    assert tasks._pending_changes == {}
    assert [k for k, _ in saved] == ["T_full", "T_sources"]


def test_ics_probe_error_is_cleared_when_fetch_works(monkeypatch):
    meta = {"type": "ics", "id": "https://x/wilma/cal.ics", "name": "ICS Calendar (Access Denied)",
            "error": True, "error_type": "forbidden", "tag": "T"}
    monkeypatch.setattr(events, "fetch_ics_calendar_metadata", lambda url: meta)
    monkeypatch.setattr(events, "get_ics_events", lambda s, e, url: [])
    events.get_events(meta, date(2026, 11, 1), date(2026, 11, 2))
    assert meta["name"] == "cal.ics" and "error" not in meta and meta["tag"] == "T"


def test_rrule_warning_ignores_vtimezone_dst_rules(monkeypatch, caplog):
    vtz = ("BEGIN:VTIMEZONE\nTZID:Europe/Helsinki\nBEGIN:DAYLIGHT\nDTSTART:19700329T030000\n"
           "TZOFFSETFROM:+0200\nTZOFFSETTO:+0300\nRRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\nEND:DAYLIGHT\n"
           "END:VTIMEZONE\n")
    plain = ICS.format(start="1000", end="1100").replace("PRODID:test\n", "PRODID:test\n" + vtz)
    series = plain.replace("SUMMARY:Mini Exam\n", "SUMMARY:Mini Exam\nRRULE:FREQ=WEEKLY;COUNT=3\n")
    warned = []
    monkeypatch.setattr(events.logger, "warning", lambda msg, *a, **k: warned.append(msg))
    for content in (plain, series):
        monkeypatch.setattr(events, "_fetch_ics_content", lambda url, c=content: c)
        events.get_ics_events(date(2026, 11, 1), date(2026, 11, 30), "https://x/" + str(len(warned)))
    assert sum("RRULE" in m for m in warned) == 1


def test_floating_conversion_leaves_vtimezone_rules_alone():
    vtz = ("BEGIN:VTIMEZONE\nTZID:Europe/Helsinki\nBEGIN:DAYLIGHT\nDTSTART:19700329T030000\n"
           "TZOFFSETFROM:+0200\nTZOFFSETTO:+0300\nEND:DAYLIGHT\nEND:VTIMEZONE\n")
    floating = ICS.replace("{start}00Z", "{start}00").replace("{end}00Z", "{end}00").format(start="0800", end="0900")
    out = floating_times_to_utc(floating.replace("PRODID:test\n", "PRODID:test\n" + vtz))
    assert "DTSTART:19700329T030000\n" in out           # DST rule untouched
    assert "DTSTART:20261103T080000\n" not in out       # event time converted


def test_title_model_not_found_disables_openai_once(monkeypatch):
    import openai, httpx
    import ai_title_parser as atp
    calls = []

    class FakeCompletions:
        def create(self, **kw):
            calls.append(kw["model"])
            raise openai.NotFoundError("gone", response=httpx.Response(404, request=httpx.Request("POST", "http://x")), body=None)

    parser = atp.AITitleParser()
    parser.client = type("C", (), {"chat": type("Ch", (), {"completions": FakeCompletions()})()})()
    assert parser.simplify_title("Mini exam one (A1)") and parser.simplify_title("Another title here (B2)")
    assert len(calls) == 1 and parser.client is None


# --- message UX ------------------------------------------------------------------
def test_monday_daily_post_only_collects_events_already_in_the_week_post(monkeypatch):
    sends = {}

    async def fake_post(bot, tag, day, allow_partial=True, send=True):
        sends[tag] = send
        return [{"summary": tag}]

    monkeypatch.setattr(tasks, "GROUPED_CALENDARS", {"A": [], "B": []})
    monkeypatch.setattr(tasks, "post_tagged_events", fake_post)
    monkeypatch.setattr(tasks, "AI_TOGGLE", False)
    state = {"daily": set(), "events": [], "weekly": {"A"}}
    assert asyncio.run(tasks.post_todays_happenings(None, True, state)) is True
    assert sends == {"A": False, "B": True}
    assert len(state["events"]) == 2  # the greeting still sees Monday's events


def test_change_lines_carry_dates_and_all_day_is_not_noon(monkeypatch):
    import utils
    from views import format_change_lines
    monkeypatch.setattr(utils, "get_local_timezone", lambda: tz.gettz("Europe/Helsinki"))
    timed = {"summary": "Kampaaja", "start": {"dateTime": "2026-10-22T16:30:00+03:00"},
             "end": {"dateTime": "2026-10-22T19:00:00+03:00"}, "id": "k"}
    all_day = {"summary": "Boat", "start": {"date": "2026-10-23"}, "end": {"date": "2026-10-24"}, "id": "b"}
    moved = {**timed, "start": {"dateTime": "2026-10-23T15:00:00+03:00"}, "end": {"dateTime": "2026-10-23T17:00:00+03:00"}}
    text, _ = format_change_lines([timed], [all_day], [(timed, moved)])
    assert "`Thu 22.10 16:30–19:00`" in text
    assert "~~**Boat** `Fri 23.10 · all day`~~" in text and "12:00" not in text
    assert "`Fri 23.10 15:00–17:00` · was `Thu 22.10 16:30–19:00`" in text


def test_renamed_event_with_same_id_is_one_change():
    old = {"summary": "Fira pappa", "original_summary": "Fira pappa", "id": "x",
           "start": {"dateTime": "2026-11-04T13:30:00+02:00"}, "end": {"dateTime": "2026-11-04T15:00:00+02:00"}}
    new = {**old, "summary": "Fira mamma", "original_summary": "Fira mamma", "location": "Hemma"}
    added, removed, changed = tasks.detect_event_changes([old], [new], date(2026, 11, 3))
    assert (added, removed) == ([], []) and changed == [(old, new)]
    from views import _format_change_diff
    assert "title was *Fira pappa*" in _format_change_diff(old, new)


def test_short_titles_are_kept_as_typed():
    import ai_title_parser as atp
    parser = atp.AITitleParser()
    parser.client = object()  # any model call would crash
    for title in ["Emmi tuparit", "Juna tre-hki", "Fira pappa", "DIFF möte"]:
        assert parser.simplify_title(title) == title
    assert parser.simplify_title("TEAMMÖTE EL") == "Teammöte el"
    assert atp._uncaps("3 ANSVARSARBETSTID") == "3 Ansvarsarbetstid"
    assert atp._uncaps("AI-material FAST ARBETSTID") == "AI-material fast arbetstid"
    assert atp._uncaps("PEDAGOGISK TIMME") == "Pedagogisk timme"
    assert atp._uncaps("Komplettering EM24H") == "Komplettering EM24H"
    assert atp._strip_codes("RESERVERAT (DUBBELBOKNING TILLÅTEN) GEM KOMPLETTERING/YRKESPLANERING") == "Reserverat gem komplettering/yrkesplanering"
    assert atp._strip_codes("2627H.Arbete inom el- och automationsbranschen (230.1) (AM26H)") == "Arbete inom el- och automationsbranschen"
    # a model answer with a word the original doesn't contain (typo, translation) is rejected
    assert not parser._validate_simplified_title("Organisatiionens utveckling", "2 MIN OCH ORGANISATIONENS UTVECKLING")
    assert parser._validate_simplified_title("Arbete el automation Elgrunder", "2627H.Arbete inom el- och automationsbranschen Elgrunder (230.1)")


def test_shorten_cuts_at_a_word():
    from utils import shorten
    assert shorten("Ansvarsarbetstid Kulturfonden AI Utbildningsmaterial", 40) == "Ansvarsarbetstid Kulturfonden AI…"
    assert shorten("short", 40) == "short"
