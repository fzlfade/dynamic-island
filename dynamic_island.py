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

Run:  python dynamic_island.py      Quit: right-click the island.
"""
import asyncio
import bisect
import ctypes
import uuid
from ctypes import wintypes
import json
import math
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal, QObject
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SessionManager
from winrt.windows.storage.streams import DataReader

PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
COLLAPSED = (190.0, 34.0)
COLLAPSED_PLAYING = (260.0, 34.0)
COLLAPSED_LYRICS = (380.0, 34.0)
HUD = (300.0, 34.0)
HUD_SECONDS = 1.5
BATTERY_POPUP = (340.0, 64.0)
BATTERY_SECONDS = 3.0
BATTERY_LOW, BATTERY_CRITICAL = 20, 10  # % on battery; Nusa's own thresholds aren't visible in its binary
VOLUME_STEP = 0.02  # same 2 % step as the Windows flyout
EXPANDED = (400.0, 124.0)
WIN_W, WIN_H = 440, 140  # window fits the largest island; transparent pixels are click-through
LRCLIB = "https://lrclib.net/api/search?"
LRC_STAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def parse_lrc(text):
    """'[01:02.50] words' lines -> sorted [(62.5, 'words')]. One line may carry several stamps."""
    out = []
    for line in text.splitlines():
        words = LRC_STAMP.sub("", line).strip()
        out += [(int(m) * 60 + float(s), words) for m, s in LRC_STAMP.findall(line)]
    return sorted(out)


def line_at(lyrics, pos):
    i = bisect.bisect_right(lyrics, pos, key=lambda l: l[0]) - 1
    return lyrics[i][1] if i >= 0 else ""


def fetch_lyrics(title, artist, duration):
    """Best synced match from LRCLIB, or [] when none fits this track's length."""
    artist = artist.split(" — ")[0]  # Apple Music reports "Artist — Album" as the artist
    q = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
    req = urllib.request.Request(LRCLIB + q, headers={"User-Agent": "DynamicIsland/0.1"})
    with urllib.request.urlopen(req, timeout=10) as r:
        hits = [h for h in json.load(r) if h.get("syncedLyrics")]
    if not hits:
        return []
    best = min(hits, key=lambda h: abs((h.get("duration") or 0) - duration))
    if abs((best.get("duration") or 0) - duration) > 5:  # another cut of the song: its timings would be off
        return []
    return parse_lrc(best["syncedLyrics"])


def _guid(s):
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)


def _com(ptr, index, *args):
    """Call vtable slot `index` of a COM object; args are (ctype, value) pairs. Failed HRESULT raises OSError."""
    fn = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0][index]
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *(t for t, _ in args))(fn)(ptr, *(v for _, v in args))


class Volume:
    """Master volume of the default playback device via Core Audio (the GUIDs Nusa's binary carries)."""
    CLSID_MMDeviceEnumerator = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
    IID_IMMDeviceEnumerator = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
    IID_IAudioEndpointVolume = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")

    def __init__(self):
        ctypes.windll.ole32.CoInitializeEx(None, 2)  # STA; S_FALSE/RPC_E_CHANGED_MODE when Qt already did it
        self.enum = ctypes.c_void_p()
        ctypes.oledll.ole32.CoCreateInstance(ctypes.byref(self.CLSID_MMDeviceEnumerator), None, 0x17,
                                             ctypes.byref(self.IID_IMMDeviceEnumerator), ctypes.byref(self.enum))

    def _call(self, index, *args):
        # default device fetched per call so plugging in headphones just works
        device, ep = ctypes.c_void_p(), ctypes.c_void_p()
        _com(self.enum, 4, (ctypes.c_int, 0), (ctypes.c_int, 1), (ctypes.c_void_p, ctypes.addressof(device)))  # eRender, eMultimedia
        try:
            _com(device, 3, (ctypes.c_void_p, ctypes.addressof(self.IID_IAudioEndpointVolume)), (wintypes.DWORD, 0x17),
                 (ctypes.c_void_p, None), (ctypes.c_void_p, ctypes.addressof(ep)))
            try:
                return _com(ep, index, *args)
            finally:
                _com(ep, 2)  # Release
        finally:
            _com(device, 2)

    def get(self):
        level, muted = ctypes.c_float(), wintypes.BOOL()
        self._call(9, (ctypes.c_void_p, ctypes.addressof(level)))   # GetMasterVolumeLevelScalar
        self._call(15, (ctypes.c_void_p, ctypes.addressof(muted)))  # GetMute
        return level.value, bool(muted.value)

    def set(self, level, muted):
        self._call(7, (ctypes.c_float, max(0.0, min(1.0, level))), (ctypes.c_void_p, None))  # SetMasterVolumeLevelScalar
        self._call(14, (wintypes.BOOL, muted), (ctypes.c_void_p, None))                       # SetMute
        return self.get()

    def step(self, delta):
        level, muted = self.get()
        return self.set(round(level + delta, 2), muted and delta < 0)  # volume up unmutes, like Windows

    def toggle_mute(self):
        level, muted = self.get()
        return self.set(level, not muted)


VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP = 0xAD, 0xAE, 0xAF
VK_CAPITAL = 0x14
LANGUAGE_SWITCH_KEYS = {0x20, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}  # Space, L/R Shift, Ctrl, Alt, Win
HOOKPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user32 = ctypes.windll.user32
_user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
_user32.CallNextHookEx.restype = wintypes.LPARAM
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_kernel32 = ctypes.windll.kernel32
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE


GUID_VIDEO_BRIGHTNESS = _guid("ADED5E82-B909-4619-9949-F5D71DAC0BCB")  # GUID_DEVICE_POWER_POLICY_VIDEO_BRIGHTNESS
_user32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
_user32.RegisterPowerSettingNotification.restype = ctypes.c_void_p


def install_brightness(island):
    """Ask Windows to post WM_POWERBROADCAST to the island when display brightness changes (Nusa does the same).
    Listen-only: brightness keys still reach Windows, so its own flyout can still appear."""
    if not _user32.RegisterPowerSettingNotification(int(island.winId()), ctypes.addressof(GUID_VIDEO_BRIGHTNESS), 0):
        print("brightness: notification failed", ctypes.GetLastError(), file=sys.stderr)


_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
_user32.GetKeyboardLayout.restype = ctypes.c_void_p


class _PowerStatus(ctypes.Structure):  # SYSTEM_POWER_STATUS
    _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
                ("saver", ctypes.c_ubyte), ("life", wintypes.DWORD), ("full_life", wintypes.DWORD)]


def battery_status():
    """(on AC, percent, charging), or None on a desktop / while Windows reports 'unknown'."""
    s = _PowerStatus()
    if not _kernel32.GetSystemPowerStatus(ctypes.byref(s)) or s.flag & 128 or s.ac == 255 or s.percent > 100:
        return None
    # charging is its own flag: plugged in but held at ~80 % (Lenovo conservation mode) is AC without charging
    return s.ac == 1, s.percent, bool(s.flag & 8)


def battery_popup(prev, cur):
    """(title, subtitle) for a change worth a popup between two battery_status() readings, else None."""
    if not prev or not cur:
        return None
    (was_ac, was_pct, _), (ac, pct, charging) = prev, cur
    if ac and not was_ac:
        return "Charger connected", "Fully charged" if pct >= 100 else f"{'Charging' if charging else 'Plugged in'} · {pct}%"
    if was_ac and not ac:
        return "Charger unplugged", f"On battery · {pct}%"
    if ac and pct >= 100 > was_pct:
        return "Fully charged", "You can unplug"
    if not ac and pct <= BATTERY_CRITICAL < was_pct:  # before "low": a drop across both is critical
        return "Battery critical", "Plug in now"
    if not ac and pct <= BATTERY_LOW < was_pct:
        return "Low battery", "Plug in soon"
    return None


def foreground_layout():
    """(foreground window, LANGID of the keyboard layout its thread is typing with)."""
    hwnd = _user32.GetForegroundWindow()
    hkl = _user32.GetKeyboardLayout(_user32.GetWindowThreadProcessId(hwnd, None)) or 0
    return hwnd, hkl & 0xFFFF  # low word of the HKL is the language


def language_name(langid):
    """0x0409 -> ('English (United States)', 'EN-US')."""
    tag = ctypes.create_unicode_buffer(85)
    _kernel32.LCIDToLocaleName(langid, tag, 85, 0)
    display = ctypes.create_unicode_buffer(128)
    _kernel32.GetLocaleInfoEx(tag, 0x2, display, 128)  # LOCALE_SLOCALIZEDDISPLAYNAME
    return display.value or tag.value or f"0x{langid:04X}", tag.value.upper()


def install_keys(island, volume):
    """WH_KEYBOARD_LL hook on the Qt thread (Qt pumps its messages).
    Volume keys are swallowed (hides the Windows flyout); Caps Lock passes through and only triggers the HUD."""
    actions = {VK_VOLUME_MUTE: volume.toggle_mute,
               VK_VOLUME_DOWN: lambda: volume.step(-VOLUME_STEP),
               VK_VOLUME_UP: lambda: volume.step(VOLUME_STEP)}

    @HOOKPROC
    def proc(code, wparam, lparam):
        vk = ctypes.cast(lparam, ctypes.POINTER(wintypes.DWORD))[0]  # KBDLLHOOKSTRUCT.vkCode is the first field
        if code == 0 and vk == VK_CAPITAL and wparam in (0x100, 0x104):
            # the toggle flips only after this hook returns: read it from the event loop, not here
            QTimer.singleShot(0, island.show_caps)
        if code == 0 and vk in LANGUAGE_SWITCH_KEYS and wparam in (0x101, 0x105):  # WM_KEYUP, WM_SYSKEYUP
            # Win+Space / Alt+Shift / Ctrl+Shift commit on release; the app applies the layout a moment later
            QTimer.singleShot(150, island.check_language)
        # hidden over a fullscreen app: leave the keys to Windows so they still do something
        if code == 0 and vk in actions and island.isVisible():
            if wparam in (0x100, 0x104):  # WM_KEYDOWN, WM_SYSKEYDOWN (auto-repeat arrives as more keydowns)
                try:
                    island.show_volume(*actions[vk]())
                except OSError as e:  # no audio device etc.: let Windows handle the key
                    print("volume:", e, file=sys.stderr)
                    return _user32.CallNextHookEx(None, code, wparam, lparam)
            return 1
        return _user32.CallNextHookEx(None, code, wparam, lparam)

    island._hook_proc = proc  # keep the callback alive as long as the hook
    module = _kernel32.GetModuleHandleW(None)
    if not _user32.SetWindowsHookExW(13, proc, module, 0):  # WH_KEYBOARD_LL
        print("volume: keyboard hook failed", ctypes.GetLastError(), file=sys.stderr)


class Media(QObject):
    """Polls the current media session on its own asyncio thread."""
    changed = Signal(dict)

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.session = None
        self._last_title = None
        self.lyrics = []
        self._lyrics_task = None  # strong ref: the loop only holds tasks weakly
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(self._poll(), self.loop)

    async def _poll(self):
        manager = await SessionManager.request_async()
        while True:
            # shortcut: 1 s polling instead of WinRT change events, upgrade if 1 s lag on track change bothers you
            try:
                await self._read(manager)
            except Exception as e:  # session can vanish mid-read when a player closes
                print("media:", e, file=sys.stderr)
            await asyncio.sleep(1)

    async def _read(self, manager):
        s = self.session = manager.get_current_session()
        if not s:
            self._last_title = None
            self.changed.emit({})
            return
        props = await s.try_get_media_properties_async()
        playing = s.get_playback_info().playback_status == PLAYING
        tl = s.get_timeline_properties()
        duration = (tl.end_time - tl.start_time).total_seconds()
        # players only report position now and then; extrapolate from their last report
        pos = tl.position.total_seconds()
        if playing:
            pos += (datetime.now(timezone.utc) - tl.last_updated_time).total_seconds()
        info = {"title": props.title or "", "artist": props.artist or "", "playing": playing,
                "pos": max(0.0, min(pos, duration)), "pos_at": time.monotonic()}
        if props.title != self._last_title:  # thumbnail and lyrics only when the track changes
            self._last_title = props.title
            self.lyrics = []
            info["thumb"] = await self._thumb(props.thumbnail)
            if duration > 0:  # no timeline (some players) means nothing to sync against
                self._lyrics_task = asyncio.create_task(self._load_lyrics(props.title, props.artist, duration))
        info["lyrics"] = self.lyrics
        self.changed.emit(info)

    async def _load_lyrics(self, title, artist, duration):
        try:
            lyrics = await asyncio.get_running_loop().run_in_executor(None, fetch_lyrics, title, artist, duration)
        except (OSError, ValueError) as e:  # offline, LRCLIB down or bad JSON: just no lyrics
            print("lyrics:", e, file=sys.stderr)
            return
        if title == self._last_title:  # track may have changed while we waited
            self.lyrics = lyrics

    @staticmethod
    async def _thumb(ref):
        if not ref:
            return b""
        stream = await ref.open_read_async()
        reader = DataReader(stream.get_input_stream_at(0))
        n = await reader.load_async(stream.size)
        return bytes(reader.read_buffer(n))

    def send(self, action):
        if self.session:
            coro = {"prev": self.session.try_skip_previous_async,
                    "toggle": self.session.try_toggle_play_pause_async,
                    "next": self.session.try_skip_next_async}[action]()
            asyncio.run_coroutine_threadsafe(_await(coro), self.loop)


async def _await(op):
    await op


def fullscreen_app_running():
    state = ctypes.c_int()
    ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    return state.value in (2, 3, 4)  # QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE


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
        self.hud_timer = QTimer(self, singleShot=True, timeout=self.update)  # repaint once when the HUD expires

        self.anim = QVariantAnimation(self, duration=420, easingCurve=QEasingCurve.OutBack)
        self.anim.valueChanged.connect(self._set_expand)
        self.leave_delay = QTimer(self, singleShot=True, interval=350, timeout=lambda: self._animate_to(0.0))
        self.frame = QTimer(self, interval=16, timeout=self.update)  # only runs while bars animate
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
        (self.frame.start if info.get("playing") else self.frame.stop)()
        self.update()

    def show_volume(self, level, muted):
        self._show_hud(("volume", level, muted))

    def nativeEvent(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x218 and msg.wParam == 0x8013:  # WM_POWERBROADCAST, PBT_POWERSETTINGCHANGE
            setting = ctypes.string_at(msg.lParam, 16)  # POWERBROADCAST_SETTING.PowerSetting GUID
            if setting == bytes(GUID_VIDEO_BRIGHTNESS):
                self.on_brightness(ctypes.c_uint32.from_address(msg.lParam + 20).value)  # Data: DWORD %
        if msg.message == 0x218 and msg.wParam == 0xA:  # PBT_APMPOWERSTATUSCHANGE: sent to every top-level window
            self.check_battery()
        return False, 0

    def check_battery(self):
        cur = battery_status()
        if cur is None:
            return  # keep the old baseline through 'unknown' blips
        popup = battery_popup(self.battery, cur)
        if popup:
            self._show_hud(("battery", cur[1] / 100, cur[2], cur[0], *popup), BATTERY_SECONDS)
        self.battery = cur

    def on_brightness(self, percent):
        # Windows sends the current value right after registering: remember it, don't flash the HUD
        if self.brightness is not None and percent != self.brightness:
            self._show_hud(("brightness", percent / 100, False))
        self.brightness = percent

    def show_caps(self):
        on = bool(_user32.GetKeyState(VK_CAPITAL) & 1)  # low bit = toggled
        self._show_hud(("caps", 1.0 if on else 0.0, False))

    def _show_hud(self, hud, seconds=HUD_SECONDS):
        self.hud = hud
        self.hud_until = time.monotonic() + seconds
        self.hud_timer.start(int(seconds * 1000) + 20)
        self.update()

    def _hud_active(self):
        return time.monotonic() < self.hud_until

    def check_language(self):
        current = foreground_layout()
        # only a change within the same window counts: with per-app input, switching windows changes the layout too
        if self.layout and current[0] == self.layout[0] and current[1] != self.layout[1]:
            self._show_hud(("language", current[1], False))  # level slot carries the LANGID
        self.layout = current

    def _check_fullscreen(self):
        self.setVisible(not fullscreen_app_running())
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

    def _island_rect(self):
        if self._hud_active():
            cw, ch = BATTERY_POPUP if self.hud[0] == "battery" else HUD
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
        if e.button() == Qt.RightButton:
            QApplication.quit()
        for action, rect in self.buttons.items():
            if rect.contains(e.position()):
                self.media.send(action)
                # optimistic flip so the icon reacts before the next 1 s poll
                if action == "toggle" and self.info:
                    self._on_media({**self.info, "playing": not self.info["playing"],
                                    "pos": self._pos(), "pos_at": time.monotonic()})

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
        if not self.info:
            self._text(p, QRectF(r), "No media", 11, QColor(140, 140, 140), Qt.AlignCenter)
            return
        if self.expand < 0.5:
            self._draw_compact(p, r, 1 - self.expand * 2)
        else:
            self._draw_expanded(p, r, (self.expand - 0.5) * 2)

    def _draw_compact(self, p, r, alpha):
        p.setOpacity(alpha)
        self._draw_art(p, QRectF(r.left() + 10, r.top() + 6, 22, 22), 6)
        self._draw_bars(p, QPointF(r.right() - 34, r.center().y()))
        lyric_box = QRectF(r.left() + 42, r.top(), r.width() - 88, r.height())
        self._text(p, lyric_box, self._lyric(), 10, QColor(255, 255, 255), Qt.AlignCenter)

    def _draw_expanded(self, p, r, alpha):
        p.setOpacity(min(alpha, 1.0))
        art = QRectF(r.left() + 18, r.top() + 16, 64, 64)
        self._draw_art(p, art, 14)
        x = art.right() + 14
        text_w = r.right() - x - 18
        self._text(p, QRectF(x, art.top() + 2, text_w, 22), self.info["title"], 12, QColor(255, 255, 255), Qt.AlignLeft, bold=True)
        self._text(p, QRectF(x, art.top() + 24, text_w, 20), self.info["artist"], 10, QColor(160, 160, 160), Qt.AlignLeft)
        self._text(p, QRectF(x, art.top() + 44, text_w - 44, 20), self._lyric(), 10, QColor(120, 220, 140), Qt.AlignLeft)
        self._draw_bars(p, QPointF(r.right() - 34, art.top() + 52))
        cy, cx = r.bottom() - 22, r.center().x()
        for action, dx in (("prev", -56), ("toggle", 0), ("next", 56)):
            self.buttons[action] = QRectF(cx + dx - 18, cy - 14, 36, 28)
            self._draw_icon(p, action, QPointF(cx + dx, cy))

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
        low = not ac and level * 100 <= BATTERY_LOW
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

    def _draw_hud(self, p, r):
        if self.hud[0] == "battery":
            self._draw_battery(p, r)
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
        icon_font = QFont()
        icon_font.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol"])
        icon_font.setPixelSize(16)
        p.setFont(icon_font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(r.left() + 14, r.top(), 24, r.height()), Qt.AlignCenter, glyph)
        if kind == "language":
            display, tag = language_name(level)
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

    def _draw_icon(self, p, action, c):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        tri = lambda x, d: [QPointF(x, c.y() - 7), QPointF(x + d * 10, c.y()), QPointF(x, c.y() + 7)]
        if action == "toggle" and self.info.get("playing"):
            p.drawRect(QRectF(c.x() - 6, c.y() - 8, 4, 16))
            p.drawRect(QRectF(c.x() + 2, c.y() - 8, 4, 16))
        elif action == "toggle":
            p.drawPolygon(tri(c.x() - 4, 1))
        else:
            d = 1 if action == "next" else -1
            p.drawPolygon(tri(c.x() - d * 9, d))
            p.drawPolygon(tri(c.x() - d * 1, d))

    def _text(self, p, rect, s, size, color, align, bold=False):
        font = QFont("Segoe UI Variable Text", size, QFont.DemiBold if bold else QFont.Normal)
        p.setFont(font)
        p.setPen(color)
        p.drawText(rect, align | Qt.AlignVCenter, QFontMetrics(font).elidedText(s, Qt.ElideRight, int(rect.width())))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    island = Island(Media())
    install_keys(island, Volume())
    install_brightness(island)
    sys.exit(app.exec())
