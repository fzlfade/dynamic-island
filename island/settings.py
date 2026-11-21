"""Settings window: every option the island reads from settings.txt / water.txt, edited with real controls."""
from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit, QPushButton,
                               QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

from island import prayer, store, theme

S, W = "settings.txt", "water.txt"
# (tab, file, key, kind, default, label, options). file None = not a plain key/value (handled specially)
FIELDS = [
    ("General", None, "autostart", "check", 0, "Start with Windows", None),
    ("General", S, "notif_pill", "check", 1, "Show notifications in the island", None),
    ("General", S, "shelf_clear", "check", 0, "Empty the shelf when the island starts", None),
    ("Focus", S, "focus", "int", 25, "Focus (minutes)", (1, 180, 1)),
    ("Focus", S, "short_break", "int", 5, "Short break (minutes)", (1, 60, 1)),
    ("Focus", S, "long_break", "int", 15, "Long break (minutes)", (1, 120, 1)),
    ("Water", W, "goal", "int", 1500, "Daily goal (ml)", (250, 6000, 250)),
    ("Water", W, "glass", "int", 250, "One glass (ml)", (50, 1000, 50)),
    ("Water", W, "bottle", "int", 500, "Bottle size (ml)", (100, 3000, 50)),
    ("Water", W, "every", "int", 60, "Remind every (minutes)", (10, 240, 5)),
    ("Water", W, "start", "time", 480, "Reminders from", None),
    ("Water", W, "end", "time", 1440, "Reminders until (00:00 = midnight)", None),
    ("Prayer", S, "prayer", "check", 0, "Show prayer times and reminders", None),
    ("Prayer", S, "prayer_method", "choice", prayer.DEFAULT_METHOD, "Calculation method", list(prayer.METHODS)),
    ("Prayer", S, "prayer_early", "int", 0, "Remind early (minutes)", (0, 60, 1)),
    ("Prayer", S, "prayer_pause_media", "check", 0, "Pause music at prayer time", None),
    *[("Prayer", S, f"prayer_adj_{n.lower()}", "int", 0, f"Adjust {n} (minutes)", (-30, 30, 1)) for n in prayer.NAMES],
    ("Calendar & weather", S, "calendar_url", "secret", "", "Google Calendar secret iCal link", None),
    ("Calendar & weather", None, "auto_location", "check", 1, "Detect my location automatically", None),
    ("Calendar & weather", S, "place", "text", "", "Place name", None),
    ("Calendar & weather", S, "lat", "float", 0.0, "Latitude", (-90.0, 90.0)),
    ("Calendar & weather", S, "lon", "float", 0.0, "Longitude", (-180.0, 180.0)),
]
LOCATION = ("place", "lat", "lon")

STYLE = """
QWidget { background: #111113; color: #f2f2f4; }
QTabWidget::pane { border: 1px solid #2a2a2e; border-radius: 10px; top: -1px; }
QTabBar::tab { background: transparent; color: #9a9aa2; padding: 8px 14px; border: none; }
QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #6fd58c; }
QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QComboBox {
    background: #1c1c20; border: 1px solid #2e2e34; border-radius: 8px; padding: 6px 8px; min-height: 22px; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus, QComboBox:focus { border-color: #6fd58c; }
QLineEdit:disabled, QDoubleSpinBox:disabled { color: #5c5c64; }
QCheckBox { spacing: 10px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 1px solid #44444c; background: #1c1c20; }
QCheckBox::indicator:checked { background: #6fd58c; border-color: #6fd58c; }
QPushButton { background: #24242a; border: 1px solid #34343a; border-radius: 8px; padding: 8px 18px; }
QPushButton:hover { background: #2c2c33; }
QPushButton#primary { background: #6fd58c; color: #0b0b0c; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #82e09c; }
"""


class SettingsWindow(QWidget):
    def __init__(self, island):
        super().__init__(None, Qt.Window)
        self.island = island
        self.setWindowTitle("Dynamic Island settings")
        self.setStyleSheet(STYLE)
        self.setFont(theme.font(10))
        self.resize(460, 520)
        self.widgets = {}
        from island import app  # app imports this module; import here to avoid a cycle
        self._autostart_was = app.autostart_enabled()
        values = {S: store.load_kv(S), W: store.load_kv(W)}
        tabs, forms = QTabWidget(), {}
        for tab, file, key, kind, default, label, options in FIELDS:
            if tab not in forms:
                page = QWidget()
                forms[tab] = QFormLayout(page)
                forms[tab].setVerticalSpacing(12)
                forms[tab].setContentsMargins(18, 18, 18, 18)
                tabs.addTab(page, tab.replace("&", "&&"))  # a lone & would become a shortcut marker
            w = self._make(kind, options)
            self._load(w, kind, key, default, values.get(file, {}))
            self.widgets[key] = w
            if kind == "check":
                w.setText(label)
                forms[tab].addRow(w)
            else:
                forms[tab].addRow(label, w)
        self.widgets["autostart"].setChecked(self._autostart_was)
        loc = values[S]
        self.widgets["auto_location"].setChecked(not _has_location(loc))
        self.widgets["auto_location"].toggled.connect(self._location_enabled)
        self._location_enabled(self.widgets["auto_location"].isChecked())

        cancel, save = QPushButton("Cancel"), QPushButton("Save")
        save.setObjectName("primary")
        save.setDefault(True)
        cancel.clicked.connect(self.close)
        save.clicked.connect(lambda: (self.save(), self.close()))
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.addWidget(tabs)
        root.addLayout(buttons)

    @staticmethod
    def _make(kind, options):
        if kind == "check":
            return QCheckBox()
        if kind == "int":
            w = QSpinBox()
            w.setButtonSymbols(QSpinBox.NoButtons)  # type, use arrow keys or scroll
            w.setRange(options[0], options[1])
            w.setSingleStep(options[2])
            return w
        if kind == "float":
            w = QDoubleSpinBox()
            w.setButtonSymbols(QDoubleSpinBox.NoButtons)
            w.setRange(*options)
            w.setDecimals(4)
            return w
        if kind == "time":
            w = QTimeEdit()
            w.setButtonSymbols(QTimeEdit.NoButtons)
            w.setDisplayFormat("HH:mm")
            return w
        if kind == "choice":
            w = QComboBox()
            w.addItems(options)
            return w
        w = QLineEdit()
        if kind == "secret":  # the iCal link is a password for the calendar: hidden unless being edited
            w.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        return w

    @staticmethod
    def _load(w, kind, key, default, values):
        raw = values.get(key)
        if kind == "check":
            w.setChecked(store.get_int(values, key, default) == 1)
        elif kind == "int":
            w.setValue(store.get_int(values, key, default))
        elif kind == "float":
            try:
                w.setValue(float(raw))
            except (TypeError, ValueError):
                w.setValue(default)
        elif kind == "time":
            m = store.get_int(values, key, default)
            w.setTime(QTime(m // 60 % 24, m % 60))
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
        for _, file, key, kind, _, _, _ in FIELDS:
            if file is None:
                continue
            w = self.widgets[key]
            if kind == "check":
                value = "1" if w.isChecked() else "0"
            elif kind == "int":
                value = str(w.value())
            elif kind == "float":
                value = f"{w.value():.4f}"
            elif kind == "time":
                m = w.time().hour() * 60 + w.time().minute()
                value = str(1440 if key == "end" and m == 0 else m)  # an end time of 00:00 is midnight
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
        self.island.apply_settings()


def _has_location(values):
    try:
        float(values["lat"]), float(values["lon"])
        return True
    except (KeyError, ValueError):
        return False
