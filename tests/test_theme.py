from pathlib import Path

from PySide6.QtGui import QFont, QFontInfo, QFontMetrics

from island import theme


def test_ui_font_is_installed_not_a_fallback(qapp):
    # a missing family silently falls back to Tahoma
    assert QFontInfo(theme.font(10)).family() == theme.FAMILY == "Segoe UI"


def _contrast(a, b):
    def lum(c):
        ch = [v / 255 for v in (c.red(), c.green(), c.blue())]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _over(top, below):
    """What a translucent token looks like over an opaque colour."""
    from PySide6.QtGui import QColor
    a = top.alphaF()
    return QColor(*(round(a * t + (1 - a) * b) for t, b in ((top.red(), below.red()), (top.green(), below.green()),
                                                           (top.blue(), below.blue()))))


def test_token_contrast_meets_wcag_on_glass_over_any_backdrop():
    from PySide6.QtGui import QColor
    for backdrop in (QColor("#ffffff"), QColor("#000000"), QColor("#808080")):  # glass shows what's behind it
        island, window = _over(theme.ISLAND, backdrop), _over(theme.SURFACE, backdrop)
        layers = [island, window] + [_over(t, base) for base in (island, window)
                                     for t in (theme.CARD, theme.CHIP, theme.CHIP_DARK, theme.SELECTED)]
        for bg in layers:
            for fg in (theme.TEXT, theme.TEXT_MUTED, theme.PRIMARY, theme.SECONDARY, theme.SUCCESS, theme.WARNING,
                       theme.DANGER):
                assert _contrast(fg, bg) >= 4.5, (fg.name(), bg.name(), backdrop.name())
            assert _contrast(theme.TEXT_DIM, bg) >= 3.0, ("non-text marks need 3:1", bg.name())
    for fill in (theme.PRIMARY_FILL, theme.SECONDARY_FILL):
        assert _contrast(theme.ON_ACCENT, fill) >= 4.5, "text on filled buttons"


def test_ui_modules_use_tokens_not_colour_literals():
    import re
    ui = ("app.py", "pages.py", "focus.py", "shelf.py", "ask.py", "settings.py")
    for name in ui:
        src = (Path(theme.__file__).parent / name).read_text(encoding="utf-8")
        rgb = [m for m in re.findall(r"QColor\((\d+, \d+, \d+)\)", src)]
        assert not rgb, (name, rgb)
        assert not re.search(r'"#[0-9a-fA-F]{6}"', src), (name, "hex colour outside theme.py")


def test_digits_are_tabular_so_timers_do_not_jiggle(qapp):
    m = QFontMetrics(theme.font(15, QFont.DemiBold))
    assert m.horizontalAdvance("11:11") == m.horizontalAdvance("00:00")


def test_weights_follow_the_hierarchy(qapp):
    assert theme.font(12, QFont.DemiBold).weight() == QFont.DemiBold
    assert theme.font(10).weight() == QFont.Normal


def test_no_hardcoded_font_families_left():
    # the old code named "Segoe UI Variable Text", which isn't an installed family, so Qt drew Tahoma
    src = "".join(p.read_text(encoding="utf-8") for p in (Path(theme.__file__).parent).glob("*.py") if p.name != "theme.py")
    assert "Segoe UI Variable" not in src
