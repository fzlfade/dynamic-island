"""Design tokens for the island and the settings window: Liquid Glass (dark translucent material, colour used
sparingly). Components import these names instead of writing colours inline.

Glass is a tinted, semi-transparent fill with a specular sheen and a light rim; Windows' "Transparency effects"
switch turns it opaque (the reduced-transparency fallback). Contrast is checked against the worst backdrop (glass
over white), so text stays readable whatever is behind the island."""
import winreg

from PySide6.QtGui import QColor, QFont

# --- type ---------------------------------------------------------------------
FAMILY = "Segoe UI"  # Windows' system face: the platform-native choice for a system material
ICONS = "Segoe Fluent Icons"


def font(size, weight=QFont.Normal):
    f = QFont(FAMILY, size, weight)
    f.setFeature(QFont.Tag("tnum"), 1)  # tabular digits: timers and percentages don't jiggle
    f.setStyleStrategy(QFont.NoSubpixelAntialias)  # ClearType fringes red/blue on a transparent window
    return f


def transparency_enabled():
    """Windows Settings > Personalization > Colors > Transparency effects (on when unreadable)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "EnableTransparency")[0] != 0
    except OSError:
        return True


# 0.80: the most see-through that keeps every text colour at 4.5:1 over any backdrop (tested).
# shortcut: read once at start-up; restart the island after changing Windows' transparency switch
GLASS_OPACITY = 0.80 if transparency_enabled() else 1.0


def alpha(color, a):
    """A copy of a token with alpha a (0-255)."""
    c = QColor(color)
    c.setAlpha(int(a))
    return c


def _glass(rgb, opacity=None):
    return alpha(QColor(rgb), 255 * (GLASS_OPACITY if opacity is None else opacity))


def hex_(color):
    """#rrggbb, or #aarrggbb with transparency, for stylesheets."""
    c = QColor(color)
    return c.name(QColor.HexArgb if c.alpha() < 255 else QColor.HexRgb)


# --- colour -------------------------------------------------------------------
# Glass surfaces (alpha = translucency)
ISLAND = _glass("#0c0c10")  # the island's glass
ISLAND_SOLID = QColor("#0c0c10")  # places that must stay opaque: tray icon, cut-outs
SURFACE = _glass("#0c0c10")  # settings window: the same glass
SURFACE_2 = alpha(QColor("#ffffff"), 10)  # sidebar layer on the window glass
CARD = alpha(QColor("#ffffff"), 14)  # grouped rows
CHIP = alpha(QColor("#ffffff"), 22)  # tiles, chips, placeholder cover, round buttons
CHIP_DARK = alpha(QColor("#ffffff"), 12)  # page-icons bar, widget cards, segmented track
SELECTED = alpha(QColor("#ffffff"), 34)  # the chosen segment, pressed buttons
LINE = alpha(QColor("#ffffff"), 30)  # separators and dividers
TRACK = alpha(QColor("#ffffff"), 46)  # empty part of progress bars and switches
INPUT = alpha(QColor("#ffffff"), 20)  # text fields

# Text and icons: tests check 4.5:1 (TEXT_DIM 3:1, marks only) on every glass layer over white, grey and black
TEXT = QColor("#ffffff")
TEXT_MUTED = QColor("#d8d8e0")
TEXT_DIM = QColor("#b4b4be")

# Accents: light tints for text and marks on glass, deeper fills behind white text
PRIMARY = QColor("#a8d8ff")  # progress, current page, focus ring, links
SECONDARY = QColor("#eec6ff")  # Pomodoro, highlights
SUCCESS = QColor("#8cf0b0")  # charging, on, done
WARNING = QColor("#ffe066")
DANGER = QColor("#ffc2bd")  # low battery, errors
CLOSE = QColor("#ff5f57")  # the settings window's close dot
PRIMARY_FILL = QColor("#0a66e0")  # filled buttons, selection, today
SECONDARY_FILL = QColor("#8a3fd1")
ON_ACCENT = QColor("#ffffff")  # text on PRIMARY_FILL / SECONDARY_FILL

# --- shape and effects ----------------------------------------------------------
RADIUS_SM = 6.0  # bars, chips: glass is soft and round
RADIUS_MD = 12.0  # buttons, tiles, cover art, cards
RADIUS_LG = 20.0  # settings window, panels
FOCUS_WIDTH = 2.0  # keyboard focus ring (PRIMARY)
SHEEN_ALPHA = 34  # specular highlight across the top of the glass
RIM_ALPHA = 70  # light rim where the glass catches light (top); fades toward the bottom
SHADOW_ALPHA = 70  # soft drop shadow under the floating island
SHADOW_SPREAD = 10  # px
