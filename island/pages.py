"""Expanded-island pages: the scroll wheel switches between them while the island is open."""
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics

from island import theme


class Page:
    title = ""

    def draw(self, p, r, island):
        pass

    def click(self, pos, button, island):
        return False

    def animating(self):
        return False

    def compact_text(self):
        return None


class MediaPage(Page):
    title = "Media"

    def draw(self, p, r, island):
        if not island.info:
            island._text(p, QRectF(r), "No media", 11, QColor(140, 140, 140), Qt.AlignCenter)
            return
        art = QRectF(r.left() + 18, r.top() + 16, 64, 64)
        island._draw_art(p, art, 14)
        x = art.right() + 14
        text_w = r.right() - x - 18
        island._text(p, QRectF(x, art.top() + 2, text_w, 22), island.info["title"], 12, QColor(255, 255, 255), Qt.AlignLeft, bold=True)
        island._text(p, QRectF(x, art.top() + 24, text_w, 20), island.info["artist"], 10, QColor(160, 160, 160), Qt.AlignLeft)
        island._text(p, QRectF(x, art.top() + 44, text_w - 44, 20), island._lyric(), 10, QColor(120, 220, 140), Qt.AlignLeft)
        island._draw_bars(p, QPointF(r.right() - 34, art.top() + 52))
        cy, cx = r.bottom() - 34, r.center().x()  # leaves room for the page dots below
        for action, dx in (("prev", -56), ("toggle", 0), ("next", 56)):
            island.buttons[action] = QRectF(cx + dx - 18, cy - 14, 36, 28)
            self._draw_icon(p, island, action, QPointF(cx + dx, cy))

    def click(self, pos, button, island):
        for action, rect in island.buttons.items():
            if rect.contains(pos):
                island.media.send(action)
                # optimistic flip so the icon reacts before the next 1 s poll
                if action == "toggle" and island.info:
                    island._on_media({**island.info, "playing": not island.info["playing"],
                                      "pos": island._pos(), "pos_at": time.monotonic()})
                return True
        return False

    def _draw_icon(self, p, island, action, c):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        tri = lambda x, d: [QPointF(x, c.y() - 7), QPointF(x + d * 10, c.y()), QPointF(x, c.y() + 7)]
        if action == "toggle" and island.info.get("playing"):
            p.drawRect(QRectF(c.x() - 6, c.y() - 8, 4, 16))
            p.drawRect(QRectF(c.x() + 2, c.y() - 8, 4, 16))
        elif action == "toggle":
            p.drawPolygon(tri(c.x() - 4, 1))
        else:
            d = 1 if action == "next" else -1
            p.drawPolygon(tri(c.x() - d * 9, d))
            p.drawPolygon(tri(c.x() - d * 1, d))


class TodayPage(Page):
    """Rows from feature sections (weather, prayer, water, calendar, to-do), at most MAX_ROWS in total."""
    title = "Today"
    MAX_ROWS, TOP, ROW_H = 5, 12.0, 22.0

    def __init__(self, title="Today"):
        self.title = title
        self.sections = []  # (rows callable, on_click or None, pin_last)
        self.hits = []  # (row rect, on_click, index within its section), rebuilt on every draw

    def add_section(self, rows, on_click=None, pin_last=False):
        """pin_last: when the row cap truncates, keep this section's last row (e.g. "+ Add") and drop earlier ones."""
        self.sections.append((rows, on_click, pin_last))

    def draw(self, p, r, island):
        self.hits = []
        fm = QFontMetrics(theme.font(10))  # same font island._text uses at size 10
        for rows, on_click, pin_last in self.sections:
            items = list(enumerate(rows()))
            room = self.MAX_ROWS - len(self.hits)
            if len(items) > room:
                items = items[:room - 1] + items[-1:] if pin_last and room > 0 else items[:room]
            for i, (left, right) in items:
                row = QRectF(r.left() + 22, r.top() + self.TOP + len(self.hits) * self.ROW_H, r.width() - 44, self.ROW_H)
                right_w = fm.horizontalAdvance(right) + 12 if right else 0
                island._text(p, row.adjusted(0, 0, -right_w, 0), left, 10, QColor(255, 255, 255), Qt.AlignLeft)
                island._text(p, row, right, 10, QColor(160, 160, 160), Qt.AlignRight)
                self.hits.append((row, on_click, i))
        if not self.hits:
            island._text(p, QRectF(r), "Nothing today", 11, QColor(140, 140, 140), Qt.AlignCenter)

    def click(self, pos, button, island):
        for row, on_click, i in self.hits:
            if on_click and row.contains(pos):
                on_click(i, button)
                return True
        return False
