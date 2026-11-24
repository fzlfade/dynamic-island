"""Settings window in Nusa's style: a sidebar of coloured section tiles; each section is cards of rows with a title,
a grey subtitle and a control (switch, ± stepper, segmented choice). Every option here changes real behaviour."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTime, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
                               QGridLayout, QLineEdit, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from island import prayer, store, theme, widgets

S, W = "settings.txt", "water.txt"
GREEN, GREY = theme.SUCCESS, theme.TEXT_MUTED

SECTIONS = [  # (name, glyph colour, Segoe Fluent glyph)
    ("General", theme.TEXT_MUTED, ""), ("Pages", theme.PRIMARY, ""), ("Appearance", theme.SECONDARY, ""),
    ("Music and lyrics", theme.SECONDARY, ""), ("Notifications", theme.DANGER, ""), ("To-do", theme.SUCCESS, ""),
    ("Pomodoro", theme.SECONDARY, ""), ("Water", theme.PRIMARY, ""), ("Prayer", theme.PRIMARY, ""),
    ("Shelf", theme.WARNING, ""), ("HUD & popups", theme.PRIMARY, ""), ("Ask Claude", theme.SECONDARY, ""),
    ("Widgets", theme.PRIMARY, "\uF0E2"),
    ("About", theme.TEXT_MUTED, ""),
]
PAGES = [("media", "Music"), ("widgets", "Widgets"), ("focus", "Pomodoro"), ("water", "Water"), ("shelf", "Shelf"), ("todo", "To-do"),
         ("today", "Today")]
DEFAULT_PAGES = "media,widgets,focus,water,shelf,todo"

# (section, group, file, key, kind, default, title, subtitle, options). file None: not a plain key=value
FIELDS = [
    ("General", "Startup", None, "autostart", "switch", 0, "Start with Windows", "", None),
    ("General", "Notch", S, "notch_style", "segment", 1, "Style", "On the top edge, or floating just below it",
     ["Notch", "Floating"]),
    ("General", "Notch", S, "idle_pill", "segment", 0, "When idle", "The time and battery ring, or a thin sliver",
     ["Clock", "Minimal"]),
    ("General", "Notch", S, "clock", "switch", 1, "Date & time", "The clock and date beside the status ring", None),
    ("General", "Notch", S, "ring", "switch", 1, "Status ring", "Battery level next to the clock", None),
    ("General", "Full screen", S, "hide_fullscreen", "switch", 1, "Hide in full screen",
     "Games, videos and slides that fill the screen", None),
    ("Pages", "", S, "pages", "pages", DEFAULT_PAGES, "", "", None),
    ("Widgets", "", S, "widgets", "widgets", widgets.DEFAULT, "", "", None),
    ("Widgets", "World clock", S, "clock_city_1", "choice", widgets.CITY_DEFAULTS[0], "First city", "",
     list(widgets.ZONES)),
    ("Widgets", "World clock", S, "clock_city_2", "choice", widgets.CITY_DEFAULTS[1], "Second city", "",
     list(widgets.ZONES)),
    ("Widgets", "Countdown", S, "countdown_title", "text", "New Year", "Title", "What you are counting down to",
     None),
    ("Widgets", "Countdown", S, "countdown_date", "text", "", "Date", "YYYY-MM-DD; empty counts to next 1 January",
     None),
    ("Appearance", "Notch", S, "open_click", "segment", 0, "Open the notch", "", ["Hover", "Click"]),
    ("Appearance", "Notch", S, "page_icons", "switch", 1, "Page icons",
     "Show page icons when you hover the page dots", None),
    ("Appearance", "Motion", S, "fast_animation", "segment", 0, "Animation speed", "", ["Normal", "Fast"]),
    ("Music and lyrics", "Lyrics", S, "lyrics", "switch", 1, "Show lyrics",
     "From LRCLIB, a community-contributed lyrics database", None),
    ("Notifications", "In the notch", S, "notif_pill", "switch", 1, "Show notifications",
     "A short pill when something arrives", None),
    ("To-do", "Google Calendar", S, "calendar_url", "secret", "", "Calendar link",
     "Google Calendar › Settings › your calendar › Secret address in iCal format", None),
    ("Pomodoro", "Durations", S, "focus", "int", 25, "Focus", "", (1, 180, 1, " min")),
    ("Pomodoro", "Durations", S, "short_break", "int", 5, "Short break", "", (1, 60, 1, " min")),
    ("Pomodoro", "Durations", S, "long_break", "int", 15, "Long break", "", (1, 120, 1, " min")),
    ("Water", "Reminders", W, "on", "switch", 1, "Water reminders", "Spread across your active hours", None),
    ("Water", "Plan", W, "goal", "int", 1500, "Daily goal", "", (250, 6000, 250, " ml")),
    ("Water", "Plan", W, "bottle", "int", 500, "Bottle size", "", (100, 3000, 50, " ml")),
    ("Water", "Plan", W, "glass", "int", 250, "One glass", "", (50, 1000, 50, " ml")),
    ("Water", "Plan", W, "every", "int", 60, "Remind every", "", (10, 240, 5, " min")),
    ("Water", "Plan", W, "start", "time", 480, "Active from", "", False),
    ("Water", "Plan", W, "end", "time", 1440, "Active until", "", True),
    ("Prayer", "Prayer times", S, "prayer", "switch", 0, "Show prayer times and reminders", "", None),
    ("Prayer", "Prayer times", S, "prayer_method", "choice", prayer.DEFAULT_METHOD, "Method", "", list(prayer.METHODS)),
    ("Prayer", "Reminders", S, "prayer_early", "int", 0, "Remind early", "", (0, 60, 1, " min")),
    ("Prayer", "Reminders", S, "prayer_pause_media", "switch", 0, "Pause media at prayer time", "", None),
    *[("Prayer", "Fine-tune", S, f"prayer_adj_{n.lower()}", "int", 0, n, "", (-30, 30, 1, " min"))
      for n in prayer.NAMES],
    ("Prayer", "Location", None, "auto_location", "switch", 1, "My location",
     "Detected automatically; used for prayer times and weather", None),
    ("Prayer", "Location", S, "place", "text", "", "Place name", "", None),
    ("Prayer", "Location", S, "lat", "float", 0.0, "Latitude", "", (-90.0, 90.0)),
    ("Prayer", "Location", S, "lon", "float", 0.0, "Longitude", "", (-180.0, 180.0)),
    ("Shelf", "Shelf", S, "shelf_clear", "switch", 0, "Start with an empty Shelf",
     "Files from your last session are cleared when the island starts", None),
    ("Shelf", "Smart OCR", None, "ocr_info", "info", "Ctrl + Alt + T", "Copy text from screen",
     "Select any area and the island copies its text", None),
    *[("HUD & popups", "Indicators", S, f"hud_{k}", "switch", 1, t, "", None)
      for k, t in (("volume", "Volume"), ("brightness", "Brightness"), ("caps", "Caps Lock"), ("language", "Input language"))],
    *[("HUD & popups", "Popups", S, f"popup_{k}", "switch", 1, t, "", None)
      for k, t in (("battery", "Battery"), ("wifi", "Wi-Fi"), ("audio", "Audio output"))],
    ("Ask Claude", "Ask", None, "ask_key", "info", "Ctrl + Alt + Space", "Shortcut", "Or tray › Ask Claude…", None),
    ("Ask Claude", "Ask", None, "ask_auth", "info", "", "Account", "Uses ANTHROPIC_API_KEY or `ant auth login`", None),
    ("About", "Info", None, "about_lyrics", "info", "LRCLIB", "Lyrics", "", None),
    ("About", "Info", None, "about_weather", "info", "MET Norway", "Weather", "", None),
]
LOCATION = ("place", "lat", "lon")

_c = {k: theme.hex_(getattr(theme, k)) for k in ("TEXT", "TEXT_MUTED", "TEXT_DIM", "CARD", "LINE", "INPUT", "CHIP",
                                                   "PRIMARY", "PRIMARY_FILL", "ON_ACCENT")}
STYLE = f"""
QWidget {{ background: transparent; color: {_c["TEXT"]}; }}
QLabel#title {{ font-size: 20px; font-weight: 700; letter-spacing: 1px; }}
QLabel#group {{ color: {_c["PRIMARY"]}; font-size: 11px; letter-spacing: 1px; padding: 10px 0 4px 6px; }}
QLabel#sub {{ color: {_c["TEXT_MUTED"]}; font-size: 11px; }}
QLabel#value {{ color: {_c["TEXT_MUTED"]}; }}
QFrame#card {{ background: {_c["CARD"]}; border: 1px solid {_c["LINE"]}; border-radius: {theme.RADIUS_MD:g}px; }}
QFrame#sep {{ background: {_c["LINE"]}; max-height: 1px; min-height: 1px; margin-left: 14px; }}
QLineEdit, QDoubleSpinBox, QComboBox {{ background: {_c["INPUT"]}; border: 1px solid {_c["LINE"]};
    border-radius: {theme.RADIUS_SM:g}px; padding: 4px 8px; min-width: 150px; color: {_c["TEXT"]}; }}
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: {theme.FOCUS_WIDTH:g}px solid {_c["PRIMARY"]}; }}
QLineEdit:disabled, QDoubleSpinBox:disabled {{ color: {_c["TEXT_DIM"]}; }}
QComboBox QAbstractItemView {{ background: {theme.hex_(theme.ISLAND_SOLID)}; selection-background-color: {_c["PRIMARY_FILL"]};
    selection-color: {_c["ON_ACCENT"]}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
"""


def _focus_ring(p, widget, rect, radius):
    """Keyboard focus: a cyan outline, so Tab shows where you are on the custom-drawn controls."""
    if widget.hasFocus():
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(theme.PRIMARY, theme.FOCUS_WIDTH))
        p.drawRoundedRect(rect, radius, radius)


class Switch(QAbstractButton):
    """iOS-style toggle (Nusa's green switch)."""

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(lambda _: self.update())

    def sizeHint(self):
        return QSize(44, 28)  # 2 px round the 40x22 body for the focus ring

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setOpacity(1.0 if self.isEnabled() else 0.4)
        p.setBrush(GREEN if self.isChecked() else theme.TRACK)
        p.drawRoundedRect(QRectF(2, 3, 40, 22), theme.RADIUS_MD, theme.RADIUS_MD)
        p.setBrush(theme.TEXT if self.isChecked() else theme.TEXT_MUTED)
        p.drawRoundedRect(QRectF(23 if self.isChecked() else 5, 6, 16, 16), theme.RADIUS_SM, theme.RADIUS_SM)
        _focus_ring(p, self, QRectF(1, 2, 42, 24), theme.RADIUS_MD + 1)


class Stepper(QWidget):
    """Nusa's "−  25 min  +" row control."""
    changed = Signal()

    def __init__(self, lo, hi, step, suffix=""):
        super().__init__()
        self.lo, self.hi, self.step, self.suffix, self._v = lo, hi, step, suffix, lo
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.minus, self.label, self.plus = RoundButton("−"), QLabel(), RoundButton("+")
        self.label.setAlignment(Qt.AlignCenter)  # white value, like Nusa's steppers
        self.label.setMinimumWidth(64)
        self.minus.clicked.connect(lambda: self.setValue(self._v - self.step))
        self.plus.clicked.connect(lambda: self.setValue(self._v + self.step))
        for w in (self.minus, self.label, self.plus):
            row.addWidget(w)

    def value(self):
        return self._v

    def setValue(self, v):
        self._v = max(self.lo, min(self.hi, int(v)))
        self.label.setText(self.text())
        self.changed.emit()

    def text(self):
        return f"{self._v}{self.suffix}"


class TimeStepper(Stepper):
    """Time of day in 30-minute steps; an end time may be 24:00 (midnight)."""

    def __init__(self, end=False):
        self.end = end
        super().__init__(0, 1440 if end else 1410, 30)

    def text(self):
        return f"{self._v // 60:02d}:{self._v % 60:02d}"

    def time(self):
        return QTime(self._v // 60 % 24, self._v % 60)

    def setTime(self, t):
        m = t.hour() * 60 + t.minute()
        self.setValue(1440 if self.end and m == 0 else m)


class Segmented(QWidget):
    """Nusa's segmented control (e.g. Hover | Click)."""

    def __init__(self, options):
        super().__init__()
        self.options, self.index = options, 0
        self.setFixedSize(46 * len(options) + 4, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)  # Tab reaches it; Left/Right choose

    def currentText(self):
        return self.options[self.index]

    def setCurrentText(self, text):
        self.index = self.options.index(text) if text in self.options else 0
        self.update()

    def mousePressEvent(self, e):
        self.index = min(len(self.options) - 1, int(e.position().x() // (self.width() / len(self.options))))
        self.update()

    def keyPressEvent(self, e):
        step = {Qt.Key_Left: -1, Qt.Key_Right: 1}.get(e.key())
        if step is None:
            return super().keyPressEvent(e)
        self.index = max(0, min(len(self.options) - 1, self.index + step))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.CHIP_DARK)
        p.drawRoundedRect(QRectF(self.rect()), theme.RADIUS_MD, theme.RADIUS_MD)
        w = (self.width() - 4) / len(self.options)
        p.setBrush(theme.SELECTED)  # a lighter glass segment, as on Apple's segmented controls
        p.drawRoundedRect(QRectF(2 + self.index * w, 2, w, self.height() - 4), theme.RADIUS_SM, theme.RADIUS_SM)
        p.setFont(theme.font(9))
        for i, text in enumerate(self.options):
            p.setPen(theme.TEXT if i == self.index else GREY)
            p.drawText(QRectF(2 + i * w, 0, w, self.height()), Qt.AlignCenter, text)
        _focus_ring(p, self, QRectF(self.rect()).adjusted(1, 1, -1, -1), theme.RADIUS_MD)


class PagesList(QWidget):
    """Which pages the notch shows, in order: a switch and ▲▼ per page (Nusa: "Drag to rearrange")."""

    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.order, self.switches = [k for k, _ in PAGES], {}

    def setText(self, value):
        on = [k for k in value.split(",") if k in dict(PAGES)]
        self.order = on + [k for k, _ in PAGES if k not in on]
        self.enabled = set(on)
        self._build()

    def text(self):
        return ",".join(k for k in self.order if self.switches[k].isChecked())

    def _move(self, key, d):
        on = {k for k in self.order if self.switches[k].isChecked()}
        i = self.order.index(key)
        self.order.insert(max(0, min(len(self.order) - 1, i + d)), self.order.pop(i))
        self.enabled = on
        self._build()

    def _build(self):
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        card = _card()
        names = dict(PAGES)
        for n, key in enumerate(self.order):
            sw = self.switches[key] = Switch()
            sw.setChecked(key in self.enabled)
            up, down = RoundButton("▲"), RoundButton("▼")
            up.clicked.connect(lambda _=0, k=key: self._move(k, -1))
            down.clicked.connect(lambda _=0, k=key: self._move(k, 1))
            _add_row(card, f"{n + 1}   {names[key]}", "", [up, down, sw])
        self.lay.addWidget(QLabel("Your notch shows these pages in order.", objectName="sub"))
        self.lay.addWidget(card)


class WidgetTile(QAbstractButton):
    """One widget in the picker grid; shows L / R when it fills a side."""

    def __init__(self, kind, name):
        super().__init__()
        self.setText(name)
        self.kind = kind
        self.badge = ""
        self.setFixedSize(112, 64)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QPen(theme.PRIMARY if self.badge else theme.LINE, 1.5 if self.badge else 1))
        p.setBrush(theme.CHIP_DARK)
        p.drawRoundedRect(box, theme.RADIUS_MD, theme.RADIUS_MD)
        icon = QFont()
        icon.setFamilies([theme.ICONS, "Segoe MDL2 Assets"])
        icon.setPixelSize(16)
        p.setFont(icon)
        p.setPen(theme.PRIMARY if self.badge else theme.TEXT_MUTED)
        p.drawText(QRectF(box.left() + 8, box.top() + 8, 20, 20), Qt.AlignCenter, widgets.GLYPHS[self.kind])
        p.setFont(theme.font(9))
        p.setPen(theme.TEXT if self.badge else theme.TEXT_MUTED)
        p.drawText(box.adjusted(8, 0, -8, -8), Qt.AlignLeft | Qt.AlignBottom, self.text())
        if self.badge:
            tag = QRectF(box.right() - 22, box.top() + 5, 17, 17)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.PRIMARY_FILL)
            p.drawRoundedRect(tag, theme.RADIUS_SM, theme.RADIUS_SM)
            p.setPen(theme.ON_ACCENT)
            p.setFont(theme.font(8, QFont.Bold))
            p.drawText(tag, Qt.AlignCenter, self.badge)
        _focus_ring(p, self, QRectF(self.rect()).adjusted(1, 1, -1, -1), theme.RADIUS_MD)


class WidgetPicker(QWidget):
    """Nusa-style "Choose widgets": pick Left or Right, then click a widget for that side."""

    def __init__(self):
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(QLabel("Choose the two widgets on the Widgets page.", objectName="sub"))
        self.side = Segmented(["Left", "Right"])
        col.addWidget(self.side)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.tiles = {}
        for n, (kind, name) in enumerate(widgets.KINDS):
            t = self.tiles[kind] = WidgetTile(kind, name)
            t.clicked.connect(lambda _=0, k=kind: self._pick(k))
            grid.addWidget(t, n // 3, n % 3)
        col.addLayout(grid)
        self.left, self.right = widgets.parse(None)

    def _pick(self, kind):
        if self.side.index == 0:
            self.left = kind
        else:
            self.right = kind
        self._badges()

    def _badges(self):
        for kind, t in self.tiles.items():
            t.badge = "L" if kind == self.left else "R" if kind == self.right else ""
            t.update()

    def setText(self, value):
        self.left, self.right = widgets.parse(value)
        self._badges()

    def text(self):
        return f"{self.left},{self.right}"


class SidebarItem(QAbstractButton):
    def __init__(self, name, color, glyph):
        super().__init__()
        self.name, self.color, self.glyph = name, QColor(color), glyph
        self.setCheckable(True)
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(theme.CHIP)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 0, -2, 0), theme.RADIUS_MD, theme.RADIUS_MD)
            p.setBrush(theme.PRIMARY)
            p.drawRect(QRectF(2, 6, 2, self.height() - 12))  # accent marker on the open section
        tile = QRectF(10, 5, 22, 22)
        p.setPen(QPen(theme.alpha(self.color, 140), 1))
        p.setBrush(theme.CHIP_DARK)
        p.drawRoundedRect(tile, theme.RADIUS_SM, theme.RADIUS_SM)
        icon = QFont()
        icon.setFamilies([theme.ICONS, "Segoe MDL2 Assets"])
        icon.setPixelSize(13)
        p.setFont(icon)
        p.setPen(self.color)
        p.drawText(tile, Qt.AlignCenter, self.glyph)
        p.setFont(theme.font(10))
        p.setPen(theme.TEXT if self.isChecked() else theme.TEXT_MUTED)
        p.drawText(QRectF(42, 0, self.width() - 46, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.name)
        _focus_ring(p, self, QRectF(self.rect()).adjusted(3, 1, -3, -1), theme.RADIUS_MD)


class RoundButton(QAbstractButton):
    """Small round grey button with a symbol (steppers, reorder arrows)."""

    def __init__(self, text):
        super().__init__()
        self.setText(text)
        self.setFixedSize(26, 26)  # 20 px button plus room for the focus ring
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(theme.alpha(theme.PRIMARY, 90), 1))
        p.setBrush(theme.SELECTED if self.isDown() else theme.CHIP)  # pressed: lighter glass
        p.drawRoundedRect(QRectF(3, 3, 20, 20), theme.RADIUS_SM, theme.RADIUS_SM)
        _focus_ring(p, self, QRectF(1, 1, 24, 24), theme.RADIUS_MD)
        p.setPen(theme.TEXT)
        p.setFont(theme.font(9 if len(self.text()) == 1 and self.text() in "+−" else 6, QFont.Bold))
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, self.text())


def _card():
    card = QFrame()
    card.setObjectName("card")
    QVBoxLayout(card).setContentsMargins(0, 2, 0, 2)
    card.layout().setSpacing(0)
    return card


def _add_row(card, title, subtitle, controls):
    if card.layout().count():
        sep = QFrame()
        sep.setObjectName("sep")
        card.layout().addWidget(sep)
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(14, 8, 12, 8)
    text = QVBoxLayout()
    text.setSpacing(1)
    text.addWidget(QLabel(title))
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        text.addWidget(sub)
    h.addLayout(text, 1)
    for c in controls:
        h.addWidget(c, 0, Qt.AlignVCenter)
    card.layout().addWidget(row)


class SettingsWindow(QWidget):
    def __init__(self, island, section=None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.island = island
        self.setWindowTitle("Dynamic Island settings")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.setFont(theme.font(10))
        self.resize(654, 556)
        self.widgets, self.drag_from = {}, None
        from island import app  # app imports this module; import here to avoid a cycle
        self._autostart_was = app.autostart_enabled()
        values = {S: store.load_kv(S), W: store.load_kv(W)}

        side, self.stack = QVBoxLayout(), QStackedWidget()
        side.setContentsMargins(8, 34, 8, 12)
        side.setSpacing(1)
        group, cards, self.section_index = QButtonGroup(self), {}, {}
        for n, (name, color, glyph) in enumerate(SECTIONS):
            item = SidebarItem(name, color, glyph)
            group.addButton(item, n)
            side.addWidget(item)
            if name == "About":
                side.insertStretch(side.count() - 1)
            page = QWidget()
            col = QVBoxLayout(page)
            col.setContentsMargins(20, 18, 20, 20)
            col.setSpacing(2)
            title = QLabel(name)
            title.setObjectName("title")
            col.addWidget(title)
            if name == "About":
                about = QLabel("Dynamic Island\nA living notch for Windows")
                about.setAlignment(Qt.AlignCenter)
                col.addWidget(about)
            cards[name] = col
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
            self.section_index[name] = n
        group.idClicked.connect(self.stack.setCurrentIndex)
        self.buttons = group

        open_card = {}
        for sec, grp, file, key, kind, default, title, subtitle, options in FIELDS:  # not `section`: that's the one to open
            col = cards[sec]
            if kind in ("pages", "widgets"):
                w = PagesList() if kind == "pages" else WidgetPicker()
                w.setText(values[S].get(key, default))
                col.addWidget(w)
                self.widgets[key] = w
                continue
            if (sec, grp) not in open_card:
                label = QLabel(grp)
                label.setObjectName("group")
                col.addWidget(label)
                open_card[(sec, grp)] = _card()
                col.addWidget(open_card[(sec, grp)])
            w = self._make(kind, options, default)
            if kind != "info":
                self._load(w, kind, key, default, values.get(file, {}))
            self.widgets[key] = w
            _add_row(open_card[(sec, grp)], title, subtitle, [w])
        for col in cards.values():
            col.addStretch()
        self.widgets["autostart"].setChecked(self._autostart_was)
        self.widgets["auto_location"].setChecked(not _has_location(values[S]))
        self.widgets["auto_location"].toggled.connect(self._location_enabled)
        self._location_enabled(self.widgets["auto_location"].isChecked())

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QWidget()
        sidebar.setFixedWidth(194)
        sidebar.setLayout(side)
        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)
        self.show_section(section or "General")

    def show_section(self, name):
        n = self.section_index.get(name, 0)
        self.buttons.button(n).setChecked(True)
        self.stack.setCurrentIndex(n)

    # --- window chrome: rounded dark panel, red close dot, drag anywhere on the sidebar top ---
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS_LG, theme.RADIUS_LG)
        p.fillPath(shape, theme.SURFACE)
        p.save()
        p.setClipPath(shape)
        p.fillRect(QRectF(0, 0, 194, self.height()), theme.SURFACE_2)
        p.restore()
        p.setPen(QPen(theme.alpha(theme.TEXT, theme.RIM_ALPHA), 1))  # glass rim
        p.setBrush(Qt.NoBrush)
        p.drawPath(shape)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.CLOSE)
        p.drawEllipse(QPointF(20, 18), 6, 6)

    def mousePressEvent(self, e):
        if QRectF(12, 10, 16, 16).contains(e.position()):
            self.close()
        elif e.position().y() < 32:
            self.drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag_from is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag_from)

    def mouseReleaseEvent(self, e):
        self.drag_from = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, e):
        self.save()  # like Nusa there is no Save button: whatever is set when the window closes applies
        super().closeEvent(e)

    @staticmethod
    def _make(kind, options, default):
        if kind == "switch":
            return Switch()
        if kind == "int":
            return Stepper(*options)
        if kind == "time":
            return TimeStepper(end=options)
        if kind == "segment":
            return Segmented(options)
        if kind == "float":
            w = QDoubleSpinBox()
            w.setButtonSymbols(QDoubleSpinBox.NoButtons)
            w.setRange(*options)
            w.setDecimals(4)
            return w
        if kind == "choice":
            w = QComboBox()
            w.addItems(options)
            return w
        if kind == "info":
            label = QLabel(default)
            label.setObjectName("value")
            return label
        w = QLineEdit()
        if kind == "secret":  # the iCal link is a password for the calendar: hidden unless being edited
            w.setEchoMode(QLineEdit.PasswordEchoOnEdit)
            w.setPlaceholderText("Paste link")
        return w

    @staticmethod
    def _load(w, kind, key, default, values):
        raw = values.get(key)
        if kind == "switch":
            w.setChecked(store.get_int(values, key, default) == 1)
        elif kind == "int":
            w.setValue(store.get_int(values, key, default))
        elif kind == "segment":
            w.setCurrentText(w.options[1 if store.get_int(values, key, default) == 1 else 0])
        elif kind == "float":
            try:
                w.setValue(float(raw))
            except (TypeError, ValueError):
                w.setValue(default)
        elif kind == "time":
            w.setValue(store.get_int(values, key, default))
        elif kind == "choice":
            w.setCurrentText(raw if raw in [w.itemText(i) for i in range(w.count())] else default)
        else:
            w.setText(raw or default)

    def _location_enabled(self, auto):
        for key in LOCATION:
            self.widgets[key].setEnabled(not auto)

    def save(self):
        """Write both files (keeping keys this window doesn't show) and apply the changes right away."""
        files = {S: store.load_kv(S), W: store.load_kv(W)}
        for _, _, file, key, kind, _, _, _, _ in FIELDS:
            if file is None or kind == "info":
                continue
            w = self.widgets[key]
            if kind == "switch":
                value = "1" if w.isChecked() else "0"
            elif kind in ("int", "time"):
                value = str(w.value())
            elif kind == "segment":
                value = str(w.index)
            elif kind == "float":
                value = f"{w.value():.4f}"
            elif kind == "choice":
                value = w.currentText()
            else:
                value = w.text().strip()
            files[file][key] = value
        if self.widgets["auto_location"].isChecked():
            for key in LOCATION:  # no saved location: the next start detects it again
                files[S].pop(key, None)
        for file, values in files.items():
            store.save_kv(file, values)
        from island import app
        if self.widgets["autostart"].isChecked() != self._autostart_was:
            app.set_autostart(self.widgets["autostart"].isChecked())
            self._autostart_was = self.widgets["autostart"].isChecked()
        self.island.apply_settings()


def _has_location(values):
    try:
        float(values["lat"]), float(values["lon"])
        return True
    except (KeyError, ValueError):
        return False
