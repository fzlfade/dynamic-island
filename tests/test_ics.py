import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from island import ics

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


class Resp:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self):
        return self.data


def test_calendar_fetch_failure_keeps_events(monkeypatch):
    calls = []

    def fake(req, timeout=None):
        calls.append((req.full_url, timeout, req.get_header("User-agent")))
        if len(calls) > 1:
            raise urllib.error.URLError("down")
        return Resp(TEXT.encode())

    monkeypatch.setattr("urllib.request.urlopen", fake)
    c = ics.Calendar("webcal://example.com/x.ics")
    c.fetch_once()
    first = c.series
    assert len(first) == 9
    c.fetch_once()
    assert c.series is first
    assert calls[0] == ("https://example.com/x.ics", 10, "DynamicIsland/0.1")


def test_calendar_without_url_does_nothing(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: 1 / 0)
    c = ics.Calendar("")
    c.fetch_once()
    assert c.series == []
