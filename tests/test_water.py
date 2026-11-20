from datetime import datetime

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from island import store, water
from island.water import Water

D = "20261121"


def at(h, m=0):
    return datetime(2026, 11, 21, h, m)


def w(**kv):
    return Water({"day": D, **{k: str(v) for k, v in kv.items()}})


def test_due_interval_and_window():
    assert w(last=480).due(at(9))
    assert not w(last=480).due(at(8, 30))
    assert not w(start=600, last=0).due(at(9))
    assert not w(end=600, last=0).due(at(10))
    assert not w(taken=1500, last=0).due(at(12))


def test_drink_and_refill():
    x = w(taken=0)
    assert x.drink(at(9)) is None and x.taken == 250
    assert x.drink(at(9)) == ("Time to Refill", "Your bottle is probably empty") and x.taken == 500
    assert x.drink(at(9)) is None


def test_new_day_resets():
    x = Water({"day": "20261120", "taken": "750"})
    x.roll(at(9))
    assert (x.taken, x.day) == (0, D)


def test_bad_values_use_defaults():
    x = Water({"bottle": "x", "goal": "-5", "glass": "0", "every": "", "taken": "oops"})
    assert (x.bottle, x.goal, x.glass, x.every, x.taken) == (500, 1500, 250, 60, 0)


def test_remind_records_last_and_roundtrips():
    x = w(last=0)
    assert x.remind(at(9)) == ("popup", "\uE9CA", "Time to Drink", "0 / 1500 ml")
    assert x.remind(at(9, 30)) is None
    assert Water(x.to_kv() | {k: str(v) for k, v in x.to_kv().items()}).last == 540


def test_click_runs_popup_action(island):
    island.water = w(last=0)
    hits = []
    island.popup_actions["Time to Drink"] = lambda: hits.append(1)
    island._set_expand(0.0)
    island._show_hud(("popup", "\uE9CA", "Time to Drink", "0 / 1500 ml"))
    click = lambda: island.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    click()
    assert hits == [1] and not island._hud_active(), "click triggers the action and dismisses the popup"
    click()
    assert hits == [1], "no popup, no action"


def test_island_drink_saves(island):
    island.drink()
    assert island.water.taken == 250 and store.load_kv("water.txt")["taken"] == "250"
