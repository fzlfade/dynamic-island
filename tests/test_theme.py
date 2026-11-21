from pathlib import Path

from PySide6.QtGui import QFont, QFontInfo, QFontMetrics

from island import theme


def test_ui_font_is_inter_not_a_fallback(qapp):
    theme.load_fonts()
    assert QFontInfo(theme.font(10)).family() == "Inter", "a missing family silently falls back to Tahoma"


def test_digits_are_tabular_so_timers_do_not_jiggle(qapp):
    theme.load_fonts()
    m = QFontMetrics(theme.font(15, QFont.DemiBold))
    assert m.horizontalAdvance("11:11") == m.horizontalAdvance("00:00")


def test_weights_follow_the_hierarchy(qapp):
    assert theme.font(12, QFont.DemiBold).weight() == QFont.DemiBold
    assert theme.font(10).weight() == QFont.Normal


def test_island_loads_the_font(island):
    assert QFontInfo(theme.font(10)).family() == "Inter"


def test_no_hardcoded_font_families_left():
    # the old code named "Segoe UI Variable Text", which isn't an installed family, so Qt drew Tahoma
    src = "".join(p.read_text(encoding="utf-8") for p in (Path(theme.__file__).parent).glob("*.py") if p.name != "theme.py")
    assert "Segoe UI Variable" not in src
