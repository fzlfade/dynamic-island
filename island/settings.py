"""Settings window in Nusa's style: a sidebar of coloured section tiles; each section is cards of rows with a title,
a grey subtitle and a control (switch, ± stepper, segmented choice). Every option here changes real behaviour."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTime, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from island import prayer, store, theme

S, W = "settings.txt", "water.txt"
BG, SIDEBAR, CARD, LINE = "#1c1c1e", "#232325", "#2c2c2e", "#38383a"
GREEN, GREY = QColor(52, 199, 89), QColor(142, 142, 147)

SECTIONS = [  # (name, tile colour, Segoe Fluent glyph)
    ("General", "#8e8e93", ""), ("Pages", "#0a84ff", ""), ("Appearance", "#3a3a3c", ""),
    ("Music and lyrics", "#ff375f", ""), ("Notifications", "#ff3b30", ""), ("To-do", "#34c759", ""),
    ("Pomodoro", "#af52de", ""), ("Water", "#0a84ff", ""), ("Prayer", "#30b0c7", ""),
    ("Shelf", "#ff9f0a", ""), ("HUD & popups", "#32ade6", ""), ("Ask Claude", "#5e5ce6", ""),
    ("About", "#636366", ""),
]
PAGES = [("media", "Music"), ("focus", "Pomodoro"), ("water", "Water"), ("shelf", "Shelf"), ("todo", "To-do"),
         ("today", "Today")]
DEFAULT_PAGES = "media,focus,water,shelf,todo"

# (section, group, file, key, kind, default, title, subtitle, options). file None: not a plain key=value
FIELDS = [
    ("General", "Startup", None, "autostart", "switch", 0, "Start with Windows", "", None),
    ("General", "Notch", S, "minimal", "switch", 1, "Minimal notch", "A smaller pill when nothing is playing", None),
    ("General", "Notch", S, "clock", "switch", 1, "Date & time", "The clock and date beside the status ring", None),
    ("General", "Notch", S, "ring", "switch", 1, "Status ring", "Battery level next to the clock", None),
    ("General", "Full screen", S, "hide_fullscreen", "switch", 1, "Hide in full screen",
     "Games, videos and slides that fill the screen", None),
    ("Pages", "", S, "pages", "pages", DEFAULT_PAGES, "", "", None),
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

STYLE = f"""
QWidget {{ background: transparent; color: #f2f2f4; }}
QLabel#title {{ font-size: 20px; font-weight: 700; }}
QLabel#group {{ color: #8e8e93; font-size: 11px; padding: 10px 0 4px 6px; }}
QLabel#sub {{ color: #8e8e93; font-size: 11px; }}
QLabel#value {{ color: #8e8e93; }}
QFrame#card {{ background: {CARD}; border-radius: 10px; }}
QFrame#sep {{ background: {LINE}; max-height: 1px; min-height: 1px; margin-left: 14px; }}
QLineEdit, QDoubleSpinBox, QComboBox {{ background: #3a3a3c; border: none; border-radius: 6px; padding: 4px 8px;
    min-width: 150px; color: #f2f2f4; }}
QLineEdit:disabled, QDoubleSpinBox:disabled {{ color: #5c5c64; }}
QComboBox QAbstractItemView {{ background: #2c2c2e; selection-background-color: #0a84ff; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
"""


class Switch(QAbstractButton):
    """iOS-style toggle (Nusa's green switch)."""

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(lambda _: self.update())

    def sizeHint(self):
        return QSize(40, 24)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setOpacity(1.0 if self.isEnabled() else 0.4)
        p.setBrush(GREEN if self.isChecked() else QColor(72, 72, 76))
        p.drawRoundedRect(QRectF(0, 1, 40, 22), 11, 11)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(29 if self.isChecked() else 11, 12), 9, 9)


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

    def currentText(self):
        return self.options[self.index]

    def setCurrentText(self, text):
        self.index = self.options.index(text) if text in self.options else 0
        self.update()

    def mousePressEvent(self, e):
        self.index = min(len(self.options) - 1, int(e.position().x() // (self.width() / len(self.options))))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(28, 28, 30))
        p.drawRoundedRect(QRectF(self.rect()), 7, 7)
        w = (self.width() - 4) / len(self.options)
        p.setBrush(QColor(72, 72, 76))
        p.drawRoundedRect(QRectF(2 + self.index * w, 2, w, self.height() - 4), 6, 6)
        p.setFont(theme.font(9))
        for i, text in enumerate(self.options):
            p.setPen(QColor(255, 255, 255) if i == self.index else GREY)
            p.drawText(QRectF(2 + i * w, 0, w, self.height()), Qt.AlignCenter, text)


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
            p.setBrush(QColor(52, 52, 56))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 0, -2, 0), 8, 8)
        tile = QRectF(10, 5, 22, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawRoundedRect(tile, 6, 6)
        icon = QFont()
        icon.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
        icon.setPixelSize(13)
        p.setFont(icon)
        p.setPen(QColor(255, 255, 255))
        p.drawText(tile, Qt.AlignCenter, self.glyph)
        p.setFont(theme.font(10))
        p.drawText(QRectF(42, 0, self.width() - 46, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.name)


class RoundButton(QAbstractButton):
    """Small round grey button with a symbol (steppers, reorder arrows)."""

    def __init__(self, text):
        super().__init__()
        self.setText(text)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(72, 72, 76) if not self.isDown() else QColor(99, 99, 104))
        p.drawEllipse(QRectF(1, 1, 20, 20))
        p.setPen(QColor(255, 255, 255))
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
        for section, grp, file, key, kind, default, title, subtitle, options in FIELDS:
            col = cards[section]
            if kind == "pages":
                w = PagesList()
                w.setText(values[S].get("pages", DEFAULT_PAGES))
                col.addWidget(w)
                self.widgets[key] = w
                continue
            if (section, grp) not in open_card:
                label = QLabel(grp)
                label.setObjectName("group")
                col.addWidget(label)
                open_card[(section, grp)] = _card()
                col.addWidget(open_card[(section, grp)])
            w = self._make(kind, options, default)
            if kind != "info":
                self._load(w, kind, key, default, values.get(file, {}))
            self.widgets[key] = w
            _add_row(open_card[(section, grp)], title, subtitle, [w])
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
        shape.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.fillPath(shape, QColor(BG))
        p.save()
        p.setClipPath(shape)
        p.fillRect(QRectF(0, 0, 194, self.height()), QColor(SIDEBAR))
        p.restore()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 95, 87))
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
