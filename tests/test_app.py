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


def test_notify_queues_while_hidden(island):
    island.setVisible(False)
    island.notify(("popup", "x", "Due", "now"))
    assert not island._hud_active()
    island.setVisible(True)
    island._drain()
    assert island._hud_active() and island.hud[2] == "Due"
    assert island._island_rect().height() == app.BATTERY_POPUP[1]


def test_notify_drops_stale(island, monkeypatch, tmp_path):
    now = [1000.0]
    monkeypatch.setattr(app.time, "monotonic", lambda: now[0])
    island.setVisible(False)
    island.notify(("popup", "", "To-do", "Call mom"))
    now[0] += 11 * 60
    island.setVisible(True)
    island._drain()
    assert not island._hud_active() and not island.queue
    island.notify(("popup", "", "To-do", "Call mom"))
    island.grab().save(str(tmp_path / "popup.png"))


def test_notify_serializes(island):
    island.notify(("popup", "x", "First", ""))
    island.notify(("popup", "x", "Second", ""))
    assert island.hud[2] == "First"
    island._drain()
    assert island.hud[2] == "First", "waits while the first is showing"
    island.hud_until = 0
    island._drain()
    assert island._hud_active() and island.hud[2] == "Second"


def test_notify_waits_while_expanded(island):
    island._set_expand(1.0)
    island.notify(("popup", "x", "Due", "now"))
    assert not island._hud_active(), "a HUD drawn under the open island would be lost"
    island._set_expand(0.0)
    island._drain()
    assert island.hud[2] == "Due"


def test_autostart_roundtrip():
    import winreg
    name = "DynamicIslandTest"
    try:
        app.set_autostart(True, name)
        assert app.autostart_enabled(name)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, app.RUN_KEY) as k:
            assert winreg.QueryValueEx(k, name)[0].endswith('dynamic_island.py"')
        app.set_autostart(False, name)
        assert not app.autostart_enabled(name)
    finally:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, app.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass


def test_network_popup_and_errors(island, monkeypatch, tmp_path, capsys):
    from island import network
    island.network = (False, None)
    monkeypatch.setattr(network, "network_state", lambda: (True, "Home"))
    island.check_network()
    assert island.hud == ("popup", "\uE701", "Connected", "Home") and island.network == (True, "Home")
    assert island._island_rect().height() == app.BATTERY_POPUP[1]
    island.grab().save(str(tmp_path / "wifi_on.png"))
    island.check_network()  # unchanged: no new popup
    island._show_hud(("volume", 0.5, False))
    island.check_network()
    assert island.hud[0] == "volume"
    monkeypatch.setattr(network, "network_state", lambda: (False, None))
    island.check_network()
    assert island.hud[2:] == ("Disconnected", "No internet")
    island.grab().save(str(tmp_path / "wifi_off.png"))

    def boom():
        raise OSError("winrt")
    monkeypatch.setattr(network, "network_state", boom)
    island._show_hud(("volume", 0.5, False))
    island.check_network()
    assert island.network == (False, None) and island.hud[0] == "volume"
    assert "winrt" in capsys.readouterr().err


def test_hud_timer_precise_and_restarts_early_fire(island):
    assert island.hud_timer.timerType() == app.Qt.TimerType.PreciseTimer
    island._show_hud(("volume", 0.5, False))
    island.hud_timer.stop()
    island._hud_expired()  # fired while still active: must re-arm, not finish
    assert island.hud_timer.isActive()


def test_notify_requeued_when_expanding(island):
    island.notify(("popup", "x", "Due", "now"))
    assert island.hud[2] == "Due" and not island.queue
    island._animate_to(1.0)
    assert [q[0][2] for q in island.queue] == ["Due"]
    island.anim.stop()
    island._set_expand(0.0)
    island.hud_until = 0
    island._drain()
    assert island.hud[2] == "Due"


def test_instant_hud_not_requeued(island):
    island._show_hud(("volume", 0.5, False))
    island._animate_to(1.0)
    assert not island.queue


def test_audio_popup_and_errors(island, monkeypatch, tmp_path, capsys):
    dev = {"v": ("b", "Buds Pro")}
    monkeypatch.setattr(island.volume, "default_device", lambda: dev["v"])
    island.audio = ("a", "Speakers")
    island.check_audio()
    assert island.hud == ("popup", "\uE7F6", "Audio output", "Buds Pro") and island.audio == ("b", "Buds Pro")
    island.grab().save(str(tmp_path / "audio.png"))

    def boom():
        raise OSError("mm")
    monkeypatch.setattr(island.volume, "default_device", boom)
    island._show_hud(("volume", 0.5, False))
    island.check_audio()
    assert island.audio == ("b", "Buds Pro") and island.hud[0] == "volume"
    assert "mm" in capsys.readouterr().err
