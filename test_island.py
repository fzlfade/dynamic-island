"""Offscreen self-check: renders the island collapsed and expanded with fake media.  python test_island.py"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import dynamic_island as di


class FakeMedia(QObject):
    changed = Signal(dict)
    sent = []

    def send(self, action):
        self.sent.append(action)


app = QApplication([])
media = FakeMedia()
island = di.Island(media)

# no media: small grey pill
img = island.grab().toImage()
assert img.pixelColor(di.WIN_W // 2, 5).alpha() == 255, "pill should be opaque at top centre"
assert img.pixelColor(5, 100).alpha() == 0, "outside the pill must be transparent (click-through)"

media.changed.emit({"title": "A very long song title that must be elided", "artist": "Artist", "playing": True, "thumb": b""})
assert island.frame.isActive(), "render timer runs while playing"
island.grab().save("shot_collapsed.png")

island._set_expand(1.0)
img = island.grab().toImage()
img.save("shot_expanded.png")
assert set(island.buttons) == {"prev", "toggle", "next"}
assert img.pixelColor(di.WIN_W // 2, 110).alpha() == 255, "expanded island reaches its full height"

media.changed.emit({"title": "x", "artist": "y", "playing": False})
assert not island.frame.isActive(), "render timer stops when paused (idle like Nusa)"

# lyrics: parser handles repeated stamps, blank lines and out-of-order stamps
lrc = di.parse_lrc("[00:10.00] first\n[00:20.50][01:00.00] chorus\n[00:30.00]\n[00:05.00] intro\nno stamp")
assert lrc == [(5.0, "intro"), (10.0, "first"), (20.5, "chorus"), (30.0, ""), (60.0, "chorus")], lrc
assert di.line_at(lrc, 4.9) == "" and di.line_at(lrc, 10.0) == "first" and di.line_at(lrc, 25) == "chorus"
assert di.line_at(lrc, 999) == "chorus"

media.changed.emit({"title": "Song", "artist": "Artist", "playing": False, "pos": 12.0, "pos_at": 0, "lyrics": lrc})
assert island._lyric() == "first"
media.changed.emit({**island.info, "pos": 31.0})
assert island._lyric() == "♪", "instrumental gap shows a note"
media.changed.emit({**island.info, "pos": 21.0})
island._set_expand(0.0)
assert island._island_rect().width() == di.COLLAPSED_LYRICS[0], "collapsed island widens for lyrics"
island.grab().save("shot_lyrics_collapsed.png")
island._set_expand(1.0)
island.grab().save("shot_lyrics_expanded.png")

# volume HUD: replaces the compact view, widens, then expires back to the media layout
island._set_expand(0.0)
island.show_volume(0.42, False)
assert island._island_rect().width() == di.HUD[0]
island.grab().save("shot_volume.png")
island.show_volume(0.42, True)
island.grab().save("shot_volume_muted.png")
island.hud_until = 0
assert island._island_rect().width() == di.COLLAPSED_LYRICS[0], "HUD expires"


# brightness HUD: initial value is silent, changes show, repeats don't
island.on_brightness(70)
assert not island._hud_active(), "first notification is the current value, not a change"
island.on_brightness(60)
assert island._hud_active() and island.hud == ("brightness", 0.6, False)
island.grab().save("shot_brightness.png")
island.hud_until = 0
island.on_brightness(60)
assert not island._hud_active(), "same value again does not flash the HUD"

# parse a real POWERBROADCAST_SETTING the way Windows delivers it in WM_POWERBROADCAST
import ctypes
from ctypes import wintypes
setting = ctypes.create_string_buffer(bytes(di.GUID_VIDEO_BRIGHTNESS) + (4).to_bytes(4, "little") + (35).to_bytes(4, "little"))
msg = wintypes.MSG(message=0x218, wParam=0x8013, lParam=ctypes.addressof(setting))
assert island.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg)) == (False, 0)
assert island.hud == ("brightness", 0.35, False) and island.brightness == 35
island.hud_until = 0


# Caps Lock HUD reflects the real toggle state; both looks render
island.show_caps()
real = bool(ctypes.windll.user32.GetKeyState(di.VK_CAPITAL) & 1)
assert island._hud_active() and island.hud == ("caps", 1.0 if real else 0.0, False)
island._show_hud(("caps", 1.0, False))
island.grab().save("shot_caps_on.png")
island._show_hud(("caps", 0.0, False))
island.grab().save("shot_caps_off.png")
island.hud_until = 0


# input language HUD: names, and only same-window changes count
assert di.language_name(0x0409) == ("English (United States)", "EN-US"), di.language_name(0x0409)
assert di.language_name(0x3809) == ("English (Indonesia)", "EN-ID"), di.language_name(0x3809)
real_foreground_layout = di.foreground_layout
for fg, lang, expect_hud in [(1, 0x0409, False),   # first look: baseline only
                             (1, 0x0409, False),   # nothing changed
                             (1, 0x3809, True),    # same window, new language -> HUD
                             (2, 0x0409, False)]:  # switched window (per-app input): not a change
    island.hud_until = 0
    di.foreground_layout = lambda: (fg, lang)
    island.check_language()
    assert island._hud_active() == expect_hud, (fg, lang)
di.foreground_layout = lambda: (2, 0x3809)
island.check_language()
assert island.hud == ("language", 0x3809, False)
island.grab().save("shot_language.png")
di.foreground_layout = real_foreground_layout
island.layout = None
island.hud_until = 0


# battery popup rules: (prev, cur) -> popup.  status = (on AC, percent, charging)
bp = di.battery_popup
assert bp(None, (True, 79, False)) is None, "startup reading is a baseline"
assert bp((False, 79, False), (True, 79, True)) == ("Charger connected", "Charging · 79%")
assert bp((False, 79, False), (True, 79, False)) == ("Charger connected", "Plugged in · 79%"), "conservation mode"
assert bp((False, 100, False), (True, 100, False)) == ("Charger connected", "Fully charged")
assert bp((True, 79, False), (False, 79, False)) == ("Charger unplugged", "On battery · 79%")
assert bp((True, 99, True), (True, 100, False)) == ("Fully charged", "You can unplug")
assert bp((True, 100, False), (True, 100, False)) is None
assert bp((False, 21, False), (False, 20, False)) == ("Low battery", "Plug in soon")
assert bp((False, 20, False), (False, 19, False)) is None, "low fires once, on crossing"
assert bp((False, 11, False), (False, 10, False)) == ("Battery critical", "Plug in now")
assert bp((False, 22, False), (False, 9, False)) == ("Battery critical", "Plug in now"), "big drop: critical wins"
assert bp((True, 15, True), (True, 16, True)) is None, "charging upward: no low warning"

status = di.battery_status()
assert status is None or (isinstance(status[0], bool) and 0 <= status[1] <= 100), status
island.battery = (False, 79, False)
di_status = di.battery_status
di.battery_status = lambda: (True, 79, False)
island.check_battery()
assert island.hud[0] == "battery" and island._island_rect().height() == di.BATTERY_POPUP[1]
island.grab().save("shot_battery_plugged.png")
island._show_hud(("battery", 0.18, False, False, "Low battery", "Plug in soon"), 3)
island.grab().save("shot_battery_low.png")
island._show_hud(("battery", 0.79, True, True, "Charger connected", "Charging · 79%"), 3)
island.grab().save("shot_battery_charging.png")
di.battery_status = di_status
island.battery = None
island.hud_until = 0


class FakeVolume(di.Volume):
    def __init__(self, level, muted):
        self.state = (level, muted)

    def get(self):
        return self.state

    def set(self, level, muted):
        self.state = (max(0.0, min(1.0, level)), muted)
        return self.state


assert FakeVolume(0.99, True).step(0.02) == (1.0, False), "up clamps at 100 and unmutes"
assert FakeVolume(0.01, False).step(-0.02) == (0.0, False), "down clamps at 0"
assert FakeVolume(0.5, True).step(-0.02) == (0.48, True), "down keeps mute"
assert FakeVolume(0.5, False).toggle_mute() == (0.5, True)

# real device, non-destructive: write back exactly what we read
vol = di.Volume()
before = vol.get()
after = vol.set(*before)
assert abs(after[0] - before[0]) < 0.005 and after[1] == before[1], (before, after)

# Apple Music style artist field ("Artist — Album") must be cleaned before the LRCLIB query
seen = []
di.urllib.request.urlopen = lambda req, timeout: seen.append(req.full_url) or __import__("io").BytesIO(b"[]")
di.fetch_lyrics("Nutshell", "Alice In Chains — Jar of Flies - EP", 259)
assert "artist_name=Alice+In+Chains" in seen[0] and "Jar" not in seen[0], seen
print("ok")
