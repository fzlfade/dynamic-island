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
import threading
import time
import winreg
from collections import deque
from datetime import datetime
from ctypes import wintypes

from PySide6.QtCore import QBuffer, QByteArray, QEasingCurve, QIODevice, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from island import ics, network, notifications, ocr, prayer, shelf, store, system, weather
from island.focus import FocusPage
from island.media import Media, line_at
from island.pages import MediaPage, TodayPage
from island.shelf import ShelfPage
from island.todo import Todo
from island.water import Water

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
    notified = Signal(str, str)  # (app, title) from the notification worker thread
    ocr_done = Signal(str)  # recognised text from the OCR worker thread

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
        self.page_hits = {}  # page dots and ‹ › arrows, rebuilt each paint
        self.hud = ("volume", 0.0, False)  # (kind, level 0..1, muted)
        self.brightness = None  # last reported %, None until Windows sends the initial value
        self.layout = None  # (foreground window, LANGID) last seen
        self.battery = None  # last battery_status()
        self.network = None  # last network_state()
        self.volume = system.Volume()  # only for default_device(); the key hook has its own instance
        self.audio = None  # last default_device()
        self.hud_notified = None  # (hud, seconds, created) while the current HUD came from notify()
        self.hud_until = 0.0
        self.queue = deque()  # (hud, seconds, created) reminders waiting for a visible, HUD-free island
        self.hud_timer = QTimer(self, singleShot=True, timeout=self._hud_expired, timerType=Qt.TimerType.PreciseTimer)
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
        self.todo = Todo(self, self.notify)
        self.weather, self.weather_place = None, ""  # set by the worker once the location is known
        self.today.add_section(self._weather_rows)  # first, so the row cap never trims it
        self.prayer = prayer.Prayer(store.load_kv("settings.txt"))
        self.prayer_prev = prayer.minute_of(datetime.now())
        self._weather_thread = threading.Thread(target=self._start_weather, daemon=True)
        self._weather_thread.start()
        QTimer(self, interval=1_800_000, timeout=lambda: self.weather and self.weather.refresh()).start()
        self.water = Water(store.load_kv("water.txt"))
        self.water.roll(datetime.now())
        self.popup_actions = {"Time to Drink": self.drink}  # left-click on the collapsed island while that popup shows
        self.today.add_section(lambda: [("Water", self.water.status())])
        QTimer(self, interval=60_000, timeout=self._water_check).start()
        self.today.add_section(lambda: self.prayer.rows(datetime.now()))  # before the calendar, so events are trimmed first
        QTimer(self, interval=60_000, timeout=self._prayer_check).start()
        self.calendar = ics.Calendar(store.load_kv("settings.txt").get("calendar_url", ""))
        self.cal_rows = (None, None, [])  # (series, day, rows): the Today page repaints often, so expand recurrences once
        self.reminded = set()
        self.today.add_section(self._calendar_rows)  # after Water, so the row cap trims events first
        self.calendar.refresh()
        QTimer(self, interval=900_000, timeout=self.calendar.refresh).start()
        QTimer(self, interval=60_000, timeout=self._calendar_check).start()
        self.todo_page = TodayPage("To-do")
        self.todo_page.add_section(self.todo.rows, lambda i, b: (self.todo.click(i, b), self.update()), pin_last=True)
        self.add_page(self.todo_page)
        self.add_page(FocusPage(self.notify, self.update))
        if store.get_int(store.load_kv("settings.txt"), "shelf_clear", 0) == 1:
            shelf.save([])
        self.shelf_page = ShelfPage(shelf.load())
        self.add_page(self.shelf_page)
        self.setAcceptDrops(True)
        self.press_at = None  # where a left-button press started, for dragging shelf chips out
        self.ocr_done.connect(self._ocr_finished)
        self.notifier = None  # built on the worker: Qt's UI thread is a COM STA and the listener must live off it
        self._notif_thread = None
        self.notified.connect(lambda app_name, title: self._show_hud(("popup", "", app_name, title), NOTIFY_SECONDS))
        QTimer(self, interval=2000, timeout=self._notif_check).start()
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
        if msg.message == 0x312 and msg.wParam == ocr.HOTKEY_ID:  # WM_HOTKEY: Ctrl+Alt+T
            self.start_ocr()
        return False, 0

    def start_ocr(self):
        self.picker = ocr.RegionPicker()  # kept on self so it isn't collected while open
        self.picker.picked.connect(self._ocr_region)
        self.picker.show()
        self.picker.activateWindow()  # the picker takes focus so Esc reaches it; the island never does

    def _ocr_region(self, rect):
        if max(rect.width(), rect.height()) > ocr.max_dimension():
            self._show_hud(("popup", ocr.GLYPH, "That area is too large", "Select a smaller part"), NOTIFY_SECONDS)
            return
        screen = QGuiApplication.primaryScreen()
        QTimer.singleShot(50, lambda: self._ocr_grab(screen, rect))  # let the overlay disappear before grabbing

    def _ocr_grab(self, screen, rect):
        buf = QBuffer(data := QByteArray())
        buf.open(QIODevice.WriteOnly)
        screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height()).save(buf, "PNG")
        threading.Thread(target=self._ocr_work, args=(bytes(data),), daemon=True).start()

    def _ocr_work(self, png):  # worker thread: recognition takes a moment
        try:
            text = ocr.ocr_png(png)
        except Exception as e:  # e.g. no OCR language pack: report "nothing found" rather than crash
            print("ocr failed:", type(e).__name__, file=sys.stderr)
            text = ""
        self.ocr_done.emit(text)

    def _ocr_finished(self, text):
        if text.strip():
            QGuiApplication.clipboard().setText(text)
        self._show_hud(ocr.result_popup(text), NOTIFY_SECONDS)

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
        self.hud_notified = None
        self.hud_until = time.monotonic() + seconds
        self.hud_timer.start(int(seconds * 1000) + 20)
        self.update()

    def drink(self):
        popup = self.water.drink(datetime.now())
        store.save_kv("water.txt", self.water.to_kv())
        if popup:
            self.notify(("popup", "", *popup))
        self.update()

    def _calendar_rows(self):
        series, day = self.calendar.series, datetime.now().date()
        if self.cal_rows[0] is not series or self.cal_rows[1] != day:
            self.cal_rows = (series, day, ics.rows(series, datetime.now().astimezone()))
        return self.cal_rows[2]

    def _start_weather(self):  # worker thread: the Geolocator read may take seconds; only rebinds attributes
        lat, lon, self.weather_place = weather.location(store.load_kv("settings.txt"))
        self.prayer.set_location(lat, lon)
        w = weather.Weather(lat, lon)
        w.fetch_once()
        self.weather = w

    def _weather_rows(self):
        w = self.weather
        return [(self.weather_place, f"{round(w.now[0])}° {w.now[1]}")] if w and w.now else []

    def _calendar_check(self):
        for summary in ics.due_reminders(self.calendar.series, datetime.now().astimezone(), self.reminded):
            self.notify(("popup", "", "In 10 min", summary))

    def _prayer_check(self):
        now = datetime.now()
        hits = self.prayer.due(now, self.prayer_prev)
        self.prayer_prev = prayer.minute_of(now)
        for name, hhmm in hits:
            self.notify(("popup", prayer.GLYPH, name, hhmm))
        if hits and self.prayer.pause_media and self.info.get("playing"):
            self.media.send("toggle")

    def _water_check(self):
        hud = self.water.remind(datetime.now())
        if hud:
            store.save_kv("water.txt", self.water.to_kv())
            self.notify(hud)

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
                self.hud_notified = (hud, seconds, created)
                return

    def _hud_expired(self):
        if self._hud_active():  # fired early: keep the popup alive until it is really due
            self.hud_timer.start(int((self.hud_until - time.monotonic()) * 1000) + 20)
            return
        self.update()
        self._drain()

    def check_language(self):
        current = system.foreground_layout()
        # only a change within the same window counts: with per-app input, switching windows changes the layout too
        if self.layout and current[0] == self.layout[0] and current[1] != self.layout[1]:
            self._show_hud(("language", current[1], False))  # level slot carries the LANGID
        self.layout = current

    def check_network(self):
        try:
            cur = network.network_state()
        except Exception as e:  # unknown, not offline: keep the baseline and stay quiet
            print(f"network_state failed: {e}", file=sys.stderr)
            return
        popup = network.network_popup(self.network, cur)
        if popup:
            self._show_hud(("popup", "", *popup))  # Wi-Fi glyph
        self.network = cur

    def check_audio(self):
        try:
            cur = self.volume.default_device()
        except Exception as e:  # keep the baseline and stay quiet
            print(f"default_device failed: {e}", file=sys.stderr)
            return
        popup = system.audio_popup(self.audio, cur)
        if popup:
            self._show_hud(("popup", "\uE7F6", *popup))  # headphone glyph
        self.audio = cur

    def _check_fullscreen(self):
        self.setVisible(not system.fullscreen_app_running())
        self.todo.tick()
        self._drain()  # reminders queued behind a fullscreen app show once it closes
        self._update_frame()  # picks up pages that started animating on their own
        self.check_language()  # also catches switches made with the mouse from the taskbar
        self.check_battery()  # backup for the power broadcast
        self.check_network()
        self.check_audio()

    def _set_expand(self, v):
        self.expand = v
        self.update()

    def _animate_to(self, target):
        if target >= 1.0 and self.hud_notified and self._hud_active():  # expanding hides the HUD: show the reminder again later
            self.queue.appendleft(self.hud_notified)
            self.hud_until, self.hud_notified = 0.0, None
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
    def _notif_check(self):  # 2 s timer: the WinRT read takes ~40 ms, so it runs off the UI thread
        if self._notif_thread is None or not self._notif_thread.is_alive():
            self._notif_thread = threading.Thread(target=self._notif_poll, daemon=True)
            self._notif_thread.start()

    def _notif_poll(self):
        if self.notifier is None:
            self.notifier = notifications.Listener()  # its first poll only records what's already there
        new = self.notifier.poll()
        if new:  # several at once: show the newest; the signal is queued onto the UI thread
            app_name, title, _ = new[-1]
            self.notified.emit(app_name, title)

    def mousePressEvent(self, e):
        self.press_at = e.position() if e.button() == Qt.LeftButton else None

    def drop_mime(self, mime):
        """Shelf the dropped files/text/links and open the island on the Shelf page."""
        items = shelf.items_from_mime(mime, shelf.store_dir())
        if items:
            self.shelf_page.add(items)
            self.page = self.pages.index(self.shelf_page)
            self.update()
        return bool(items)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()
            self.leave_delay.stop()
            self.page = self.pages.index(self.shelf_page)
            self._animate_to(1.0)

    def dragLeaveEvent(self, e):
        self.leave_delay.start()

    def dropEvent(self, e):
        if self.drop_mime(e.mimeData()):
            e.acceptProposedAction()
        self.leave_delay.start()

    def mouseMoveEvent(self, e):
        if (self.press_at is not None and e.buttons() & Qt.LeftButton and self.expand >= 0.5
                and (e.position() - self.press_at).manhattanLength() >= QApplication.startDragDistance()):
            start, self.press_at = self.press_at, None
            drag = getattr(self.pages[self.page], "drag", None)
            if drag and drag(start, self):
                return
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
        if (self.expand < 0.5 and e.button() == Qt.LeftButton and self._hud_active() and self.hud[0] == "popup"
                and self.hud[2] in self.popup_actions):
            self.hud_until = 0.0  # dismiss first so a follow-up popup (refill) can show
            self.hud_timer.stop()
            self.popup_actions[self.hud[2]]()
            self._drain()
            self.update()
            return
        if self.expand >= 0.5:  # page hit areas are only drawn while expanded
            hit = next((k for k, rect in self.page_hits.items() if rect.contains(e.position())), None)
            if hit is not None and e.button() == Qt.LeftButton:
                step = {"prev": -1, "next": 1}.get(hit)
                self.page = (self.page + step) % len(self.pages) if step else hit
                self.update()
                return
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
        self.page_hits = {}
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
        """Page dots (click to jump) flanked by ‹ › arrows (click to step); hit areas land in page_hits."""
        n = len(self.pages)
        if n < 2:
            return
        cy, step = r.bottom() - 9, 14
        p.setPen(Qt.NoPen)
        for i in range(n):
            c = QPointF(r.center().x() + (i - (n - 1) / 2) * step, cy)
            p.setBrush(QColor(255, 255, 255) if i == self.page else QColor(90, 90, 95))
            p.drawEllipse(c, 3, 3)
            self.page_hits[i] = QRectF(c.x() - step / 2, cy - 9, step, 18)
        edge = r.center().x() + (n / 2) * step
        for key, x, glyph in (("prev", 2 * r.center().x() - edge - 14, "‹"), ("next", edge, "›")):
            self.page_hits[key] = QRectF(x, cy - 9, 14, 18)
            self._text(p, self.page_hits[key], glyph, 12, QColor(170, 170, 175), Qt.AlignCenter)

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
        p.setPen(QColor(140, 140, 140) if title == "Disconnected" else QColor(255, 255, 255))  # grey Wi-Fi glyph offline
        p.drawText(QRectF(r.left() + 18,r.top(), 38, r.height()), Qt.AlignCenter, glyph)
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
    if not ctypes.windll.user32.RegisterHotKey(int(island.winId()), ocr.HOTKEY_ID, 0x1 | 0x2 | 0x4000, ord("T")):
        print("ocr: Ctrl+Alt+T is taken by another app", file=sys.stderr)  # MOD_ALT|MOD_CONTROL|MOD_NOREPEAT
    sys.exit(app.exec())
