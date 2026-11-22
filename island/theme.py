"""The island's UI font: Segoe UI, the font Nusa draws with (its only font name, found by rea in nusa.exe),
with tabular figures so timers and percentages don't jiggle."""
from PySide6.QtGui import QFont

FAMILY = "Segoe UI"


def font(size, weight=QFont.Normal):
    f = QFont(FAMILY, size, weight)
    f.setFeature(QFont.Tag("tnum"), 1)
    f.setStyleStrategy(QFont.NoSubpixelAntialias)  # ClearType fringes red/blue on a transparent window
    return f
