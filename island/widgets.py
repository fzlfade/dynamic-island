"""Widgets page: two cards side by side, each one of nine small widgets picked in Settings (Left / Right)."""
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPen

from island import store, theme
from island.pages import Page, bar

KINDS = [("week", "This week"), ("prayer", "Next prayer"), ("water", "Water"), ("focus", "Focus today"),
         ("clock", "World clock"), ("battery", "Battery"), ("moon", "Moon"), ("countdown", "Countdown"),
         ("weather", "Weather")]
NAMES = dict(KINDS)
GLYPHS = {"week": "", "prayer": "", "water": "", "focus": "", "clock": "",
          "battery": "", "moon": "", "countdown": "", "weather": ""}  # Segoe Fluent
DEFAULT = "week,prayer"  # left,right
ZONES = {  # World clock cities, picked in Settings > Widgets
    "Jakarta": "Asia/Jakarta", "Singapore": "Asia/Singapore", "Kuala Lumpur": "Asia/Kuala_Lumpur",
    "Bangkok": "Asia/Bangkok", "Manila": "Asia/Manila", "Hong Kong": "Asia/Hong_Kong", "Shanghai": "Asia/Shanghai",
    "Seoul": "Asia/Seoul", "Tokyo": "Asia/Tokyo", "Sydney": "Australia/Sydney", "Auckland": "Pacific/Auckland",
    "Delhi": "Asia/Kolkata", "Dubai": "Asia/Dubai", "Riyadh": "Asia/Riyadh", "Mecca": "Asia/Riyadh",
    "Istanbul": "Europe/Istanbul", "Moscow": "Europe/Moscow", "Cairo": "Africa/Cairo", "Berlin": "Europe/Berlin",
    "Paris": "Europe/Paris", "Amsterdam": "Europe/Amsterdam", "London": "Europe/London", "São Paulo": "America/Sao_Paulo",
    "New York": "America/New_York", "Toronto": "America/Toronto", "Chicago": "America/Chicago",
    "Denver": "America/Denver", "Los Angeles": "America/Los_Angeles", "Honolulu": "Pacific/Honolulu", "UTC": "UTC",
}
CITY_DEFAULTS = ("Tokyo", "London")


def cities(values):
    """The two World clock cities from settings (unknown names fall back to the defaults)."""
    return tuple(c if (c := values.get(f"clock_city_{i + 1}", "")) in ZONES else d for i, d in enumerate(CITY_DEFAULTS))
SYNODIC = 29.530588853  # days from new moon to new moon
NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)  # a known new moon
MOON_NAMES = ("New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous", "Full Moon", "Waning Gibbous",
              "Last Quarter", "Waning Crescent")


def parse(value):
    """'left,right' from settings -> two known widget kinds (unknown or missing ones fall back to the default)."""
    picked = [k for k in (value or "").split(",") if k in NAMES]
    left, right = (picked + DEFAULT.split(","))[:2] if len(picked) < 2 else picked[:2]
    return left, right


def moon(now):
    """(age in days 0..29.5, lit fraction 0..1, phase name) for a timezone-aware moment."""
    age = ((now - NEW_MOON).total_seconds() / 86400) % SYNODIC
    lit = (1 - math.cos(2 * math.pi * age / SYNODIC)) / 2
    return age, lit, MOON_NAMES[int((age / SYNODIC) * 8 + 0.5) % 8]


def countdown(values, today):
    """(title, target date, days left) from settings; with no valid date it counts to next New Year."""
    title = values.get("countdown_title", "").strip() or "New Year"
    try:
        target = date.fromisoformat(values.get("countdown_date", "").strip())
    except ValueError:
        target = date(today.year + 1, 1, 1)
    return title, target, (target - today).days


class WidgetsPage(Page):
    title = "Widgets"
    icon = ""  # page-icons bar (Fluent "widgets"-style grid)
    status_icon = "bell"

    def __init__(self):
        self.apply(store.load_kv("settings.txt"))

    def apply(self, values):
        self.left, self.right = parse(values.get("widgets"))
        self.cities = cities(values)

    def draw(self, p, r, island):
        top, h, w, gap = r.top() + 54, 114.0, 186.0, 9.0
        for kind, x in ((self.left, r.left() + 37), (self.right, r.left() + 37 + w + gap)):
            card = QRectF(x, top, w, h)
            p.setPen(QPen(theme.LINE, 1))
            p.setBrush(theme.CHIP_DARK)
            p.drawRoundedRect(card, theme.RADIUS_MD, theme.RADIUS_MD)
            island._text(p, QRectF(card.left() + 12, card.top() + 8, w - 24, 14), NAMES[kind].upper(), 7,
                         theme.PRIMARY, Qt.AlignLeft, bold=True)
            getattr(self, "_" + kind)(p, card.adjusted(12, 26, -12, -10), island)

    # --- one method per widget, drawn into the card's content box -----------------------------
    @staticmethod
    def _big(island, p, box, text, sub, color=theme.TEXT):
        island._text(p, QRectF(box.left(), box.top(), box.width(), 34), text, 20, color, Qt.AlignLeft, bold=True)
        island._text(p, QRectF(box.left(), box.top() + 34, box.width(), 18), sub, 9, theme.TEXT_MUTED, Qt.AlignLeft)

    def _week(self, p, box, island):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        cw = box.width() / 7
        for i in range(7):
            d = monday + timedelta(days=i)
            cell = QRectF(box.left() + i * cw, box.top(), cw, 16)
            island._text(p, cell, "MTWTFSS"[i], 8, theme.TEXT_MUTED, Qt.AlignCenter)
            num = QRectF(cell.center().x() - 10, box.top() + 18, 20, 20)
            if d == today:
                p.setPen(Qt.NoPen)
                p.setBrush(theme.PRIMARY_FILL)
                p.drawRoundedRect(num, theme.RADIUS_SM, theme.RADIUS_SM)
            island._text(p, num, str(d.day), 9, theme.ON_ACCENT if d == today else theme.TEXT, Qt.AlignCenter,
                         bold=d == today)
        rows = island._calendar_rows()
        line = f"{rows[0][0]}  {rows[0][1]}" if rows else "No events today"
        p.setPen(Qt.NoPen)
        p.setBrush(theme.SECONDARY if rows else theme.TEXT_DIM)
        p.drawEllipse(QPointF(box.left() + 3, box.top() + 56), 2.5, 2.5)
        island._text(p, QRectF(box.left() + 11, box.top() + 47, box.width() - 11, 18), line, 9,
                     theme.TEXT if rows else theme.TEXT_MUTED, Qt.AlignLeft)

    def _prayer(self, p, box, island):
        rows = island.prayer.rows(datetime.now())
        if not rows:
            self._big(island, p, box, "Off", "Turn on prayer times in Settings", theme.TEXT_MUTED)
            return
        name, _, hhmm = rows[0][1].rpartition(" ")
        self._big(island, p, box, hhmm, name)

    def _water(self, p, box, island):
        w = island.water
        self._big(island, p, box, f"{w.taken} ml", f"of {w.goal / 1000:g} L")
        bar(p, QRectF(box.left(), box.bottom() - 6, box.width(), 5), w.taken / w.goal if w.goal else 0.0)

    def _focus(self, p, box, island):
        minutes, sessions = island.focus_page.today()
        running = island.focus_page.compact_text()
        self._big(island, p, box, f"{minutes} min", running or f"{sessions} session{'s' * (sessions != 1)}",
                  theme.SECONDARY if minutes else theme.TEXT)

    def _clock(self, p, box, island):
        now = datetime.now(timezone.utc)
        for i, city in enumerate(self.cities):
            row = QRectF(box.left(), box.top() + 4 + i * 30, box.width(), 26)
            t = now.astimezone(ZoneInfo(ZONES[city]))
            island._text(p, row, city, 10, theme.TEXT_MUTED, Qt.AlignLeft | Qt.AlignVCenter)
            island._text(p, row, f"{t:%H:%M}", 15, theme.TEXT, Qt.AlignRight | Qt.AlignVCenter, bold=True)

    def _battery(self, p, box, island):
        if island.battery is None:
            self._big(island, p, box, "—", "No battery", theme.TEXT_MUTED)
            return
        ac, pct, charging = island.battery
        c, rad = QPointF(box.left() + 26, box.top() + 30), 22.0
        ring = QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(theme.TRACK, 5))
        p.drawEllipse(ring)
        color = theme.SUCCESS if pct > 20 or ac else theme.DANGER
        p.setPen(QPen(color, 5, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(ring, 90 * 16, -int(pct / 100 * 360 * 16))
        state = "Charging" if charging else "Plugged in" if ac else "On battery"
        island._text(p, QRectF(c.x() + rad + 12, box.top() + 8, 100, 30), f"{pct}%", 18, theme.TEXT, Qt.AlignLeft,
                     bold=True)
        island._text(p, QRectF(c.x() + rad + 12, box.top() + 38, 100, 18), state, 9, color, Qt.AlignLeft)

    def _moon(self, p, box, island):
        age, lit, name = moon(datetime.now(timezone.utc))
        c, rad = QPointF(box.left() + 24, box.top() + 30), 22.0
        p.setPen(Qt.NoPen)
        p.setBrush(theme.TRACK)
        p.drawEllipse(c, rad, rad)
        p.setBrush(theme.TEXT)
        p.drawPath(moon_path(c, rad, age))
        island._text(p, QRectF(c.x() + rad + 12, box.top() + 10, box.width() - 2 * rad - 12, 20), name, 10,
                     theme.TEXT, Qt.AlignLeft, bold=True)
        island._text(p, QRectF(c.x() + rad + 12, box.top() + 32, 100, 18), f"{round(lit * 100)}% lit", 9,
                     theme.TEXT_MUTED, Qt.AlignLeft)

    def _countdown(self, p, box, island):
        self._refresh()
        title, target, days = countdown(self._values, date.today())
        self._big(island, p, box, f"{days} days" if days >= 0 else "Done", f"to {title} · {target:%d %b %Y}",
                  theme.WARNING)

    def _weather(self, p, box, island):
        w = island.weather
        if not (w and w.now):
            self._big(island, p, box, "—", "Weather is loading", theme.TEXT_MUTED)
            return
        self._big(island, p, box, f"{round(w.now[0])}°", f"{w.now[1]} · {island.weather_place}")

    # countdown settings: read at most once a minute, never every frame
    _values, _read_at = {}, None

    def _refresh(self):
        now = datetime.now()
        if self._read_at is None or (now - self._read_at).total_seconds() > 60:
            self._values, self._read_at = store.load_kv("settings.txt"), now


def moon_path(c, rad, age):
    """The lit part of the moon disc: a half disc plus the terminator's half ellipse."""
    k = math.cos(2 * math.pi * age / SYNODIC)  # 1 new, 0 quarter, -1 full
    waxing = age < SYNODIC / 2
    disc = QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad)
    ell = QRectF(c.x() - abs(k) * rad, c.y() - rad, 2 * abs(k) * rad, 2 * rad)
    path = QPainterPath(QPointF(c.x(), c.y() - rad))
    path.arcTo(disc, 90, -180 if waxing else 180)  # lit half: right while waxing, left while waning
    bulge_right = (k > 0) == waxing  # a crescent's terminator bows toward the lit side, a gibbous's away
    path.arcTo(ell, -90, 180 if bulge_right else -180)
    path.closeSubpath()
    return path
