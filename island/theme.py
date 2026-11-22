"""Design tokens for the island and the settings window: Cyberpunk UI (neon on near-black, dark only).

Colours, type, radii and effects live here; components import these names instead of writing colours inline.
Fonts are Windows' own (Bahnschrift's DIN shapes for text, tabular digits), so nothing is downloaded."""
from PySide6.QtGui import QColor, QFont

# --- type ---------------------------------------------------------------------
FAMILY = "Bahnschrift"  # ships with Windows 10+; engineered DIN letterforms read as HUD text
ICONS = "Segoe Fluent Icons"


def font(size, weight=QFont.Normal):
    f = QFont(FAMILY, size, weight)
    f.setFeature(QFont.Tag("tnum"), 1)  # tabular digits: timers and percentages don't jiggle
    f.setStyleStrategy(QFont.NoSubpixelAntialias)  # ClearType fringes red/blue on a transparent window
    return f


# --- colour -------------------------------------------------------------------
# Surfaces
ISLAND = QColor(0, 0, 0)  # the notch itself stays pure black so it blends into the screen bezel
SURFACE = QColor("#0a0f14")  # settings window
SURFACE_2 = QColor("#0f161d")  # settings sidebar
CARD = QColor("#111c25")  # grouped rows in settings
CHIP = QColor("#0f1c26")  # tiles, chips, placeholder cover, round buttons
CHIP_DARK = QColor("#0a131a")  # page-icons bar, segmented track
LINE = QColor("#1d3340")  # separators and dividers
TRACK = QColor("#1b2c37")  # empty part of progress bars and switches
INPUT = QColor("#13222d")  # text fields

# Text and icons (contrast on ISLAND/SURFACE: TEXT 18:1, TEXT_MUTED 8:1, TEXT_DIM 3.4:1 for non-text marks only)
TEXT = QColor("#e8fbff")
TEXT_MUTED = QColor("#8fb3c2")
TEXT_DIM = QColor("#4d6f7d")

# Neon accents
PRIMARY = QColor("#00f0ff")  # cyan: progress, active page, focus ring, links
SECONDARY = QColor("#ff2bd6")  # magenta: Pomodoro, highlights
SUCCESS = QColor("#39ff88")  # charging, on, done
WARNING = QColor("#ffb020")
DANGER = QColor("#ff3b5c")  # low battery, errors, close
ON_ACCENT = QColor("#00161a")  # text on a filled neon button

# --- shape and effects ----------------------------------------------------------
RADIUS_SM = 2.0  # bars, chips: cyberpunk keeps corners hard
RADIUS_MD = 4.0  # buttons, tiles, cover art
RADIUS_LG = 8.0  # settings window, cards
FOCUS_WIDTH = 2.0  # keyboard focus ring (PRIMARY)
EDGE_ALPHA = 0.55  # neon hairline along the island's edge
SCANLINE_ALPHA = 10  # 0-255, CRT scanlines over the open island; static, so nothing moves


def alpha(color, a):
    """A copy of a token with alpha a (0-255)."""
    c = QColor(color)
    c.setAlpha(int(a))
    return c


def hex_(color):
    """#rrggbb for stylesheets."""
    return QColor(color).name()
