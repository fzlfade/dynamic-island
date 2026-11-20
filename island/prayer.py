"""Prayer times from sun position (no network, no Qt in times()); reminders are driven by the caller."""
import math
from datetime import date, datetime, time

from island import store, todo

GLYPH = "\uE706"
NAMES = ("Subuh", "Dzuhur", "Ashar", "Maghrib", "Isya")
DEFAULT_METHOD = "Kemenag RI"
METHODS = {"Kemenag RI": (20, 18), "JAKIM": (20, 18), "MUIS": (20, 18),
           "Muslim World League": (18, 17), "Umm al-Qura": (18.5, "+90")}
IHTIYAT = 2  # minutes, Kemenag only


def _sin(d):
    return math.sin(math.radians(d))


def _cos(d):
    return math.cos(math.radians(d))


def times(day, lat, lon, tz_hours, method=DEFAULT_METHOD, asr_factor=1, adj=None):
    """{name: datetime.time}, rounded up to the minute, after ihtiyat and per-prayer `adj` minutes."""
    fajr, isha = METHODS.get(method) or METHODS[DEFAULT_METHOD]
    d = day.toordinal() + 1721424.5 - 2451545.0  # Julian day at 0h UT
    g, q = 357.529 + 0.98560028 * d, 280.459 + 0.98564736 * d
    L = q + 1.915 * _sin(g) + 0.020 * _sin(2 * g)
    e = 23.439 - 0.00000036 * d
    ra = math.degrees(math.atan2(_cos(e) * _sin(L), _cos(L))) % 360 / 15
    decl = math.degrees(math.asin(_sin(e) * _sin(L)))
    eqt = q / 15 - ra
    eqt -= 24 * round(eqt / 24)
    dhuhr = 12 + tz_hours - lon / 15 - eqt

    def hours(a):  # shortcut: clamped, so polar day/night gives edge values, upgrade if high latitudes matter
        x = (-_sin(a) - _sin(decl) * _sin(lat)) / (_cos(decl) * _cos(lat))
        return math.degrees(math.acos(max(-1.0, min(1.0, x)))) / 15

    sunset = dhuhr + hours(0.833)
    asr_angle = -math.degrees(math.atan(1 / (asr_factor + math.tan(math.radians(abs(lat - decl))))))
    raw = (dhuhr - hours(fajr), dhuhr, dhuhr + hours(asr_angle), sunset,
           sunset + 1.5 if isha == "+90" else dhuhr + hours(isha))
    bonus = IHTIYAT if method == DEFAULT_METHOD or method not in METHODS else 0
    out = {}
    for name, h in zip(NAMES, raw):
        m = math.ceil(h * 60) + bonus + (adj or {}).get(name, 0)  # round up: never announce a prayer early
        out[name] = time(m // 60 % 24, m % 60)
    return out


def minute_of(t):
    return t.hour * 60 + t.minute


class Prayer:
    """Settings, location and the cached day schedule. rows() runs on every paint, so times() runs once per day."""

    def __init__(self, values):
        self.enabled = values.get("prayer") == "1"
        method = values.get("prayer_method", DEFAULT_METHOD)
        self.method = method if method in METHODS else DEFAULT_METHOD
        self.early = max(0, store.get_int(values, "prayer_early", 0))
        self.pause_media = values.get("prayer_pause_media") == "1"
        self.adj = {n: a for n in NAMES if (a := store.get_int(values, f"prayer_adj_{n.lower()}", 0))}
        self.loc = None  # (lat, lon); set from the weather thread, rebound atomically
        self.tz = None  # tests only; None means the machine's UTC offset at `now`
        self.cache = (None, {})

    def set_location(self, lat, lon):
        self.loc = (lat, lon)

    def schedule(self, day, tz=None):
        tz = self.tz if self.tz is not None else tz
        key = (day, self.loc, tz)
        if self.cache[0] != key:
            self.cache = (key, times(day, *self.loc, tz, self.method, adj=self.adj))
        return self.cache[1]

    def _ready(self):
        return self.enabled and self.loc is not None

    @staticmethod
    def _tz(now):
        return now.astimezone().utcoffset().total_seconds() / 3600

    def rows(self, now):
        if not self._ready():
            return []
        tz, m = self._tz(now), minute_of(now)
        for name, t in self.schedule(now.date(), tz).items():
            if minute_of(t) > m:
                return [("Next prayer", f"{name} {t:%H:%M}")]
        nxt = self.schedule(date.fromordinal(now.date().toordinal() + 1), tz)["Subuh"]
        return [("Next prayer", f"Subuh {nxt:%H:%M}")]

    def due(self, now, prev_min):
        """[(name, "HH:MM")] whose reminder moment is in (prev_min, now]; after a >2 h gap only the latest."""
        if not self._ready():
            return []
        sched = self.schedule(now.date(), self._tz(now))
        tasks = [todo.Task(False, max(0, minute_of(t) - self.early), n) for n, t in sched.items()]
        return [(t.text, f"{sched[t.text]:%H:%M}") for t in todo.due(tasks, prev_min, minute_of(now))]
