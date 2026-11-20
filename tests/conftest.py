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
