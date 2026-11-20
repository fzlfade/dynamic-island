"""Regression tests for the final whole-branch review findings."""
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from PySide6.QtGui import QGuiApplication

from island import ics, notifications, system


def _join_workers():
    for t in threading.enumerate():
        if t is not threading.main_thread() and t.daemon:
            t.join(5)


# 1. calendar: recurrence expansion never runs on the UI thread (it also hosts the system-wide keyboard hook)
def test_calendar_rows_and_check_never_expand_on_ui_thread(island, monkeypatch):
    calls = []
    real = ics.events_on
    monkeypatch.setattr(ics, "events_on", lambda *a: calls.append(threading.current_thread()) or real(*a))
    island.calendar.series = ics.parse_ics(
        "BEGIN:VEVENT\nDTSTART:20160101T090000Z\nRRULE:FREQ=DAILY\nSUMMARY:Daily\nEND:VEVENT\n")
    island.calendar.days = {}  # new data: nothing built yet
    island._calendar_rows()
    island._calendar_check()
    _join_workers()
    assert calls and all(t is not threading.main_thread() for t in calls)
    calls.clear()
    assert [summary for summary, _ in island._calendar_rows()] == ["Daily"], "built off-thread, then just read"
    assert calls == [], "reading the rows expands nothing"


# 2. back online: calendar and weather refetch right away instead of waiting 15-30 minutes
def test_coming_online_refreshes_calendar_and_weather(island, monkeypatch):
    refreshed = []
    monkeypatch.setattr(island.calendar, "refresh", lambda: refreshed.append("calendar"))
    island.weather = NS(refresh=lambda: refreshed.append("weather"), now=None)
    island.network = (False, None)
    monkeypatch.setattr(system, "fullscreen_app_running", lambda: False)
    from island import network
    monkeypatch.setattr(network, "network_state", lambda: (True, "Home"))
    island.check_network()
    assert sorted(refreshed) == ["calendar", "weather"]


# 3. a reminder on screen survives an instant popup and a fullscreen app
def test_instant_popup_requeues_visible_reminder(island):
    island.notify(("popup", "x", "To-do", "Call mom"))
    assert island.hud[2] == "To-do"
    island._show_hud(("popup", "y", "Slack", "hi"))
    assert island.queue and island.queue[0][0][2] == "To-do", "the reminder waits to be shown again"


def test_fullscreen_requeues_visible_reminder(island, monkeypatch):
    island.notify(("popup", "x", "Prayer", "Ashar"))
    monkeypatch.setattr(system, "fullscreen_app_running", lambda: True)
    island._check_fullscreen()
    assert not island.isVisible()
    assert island.queue and island.queue[0][0][2] == "Prayer"


# 4. Ask: a newer question owns the page; an unexpected error never leaves it streaming
class FakeClient:
    def __init__(self, raises=None):
        self.raises = raises
        self.beta = NS(messages=NS(stream=self._stream))

    @contextmanager
    def _stream(self, **kw):
        if self.raises:
            raise self.raises
        yield NS(text_stream=iter(["old ", "answer"]), get_final_message=lambda: NS(stop_reason="end_turn"))


def test_unexpected_error_ends_streaming(island, qapp):
    island.ask_page.start("q")
    island.asker.ask("q", client=FakeClient(raises=RuntimeError("boom")))
    island.asker.thread.join(5)
    qapp.processEvents()
    assert island.ask_page.state == "error" and not island.ask_page.animating()


def test_stale_answer_does_not_mix_into_new_question(island, qapp):
    island.ask_page.start("first")
    island.asker.ask("first", client=FakeClient())
    first = island.asker.thread
    island.ask_page.start("second")
    island.asker.ask("second", client=NS(beta=NS(messages=NS(stream=_never))))  # second stays pending
    first.join(5)
    qapp.processEvents()
    assert island.ask_page.text == "" and island.ask_page.state == "streaming", "first answer was ignored"


@contextmanager
def _never(**kw):
    import time
    time.sleep(0.5)
    yield NS(text_stream=iter([]), get_final_message=lambda: NS(stop_reason="end_turn"))


# 6. notification pill: setting to switch it off, and quiet while Windows isn't accepting notifications
def test_notification_pill_respects_setting_and_quiet_mode(island, monkeypatch):
    monkeypatch.setattr(system, "notifications_quiet", lambda: True)
    island.notified.emit("Slack", "secret message")
    assert not island._hud_active(), "quiet hours / presentation: nothing on screen"
    monkeypatch.setattr(system, "notifications_quiet", lambda: False)
    island.notif_pill = False
    island.notified.emit("Slack", "secret message")
    assert not island._hud_active(), "notif_pill=0 turns it off"
    island.notif_pill = True
    island.notified.emit("Slack", "hi")
    assert island._hud_active() and island.hud[2] == "Slack"


def test_notifications_quiet_reads_windows_state(monkeypatch):
    import ctypes

    def fake_state(ptr):
        ctypes.cast(ptr, ctypes.POINTER(ctypes.c_int))[0] = 6  # QUNS_QUIET_TIME
        return 0
    monkeypatch.setattr(system, "_query_notification_state", fake_state)
    assert system.notifications_quiet()
