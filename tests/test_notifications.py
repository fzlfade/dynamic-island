import asyncio
from types import SimpleNamespace as NS

from island import notifications


class FakeListener:
    """Stands in for UserNotificationListener: each get_notifications_async returns the next batch of toasts."""

    def __init__(self, batches, status=1):
        self.batches, self.status = list(batches), status

    async def request_access_async(self):
        return self.status

    async def get_notifications_async(self, kind):
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return [_toast(i) for i in batch]


def _toast(i):
    texts = [NS(text=f"title {i}"), NS(text=f"body {i}")]
    binding = NS(get_text_elements=lambda: texts)
    return NS(id=i, app_info=NS(display_info=NS(display_name=f"App {i}")),
              notification=NS(visual=NS(get_binding=lambda kind: binding)))


def test_second_poll_returns_only_new(qapp):
    lis = notifications.Listener(FakeListener([[1, 2], [1, 2, 3]]))
    assert lis.available
    assert lis.poll() == [], "first poll only records what is already in the action center"
    assert lis.poll() == [("App 3", "title 3", "body 3")]


def test_denied_access_is_unavailable_and_silent(qapp):
    lis = notifications.Listener(FakeListener([[1]], status=2))
    assert not lis.available and lis.poll() == []


def test_read_error_keeps_baseline(qapp, capsys):
    lis = notifications.Listener(FakeListener([[1], OSError("boom"), [1, 2]]))
    lis.poll()
    assert lis.poll() == []
    assert "OSError" in capsys.readouterr().err
    assert lis.poll() == [("App 2", "title 2", "body 2")], "the failed read did not reset what was seen"


class Op:
    """Awaitable but not a coroutine, like a real WinRT IAsyncOperation."""

    def __init__(self, value):
        self.value = value

    def __await__(self):
        return self.value
        yield


class WinRTStyleListener(FakeListener):
    def request_access_async(self):
        return Op(self.status)

    def get_notifications_async(self, kind):
        return Op([_toast(i) for i in self.batches.pop(0)])


def test_works_with_winrt_style_awaitables(qapp):
    lis = notifications.Listener(WinRTStyleListener([[1], [1, 4]]))
    assert lis.available
    lis.poll()
    assert lis.poll() == [("App 4", "title 4", "body 4")]


def test_new_notification_shows_pill(island, monkeypatch):
    island.notifier = notifications.Listener(FakeListener([[], [7]]))
    island.notifier.poll()
    island._notif_poll()
    assert island._hud_active() and island.hud == ("popup", "", "App 7", "title 7")
    import time
    assert island.hud_until - time.monotonic() > 3, "long enough to read, like reminders"


def test_poll_never_runs_on_the_ui_thread(island, qapp):
    import threading
    threads = []
    island.notifier = NS(poll=lambda: threads.append(threading.current_thread()) or [])
    island._notif_check()
    island._notif_thread.join(5)
    assert threads and threads[0] is not threading.main_thread(), "a ~40 ms WinRT read would stutter the animation"


def test_listener_is_created_on_the_worker_thread(island, qapp, monkeypatch):
    # Qt makes the UI thread a COM single-threaded apartment: a listener made there fails when used from the worker
    import threading
    made_on = []

    class Spy:
        def __init__(self):
            made_on.append(threading.current_thread())

        def poll(self):
            return []
    monkeypatch.setattr(notifications, "Listener", Spy)
    island.notifier = None
    island._notif_check()
    island._notif_thread.join(5)
    assert made_on and made_on[0] is not threading.main_thread()
