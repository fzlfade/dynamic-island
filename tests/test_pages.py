from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent

from island import app, focus, pages


def _wheel(island, dy):
    pos = QPointF(app.WIN_W / 2, 40)
    island.wheelEvent(QWheelEvent(pos, pos, QPoint(), QPoint(0, dy), Qt.NoButton, Qt.NoModifier,
                                  Qt.NoScrollPhase, False))


def test_wheel_switches_pages(island):
    assert [type(pg) for pg in island.pages] == [pages.MediaPage, pages.TodayPage, focus.FocusPage]
    _wheel(island, -120)
    assert island.page == 0, "wheel does nothing while collapsed"
    island._set_expand(1.0)
    _wheel(island, -120)
    assert island.page == 1
    _wheel(island, -120)
    assert island.page == 2
    _wheel(island, -120)
    assert island.page == 0, "wraps around"


def test_page_dots_drawn(island):
    island._set_expand(1.0)
    img = island.grab().toImage()
    c = img.pixelColor(app.WIN_W // 2 + 10, int(app.EXPANDED[1] - 8))
    assert (c.red(), c.green(), c.blue()) != (0, 0, 0)


class Stub(pages.Page):
    title = "Stub"

    def compact_text(self):
        return "● 24:13"


def test_compact_text_wins(island, fake_media):
    fake_media.changed.emit({"title": "x", "artist": "y", "playing": True, "pos": 0, "pos_at": 0})
    assert island._compact_label() == ""
    island.add_page(Stub())
    assert island._compact_label() == "● 24:13"
    island.grab()  # collapsed draw path runs with the label


def test_today_rows_route_clicks(island, tmp_path):
    got = []
    island.today.add_section(lambda: [("Water", "500 / 1500 ml")])
    island.today.add_section(lambda: [("Call mom", "09:30"), ("Buy milk", "")], lambda i, b: got.append((i, b)))
    island.page = 1
    island._set_expand(1.0)
    island.grab().save(str(tmp_path / "today.png"))
    y = pages.TodayPage.TOP + 2.5 * pages.TodayPage.ROW_H  # third drawn row = second row of section 2
    pos = QPointF(app.WIN_W / 2, y)
    island.mouseReleaseEvent(QMouseEvent(QMouseEvent.MouseButtonRelease, pos, pos, Qt.RightButton, Qt.NoButton, Qt.NoModifier))
    assert got == [(1, Qt.RightButton)]
    pos = QPointF(app.WIN_W / 2, pages.TodayPage.TOP + 0.5 * pages.TodayPage.ROW_H)
    assert not island.today.click(pos, Qt.LeftButton, island), "section without on_click ignores clicks"


def test_today_empty_and_row_cap(island, tmp_path):
    island.page = 1
    island._set_expand(1.0)
    island.grab().save(str(tmp_path / "today_empty.png"))
    island.today.add_section(lambda: [(f"row {i}", "") for i in range(8)])
    island.grab()
    assert len(island.today.hits) == 5
