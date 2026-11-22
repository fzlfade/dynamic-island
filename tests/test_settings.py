"""The settings window: shows what's saved, saves what you change, and the island picks it up without a restart."""
from PySide6.QtCore import QTime

from island import app, settings, store


def _window(island):
    w = settings.SettingsWindow(island)
    return w, w.widgets


def test_shows_defaults_when_nothing_is_saved(island):
    _, f = _window(island)
    assert f["focus"].value() == 25 and f["short_break"].value() == 5 and f["long_break"].value() == 15
    assert f["goal"].value() == 1500 and f["every"].value() == 60
    assert f["start"].time() == QTime(8, 0) and f["end"].time() == QTime(0, 0), "00:00 means midnight"
    assert f["notif_pill"].isChecked() and not f["prayer"].isChecked()
    assert f["prayer_method"].currentText() == "Kemenag RI"
    assert f["auto_location"].isChecked() and f["calendar_url"].text() == ""


def test_shows_what_is_saved(island):
    store.save_kv("settings.txt", {"focus": "30", "prayer": "1", "prayer_method": "JAKIM", "notif_pill": "0",
                                   "calendar_url": "https://x.test/basic.ics", "lat": "1.35", "lon": "103.82",
                                   "place": "Singapore"})
    store.save_kv("water.txt", {"goal": "2000", "every": "45", "start": "420", "taken": "750"})
    _, f = _window(island)
    assert f["focus"].value() == 30 and f["prayer"].isChecked() and f["prayer_method"].currentText() == "JAKIM"
    assert not f["notif_pill"].isChecked() and f["calendar_url"].text() == "https://x.test/basic.ics"
    assert f["goal"].value() == 2000 and f["every"].value() == 45 and f["start"].time() == QTime(7, 0)
    assert not f["auto_location"].isChecked() and f["place"].text() == "Singapore" and f["lat"].value() == 1.35


def test_save_writes_files_and_keeps_other_data(island):
    store.save_kv("settings.txt", {"lat": "1.35", "lon": "103.82", "place": "Singapore", "custom": "keep me"})
    store.save_kv("water.txt", {"day": "20261121", "taken": "750", "last": "600"})
    w, f = _window(island)
    f["focus"].setValue(40)
    f["goal"].setValue(2500)
    f["end"].setTime(QTime(0, 0))
    w.save()
    s, wt = store.load_kv("settings.txt"), store.load_kv("water.txt")
    assert s["focus"] == "40" and s["custom"] == "keep me" and s["place"] == "Singapore"
    assert wt["goal"] == "2500" and wt["end"] == "1440", "midnight is the end of the day"
    assert (wt["day"], wt["taken"], wt["last"]) == ("20261121", "750", "600"), "today's progress survives"


def test_auto_location_clears_saved_coordinates(island):
    store.save_kv("settings.txt", {"lat": "1.35", "lon": "103.82", "place": "Singapore"})
    w, f = _window(island)
    f["auto_location"].setChecked(True)
    w.save()
    assert not {"lat", "lon", "place"} & set(store.load_kv("settings.txt")), "next start detects again"


def test_saving_applies_without_restart(island, monkeypatch):
    refreshed = []
    monkeypatch.setattr(app.ics.Calendar, "refresh", lambda self: refreshed.append(self.url))
    island.water.taken = 500
    w, f = _window(island)
    f["notif_pill"].setChecked(False)
    f["prayer"].setChecked(True)
    f["prayer_method"].setCurrentText("MUIS")
    f["goal"].setValue(3000)
    f["calendar_url"].setText("https://x.test/new.ics")
    w.save()
    assert island.notif_pill is False
    assert island.prayer.enabled and island.prayer.method == "MUIS"
    assert island.water.goal == 3000 and island.water.taken == 500, "today's progress is kept"
    assert island.calendar.url == "https://x.test/new.ics" and refreshed == ["https://x.test/new.ics"]


def test_prayer_keeps_its_location_across_a_save(island):
    island.prayer.set_location(-6.2, 106.8)
    w, _ = _window(island)
    w.save()
    assert island.prayer.loc == (-6.2, 106.8)


def test_start_with_windows_box_uses_the_registry_helper(island, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "autostart_enabled", lambda *a: False)
    monkeypatch.setattr(app, "set_autostart", lambda on, *a: calls.append(on))
    w, f = _window(island)
    f["autostart"].setChecked(True)
    w.save()
    assert calls == [True]


def test_tray_and_island_open_settings(island, monkeypatch):
    opened = []
    monkeypatch.setattr(island, "open_settings", lambda *section: opened.append(1))
    tray = app.make_tray(island)
    try:
        {a.text(): a for a in tray.contextMenu().actions()}["Settings…"].trigger()
    finally:
        tray.hide()
    island.water_page.on_settings()  # the Water page's Settings button
    assert opened == [1, 1]
    assert "settings" not in island.page_hits, "like Nusa, the island itself has no gear"


def test_pages_order_and_switches_are_saved_and_applied(island):
    w, f = _window(island)
    pages = f["pages"]
    pages._move("todo", -5)  # To-do to the top
    pages.switches["water"].setChecked(False)
    w.save()
    assert store.load_kv("settings.txt")["pages"] == "todo,media,widgets,focus,shelf"
    assert island.pages == [island.todo_page, island.media_page, island.widgets_page, island.focus_page,
                            island.shelf_page]


def test_open_on_click_and_fast_motion(island):
    w, f = _window(island)
    f["open_click"].setCurrentText("Click")
    f["fast_animation"].setCurrentText("Fast")
    w.save()
    assert island.on_click and island.fast and island.page_anim.duration() < 380


def test_hud_switches_take_effect(island):
    w, f = _window(island)
    f["hud_caps"].setChecked(False)
    w.save()
    assert not island.on("hud_caps") and island.on("hud_volume")
    island.show_caps()
    assert not island._hud_active(), "Caps Lock HUD switched off"


def test_closing_saves_like_nusa(island):
    w, f = _window(island)
    f["focus"].setValue(45)
    w.close()
    assert store.load_kv("settings.txt")["focus"] == "45"


def test_water_page_opens_the_water_section(island):
    island.open_settings("Water")
    win = island.settings_window
    try:
        assert win.stack.currentIndex() == win.section_index["Water"]
    finally:
        win.close()


def test_segmented_works_from_the_keyboard(qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    seg = settings.Segmented(["Hover", "Click"])
    assert seg.focusPolicy() == Qt.StrongFocus, "Tab reaches it"
    seg.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
    assert seg.currentText() == "Click"
    seg.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.NoModifier))
    assert seg.currentText() == "Hover"


def test_opens_on_the_section_asked_for(island):
    w = settings.SettingsWindow(island, "Appearance")
    assert w.stack.currentIndex() == w.section_index["Appearance"], "the island's gear and tray links open a section"
