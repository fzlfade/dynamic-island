import ctypes
from ctypes import wintypes

from island import app, system

LRC = [(5.0, "intro"), (10.0, "first"), (20.5, "chorus"), (30.0, ""), (60.0, "chorus")]


def test_rendering_and_render_timer(island, fake_media, tmp_path):
    img = island.grab().toImage()
    assert img.pixelColor(app.WIN_W // 2, 5).alpha() == 255, "pill should be opaque at top centre"
    assert img.pixelColor(5, 100).alpha() == 0, "outside the pill must be transparent (click-through)"

    fake_media.changed.emit({"title": "A very long song title that must be elided", "artist": "Artist", "playing": True, "thumb": b""})
    assert island.frame.isActive(), "render timer runs while playing"
    island.grab().save(str(tmp_path / "collapsed.png"))

    island._set_expand(1.0)
    img = island.grab().toImage()
    assert set(island.buttons) == {"prev", "toggle", "next"}
    assert img.pixelColor(app.WIN_W // 2, 110).alpha() == 255, "expanded island reaches its full height"

    fake_media.changed.emit({"title": "x", "artist": "y", "playing": False})
    assert not island.frame.isActive(), "render timer stops when paused (idle like Nusa)"


def _with_lyrics(fake_media):
    fake_media.changed.emit({"title": "Song", "artist": "Artist", "playing": False, "pos": 12.0, "pos_at": 0, "lyrics": LRC})


def test_lyrics_line_and_widening(island, fake_media, tmp_path):
    _with_lyrics(fake_media)
    assert island._lyric() == "first"
    fake_media.changed.emit({**island.info, "pos": 31.0})
    assert island._lyric() == "♪", "instrumental gap shows a note"
    fake_media.changed.emit({**island.info, "pos": 21.0})
    island._set_expand(0.0)
    assert island._island_rect().width() == app.COLLAPSED_LYRICS[0], "collapsed island widens for lyrics"
    island.grab().save(str(tmp_path / "lyrics_collapsed.png"))
    island._set_expand(1.0)
    island.grab().save(str(tmp_path / "lyrics_expanded.png"))


def test_volume_hud_expires(island, fake_media, tmp_path):
    _with_lyrics(fake_media)
    fake_media.changed.emit({**island.info, "pos": 21.0})
    island._set_expand(0.0)
    island.show_volume(0.42, False)
    assert island._island_rect().width() == app.HUD[0]
    island.grab().save(str(tmp_path / "volume.png"))
    island.show_volume(0.42, True)
    island.grab().save(str(tmp_path / "volume_muted.png"))
    island.hud_until = 0
    assert island._island_rect().width() == app.COLLAPSED_LYRICS[0], "HUD expires"


def test_brightness_hud(island, tmp_path):
    island.on_brightness(70)
    assert not island._hud_active(), "first notification is the current value, not a change"
    island.on_brightness(60)
    assert island._hud_active() and island.hud == ("brightness", 0.6, False)
    island.grab().save(str(tmp_path / "brightness.png"))
    island.hud_until = 0
    island.on_brightness(60)
    assert not island._hud_active(), "same value again does not flash the HUD"


def test_native_power_broadcast_brightness(island):
    island.on_brightness(70)  # baseline: the first reading never shows the HUD
    setting = ctypes.create_string_buffer(bytes(system.GUID_VIDEO_BRIGHTNESS) + (4).to_bytes(4, "little") + (35).to_bytes(4, "little"))
    msg = wintypes.MSG(message=0x218, wParam=0x8013, lParam=ctypes.addressof(setting))
    assert island.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg)) == (False, 0)
    assert island.hud == ("brightness", 0.35, False) and island.brightness == 35


def test_caps_hud(island, tmp_path):
    island.show_caps()
    real = bool(ctypes.windll.user32.GetKeyState(system.VK_CAPITAL) & 1)
    assert island._hud_active() and island.hud == ("caps", 1.0 if real else 0.0, False)
    island._show_hud(("caps", 1.0, False))
    island.grab().save(str(tmp_path / "caps_on.png"))
    island._show_hud(("caps", 0.0, False))
    island.grab().save(str(tmp_path / "caps_off.png"))


def test_language_hud(island, monkeypatch, tmp_path):
    for fg, lang, expect_hud in [(1, 0x0409, False),   # first look: baseline only
                                 (1, 0x0409, False),   # nothing changed
                                 (1, 0x3809, True),    # same window, new language -> HUD
                                 (2, 0x0409, False)]:  # switched window (per-app input): not a change
        island.hud_until = 0
        monkeypatch.setattr(system, "foreground_layout", lambda fg=fg, lang=lang: (fg, lang))
        island.check_language()
        assert island._hud_active() == expect_hud, (fg, lang)
    monkeypatch.setattr(system, "foreground_layout", lambda: (2, 0x3809))
    island.check_language()
    assert island.hud == ("language", 0x3809, False)
    island.grab().save(str(tmp_path / "language.png"))


def test_battery_hud(island, monkeypatch, tmp_path):
    island.battery = (False, 79, False)
    monkeypatch.setattr(system, "battery_status", lambda: (True, 79, False))
    island.check_battery()
    assert island.hud[0] == "battery" and island._island_rect().height() == app.BATTERY_POPUP[1]
    island.grab().save(str(tmp_path / "battery_plugged.png"))
    island._show_hud(("battery", 0.18, False, False, "Low battery", "Plug in soon"), 3)
    island.grab().save(str(tmp_path / "battery_low.png"))
    island._show_hud(("battery", 0.79, True, True, "Charger connected", "Charging · 79%"), 3)
    island.grab().save(str(tmp_path / "battery_charging.png"))
