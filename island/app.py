"""Dynamic Island notch for Windows: now-playing media, synced lyrics, hover-to-expand controls.

Same building blocks as Nusa's core notch, rebuilt in Python:
  - topmost, no-activate, tool window centred on the top edge (Nusa: WS_EX_NOACTIVATE|TOPMOST|TOOLWINDOW)
  - media from WinRT GlobalSystemMediaTransportControlsSessionManager
  - render timer only runs while something animates (Nusa's adaptive "idle.log" frame loop)
  - hides while a fullscreen app/game runs (Nusa: SHQueryUserNotificationState, "hide_fullscreen")
  - synced lyrics from LRCLIB's search API, timed off the session's timeline (Nusa: lrclib.net/api/search)
  - volume HUD: low-level keyboard hook eats the volume keys, sets volume through Core Audio
    IAudioEndpointVolume and shows it in the island instead of the Windows flyout (Nusa: same APIs, "hud_volume")
  - brightness HUD: RegisterPowerSettingNotification(GUID_DEVICE_POWER_POLICY_VIDEO_BRIGHTNESS), listen-only
    (Nusa: same GUID in its binary, "hud_brightness")
  - Caps Lock HUD: same keyboard hook sees VK_CAPITAL, reads GetKeyState after the key lands (Nusa: "hud_caps")
  - battery popup: GetSystemPowerStatus on PBT_APMPOWERSTATUSCHANGE and every second; charger in/out, full,
    low, critical (Nusa: same import and popup texts, "popup_battery")
  - input language HUD: GetKeyboardLayout of the foreground window's thread, named via LCIDToLocaleName +
    GetLocaleInfoEx; checked after switch-key releases and every second (Nusa: same imports, "hud_language")

Run:  python dynamic_island.py      Quit: tray icon menu.
"""
import ctypes
import math
import os
import sys
import time
import winreg
from collections import deque
from ctypes import wintypes

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QAction, QColor, QIcon, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from island import store, system
from island.media import Media, line_at
from island.pages import MediaPage, TodayPage

COLLAPSED = (190.0, 34.0)
COLLAPSED_PLAYING = (260.0, 34.0)
COLLAPSED_LYRICS = (380.0, 34.0)
HUD = (300.0, 34.0)
HUD_SECONDS = 1.5
BATTERY_POPUP = (340.0, 64.0)
BATTERY_SECONDS = 3.0
EXPANDED = (400.0, 150.0)
WIN_W, WIN_H = 440, 170  # window fits the largest island; transparent pixels are click-through
NOTIFY_SECONDS = 4.0
NOTIFY_MAX_AGE = 600.0  # a reminder still queued after 10 min (hidden behind a fullscreen game) is dropped

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dynamic_island.py")


def set_autostart(on, key_name="DynamicIsland"):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            winreg.SetValueEx(k, key_name, 0, winreg.REG_SZ, f'"{pythonw}" "{SCRIPT}"')
        else:
            try:
                winreg.DeleteValue(k, key_name)
            except FileNotFoundError:
                pass


def autostart_enabled(key_name="DynamicIsland"):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, key_name)
        return True
    except FileNotFoundError:
        return False


def lerp(a, b, t):
    return a + (b - a) * t


class Island(QWidget):
    def __init__(self, media):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.media = media
        self.info = {}
        self.art = QPixmap()
        self.expand = 0.0  # 0 collapsed .. 1 expanded (overshoots slightly with OutBack)
        self.hovered = False
        self.buttons = {}
        self.hud = ("volume", 0.0, False)  # (kind, level 0..1, muted)
        self.brightness = None  # last reported %, None until Windows sends the initial value
        self.layout = None  # (foreground window, LANGID) last seen
        self.battery = None  # last battery_status()
        self.hud_until = 0.0
        self.queue = deque()  # (hud, seconds, created) reminders waiting for a visible, HUD-free island
        self.hud_timer = QTimer(self, singleShot=True, timeout=self._hud_expired)
        self.pages = []
        self.page = 0
        self.wheel = 0  # accumulated angle delta, so touchpads switch once per notch

        self.anim = QVariantAnimation(self, duration=420, easingCurve=QEasingCurve.OutBack)
        self.anim.valueChanged.connect(self._set_expand)
        self.anim.finished.connect(self._drain)  # reminders held while the island was open
        self.leave_delay = QTimer(self, singleShot=True, interval=350, timeout=lambda: self._animate_to(0.0))
        self.frame = QTimer(self, interval=16, timeout=self._frame_tick)  # only runs while something animates
        self.add_page(MediaPage())
        self.today = TodayPage()
        self.add_page(self.today)
        media.changed.connect(self._on_media)
        QTimer(self, interval=1000, timeout=self._check_fullscreen).start()

        screen = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(screen.x() + (screen.width() - WIN_W) // 2, screen.y(), WIN_W, WIN_H)
        self.show()
        hwnd = int(self.winId())  # WS_EX_NOACTIVATE: clicking the island never steals focus
        ctypes.windll.user32.SetWindowLongPtrW(hwnd, -20, ctypes.windll.user32.GetWindowLongPtrW(hwnd, -20) | 0x08000000)

    # --- state ---------------------------------------------------------------
    def _on_media(self, info):
        if "thumb" in info:
            self.art = QPixmap()
            self.art.loadFromData(info.pop("thumb"))
        self.info = info
        self._update_frame()
        self.update()

    def add_page(self, page):
        self.pages.append(page)
        self.update()

    def _update_frame(self):
        if not (self.info.get("playing") or any(pg.animating() for pg in self.pages)):
            self.frame.stop()
        elif not self.frame.isActive():
            self.frame.start()

    def _frame_tick(self):
        self.update()
        self._update_frame()

    def show_volume(self, level, muted):
        self._show_hud(("volume", level, muted))

    def nativeEvent(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x218 and msg.wParam == 0x8013:  # WM_POWERBROADCAST, PBT_POWERSETTINGCHANGE
            setting = ctypes.string_at(msg.lParam, 16)  # POWERBROADCAST_SETTING.PowerSetting GUID
            if setting == bytes(system.GUID_VIDEO_BRIGHTNESS):
                self.on_brightness(ctypes.c_uint32.from_address(msg.lParam + 20).value)  # Data: DWORD %
        if msg.message == 0x218 and msg.wParam == 0xA:  # PBT_APMPOWERSTATUSCHANGE: sent to every top-level window
            self.check_battery()
        return False, 0

    def check_battery(self):
        cur = system.battery_status()
        if cur is None:
            return  # keep the old baseline through 'unknown' blips
        popup = system.battery_popup(self.battery, cur)
        if popup:
            self._show_hud(("battery", cur[1] / 100, cur[2], cur[0], *popup), BATTERY_SECONDS)
        self.battery = cur

    def on_brightness(self, percent):
        # Windows sends the current value right after registering: remember it, don't flash the HUD
        if self.brightness is not None and percent != self.brightness:
            self._show_hud(("brightness", percent / 100, False))
        self.brightness = percent

    def show_caps(self):
        on = bool(system._user32.GetKeyState(system.VK_CAPITAL) & 1)  # low bit = toggled
        self._show_hud(("caps", 1.0 if on else 0.0, False))

    def _show_hud(self, hud, seconds=HUD_SECONDS):
        self.hud = hud
        self.hud_until = time.monotonic() + seconds
        self.hud_timer.start(int(seconds * 1000) + 20)
        self.update()

    def _hud_active(self):
        return time.monotonic() < self.hud_until

    def notify(self, hud, seconds=NOTIFY_SECONDS):
        """Queue a reminder: shown when the island is visible and no HUD is up, one at a time."""
        self.queue.append((hud, seconds, time.monotonic()))
        self._drain()

    def _drain(self):
        if not self.isVisible() or self._hud_active() or self.expand >= 0.5:  # HUDs only draw collapsed
            return
        while self.queue:
            hud, seconds, created = self.queue.popleft()
            if time.monotonic() - created <= NOTIFY_MAX_AGE:
                self._show_hud(hud, seconds)
                return

    def _hud_expired(self):
        self.update()
        self._drain()

    def check_language(self):
        current = system.foreground_layout()
        # only a change within the same window counts: with per-app input, switching windows changes the layout too
        if self.layout and current[0] == self.layout[0] and current[1] != self.layout[1]:
            self._show_hud(("language", current[1], False))  # level slot carries the LANGID
        self.layout = current

    def _check_fullscreen(self):
        self.setVisible(not system.fullscreen_app_running())
        self._drain()  # reminders queued behind a fullscreen app show once it closes
        self._update_frame()  # picks up pages that started animating on their own
        self.check_language()  # also catches switches made with the mouse from the taskbar
        self.check_battery()  # backup for the power broadcast

    def _set_expand(self, v):
        self.expand = v
        self.update()

    def _animate_to(self, target):
        self.anim.stop()
        self.anim.setStartValue(self.expand)
        self.anim.setEndValue(target)
        self.anim.start()

    def _pos(self):
        return self.info["pos"] + (time.monotonic() - self.info["pos_at"] if self.info["playing"] else 0)

    def _lyric(self):
        lyrics = self.info.get("lyrics")
        return (line_at(lyrics, self._pos()) or "♪") if lyrics else ""  # ♪ during instrumental gaps

    def _compact_label(self):
        for pg in self.pages:
            text = pg.compact_text()
            if text is not None:
                return text
        return self._lyric()

    def _island_rect(self):
        if self._hud_active():
            cw, ch = BATTERY_POPUP if self.hud[0] in ("battery", "popup") else HUD
        elif not self.info:
            cw, ch = COLLAPSED
        else:
            cw, ch = COLLAPSED_LYRICS if self.info.get("lyrics") else COLLAPSED_PLAYING
        w, h = lerp(cw, EXPANDED[0], self.expand), lerp(ch, EXPANDED[1], self.expand)
        return QRectF((WIN_W - w) / 2, 0, w, h)

    # --- input ---------------------------------------------------------------
    def mouseMoveEvent(self, e):
        inside = self._island_rect().contains(e.position())
        if inside and not self.hovered:
            self.leave_delay.stop()
            self._animate_to(1.0)
        elif not inside and self.hovered:
            self.leave_delay.start()
        self.hovered = inside

    def leaveEvent(self, e):
        self.hovered = False
        self.leave_delay.start()

    def mouseReleaseEvent(self, e):
        if self.expand >= 0.5:  # page hit areas are only drawn while expanded
            self.pages[self.page].click(e.position(), e.button(), self)
            self._update_frame()
            self.update()

    def wheelEvent(self, e):
        if self.expand <= 0.5:
            return
        self.wheel += e.angleDelta().y()
        if abs(self.wheel) >= 120:
            self.page = (self.page + (1 if self.wheel < 0 else -1)) % len(self.pages)
            self.wheel = 0
            self.update()

    # --- drawing -------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._island_rect()
        radius = lerp(17, 32, min(self.expand, 1.0))
        path = QPainterPath()  # square top edge so it reads as a notch growing from the bezel
        path.addRoundedRect(r.adjusted(0, -radius, 0, 0), radius, radius)
        p.fillPath(path, QColor(0, 0, 0))
        self.buttons = {}
        if self._hud_active() and self.expand < 0.5:
            self._draw_hud(p, r)
            return
        if self.expand >= 0.5:
            p.setOpacity(min((self.expand - 0.5) * 2, 1.0))
            self.pages[self.page].draw(p, r, self)
            self._draw_dots(p, r)
        elif not self.info:
            self._text(p, QRectF(r), self._compact_label() or "No media", 11, QColor(140, 140, 140), Qt.AlignCenter)
        else:
            self._draw_compact(p, r, 1 - self.expand * 2)

    def _draw_compact(self, p, r, alpha):
        p.setOpacity(alpha)
        self._draw_art(p, QRectF(r.left() + 10, r.top() + 6, 22, 22), 6)
        self._draw_bars(p, QPointF(r.right() - 34, r.center().y()))
        lyric_box = QRectF(r.left() + 42, r.top(), r.width() - 88, r.height())
        self._text(p, lyric_box, self._compact_label(), 10, QColor(255, 255, 255), Qt.AlignCenter)

    def _draw_dots(self, p, r):
        n = len(self.pages)
        if n < 2:
            return
        p.setPen(Qt.NoPen)
        for i in range(n):
            p.setBrush(QColor(255, 255, 255) if i == self.page else QColor(90, 90, 95))
            p.drawEllipse(QPointF(r.center().x() + (i - (n - 1) / 2) * 10, r.bottom() - 8), 3, 3)

    def _draw_art(self, p, rect, radius):
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        if self.art.isNull():
            p.fillPath(clip, QColor(50, 50, 55))
            return
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(rect.toRect(), self.art)
        p.restore()

    def _draw_bars(self, p, at):
        # Decorative equaliser like Nusa's "w_bars": it does not read real audio levels.
        t = time.monotonic()
        for i in range(4):
            h = 4 + 10 * (0.5 + 0.5 * math.sin(t * 7 + i * 1.7)) if self.info.get("playing") else 4
            p.fillRect(QRectF(at.x() + i * 6, at.y() - h / 2, 3, h), QColor(120, 220, 140))

    def _draw_battery(self, p, r):
        _, level, charging, ac, title, subtitle = self.hud
        low = not ac and level * 100 <= system.BATTERY_LOW
        fill = QColor(120, 220, 140) if ac else QColor(255, 90, 80) if low else QColor(255, 255, 255)
        body = QRectF(r.left() + 22, r.center().y() - 8, 30, 16)
        p.setPen(QPen(QColor(150, 150, 155), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(body, 4, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(150, 150, 155))
        p.drawRoundedRect(QRectF(body.right() + 1.5, body.center().y() - 3, 2.5, 6), 1, 1)  # terminal nub
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(body.left() + 2.5, body.top() + 2.5, (body.width() - 5) * level, body.height() - 5), 2, 2)
        x = body.right() + 18
        self._text(p, QRectF(x, r.top() + 12, r.right() - x - 70, 22), title, 11, QColor(255, 255, 255), Qt.AlignLeft, bold=True)
        self._text(p, QRectF(x, r.top() + 33, r.right() - x - 70, 18), subtitle, 9, QColor(160, 160, 160), Qt.AlignLeft)
        self._text(p, QRectF(r.right() - 84, r.top(), 62, r.height()), f"{round(level * 100)}%", 15, fill, Qt.AlignRight, bold=True)

    def _draw_popup(self, p, r):
        _, glyph, title, subtitle = self.hud
        p.setFont(self._icon_font(22))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(r.left() + 18, r.top(), 38, r.height()), Qt.AlignCenter, glyph)
        x = r.left() + 70  # same text column as the battery popup
        self._text(p, QRectF(x, r.top() + 12, r.right() - x - 22, 22), title, 11, QColor(255, 255, 255), Qt.AlignLeft, bold=True)
        self._text(p, QRectF(x, r.top() + 33, r.right() - x - 22, 18), subtitle, 9, QColor(160, 160, 160), Qt.AlignLeft)

    @staticmethod
    def _icon_font(px):
        font = QFont()
        font.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol"])
        font.setPixelSize(px)
        return font

    def _draw_hud(self, p, r):
        if self.hud[0] == "battery":
            self._draw_battery(p, r)
            return
        if self.hud[0] == "popup":
            self._draw_popup(p, r)
            return
        kind, level, muted = self.hud
        # Segoe Fluent Icons: Brightness; Mute, Volume0..3. Caps Lock arrow comes from Segoe UI Symbol.
        if kind == "language":
            glyph = ""  # KeyboardClassic
        elif kind == "caps":
            glyph = "⇪"
        elif kind == "brightness":
            glyph = ""
        else:
            glyph = "" if muted else ""[min(3, math.ceil(level * 3))]
        p.setFont(self._icon_font(16))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(r.left() + 14, r.top(), 24, r.height()), Qt.AlignCenter, glyph)
        if kind == "language":
            display, tag = system.language_name(level)
            self._text(p, QRectF(r.left() + 48, r.top(), r.width() - 130, r.height()), display, 10, QColor(255, 255, 255), Qt.AlignLeft)
            self._text(p, QRectF(r.right() - 76, r.top(), 56, r.height()), tag, 10, QColor(120, 220, 140), Qt.AlignRight, bold=True)
            return
        if kind == "caps":
            on = level > 0
            self._text(p, QRectF(r.left() + 48, r.top(), 120, r.height()), "Caps Lock", 10, QColor(255, 255, 255), Qt.AlignLeft)
            self._text(p, QRectF(r.right() - 64, r.top(), 44, r.height()), "On" if on else "Off", 10,
                       QColor(120, 220, 140) if on else QColor(140, 140, 140), Qt.AlignRight, bold=on)
            return
        track = QRectF(r.left() + 48, r.center().y() - 2, r.width() - 110, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(70, 70, 75))
        p.drawRoundedRect(track, 2, 2)
        p.setBrush(QColor(110, 110, 115) if muted else QColor(255, 255, 255))
        p.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * level, 4), 2, 2)
        self._text(p, QRectF(track.right() + 8, r.top(), 44, r.height()), f"{round(level * 100)}", 10,
                   QColor(140, 140, 140) if muted else QColor(255, 255, 255), Qt.AlignRight)

    def _text(self, p, rect, s, size, color, align, bold=False):
        font = QFont("Segoe UI Variable Text", size, QFont.DemiBold if bold else QFont.Normal)
        p.setFont(font)
        p.setPen(color)
        p.drawText(rect, align | Qt.AlignVCenter, QFontMetrics(font).elidedText(s, Qt.ElideRight, int(rect.width())))


ABOUT = ("Lyrics from LRCLIB (lrclib.net).\n"
         "Weather data from MET Norway (api.met.no), CC BY 4.0.")


def make_tray(parent):
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(0, 0, 0))
    p.setPen(QColor(90, 90, 90))  # keeps the black pill visible on a dark taskbar
    p.drawRoundedRect(QRectF(0.5, 4.5, 15, 7), 3.5, 3.5)
    p.end()
    tray = QSystemTrayIcon(QIcon(pm), parent)
    menu = QMenu()

    def open_settings():
        if not (store.data_dir() / "settings.txt").exists():
            store.save_lines("settings.txt", [])
        os.startfile(store.data_dir() / "settings.txt")

    menu.addAction("Open settings file", open_settings)
    start = QAction("Start with Windows", menu, checkable=True, checked=autostart_enabled())
    start.toggled.connect(set_autostart)
    menu.addAction(start)
    menu.addAction("About", lambda: QMessageBox.information(None, "About Dynamic Island", ABOUT))
    menu.addAction("Quit", QApplication.quit)
    tray.setContextMenu(menu)
    tray._menu = menu  # keep alive
    tray.show()
    return tray


def main():
    app = QApplication(sys.argv)
    island = Island(Media())
    tray = make_tray(island)  # noqa: F841 (referenced so it is not collected)
    system.install_keys(island, system.Volume())
    system.install_brightness(island)
    sys.exit(app.exec())
