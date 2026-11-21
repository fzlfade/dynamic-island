from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent

from island import app, ask, focus, pages, shelf


def _wheel(island, dy):
    pos = QPointF(app.WIN_W / 2, 40)
    island.wheelEvent(QWheelEvent(pos, pos, QPoint(), QPoint(0, dy), Qt.NoButton, Qt.NoModifier,
                                  Qt.NoScrollPhase, False))


def test_wheel_switches_pages(island):
    assert [type(pg) for pg in island.pages] == [pages.MediaPage, pages.TodayPage, pages.TodayPage, focus.FocusPage,
                                                 shelf.ShelfPage, ask.AskPage]
    _wheel(island, -120)
    assert island.page == 0, "wheel does nothing while collapsed"
    island._set_expand(1.0)
    _wheel(island, -120)
    assert island.page == 1
    _wheel(island, -120)
    assert island.page == 2 and island.pages[2] is island.todo_page
    for _ in range(len(island.pages) - 2):
        _wheel(island, -120)
    assert island.page == 0, "wraps around"


def test_page_dots_drawn(island):
    island._set_expand(1.0)
    img = island.grab().toImage()
    dot = island.page_hits[1].center()  # an inactive dot: grey, not the black background
    c = img.pixelColor(int(dot.x()), int(dot.y()))
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
    last = len(island.pages) - 1
    island.page = last
    island.grab()
    _click_at(island, island.page_hits["next"].center())
    assert island.page == 0, "next arrow wraps"
    island.grab()
    _click_at(island, island.page_hits["prev"].center())
    assert island.page == last, "prev arrow wraps backwards"
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


class Spy(pages.Page):
    """Records the horizontal offset it was painted at."""

    def __init__(self):
        self.drawn = []

    def draw(self, p, r, island):
        self.drawn.append(round(p.transform().dx()))


def test_page_change_slides_instead_of_jumping(island):
    a, b = Spy(), Spy()
    island.pages, island.page = [a, b], 0
    island._set_expand(1.0)
    island._go_to_page(1, +1)
    assert island.page == 1, "the target page is current at once (clicks, tests)"
    assert island.page_anim.state() == island.page_anim.State.Running
    island._set_slide(0.5)
    island.grab()
    assert a.drawn[-1] < 0 < b.drawn[-1], "mid-slide: old page leaves left, new page comes in from the right"
    island.page_anim.stop()
    island._set_slide(1.0)
    a.drawn.clear()
    island.grab()
    assert a.drawn == [] and b.drawn[-1] == 0, "settled: only the new page, in place"


def test_going_back_slides_the_other_way(island):
    a, b = Spy(), Spy()
    island.pages, island.page = [a, b], 1
    island._set_expand(1.0)
    island._go_to_page(0, -1)
    island._set_slide(0.5)
    island.grab()
    assert b.drawn[-1] > 0 > a.drawn[-1], "old page leaves right, new page comes in from the left"


def test_marquee_offset():
    # fits: never moves
    assert app.marquee_offset(text_w=100, box_w=200, elapsed=9.0) == 0
    # too wide: holds at the start first, then slides left, then loops back to the start
    assert app.marquee_offset(300, 200, 0.5) == 0
    assert app.marquee_offset(300, 200, app.MARQUEE_PAUSE + 1.0) == -app.MARQUEE_SPEED
    cycle = app.MARQUEE_PAUSE + (300 + app.MARQUEE_GAP) / app.MARQUEE_SPEED
    assert app.marquee_offset(300, 200, cycle + 0.1) == 0, "loops with another pause"


def test_long_title_scrolls_while_playing(island, monkeypatch):
    long = "another night awake with you on my mind. (feat. Adeliesa)"
    island._on_media({"title": long, "artist": "eleventwelfth", "playing": True, "pos": 0, "pos_at": 0, "lyrics": []})
    island._set_expand(1.0)
    island.grab()
    t0 = island.marquee_t0[long]
    monkeypatch.setattr(app.time, "monotonic", lambda: t0 + app.MARQUEE_PAUSE + 2.0)
    drawn = []
    real = app.Island._draw_scrolling
    monkeypatch.setattr(app.Island, "_draw_scrolling", lambda self, p, rect, s, *a: drawn.append(s) or real(self, p, rect, s, *a))
    island.grab()
    assert long in drawn, "the full title is drawn and scrolled, not cut with an ellipsis"
