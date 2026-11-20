from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from island import http, ics

JKT = ZoneInfo("Asia/Jakarta")
TEXT = (Path(__file__).parent / "data" / "sample.ics").read_text(encoding="utf-8")


def on(day, text=TEXT):
    return ics.events_on(ics.parse_ics(text), day, JKT)


def times(day, summary):
    return [e.start.strftime("%H:%M") for e in on(day) if e.summary == summary]


def test_time_zones_in_local():
    assert times(date(2026, 11, 23), "UTC standup") == ["13:00"]
    assert times(date(2026, 11, 24), "Jakarta sync") == ["09:00"]
    assert times(date(2026, 11, 25), "New York call") == ["03:00"]  # 15:00 EST = 03:00 next day in Jakarta
    assert on(date(2026, 11, 24))[0].start.tzinfo is not None


def test_all_day_and_folded_summary():
    h = on(date(2026, 11, 25))[0]
    assert (h.summary, h.all_day) == ("Holiday", True)
    assert on(date(2026, 11, 26))[0].summary == "A very long summary that wraps, with escapes"


def test_weekly_count_and_exdate():
    got = [d for d in range(1, 30) if times(date(2026, 11, d), "Weekly review")]
    assert got == [2, 9, 11]  # 4th, the Nov 4 occurrence, is excluded; nothing after COUNT


def test_daily_interval_until():
    got = [d for d in range(1, 15) if times(date(2026, 11, d), "Every other day")]
    assert got == [1, 3, 5]
    assert times(date(2026, 11, 3), "Every other day") == ["15:00"]


def test_monthly_and_yearly():
    assert times(date(2026, 11, 15), "Monthly report") == ["12:00"]
    assert times(date(2026, 12, 15), "Monthly report") == ["12:00"]
    assert not times(date(2026, 11, 16), "Monthly report")
    assert times(date(2026, 1, 15), "Monthly report") == ["12:00"]
    assert not times(date(2025, 12, 15), "Monthly report")  # before DTSTART
    assert times(date(2026, 3, 22), "Anniversary") == ["01:00"]


def test_unsupported_rrule_is_single_and_floating_is_local():
    t = "BEGIN:VEVENT\nDTSTART:20261121T090000\nRRULE:FREQ=DAILY;BYHOUR=3\nSUMMARY:x\nEND:VEVENT"
    assert [e.start.strftime("%d %H:%M") for e in ics.events_on(ics.parse_ics(t), date(2026, 11, 21), JKT)] == ["21 09:00"]
    assert not ics.events_on(ics.parse_ics(t), date(2026, 11, 22), JKT)


def test_rows_and_reminders():
    series = ics.parse_ics(TEXT)
    assert ics.rows(series, datetime(2026, 11, 25, 8, tzinfo=JKT)) == [("Holiday", "All day"), ("New York call", "03:00")]
    seen = set()
    now = datetime(2026, 11, 23, 12, 51, tzinfo=JKT)
    assert ics.due_reminders(series, now, seen) == ["UTC standup"]
    assert ics.due_reminders(series, now, seen) == []  # once per occurrence
    assert ics.due_reminders(series, datetime(2026, 11, 23, 12, 30, tzinfo=JKT), set()) == []
    assert ics.due_reminders(series, datetime(2026, 11, 25, 0, 0, tzinfo=JKT), set()) == []  # all-day never reminds


def test_calendar_fetch_failure_keeps_events(monkeypatch):
    calls = []

    def fake(url, headers=None, timeout=10):
        calls.append((url, timeout))
        if len(calls) > 1:
            raise OSError("down")
        return 200, {}, TEXT.encode()

    monkeypatch.setattr(http, "get", fake)
    c = ics.Calendar("webcal://example.com/x.ics")
    c.fetch_once()
    first = c.series
    assert len(first) == 9
    c.fetch_once()
    assert c.series is first
    assert calls[0] == ("https://example.com/x.ics", 10)


def test_calendar_without_url_does_nothing(monkeypatch):
    monkeypatch.setattr(http, "get", lambda *a, **k: 1 / 0)
    c = ics.Calendar("")
    c.fetch_once()
    assert c.series == []


def vevent(*lines):
    return "BEGIN:VEVENT\n" + "\n".join(lines) + "\nEND:VEVENT\n"


MASTER = vevent("UID:a", "DTSTART;TZID=Asia/Jakarta:20261102T100000", "RRULE:FREQ=WEEKLY;COUNT=4", "SUMMARY:Sync")


def test_override_moves_instance():
    text = MASTER + vevent("UID:a", "RECURRENCE-ID;TZID=Asia/Jakarta:20261109T100000",
                           "DTSTART;TZID=Asia/Jakarta:20261109T150000", "SUMMARY:Sync")
    s = ics.parse_ics(text)
    assert [e.start.strftime("%H:%M") for e in ics.events_on(s, date(2026, 11, 9), JKT)] == ["15:00"]
    assert [e.start.strftime("%H:%M") for e in ics.events_on(s, date(2026, 11, 16), JKT)] == ["10:00"]
    seen = set()
    assert ics.due_reminders(s, datetime(2026, 11, 9, 9, 55, tzinfo=JKT), seen) == []  # old slot is gone
    assert ics.due_reminders(s, datetime(2026, 11, 9, 14, 55, tzinfo=JKT), seen) == ["Sync"]


def test_cancelled_override_and_event():
    s = ics.parse_ics(MASTER + vevent("UID:a", "RECURRENCE-ID;TZID=Asia/Jakarta:20261109T100000",
                                      "DTSTART;TZID=Asia/Jakarta:20261109T100000", "STATUS:CANCELLED", "SUMMARY:Sync")
                      + vevent("DTSTART:20261109T030000Z", "STATUS:CANCELLED", "SUMMARY:Nope"))
    assert not ics.events_on(s, date(2026, 11, 9), JKT)
    assert ics.events_on(s, date(2026, 11, 2), JKT)


def test_until_kind_mismatch_expands():
    a = vevent("DTSTART;TZID=Asia/Jakarta:20261102T100000", "RRULE:FREQ=DAILY;UNTIL=20261104", "SUMMARY:A")
    b = vevent("DTSTART:20261102T100000", "RRULE:FREQ=DAILY;UNTIL=20261104T030000Z", "SUMMARY:B")  # floating = machine zone
    got = lambda t: [d for d in range(1, 9) if ics.events_on(ics.parse_ics(t), date(2026, 11, d), JKT)]
    assert got(a) == [2, 3, 4]
    assert 2 in got(b) and 8 not in got(b)


def test_broken_series_is_skipped(monkeypatch):
    good = ics.parse_ics(vevent("DTSTART:20261109T030000Z", "SUMMARY:Good"))[0]
    bad = ics.parse_ics(vevent("DTSTART:20261109T030000Z", "SUMMARY:Bad"))[0]
    bad.rule = {"freq": "DAILY", "interval": 1, "until": date(2026, 11, 20)}  # date vs aware: raises TypeError
    assert [e.summary for e in ics.events_on([bad, good], date(2026, 11, 9), JKT)] == ["Good"]


def test_malformed_url_keeps_series_and_hides_url(capsys):
    c = ics.Calendar("")
    c.series = ["kept"]
    c.url = "not-a-url-SECRET123"
    c.fetch_once()
    assert c.series == ["kept"]
    assert "SECRET123" not in capsys.readouterr().err


def test_wkst_still_recurs():
    s = ics.parse_ics(vevent("DTSTART:20261102T030000Z", "RRULE:FREQ=WEEKLY;WKST=SU;COUNT=3", "SUMMARY:W"))
    assert [d for d in range(1, 30) if ics.events_on(s, date(2026, 11, d), JKT)] == [2, 9, 16]
