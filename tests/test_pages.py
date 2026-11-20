from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent

from island import app, focus, pages


def _wheel(island, dy):
    pos = QPointF(app.WIN_W / 2, 40)
    island.wheelEvent(QWheelEvent(pos, pos, QPoint(), QPoint(0, dy), Qt.NoButton, Qt.NoModifier,
                                  Qt.NoScrollPhase, False))


def test_wheel_switches_pages(island):
    assert [type(pg) for pg in island.pages] == [pages.MediaPage, pages.TodayPage, pages.TodayPage, focus.FocusPage]
    _wheel(island, -120)
    assert island.page == 0, "wheel does nothing while collapsed"
    island._set_expand(1.0)
    _wheel(island, -120)
    assert island.page == 1
    _wheel(island, -120)
    assert island.page == 2 and island.pages[2] is island.todo_page
    _wheel(island, -120)
    _wheel(island, -120)
    assert island.page == 0, "wraps around"


def test_page_dots_drawn(island):
    island._set_expand(1.0)
    img = island.grab().toImage()
    c = img.pixelColor(app.WIN_W // 2 + 5, int(app.EXPANDED[1] - 8))
    assert (c.red(), c.green(), c.blue()) != (0, 0, 0)


def _click_at(island, pos):
    island.mouseReleaseEvent(QMouseEvent(QMouseEvent.Type.MouseButtonRelease, pos, island.mapToGlobal(pos.toPoint()),
                                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


def test_page_buttons_switch_pages(island):
    island._set_expand(1.0)
    island.grab()  # paint lays out the dot/arrow hit areas
    _click_at(island, island.page_hits[2].center())
    assert island.page == 2, "clicking a dot jumps to that page"
    _click_at(island, island.page_hits["next"].center())
    assert island.page == 3
    island.grab()
    _click_at(island, island.page_hits["next"].center())
    assert island.page == 0, "next arrow wraps"
    island.grab()
    _click_at(island, island.page_hits["prev"].center())
    assert island.page == 3, "prev arrow wraps backwards"
    assert all(r.width() >= 12 and r.height() >= 16 for r in island.page_hits.values()), "big enough to hit"


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
    island.today.sections.clear()
    island.today.add_section(lambda: [(f"row {i}", "") for i in range(8)])
    island.grab()
    assert len(island.today.hits) == 5


def test_pin_last_keeps_last_row_and_index(island, qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    got = []
    page = pages.TodayPage()
    page.add_section(lambda: [("Water", "")])
    page.add_section(lambda: [(f"t{i}", "") for i in range(5)] + [("+ Add", "")], lambda i, b: got.append(i), pin_last=True)
    img = QImage(400, 200, QImage.Format_ARGB32)
    p = QPainter(img)
    page.draw(p, QRectF(0, 0, 400, 200), island)
    p.end()
    assert len(page.hits) == 5
    page.click(page.hits[0][0].center(), Qt.LeftButton, island)  # info row, no handler
    page.click(page.hits[-1][0].center(), Qt.LeftButton, island)
    page.click(page.hits[1][0].center(), Qt.LeftButton, island)
    assert got == [5, 0]


def test_today_page_has_water_row_by_default(island):
    assert [island.today.sections[1][0]()] == [[("Water", "0 / 1500 ml")]] and island.todo_page.title == "To-do"
