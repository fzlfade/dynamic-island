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
from datetime import datetime, timedelta
from ctypes import wintypes

from PySide6.QtCore import QBuffer, QByteArray, QEasingCurve, QIODevice, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QIcon, QFont, QFontMetrics, QGuiApplication, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from island import ask, ics, network, notifications, ocr, prayer, settings, shelf, store, system, theme, weather
from island.focus import FocusPage
from island.media import Media, line_at
from island.pages import MediaPage, TodayPage, TodoPage, WaterPage, bell
from island.shelf import ShelfPage
from island.todo import Todo
from island.water import Water

COLLAPSED = (190.0, 34.0)
MINIMAL = (53.0, 4.0)  # Nusa's idle pill (settings: minimal notch)
PEEK = (59.0, 8.0)  # the pill swells while the pointer rests on it, before opening
COLLAPSED_PLAYING = (260.0, 34.0)
COLLAPSED_LYRICS = (380.0, 34.0)
HUD = (300.0, 34.0)
HUD_SECONDS = 1.5
BATTERY_POPUP = (340.0, 64.0)
BATTERY_SECONDS = 3.0
EXPANDED = (455.0, 197.0)  # measured on Nusa 1.3.1
LYRICS_EXPANDED = (600.0, 197.0)  # Nusa's lyrics view: player left, lyrics right (from a screenshot)
EAR, CORNER = 22.0, 36.0
BAR_EXTRA = 30.0  # the island grows this much while the page-icons bar shows  # concave flare where the notch meets the bezel; bottom corner radius
WIN_W, WIN_H = 660, 240  # fits the island plus the page-icons bar  # window fits the largest island; transparent pixels are click-through
NOTIFY_SECONDS = 4.0
DEFAULT_PAGES = "media,focus,water,shelf,todo"
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


MARQUEE_PAUSE, MARQUEE_SPEED, MARQUEE_GAP = 1.5, 30.0, 40.0  # s held at the start, px/s, px between loops
MARQUEE_FADE = 14.0  # px of soft edge on scrolling text


def marquee_offset(text_w, box_w, elapsed):
    """x offset for text wider than its box: hold at the start, slide left, then loop."""
    if text_w <= box_w:
        return 0
    cycle = MARQUEE_PAUSE + (text_w + MARQUEE_GAP) / MARQUEE_SPEED
    t = elapsed % cycle
    return 0 if t < MARQUEE_PAUSE else -(t - MARQUEE_PAUSE) * MARQUEE_SPEED


def _location_settings(values):
    return tuple(values.get(k) for k in ("lat", "lon", "place"))


def notch_path(r, ear, radius):
    """Island outline: flat top that flares out into the bezel (concave `ear` arcs), rounded bottom corners."""
    path = QPainterPath()
    path.moveTo(r.left() - ear, r.top())
    path.lineTo(r.right() + ear, r.top())
    if ear > 0:
        path.arcTo(QRectF(r.right(), r.top(), 2 * ear, 2 * ear), 90, 90)
    path.lineTo(r.right(), r.bottom() - radius)
    path.arcTo(QRectF(r.right() - 2 * radius, r.bottom() - 2 * radius, 2 * radius, 2 * radius), 0, -90)
    path.lineTo(r.left() + radius, r.bottom())
    path.arcTo(QRectF(r.left(), r.bottom() - 2 * radius, 2 * radius, 2 * radius), 270, -90)
    path.lineTo(r.left(), r.top() + ear)
    if ear > 0:
        path.arcTo(QRectF(r.left() - 2 * ear, r.top(), 2 * ear, 2 * ear), 0, 90)
    path.closeSubpath()
    return path


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
        self.marquee_t0 = {}  # text -> when it started scrolling
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

        self.page_from, self.slide, self.slide_dir = None, 1.0, 1  # page-change slide: 0 → 1
        self.page_anim = QVariantAnimation(self, duration=380, easingCurve=QEasingCurve.OutCubic,
                                           startValue=0.0, endValue=1.0)
        self.page_anim.valueChanged.connect(self._set_slide)
        self.anim = QVariantAnimation(self, duration=420, easingCurve=QEasingCurve.OutBack)
        self.anim.valueChanged.connect(self._set_expand)
        self.anim.finished.connect(self._drain)  # reminders held while the island was open
        self.leave_delay = QTimer(self, singleShot=True, interval=90, timeout=lambda: self._animate_to(0.0))
        self.hover_pos = None  # pointer position while over the open island (hover-revealed controls)
        self.bar_v = 0.0  # 0..1 page-icons bar, shown while the pointer is on the page dots
        self.bar_anim = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic)
        self.bar_anim.valueChanged.connect(self._set_bar)
        self.wide_v = 0.0  # 0..1 widening into the lyrics view
        self.wide_anim = QVariantAnimation(self, duration=300, easingCurve=QEasingCurve.OutCubic)
        self.wide_anim.valueChanged.connect(self._set_wide)
        self.art_color = None  # the cover's average colour, for the glow
        self.peek = 0.0  # 0..1 swell of the closed pill while the pointer rests on it
        self.peek_anim = QVariantAnimation(self, duration=120, easingCurve=QEasingCurve.OutCubic)
        self.peek_anim.valueChanged.connect(self._set_peek)
        self.dwell = QTimer(self, singleShot=True, interval=200, timeout=lambda: self._animate_to(1.0))
        settings_now = self.prefs = store.load_kv("settings.txt")
        self.minimal = store.get_int(settings_now, "minimal", 1) == 1
        self.show_clock = store.get_int(settings_now, "clock", 1) == 1
        self.show_ring = store.get_int(settings_now, "ring", 1) == 1
        self.on_click = settings_now.get("open_click") == "1"
        self.fast = settings_now.get("fast_animation") == "1"
        self.frame = QTimer(self, interval=16, timeout=self._frame_tick)  # only runs while something animates
        self.media_page = MediaPage()
        self.today = TodayPage()
        self.todo = Todo(self, self.notify)
        self.weather, self.weather_place = None, ""  # set by the worker once the location is known
        self.today.add_section(self._weather_rows)  # first, so the row cap never trims it
        self.prayer = prayer.Prayer(store.load_kv("settings.txt"))
        self.prayer_prev = prayer.minute_of(datetime.now())
        self._loc_settings = _location_settings(store.load_kv("settings.txt"))
        self.settings_window = None
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
        self.reminded = set()
        self.today.add_section(self._calendar_rows)  # after Water, so the row cap trims events first
        self.calendar.refresh()
        QTimer(self, interval=900_000, timeout=lambda: self.calendar.refresh()).start()  # settings may swap it
        QTimer(self, interval=60_000, timeout=self._calendar_check).start()
        self.todo_page = TodoPage(self.todo, self.update)
        self.focus_page = FocusPage(self.notify, self.update)
        self.water_page = WaterPage(self.water, self.drink, lambda: self.open_settings("Water"), self.toggle_water)
        if store.get_int(store.load_kv("settings.txt"), "shelf_clear", 0) == 1:
            shelf.save([])
        self.shelf_page = ShelfPage(shelf.load())
        self.setAcceptDrops(True)
        self.press_at = None  # where a left-button press started, for dragging shelf chips out
        self.ocr_done.connect(self._ocr_finished)
        self.ask_page = ask.AskPage()  # joins the page row only while a question is open
        self.page_registry = {"media": self.media_page, "focus": self.focus_page, "water": self.water_page,
                              "shelf": self.shelf_page, "todo": self.todo_page, "today": self.today}
        self._apply_pages(store.load_kv("settings.txt"))
        self.asker = ask.Asker()  # its signals are delivered to these Island slots on the UI thread
        self.asker.chunk.connect(self._ask_chunk)
        self.asker.finished.connect(self._ask_finished)
        self.asker.failed.connect(self._ask_failed)
        self.notifier = None  # built on the worker: Qt's UI thread is a COM STA and the listener must live off it
        self._notif_thread = None
        self.notif_pill = store.get_int(store.load_kv("settings.txt"), "notif_pill", 1) == 1
        self.notified.connect(self._show_notification)
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
            self.art_color = None
            if not self.art.isNull():  # a 1x1 smooth scale averages the cover; lift dark covers so the glow reads
                c = self.art.toImage().scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
                self.art_color = QColor.fromHsvF(max(c.hsvHueF(), 0.0), c.hsvSaturationF() * 0.75, max(c.valueF(), 0.6))
        self.info = info
        self._update_frame()
        self.update()

    def add_page(self, page):
        self.pages.append(page)
        self.update()

    def _apply_pages(self, values):
        """Pages in the order the settings list them (Nusa's default: Music, Pomodoro, Water, Shelf, To-do)."""
        current = self.pages[self.page] if self.pages else None
        names = [n for n in values.get("pages", DEFAULT_PAGES).split(",") if n in self.page_registry]
        self.pages = [self.page_registry[n] for n in names] or [self.media_page]
        if self.ask_page.state != "idle":
            self.pages.append(self.ask_page)
        self.page = self.pages.index(current) if current in self.pages else 0
        self.page_from = None
        self.update()

    def _drop_page(self, page):
        if page in self.pages and len(self.pages) > 1:
            current = self.pages[self.page]
            self.pages.remove(page)
            self.page = self.pages.index(current) if current in self.pages else 0
            self.page_from = None

    def toggle_water(self):
        self.water.on = not self.water.on
        store.save_kv("water.txt", self.water.to_kv())
        self.update()

    def _update_frame(self):
        if not (self.info.get("playing") or any(pg.animating() for pg in self.pages)):
            self.frame.stop()
        elif not self.frame.isActive():
            self.frame.start()

    def _frame_tick(self):
        self.update()
        self._update_frame()

    def on(self, key):
        """A switch from the settings window; everything defaults to on, like Nusa."""
        return store.get_int(self.prefs, key, 1) == 1

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
        if msg.message == 0x312 and msg.wParam == ask.HOTKEY_ID:  # WM_HOTKEY: Ctrl+Alt+Space
            self.start_ask()
        return False, 0

    def start_ask(self):
        question, ok = QInputDialog.getText(None, "Ask", "")  # its own window takes the typing, never the island
        if not ok or not question.strip():
            return
        self.ask_page.start(question.strip())
        if self.ask_page not in self.pages:
            self.pages.append(self.ask_page)
        self.page = self.pages.index(self.ask_page)
        self._animate_to(1.0)
        self._update_frame()
        self.asker.ask(question.strip())

    def _ask_chunk(self, gen, text):  # output from a replaced or closed question is dropped
        if gen == self.asker.gen:
            self.ask_page.add(text)
            self.update()

    def _ask_finished(self, gen, _):
        if gen == self.asker.gen:
            self.ask_page.finish()
            self.update()

    def _ask_failed(self, gen, message):
        if gen == self.asker.gen:
            self.ask_page.fail(message)
            self.update()

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
            if self.on("popup_battery"):
                self._show_hud(("battery", cur[1] / 100, cur[2], cur[0], *popup), BATTERY_SECONDS)
        self.battery = cur

    def on_brightness(self, percent):
        # Windows sends the current value right after registering: remember it, don't flash the HUD
        if self.brightness is not None and percent != self.brightness:
            if self.on("hud_brightness"):
                self._show_hud(("brightness", percent / 100, False))
        self.brightness = percent

    def show_caps(self):
        if not self.on("hud_caps"):
            return
        on = bool(system._user32.GetKeyState(system.VK_CAPITAL) & 1)  # low bit = toggled
        self._show_hud(("caps", 1.0 if on else 0.0, False))

    def _requeue_reminder(self):
        """A reminder on screen that is about to be covered goes back to the front of the queue, unseen."""
        if self.hud_notified and self._hud_active():
            self.queue.appendleft(self.hud_notified)
            self.hud_until = 0.0
        self.hud_notified = None

    def _show_hud(self, hud, seconds=HUD_SECONDS):
        self._requeue_reminder()  # e.g. a toast or the Wi-Fi popup must not swallow a to-do reminder
        self.hud = hud
        self.hud_until = time.monotonic() + seconds
        self.hud_timer.start(int(seconds * 1000) + 20)
        self.update()

    def drink(self):
        popup = self.water.drink(datetime.now())
        store.save_kv("water.txt", self.water.to_kv())
        if popup:
            self.notify(("popup", "", *popup))
        self.update()

    def open_settings(self, section=None):
        if self.settings_window is None or not self.settings_window.isVisible():
            self.settings_window = settings.SettingsWindow(self)
        if section:
            self.settings_window.show_section(section)  # e.g. the Water page's Settings button
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def apply_settings(self):
        """Pick up what the settings window saved, without a restart."""
        v = store.load_kv("settings.txt")
        self.notif_pill = store.get_int(v, "notif_pill", 1) == 1
        loc = self.prayer.loc
        self.prayer = prayer.Prayer(v)
        if loc:
            self.prayer.set_location(*loc)
        calendar = ics.Calendar(v.get("calendar_url", ""))
        if calendar.url != self.calendar.url:
            self.calendar = calendar
            self.calendar.refresh()
        self.water.set_config(store.load_kv("water.txt"))  # keeps the glasses already logged today
        self.minimal = store.get_int(v, "minimal", 1) == 1
        self.show_clock = store.get_int(v, "clock", 1) == 1
        self.show_ring = store.get_int(v, "ring", 1) == 1
        self.prefs = v
        self.on_click = v.get("open_click") == "1"
        self.fast = v.get("fast_animation") == "1"
        self.page_anim.setDuration(int(380 * (0.6 if self.fast else 1.0)))
        self.focus_page.cfg = self.focus_page._settings()
        self._apply_pages(v)
        if _location_settings(v) != self._loc_settings:  # new place, or back to automatic: look it up again
            self._loc_settings = _location_settings(v)
            self._weather_thread = threading.Thread(target=self._start_weather, daemon=True)
            self._weather_thread.start()
        self.update()

    def _calendar_rows(self):  # every paint: only reads lists the calendar worker built
        now = datetime.now().astimezone()
        days = self.calendar.ensure_days(now)
        return ics.rows_from(days[now.date()]) if days else []

    def _start_weather(self):  # worker thread: the Geolocator read may take seconds; only rebinds attributes
        lat, lon, self.weather_place = weather.location(store.load_kv("settings.txt"))
        self.prayer.set_location(lat, lon)
        w = weather.Weather(lat, lon)
        w.fetch_once()
        self.weather = w

    def _weather_rows(self):
        w = self.weather
        return [(self.weather_place, f"{round(w.now[0])}° {w.now[1]}")] if w and w.now else []

    def _calendar_check(self):  # this thread also runs the system-wide keyboard hook: never expand recurrences here
        now = datetime.now().astimezone()
        days = self.calendar.ensure_days(now)
        upcoming = days[now.date()] + days[now.date() + timedelta(days=1)] if days else []
        for summary in ics.due_from(upcoming, now, self.reminded):
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
            if self.on("hud_language"):
                self._show_hud(("language", current[1], False))  # level slot carries the LANGID
        self.layout = current

    def check_network(self):
        try:
            cur = network.network_state()
        except Exception as e:  # unknown, not offline: keep the baseline and stay quiet
            print(f"network_state failed: {e}", file=sys.stderr)
            return
        popup = network.network_popup(self.network, cur)
        if popup and self.on("popup_wifi"):
            self._show_hud(("popup", "", *popup))  # Wi-Fi glyph
        if cur[0] and self.network and not self.network[0]:  # back online (e.g. Wi-Fi came up after login): refetch now
            self.calendar.refresh()
            if self.weather:
                self.weather.refresh()
        self.network = cur

    def check_audio(self):
        try:
            cur = self.volume.default_device()
        except Exception as e:  # keep the baseline and stay quiet
            print(f"default_device failed: {e}", file=sys.stderr)
            return
        popup = system.audio_popup(self.audio, cur)
        if popup and self.on("popup_audio"):
            self._show_hud(("popup", "\uE7F6", *popup))  # headphone glyph
        self.audio = cur

    def _check_fullscreen(self):
        hide = self.on("hide_fullscreen") and system.fullscreen_app_running()
        if hide and self.isVisible():
            self._requeue_reminder()  # shown again when the fullscreen app closes
        self.setVisible(not hide)
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

    def _set_bar(self, v):
        self.bar_v = v
        self.update()

    def _bar_to(self, target):
        self._tween(self.bar_anim, self.bar_v, target)

    def _set_wide(self, v):
        self.wide_v = v
        self.update()

    @staticmethod
    def _tween(anim, value, target):
        if anim.endValue() == target and anim.state() == anim.State.Running:
            return
        if abs(value - target) < 1e-3:
            return
        anim.stop()
        anim.setStartValue(value)
        anim.setEndValue(target)
        anim.start()

    def read_volume(self):
        try:
            return self.volume.get()
        except OSError:  # no audio device
            return 0.0, False

    def write_volume(self, level):
        try:
            self.volume.set(level, False)  # moving the slider unmutes, like Windows' own slider
        except OSError:
            pass

    def _set_peek(self, v):
        self.peek = v
        self.update()

    def _peek_to(self, target):
        self.peek_anim.stop()
        self.peek_anim.setStartValue(self.peek)
        self.peek_anim.setEndValue(target)
        self.peek_anim.start()

    def _animate_to(self, target):
        if target >= 1.0:  # expanding hides the HUD: show the reminder again later
            self._requeue_reminder()
        else:
            self._peek_to(0.0)
        curve = QEasingCurve(QEasingCurve.OutBack)
        curve.setOvershoot(0.8)  # Nusa overshoots ~2% (455 -> 465 px) opening and undershoots closing
        self.anim.setEasingCurve(curve)
        self.anim.setDuration(int((330 if target >= 1.0 else 300) * (0.6 if self.fast else 1.0)))
        self.anim.stop()
        self.anim.setStartValue(self.expand)
        self.anim.setEndValue(target)
        self.anim.start()

    def _pos(self):
        pos, at = self.info.get("pos", 0.0), self.info.get("pos_at")  # some players report no timeline
        return pos + (time.monotonic() - at if self.info.get("playing") and at is not None else 0)

    def _lyric(self):
        lyrics = self.info.get("lyrics") if self.on("lyrics") else None
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
            cw, ch = MINIMAL if self.minimal else COLLAPSED
        else:
            cw, ch = COLLAPSED_LYRICS if self.info.get("lyrics") else COLLAPSED_PLAYING
        cw, ch = cw + (PEEK[0] - MINIMAL[0]) * self.peek, ch + (PEEK[1] - MINIMAL[1]) * self.peek
        ew = lerp(EXPANDED[0], LYRICS_EXPANDED[0], self.wide_v)
        w, h = lerp(cw, ew, self.expand), max(0.0, lerp(ch, EXPANDED[1], self.expand))
        h += BAR_EXTRA * self.bar_v * max(0.0, min(self.expand, 1.0))  # Nusa grows to fit the page-icons bar
        return QRectF((WIN_W - w) / 2, 0, w, h)

    # --- input ---------------------------------------------------------------
    def _show_notification(self, app_name, title):
        # no pill when switched off, or while Windows itself holds toasts back (Do Not Disturb, presenting)
        if self.notif_pill and not system.notifications_quiet():
            self._show_hud(("popup", "", app_name, title), NOTIFY_SECONDS)

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
        if self.expand >= 0.5:
            self.hover_pos = e.position()
            page = self.pages[self.page]
            slider = self.buttons.get("slider")
            if (e.buttons() & Qt.LeftButton and self.press_at is not None and slider is not None
                    and slider.contains(self.press_at) and hasattr(page, "set_level")):
                page.set_level(e.position(), self)  # dragging the volume slider
                self.update()
                return
            r = self._island_rect()
            on_dots = self.wide_v < 0.5 and (e.position().y() >= r.bottom() - 24 - BAR_EXTRA * self.bar_v
                       and abs(e.position().x() - r.center().x()) < 130)
            self._bar_to(1.0 if on_dots and self.on("page_icons") else 0.0)
            self.update()
        if (self.press_at is not None and e.buttons() & Qt.LeftButton and self.expand >= 0.5
                and (e.position() - self.press_at).manhattanLength() >= QApplication.startDragDistance()):
            start, self.press_at = self.press_at, None
            drag = getattr(self.pages[self.page], "drag", None)
            if drag and drag(start, self):
                return
        inside = self._island_rect().contains(e.position())
        if inside and not self.hovered:
            self.leave_delay.stop()
            if self.expand < 0.5:  # rest on the pill for a moment (it swells), then it opens
                self._peek_to(1.0)
                if not self.on_click:
                    self.dwell.start()
        elif not inside and self.hovered:
            self._leave()
        self.hovered = inside

    def _leave(self):
        self.dwell.stop()
        if self.expand < 0.5:
            self._peek_to(0.0)
        self.leave_delay.start()

    def leaveEvent(self, e):
        self.hovered = False
        self.hover_pos = None
        self._bar_to(0.0)
        self._leave()

    def mouseReleaseEvent(self, e):
        if self.expand < 0.5 and e.button() == Qt.LeftButton and self._hud_active() and self.hud[0] == "popup":
            self.hud_until = 0.0  # a click closes any popup; dismiss first so a follow-up popup (refill) can show
            self.hud_timer.stop()
            self.popup_actions.get(self.hud[2], lambda: None)()
            self._drain()
            self.update()
            return
        if self.on_click and self.expand < 0.5 and e.button() == Qt.LeftButton and self.hovered:
            self._animate_to(1.0)  # "Open the notch: Click"
            return
        if self.expand >= 0.5:  # page hit areas are only drawn while expanded
            hit = next((k for k, rect in self.page_hits.items() if rect.contains(e.position())), None)
            if hit == "gear" and e.button() == Qt.LeftButton:
                self.open_settings()
                return
            if hit is not None and e.button() == Qt.LeftButton:
                step = {"prev": -1, "next": 1}.get(hit)
                target = (self.page + step) % len(self.pages) if step else hit
                self._go_to_page(target, step or (1 if target > self.page else -1))
                return
            self.pages[self.page].click(e.position(), e.button(), self)
            self._update_frame()
            self.update()

    def wheelEvent(self, e):
        if self.expand <= 0.5:
            return
        self.wheel += e.angleDelta().y()
        if abs(self.wheel) >= 120:
            step = 1 if self.wheel < 0 else -1
            self._go_to_page((self.page + step) % len(self.pages), step)
            self.wheel = 0

    def _go_to_page(self, n, direction):
        """Switch to page n at once (clicks land on it) and slide it in from `direction` (+1 right, -1 left)."""
        if n == self.page:
            return
        self.page_from, self.page, self.slide_dir = self.page, n, direction
        self.page_anim.stop()
        self.page_anim.start()

    def _set_slide(self, v):
        self.slide = v
        self.update()

    def _draw_pages(self, p, r, clip):
        r = QRectF(r.center().x() - EXPANDED[0] / 2, r.top(), EXPANDED[0], r.height())  # Media widens itself
        if self.page_from is None or self.slide >= 1.0:
            self._draw_title(p, r, self.pages[self.page])
            self.pages[self.page].draw(p, r, self)
            return
        travel, alpha = 45.0, p.opacity()
        for page, dx, fade in ((self.page_from, -self.slide_dir * self.slide * travel, 1 - self.slide),
                               (self.page, self.slide_dir * (1 - self.slide) * travel, self.slide)):
            p.save()
            p.setClipPath(clip)  # sliding content stays inside the notch
            p.translate(dx, 0)
            p.setOpacity(alpha * fade)
            self._draw_title(p, r, self.pages[page])
            self.pages[page].draw(p, r, self)
            p.restore()

    # --- drawing -------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._tween(self.wide_anim, self.wide_v, 1.0 if getattr(self.pages[self.page], "lyrics_view", False) else 0.0)
        r = self._island_rect()
        path = notch_path(r, EAR * max(0.0, min(self.expand, 1.0)), min(CORNER, r.height() / 2, r.width() / 2))
        p.fillPath(path, QColor(0, 0, 0))
        self.buttons = {}
        self.page_hits = {}
        if self._hud_active() and self.expand < 0.5:
            self._draw_hud(p, r)
            return
        if self.expand >= 0.5:
            fade = min((self.expand - 0.5) * 2, 1.0)
            self._glow(p, path, r, fade * self.wide_v)
            p.setOpacity(fade * (1 - self.wide_v))  # the lyrics view has no header, dots or arrows
            self._draw_header(p, r)
            p.setOpacity(fade)
            self._draw_pages(p, r, path)
            p.setOpacity(fade * (1 - self.wide_v))
            self._draw_dots(p, r)
            if self.wide_v >= 0.5:
                self.page_hits = {}
        elif not self.info:
            if r.height() >= 20:  # the minimal pill is a sliver: nothing to read on it
                self._text(p, QRectF(r), self._compact_label() or "No media", 11, QColor(140, 140, 140), Qt.AlignCenter)
        else:
            self._draw_compact(p, r, 1 - self.expand * 2, path)

    def _glow(self, p, path, r, strength):
        """Nusa's album-coloured glow rising from the bottom of the island."""
        if strength <= 0.01 or self.art_color is None:
            return
        grad = QLinearGradient(0, r.bottom(), 0, r.top() + r.height() * 0.45)
        c = QColor(self.art_color)
        c.setAlphaF(0.7 * strength)
        grad.setColorAt(0, c)
        c.setAlphaF(0.0)
        grad.setColorAt(1, c)
        p.fillPath(path, grad)

    def _lyric_pill(self):
        """The collapsed island is showing the current lyric line (no page claims the pill)."""
        return bool(self.info.get("lyrics")) and self.on("lyrics") and all(pg.compact_text() is None for pg in self.pages)

    def _draw_compact(self, p, r, alpha, path):
        lyric = self._lyric_pill()
        if lyric:
            self._glow(p, path, r, alpha)
        p.setOpacity(alpha)
        art = QRectF(r.left() + 10, r.top() + 6, 22, 22)
        if lyric:  # Nusa swaps the cover for a note while it sings along
            self._text(p, art, "\u266A", 15, QColor(150, 150, 155), Qt.AlignCenter)
        else:
            self._draw_art(p, art, 6)
            self._draw_bars(p, QPointF(r.right() - 34, r.center().y()))
        lyric_box = QRectF(r.left() + 42, r.top(), r.width() - 88, r.height())
        self._text(p, lyric_box, self._compact_label(), 10, QColor(255, 255, 255), Qt.AlignCenter, bold=lyric,
                   scroll=bool(self.info.get("playing")))

    def _draw_dots(self, p, r):
        """Nusa-style page indicator: the current page is a 16 px pill, the rest 4 px dots; the pill glides as
        pages change. Side arrows sit at mid-height. Hit areas land in page_hits."""
        n = len(self.pages)
        if n < 2:
            return
        weight = [0.0] * n  # 1 = pill
        if self.page_from is not None and self.slide < 1.0:
            weight[self.page_from], weight[self.page] = 1 - self.slide, self.slide
        else:
            weight[self.page] = 1.0
        if self.bar_v > 0.01:
            self._draw_icons_bar(p, r)
        p.save()
        p.setOpacity(p.opacity() * (1 - self.bar_v))
        widths = [4 + 12 * w for w in weight]
        gap, cy = 5.0, r.bottom() - 8 - BAR_EXTRA * self.bar_v
        x = r.center().x() - (sum(widths) + gap * (n - 1)) / 2
        p.setPen(Qt.NoPen)
        for i, w in enumerate(widths):
            p.setBrush(QColor(255, 255, 255) if weight[i] > 0.5 else QColor(105, 105, 110))
            p.drawRoundedRect(QRectF(x, cy - 2, w, 4), 2, 2)
            hit_w = max(w + gap, 14.0)  # tiny dots, comfortable click target
            if self.bar_v < 0.5:
                self.page_hits[i] = QRectF(x + w / 2 - hit_w / 2, cy - 9, hit_w, 18)
            x += w + gap
        p.restore()
        mid = r.top() + 107
        for key, cx, glyph in (("prev", r.left() + 11, "\u2039"), ("next", r.right() - 12, "\u203a")):
            self.page_hits[key] = QRectF(cx - 12, mid - 20, 24, 40)
            self._text(p, QRectF(cx - 7, mid - 11, 14, 22), glyph, 13, QColor(95, 95, 100), Qt.AlignCenter)

    def _draw_icons_bar(self, p, r):
        """Nusa's page icons: shown while the pointer is on the dots; click one to jump, the gear opens settings."""
        n, cell, sep = len(self.pages), 32.0, 14.0
        width = n * cell + sep + cell + 12
        bar = QRectF(r.center().x() - width / 2, r.bottom() - 33, width, 28)
        p.save()
        p.setOpacity(p.opacity() * self.bar_v)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(28, 28, 30))
        p.drawRoundedRect(bar, 14, 14)
        x = bar.left() + 6
        for i, page in enumerate(self.pages):
            cellr = QRectF(x, bar.top(), cell, bar.height())
            current = QColor(255, 55, 95) if i == self.page else QColor(210, 210, 214)
            p.setFont(self._icon_font(16))
            p.setPen(current)
            p.drawText(cellr, Qt.AlignCenter, getattr(page, "icon", "\uE8FD"))
            if self.bar_v >= 0.5:
                self.page_hits[i] = cellr
            x += cell
        p.setPen(QPen(QColor(70, 70, 74), 1))
        p.drawLine(QPointF(x + sep / 2, bar.top() + 6), QPointF(x + sep / 2, bar.bottom() - 6))
        gear = QRectF(x + sep, bar.top(), cell, bar.height())
        p.setFont(self._icon_font(16))
        p.setPen(QColor(210, 210, 214))
        p.drawText(gear, Qt.AlignCenter, "\uE713")
        if self.bar_v >= 0.5:
            self.page_hits["gear"] = gear
        p.restore()

    def _draw_title(self, p, r, page):
        """Page title at the top left; pages that put something else there (Media's cover) set hide_title."""
        if getattr(page, "hide_title", False):
            return
        parts = getattr(page, "title_parts", None) or ([(page.title, QColor(255, 255, 255))] if page.title else [])
        x = r.left() + 37
        for text, color in parts:
            w = QFontMetrics(theme.font(12, QFont.Bold)).horizontalAdvance(text)
            self._text(p, QRectF(x, r.top() + 27, w + 2, 22), text, 12, color, Qt.AlignLeft, bold=True)
            x += w

    def _draw_header(self, p, r):
        """Fixed top row on every page: battery ring, date and bold time, centred; status icon on the right."""
        now = datetime.now()
        date_s, time_s = f"{now:%a} {now.day} {now:%b %Y}", f"{now:%H:%M}"
        cy = r.top() + 31
        date_w = QFontMetrics(theme.font(11)).horizontalAdvance(date_s)
        time_w = QFontMetrics(theme.font(11, QFont.Bold)).horizontalAdvance(time_s)
        ring = self.battery is not None and self.show_ring
        total = (29 if ring else 0) + (date_w + 9 + time_w if self.show_clock else 0)
        x = r.center().x() - total / 2
        if ring:
            self._draw_ring(p, QPointF(x + 10, cy))
            x += 29
        if self.show_clock:
            self._text(p, QRectF(x, cy - 11, date_w + 2, 22), date_s, 11, QColor(255, 255, 255), Qt.AlignLeft)
            self._text(p, QRectF(x + date_w + 9, cy - 11, time_w + 2, 22), time_s, 11, QColor(255, 255, 255),
                       Qt.AlignLeft, bold=True)
        icon = getattr(self.pages[self.page], "status_icon", None)
        at = QPointF(r.right() - 45, cy)
        if icon == "wave" and self.info.get("playing"):  # Nusa drops the waveform when nothing plays
            t = time.monotonic()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255))
            for i in range(5):
                h = 4 + 10 * (0.5 + 0.5 * math.sin(t * 6 + i * 1.3)) if self.info.get("playing") else 4 + (i % 2) * 4
                p.drawRoundedRect(QRectF(at.x() - 10 + i * 4.5, at.y() - h / 2, 2.2, h), 1.1, 1.1)
        elif icon == "bell":
            bell(p, at, QColor(255, 255, 255))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 69, 58))
            p.drawEllipse(QPointF(at.x() + 7, at.y() - 7), 2.5, 2.5)

    def _draw_ring(self, p, c):
        """Battery level as a green ring (Nusa's status ring), with a bolt while plugged in."""
        ac, pct, _ = self.battery
        box = QRectF(c.x() - 8.5, c.y() - 8.5, 17, 17)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(48, 209, 88, 70), 3))
        p.drawEllipse(box)
        p.setPen(QPen(QColor(48, 209, 88) if pct > 20 or ac else QColor(255, 69, 58), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(box, 90 * 16, -int(pct / 100 * 360 * 16))
        if ac:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255))
            p.drawPolygon([QPointF(c.x() + 1, c.y() - 5), QPointF(c.x() - 2.5, c.y() + 1), QPointF(c.x() - 0.2, c.y() + 1),
                           QPointF(c.x() - 1, c.y() + 5), QPointF(c.x() + 2.5, c.y() - 1), QPointF(c.x() + 0.2, c.y() - 1)])

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
        font.setStyleStrategy(QFont.NoSubpixelAntialias)  # no ClearType colour fringes on the transparent window
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

    def _text(self, p, rect, s, size, color, align, bold=False, scroll=False):
        """One line of text; too long for `rect`: scrolls if `scroll` (repaints are running), else ends in "…"."""
        font = theme.font(size, QFont.Bold if bold else QFont.Normal)
        p.setFont(font)
        p.setPen(color)
        if scroll and QFontMetrics(font).horizontalAdvance(s) > rect.width():
            self._draw_scrolling(p, rect, s, font, color, align)
            return
        p.drawText(rect, align | Qt.AlignVCenter, QFontMetrics(font).elidedText(s, Qt.ElideRight, int(rect.width())))

    def _draw_scrolling(self, p, rect, s, font, color, align):
        t0 = self.marquee_t0.setdefault(s, time.monotonic())  # each line starts its own scroll from the start
        if len(self.marquee_t0) > 32:
            self.marquee_t0 = {s: t0}
        w = QFontMetrics(font).horizontalAdvance(s)
        x = marquee_offset(w, rect.width(), time.monotonic() - t0)
        # draw the line off-screen, then fade its edges with an alpha gradient (soft edges, like Apple's marquee)
        dpr = p.device().devicePixelRatioF() if p.device() else 1.0
        layer = QImage(max(1, int(rect.width() * dpr)), max(1, int(rect.height() * dpr)), QImage.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(dpr)
        layer.fill(0)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.Antialiasing)
        lp.setFont(font)
        lp.setPen(color)
        for dx in (x, x + w + MARQUEE_GAP):  # a second copy follows so the loop is seamless
            lp.drawText(QRectF(dx, 0, w + 1, rect.height()), Qt.AlignLeft | Qt.AlignVCenter, s)
        fade = min(MARQUEE_FADE, rect.width() / 4) / rect.width()
        mask = QLinearGradient(0, 0, rect.width(), 0)
        mask.setColorAt(0, QColor(0, 0, 0, 0 if x < 0 else 255))  # no left fade while the line waits at its start
        mask.setColorAt(fade, QColor(0, 0, 0, 255))
        mask.setColorAt(1 - fade, QColor(0, 0, 0, 255))
        mask.setColorAt(1, QColor(0, 0, 0, 0))
        lp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        lp.fillRect(QRectF(0, 0, rect.width(), rect.height()), mask)
        lp.end()
        p.drawImage(rect.topLeft(), layer)  # honours the painter's opacity and the page-slide clip


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

    menu.addAction("Ask Claude…", lambda: parent.start_ask())  # also reachable when another app owns the hotkey
    menu.addAction("Copy text from screen", lambda: parent.start_ocr())
    menu.addSeparator()
    menu.addAction("Settings…", lambda: parent.open_settings())
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
    if not ctypes.windll.user32.RegisterHotKey(int(island.winId()), ask.HOTKEY_ID, 0x1 | 0x2 | 0x4000, 0x20):
        print("ask: Ctrl+Alt+Space is taken by another app", file=sys.stderr)
    sys.exit(app.exec())
