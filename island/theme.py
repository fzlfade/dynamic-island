"""The island's UI font: Inter (SIL OFL, bundled in fonts/), with tabular figures so timers and percentages don't jiggle."""
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

FAMILY = "Inter"
_FILE = Path(__file__).parent / "fonts" / "Inter-Variable.ttf"
_loaded = []


def load_fonts():
    """Register the bundled font once; needs a QApplication. Without it Qt would fall back to another font."""
    if not _loaded:
        _loaded.append(QFontDatabase.addApplicationFont(str(_FILE)))


def font(size, weight=QFont.Normal):
    f = QFont(FAMILY, size, weight)
    f.setFeature(QFont.Tag("tnum"), 1)
    return f
