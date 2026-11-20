import os
os.environ.setdefault("QT_QPA_PLATFORM", "windows")  # real fonts; windows flash briefly during tests

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


class FakeMedia(QObject):
    changed = Signal(dict)

    def __init__(self):
        super().__init__()
        self.sent = []

    def send(self, action):
        self.sent.append(action)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fake_media(qapp):
    return FakeMedia()


@pytest.fixture
def island(qapp, fake_media):
    from island.app import Island
    w = Island(fake_media)
    yield w
    w._weather_thread.join(5)  # no thread may outlive the test's monkeypatches
    w.close()


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    from island import store
    monkeypatch.setattr(store, "DIR_OVERRIDE", tmp_path)


@pytest.fixture(autouse=True)
def _no_weather_io(monkeypatch):
    from island import http, weather

    def no_geo():
        raise OSError("tests never use the real Geolocator")
    monkeypatch.setattr(weather, "_geolocate", no_geo)

    def no_net(*a, **k):
        raise OSError("tests never touch the network")
    monkeypatch.setattr(http, "get", no_net)


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    from island import notifications

    def no_listener():
        raise OSError("tests never read the user's real notifications")
    monkeypatch.setattr(notifications, "default_listener", no_listener)
    import ctypes
    from island import system

    def accepting(ptr):  # QUNS_ACCEPTS_NOTIFICATIONS, not the machine's real Do Not Disturb / fullscreen state
        ctypes.cast(ptr, ctypes.POINTER(ctypes.c_int))[0] = 5
        return 0
    monkeypatch.setattr(system, "_query_notification_state", accepting)
