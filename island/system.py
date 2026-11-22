"""Windows plumbing: COM volume, keyboard hook, brightness, battery, input language, fullscreen detection."""
import ctypes
import sys
import uuid
from ctypes import wintypes

from PySide6.QtCore import QTimer

BATTERY_LOW, BATTERY_CRITICAL = 20, 10  # % on battery; Nusa's own thresholds aren't visible in its binary
VOLUME_STEP = 0.02  # same 2 % step as the Windows flyout


def _guid(s):
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)


def _com(ptr, index, *args):
    """Call vtable slot `index` of a COM object; args are (ctype, value) pairs. Failed HRESULT raises OSError."""
    fn = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0][index]
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *(t for t, _ in args))(fn)(ptr, *(v for _, v in args))


_ole32 = ctypes.windll.ole32
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.PropVariantClear.argtypes = [ctypes.c_void_p]
_PKEY_FRIENDLY_NAME_GUID = list(uuid.UUID("A45C254E-DF1C-4EFD-8020-67D146A850E0").bytes_le)


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

    def default_device(self):
        """(endpoint id, friendly name) of the default playback device, read fresh each call."""
        device, store = ctypes.c_void_p(), ctypes.c_void_p()
        _com(self.enum, 4, (ctypes.c_int, 0), (ctypes.c_int, 1), (ctypes.c_void_p, ctypes.addressof(device)))
        try:
            idp = ctypes.c_void_p()
            _com(device, 5, (ctypes.c_void_p, ctypes.addressof(idp)))  # GetId
            try:
                dev_id = ctypes.wstring_at(idp)
            finally:
                _ole32.CoTaskMemFree(idp)
            _com(device, 4, (wintypes.DWORD, 0), (ctypes.c_void_p, ctypes.addressof(store)))  # OpenPropertyStore(STGM_READ)
            try:
                key = (ctypes.c_byte * 20)(*_PKEY_FRIENDLY_NAME_GUID, 14, 0, 0, 0)  # PKEY_Device_FriendlyName: fmtid + pid 14
                pv = (ctypes.c_ubyte * 24)()  # PROPVARIANT
                _com(store, 5, (ctypes.c_void_p, ctypes.addressof(key)), (ctypes.c_void_p, ctypes.addressof(pv)))  # GetValue
                try:
                    vt = int.from_bytes(bytes(pv[:2]), "little")
                    ptr = int.from_bytes(bytes(pv[8:16]), "little")
                    name = ctypes.wstring_at(ptr) if vt == 31 and ptr else ""  # VT_LPWSTR
                finally:
                    _ole32.PropVariantClear(pv)
            finally:
                _com(store, 2)
        finally:
            _com(device, 2)
        return dev_id, name or dev_id

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


def audio_popup(prev, cur):
    """(title, subtitle) when the default output device changed between two default_device() readings."""
    if prev and prev[0] != cur[0]:
        return "Audio output", cur[1]


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
        if code == 0 and vk in actions and island.isVisible() and island.on("hud_volume"):
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


def _query_notification_state(ptr):
    return ctypes.windll.shell32.SHQueryUserNotificationState(ptr)


def _notification_state():
    state = ctypes.c_int()
    _query_notification_state(ctypes.byref(state))
    return state.value


def fullscreen_app_running():
    return _notification_state() in (2, 3, 4)  # QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE


def notifications_quiet():
    """True unless Windows is accepting notifications (QUNS 5): quiet hours, presenting, locked..."""
    return _notification_state() != 5


# --- glass: real blur behind the island -------------------------------------------------------------------------
class _AccentPolicy(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint), ("animation", ctypes.c_int)]


class _CompositionData(ctypes.Structure):
    _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.POINTER(_AccentPolicy)), ("size", ctypes.c_size_t)]


ACCENT_BLUR_BEHIND, WCA_ACCENT_POLICY = 3, 19


def enable_blur(hwnd):
    """Ask DWM to blur whatever is behind the window (undocumented SetWindowCompositionAttribute, as Windows' own
    shell uses). It blurs the whole window rectangle, so pair it with set_region. False if Windows refused."""
    try:
        swca = ctypes.windll.user32.SetWindowCompositionAttribute
    except AttributeError:
        return False
    policy = _AccentPolicy(ACCENT_BLUR_BEHIND, 0, 0, 0)  # no DWM tint: the island paints its own
    data = _CompositionData(WCA_ACCENT_POLICY, ctypes.pointer(policy), ctypes.sizeof(policy))
    return bool(swca(wintypes.HWND(hwnd), ctypes.byref(data)))


def set_region(hwnd, points):
    """Clip the window to a polygon (physical pixels): the blur and the mouse only exist inside it."""
    arr = (wintypes.POINT * len(points))(*[wintypes.POINT(round(x), round(y)) for x, y in points])
    rgn = ctypes.windll.gdi32.CreatePolygonRgn(arr, len(points), 2)  # WINDING
    if rgn and not ctypes.windll.user32.SetWindowRgn(wintypes.HWND(hwnd), rgn, False):
        ctypes.windll.gdi32.DeleteObject(rgn)  # on success the window owns the region
