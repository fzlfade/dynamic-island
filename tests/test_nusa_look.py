"""Behaviour copied from measurements of Nusa 1.3.1 (sizes, hover dwell, water's hourly log and switch)."""
from datetime import datetime

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from island import app, store
from island.water import Water


def test_sizes_match_nusa():
    assert app.EXPANDED == (455.0, 197.0) and app.MINIMAL == (53.0, 4.0)
    assert (app.EAR, app.CORNER) == (22.0, 36.0)


def test_notch_path_has_flared_ears():
    from PySide6.QtCore import QRectF
    r = QRectF(100, 0, 455, 197)
    path = app.notch_path(r, app.EAR, app.CORNER)
    assert path.contains(QPointF(r.left() - 14, 1)), "ear flares out at the bezel (Nusa: 16 px at y=1)"
    assert not path.contains(QPointF(r.left() - 18, 20)), "and curves back in below"
    assert not path.contains(QPointF(r.left() + 2, r.bottom() - 2)), "bottom corners are rounded"


def test_hover_waits_and_swells_before_opening(island):
    move = lambda y: island.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(app.WIN_W / 2, y), QPointF(0, 0),
                                                       Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    move(2)
    assert island.dwell.isActive() and island.expand == 0.0, "no instant open: the pointer must rest a moment"
    assert island.peek_anim.endValue() == 1.0, "the pill swells while it waits"
    assert island.dwell.interval() == 200 and island.leave_delay.interval() == 90


def test_water_logs_each_hour_and_keeps_the_switch(tmp_path):
    w = Water({"goal": "1500"})
    now = datetime(2026, 11, 22, 10, 15)
    w.drink(now)
    w.drink(datetime(2026, 11, 22, 10, 50))
    assert w.hours[10] == 500 and sum(w.hours) == 500
    kv = {k: str(v) for k, v in w.to_kv().items()}
    again = Water(kv)
    assert again.hours[10] == 500 and again.on, "hours and switch survive a save"
    again.on = False
    assert not again.due(datetime(2026, 11, 22, 12, 0)), "reminders off: never due"
    again.roll(datetime(2026, 11, 23, 9, 0))
    assert sum(again.hours) == 0, "a new day starts an empty chart"


def test_water_switch_on_the_page_saves(island):
    was = island.water.on
    island.toggle_water()
    assert island.water.on is not was and store.load_kv("water.txt")["on"] == str(int(island.water.on))
