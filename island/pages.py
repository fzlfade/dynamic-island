"""Expanded-island pages, laid out like Nusa 1.3.1 (measured on a 455×197 island; positions are offsets from its
top-left). The island draws the fixed header row (ring, date, time, status icon) above every page."""
import bisect
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainterPath, QPen

from island import theme

WHITE, GREY, DIM = QColor(255, 255, 255), QColor(142, 142, 147), QColor(72, 72, 76)
CHIP, CHIP_DARK = QColor(44, 44, 46), QColor(28, 28, 30)
GREEN, PURPLE, BLUE = QColor(48, 209, 88), QColor(168, 85, 247), QColor(10, 132, 255)


def glyph(p, island, rect, ch, px, color=WHITE):
    p.setFont(island._icon_font(px))
    p.setPen(color)
    p.drawText(rect, Qt.AlignCenter, ch)


def bar(p, rect, frac, fill=WHITE, track=DIM):
    rad = rect.height() / 2
    p.setPen(Qt.NoPen)
    p.setBrush(track)
    p.drawRoundedRect(rect, rad, rad)
    if frac > 0:
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(rect.left(), rect.top(), max(rect.height(), rect.width() * min(frac, 1.0)), rect.height()),
                          rad, rad)


def pill(p, island, rect, text, bg, fg=WHITE, icon=None, bold=False):
    """Rounded button: optional Fluent icon then text, centred together."""
    rad = rect.height() / 2
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(rect, rad, rad)
    tw = QFontMetrics(theme.font(10)).horizontalAdvance(text)
    x = rect.center().x() - (tw + (20 if icon else 0)) / 2
    if icon:
        glyph(p, island, QRectF(x, rect.top(), 16, rect.height()), icon, 13, fg)
        x += 20
    island._text(p, QRectF(x, rect.top(), tw + 4, rect.height()), text, 10, fg, Qt.AlignLeft, bold=bold)


def bell(p, c, color):
    """Filled bell (Nusa's reminder icon), about 14 px tall, centred on c."""
    x, y = c.x(), c.y()
    path = QPainterPath()
    path.moveTo(x - 5.5, y + 3.5)
    path.cubicTo(x - 5.5, y - 7.5, x + 5.5, y - 7.5, x + 5.5, y + 3.5)
    path.lineTo(x + 7, y + 5)
    path.lineTo(x - 7, y + 5)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(path)
    p.drawEllipse(QPointF(x, y + 7), 2, 2)
    p.drawEllipse(QPointF(x, y - 6.8), 1.3, 1.3)


def plus_circle(p, c, r=7.5):
    """Filled white circle with a black plus (Nusa's Add Task icon)."""
    p.setPen(Qt.NoPen)
    p.setBrush(WHITE)
    p.drawEllipse(c, r, r)
    p.setPen(QPen(QColor(0, 0, 0), 1.8, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(c.x() - r * 0.5, c.y()), QPointF(c.x() + r * 0.5, c.y()))
    p.drawLine(QPointF(c.x(), c.y() - r * 0.5), QPointF(c.x(), c.y() + r * 0.5))


def tray(p, c):
    """Inbox tray with a down arrow (Nusa's empty-shelf icon), about 26 px wide, centred on c."""
    x, y = c.x(), c.y()
    body = QPainterPath()
    body.moveTo(x - 13, y + 2)
    body.lineTo(x - 9, y - 4)
    body.lineTo(x + 9, y - 4)
    body.lineTo(x + 13, y + 2)
    body.lineTo(x + 13, y + 11)
    body.quadTo(x + 13, y + 13, x + 11, y + 13)
    body.lineTo(x - 11, y + 13)
    body.quadTo(x - 13, y + 13, x - 13, y + 11)
    body.closeSubpath()
    slot = QPainterPath()
    slot.addRoundedRect(QRectF(x - 6, y + 1.5, 12, 4), 1.5, 1.5)
    p.setPen(Qt.NoPen)
    p.setBrush(WHITE)
    p.drawPath(body.subtracted(slot))
    p.drawRect(QRectF(x - 1.3, y - 15, 2.6, 8))
    p.drawPolygon([QPointF(x - 5, y - 8), QPointF(x + 5, y - 8), QPointF(x, y - 3)])


def mmss(s):
    s = max(0, int(s))
    return f"{s // 60:02d}:{s % 60:02d}"


class Page:
    title = ""
    status_icon = None  # "wave" or "bell": drawn in the header's right corner
    hide_title = False

    def draw(self, p, r, island):
        pass

    def click(self, pos, button, island):
        return False

    def animating(self):
        return False

    def compact_text(self):
        return None


class MediaPage(Page):
    title = "Music"
    icon = "\uE8D6"  # page-icons bar
    status_icon = "wave"
    hide_title = True  # the cover art sits where other pages put their title
    SLIDER_W = 68.0

    def __init__(self):
        self.lyrics_view = False  # the bubble button: Nusa's wide view with synced lyrics on the right
        self.muted = False
        self.level = None  # volume 0..1, read when the slider is revealed (a COM call: not on every frame)

    def _slider(self, r):
        cy = r.top() + 157
        return QRectF(r.left() + 322, cy - 10, self.SLIDER_W, 20)

    def draw(self, p, r, island):
        """Crossfades the player and the lyrics view as the island widens; only the main one keeps buttons."""
        w = island.wide_v
        full = QRectF(r.center().x() - island._island_rect().width() / 2, r.top(), island._island_rect().width(),
                      r.height())
        for view, rect, alpha in ((self._draw_player, r, 1 - w), (self._draw_lyrics_view, full, w)):
            if alpha <= 0.01:
                continue
            keep = dict(island.buttons) if alpha < 0.5 else None
            p.save()
            p.setOpacity(p.opacity() * alpha)
            view(p, rect, island)
            p.restore()
            if keep is not None:
                island.buttons = keep

    @staticmethod
    def _cover(p, island, art, info):
        if info.get("title"):
            island._draw_art(p, art, 12)
            return info["title"]
        p.setPen(Qt.NoPen)  # Nusa keeps the whole player with a placeholder tile
        p.setBrush(CHIP)
        p.drawRoundedRect(art, 12, 12)
        glyph(p, island, art, "\uE8D6", 28, QColor(160, 160, 165))
        return "Not Playing"

    def _draw_lyrics_view(self, p, r, island):
        """Nusa's lyrics view: a compact player on the left, the synced lines scrolling on the right."""
        L, T = r.left(), r.top()
        info = island.info or {}
        playing = bool(info.get("playing"))
        title = self._cover(p, island, QRectF(L + 22, T + 27, 73, 73), info)
        island._text(p, QRectF(L + 113, T + 40, 162, 24), title, 12, WHITE, Qt.AlignLeft, bold=True, scroll=playing)
        island._text(p, QRectF(L + 113, T + 62, 162, 18), info.get("artist", ""), 9, GREY, Qt.AlignLeft, scroll=playing)
        dur = info.get("duration") or 0.0
        pos = min(island._pos(), dur) if dur and info else 0.0
        island._text(p, QRectF(L + 26, T + 114, 56, 22), mmss(pos), 13, WHITE, Qt.AlignLeft)
        bar(p, QRectF(L + 86, T + 122, 124, 4), pos / dur if dur else 0.0)
        island._text(p, QRectF(L + 212, T + 114, 60, 22), "-" + mmss(dur - pos), 13, WHITE, Qt.AlignRight)
        cy = T + 157
        island.buttons["lyrics"] = QRectF(L + 46, cy - 14, 28, 28)
        glyph(p, island, island.buttons["lyrics"], "\uE8BD", 17, WHITE)
        for action, cx in (("prev", L + 104), ("toggle", L + 148), ("next", L + 193)):
            island.buttons[action] = QRectF(cx - 20, cy - 16, 40, 32)
            self._draw_icon(p, island, action, QPointF(cx, cy))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(QPointF(L + 288, T + 40), QPointF(L + 288, T + 170))
        self._draw_lines(p, QRectF(L + 302, T + 22, r.width() - 302 - 50, r.height() - 34), island)

    @staticmethod
    def _draw_lines(p, box, island):
        lyrics = (island.info or {}).get("lyrics") if island.on("lyrics") else None
        if not lyrics:
            island._text(p, box, "Lyrics are off" if not island.on("lyrics") else "No synced lyrics", 11, GREY,
                         Qt.AlignCenter)
            return
        pos = island._pos()
        i = bisect.bisect_right(lyrics, pos, key=lambda l: l[0]) - 1
        font = theme.font(12, QFont.Bold)
        fm = QFontMetrics(font)
        wrap = lambda k: lyrics[k][1]  # Nusa leaves instrumental gaps blank
        height = lambda k: fm.boundingRect(box.toRect().adjusted(0, 0, 0, 1000), Qt.TextWordWrap, wrap(k) or "x").height()
        gap = 14.0
        t = min(1.0, max(0.0, (pos - lyrics[i][0]) / 0.35)) if i >= 0 else 1.0
        ease = 1 - (1 - t) ** 3  # the new line glides up into place
        cur = max(i, 0)
        y = box.top() + 42 + ((height(i - 1) + gap) * (1 - ease) if i >= 1 else 0)
        k = cur - 1
        ky = y
        while k >= 0 and ky > box.top():  # earlier lines above, fading out of the top
            ky -= height(k) + gap
            k -= 1
        k += 1
        p.save()
        p.setClipRect(box, Qt.IntersectClip)
        p.setFont(font)
        while k < len(lyrics) and ky < box.bottom():
            h = height(k)
            dim = int(70 * (1 - ease)) if k < i else 70  # the line just sung fades out as it rises
            p.setPen(QColor(255, 255, 255) if k == i else QColor(255, 255, 255, dim))
            p.drawText(QRectF(box.left(), ky, box.width(), h), Qt.AlignLeft | Qt.TextWordWrap, wrap(k))
            ky += h + gap
            k += 1
        p.restore()

    def _draw_player(self, p, r, island):
        L, T = r.left(), r.top()
        info = island.info or {}
        playing = bool(info.get("playing"))
        art = QRectF(L + 37, T + 28, 71, 70)
        title = self._cover(p, island, art, info)
        n = info.get("sessions", 0)
        if n > 1:  # one dot per media source; the current one is white
            x0 = art.center().x() - (n - 1) * 3.5
            for i in range(n):
                c = QPointF(x0 + i * 7, T + 104)
                island.buttons[f"src{i}"] = QRectF(c.x() - 4, c.y() - 5, 8, 10)
                p.setPen(Qt.NoPen)
                p.setBrush(WHITE if i == info.get("source", 0) else DIM)
                p.drawEllipse(c, 1.8, 1.8)
        x, w = L + 126, r.right() - 37 - (L + 126)
        island._text(p, QRectF(x, T + 49, w, 24), title, 12, WHITE, Qt.AlignLeft, bold=True, scroll=playing)
        island._text(p, QRectF(x, T + 71, w, 18), info.get("artist", ""), 9, GREY, Qt.AlignLeft, scroll=playing)
        dur = info.get("duration") or 0.0
        pos = min(island._pos(), dur) if dur and info else 0.0
        island._text(p, QRectF(L + 37, T + 112, 60, 22), mmss(pos), 13, WHITE, Qt.AlignLeft)
        bar(p, QRectF(L + 97, T + 120, 253, 4), pos / dur if dur else 0.0)
        island._text(p, QRectF(L + 352, T + 112, 66, 22), "-" + mmss(dur - pos), 13, WHITE, Qt.AlignRight)
        cy = T + 157
        island.buttons["lyrics"] = QRectF(L + 58, cy - 14, 28, 28)
        glyph(p, island, island.buttons["lyrics"], "\uE8BD", 17, WHITE)
        for action, cx in (("prev", L + 173), ("toggle", L + 228), ("next", L + 281)):
            island.buttons[action] = QRectF(cx - 20, cy - 16, 40, 32)
            self._draw_icon(p, island, action, QPointF(cx, cy))
        island.buttons["volume"] = QRectF(L + 395, cy - 14, 28, 28)
        glyph(p, island, island.buttons["volume"], "\uE74F" if self.muted else "\uE767", 15)
        slider = self._slider(r)
        hover = island.hover_pos
        if hover is not None and slider.united(island.buttons["volume"]).adjusted(-4, -6, 4, 6).contains(hover):
            if self.level is None:
                self.level, self.muted = island.read_volume()
            island.buttons["slider"] = slider
            bar(p, QRectF(slider.left(), cy - 2.5, slider.width(), 5), self.level, WHITE)
        else:
            self.level = None  # read afresh next time it opens

    def set_level(self, pos, island):
        """Click or drag on the hover slider: set the system volume."""
        slider = island.buttons.get("slider")
        if slider is None:
            return False
        self.level = max(0.0, min(1.0, (pos.x() - slider.left()) / slider.width()))
        island.write_volume(self.level)
        return True

    def click(self, pos, button, island):
        for action, rect in island.buttons.items():
            if not rect.contains(pos):
                continue
            if action == "slider":
                self.set_level(pos, island)
            elif action.startswith("src"):
                getattr(island.media, "select", lambda n: None)(int(action[3:]))
            elif action == "lyrics":
                self.lyrics_view = not self.lyrics_view
                island.update()
            elif action == "volume":
                try:
                    self.muted = island.volume.toggle_mute()[1]
                except OSError:  # no audio device: nothing to mute
                    pass
            else:
                island.media.send(action)
                if action == "toggle" and island.info:  # optimistic flip so the icon reacts before the next poll
                    island._on_media({**island.info, "playing": not island.info.get("playing"),
                                      "pos": island._pos(), "pos_at": time.monotonic()})
            return True
        return False

    def _draw_icon(self, p, island, action, c):
        p.setPen(Qt.NoPen)
        p.setBrush(WHITE)
        tri = lambda x, d: [QPointF(x, c.y() - 8), QPointF(x + d * 11, c.y()), QPointF(x, c.y() + 8)]
        if action == "toggle" and island.info.get("playing"):
            p.drawRoundedRect(QRectF(c.x() - 6.5, c.y() - 9, 4.5, 18), 1.2, 1.2)
            p.drawRoundedRect(QRectF(c.x() + 2, c.y() - 9, 4.5, 18), 1.2, 1.2)
        elif action == "toggle":  # Nusa's play triangle is larger than the skip arrows
            p.drawPolygon([QPointF(c.x() - 6, c.y() - 10), QPointF(c.x() + 9, c.y()), QPointF(c.x() - 6, c.y() + 10)])
        else:
            d = 1 if action == "next" else -1
            p.drawPolygon(tri(c.x() - d * 10, d))
            p.drawPolygon(tri(c.x() - d * 0.5, d))


class WaterPage(Page):
    icon = "\uEB42"
    """Today's water: big litres, reminder switch, progress, Drink/Settings, and an hourly chart (09-21)."""
    title = "Water"
    status_icon = "bell"
    HOURS = range(9, 22)

    def __init__(self, water, drink, open_settings, toggle_reminders):
        self.water, self.on_drink, self.on_settings, self.on_toggle = water, drink, open_settings, toggle_reminders
        self.hits = {}

    def draw(self, p, r, island):
        L, T, w = r.left(), r.top(), self.water
        self.hits = {}
        big = f"{w.taken / 1000:.1f}"
        bw = QFontMetrics(theme.font(24, QFont.Bold)).horizontalAdvance(big)
        island._text(p, QRectF(L + 37, T + 56, bw + 4, 40), big, 24, WHITE, Qt.AlignLeft, bold=True)
        island._text(p, QRectF(L + 43 + bw, T + 68, 70, 24), f"/ {w.goal / 1000:g} L", 11, GREY, Qt.AlignLeft)
        self.hits["switch"] = sw = QRectF(L + 172, T + 64, 39, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(GREEN if w.on else CHIP)
        p.drawRoundedRect(sw, 11, 11)
        knob = QPointF(sw.right() - 11 if w.on else sw.left() + 11, sw.center().y())
        p.setBrush(WHITE)
        p.drawEllipse(knob, 9, 9)
        p.save()
        p.translate(knob)
        p.scale(0.62, 0.62)
        bell(p, QPointF(0, 0), QColor(70, 70, 74))
        p.restore()
        pct = round(100 * w.taken / w.goal) if w.goal else 0
        island._text(p, QRectF(L + 37, T + 96, 200, 20), f"Today · {pct}% · Reminders {'on' if w.on else 'off'}", 10,
                     GREY, Qt.AlignLeft)
        bar(p, QRectF(L + 37, T + 121, 174, 5), w.taken / w.goal if w.goal else 0, BLUE)
        self.hits["drink"] = QRectF(L + 37, T + 141, 66, 29)
        pill(p, island, self.hits["drink"], "Drink", QColor(10, 132, 255, 55), QColor(120, 180, 255), "")
        self.hits["settings"] = QRectF(L + 111, T + 141, 72, 29)
        pill(p, island, self.hits["settings"], "Settings", CHIP, WHITE, "")
        self._chart(p, island, QRectF(L + 228, T + 82, 144, 70))

    def _chart(self, p, island, a):
        p.setPen(QPen(QColor(50, 50, 54), 1))
        p.drawLine(QPointF(a.left() - 3, a.top() - 12), QPointF(a.left() - 3, a.bottom() + 16))
        p.drawLine(QPointF(a.left(), a.bottom()), QPointF(a.right(), a.bottom()))
        dash = QPen(QColor(70, 70, 74), 1, Qt.DashLine)
        for ml, y in ((200, a.top()), (100, a.center().y())):
            p.setPen(dash)
            p.drawLine(QPointF(a.left(), y), QPointF(a.right(), y))
        for label, y in (("200", a.top()), ("100", a.center().y()), ("0 ml", a.bottom())):
            island._text(p, QRectF(a.right() + 5, y - 9, 40, 18), label, 8, GREY, Qt.AlignLeft)
        slot = a.width() / len(self.HOURS)
        for n, hour in enumerate(self.HOURS):
            col = QRectF(a.left() + n * slot + slot * 0.18, a.top(), slot * 0.64, a.height())
            bar_h = a.height() * min(self.water.hours[hour] / 200, 1.0)
            p.setPen(Qt.NoPen)
            p.setBrush(CHIP_DARK)
            p.drawRoundedRect(col, 2, 2)
            if bar_h:
                p.setBrush(BLUE)
                p.drawRoundedRect(QRectF(col.left(), col.bottom() - bar_h, col.width(), bar_h), 2, 2)
            if hour % 3 == 0:
                island._text(p, QRectF(col.center().x() - 12, a.bottom() + 5, 24, 16), f"{hour:02d}", 8, GREY,
                             Qt.AlignCenter)

    def click(self, pos, button, island):
        for key, action in (("drink", self.on_drink), ("settings", self.on_settings), ("switch", self.on_toggle)):
            if key in self.hits and self.hits[key].contains(pos):
                action()
                return True
        return False


class TodoPage(Page):
    icon = "\uE9D5"
    """Done/total today, Add Task / Edit Task, and the task list (or an empty state) in a panel on the right."""
    title = "Todo"
    title_parts = [("Todo", WHITE), ("List", GREEN)]
    status_icon = "bell"
    ROWS = 4

    def __init__(self, todo, changed):
        self.todo, self.changed = todo, changed
        self.editing = False
        self.hits = {}

    def draw(self, p, r, island):
        from island.todo import ordered
        L, T = r.left(), r.top()
        tasks = ordered(self.todo.tasks)
        self.hits = {}
        done = sum(t.done for t in tasks)
        island._text(p, QRectF(L + 37, T + 58, 90, 44), f"{done}/{len(tasks)}", 26, WHITE, Qt.AlignLeft, bold=True)
        p.setPen(Qt.NoPen)
        p.setBrush(CHIP)
        p.drawEllipse(QPointF(L + 136, T + 82), 16, 16)
        glyph(p, island, QRectF(L + 126, T + 72, 20, 20), "", 13)
        p.setBrush(BLUE)
        p.drawEllipse(QPointF(L + 148, T + 71), 3.5, 3.5)
        island._text(p, QRectF(L + 37, T + 110, 170, 20), "Task Done Today", 10, GREY, Qt.AlignLeft)
        self.hits["add"] = QRectF(L + 34, T + 141, 84, 29)
        pill(p, island, self.hits["add"], "Add Task", CHIP, WHITE, " ")
        tw = QFontMetrics(theme.font(10)).horizontalAdvance("Add Task")  # pill() centres [icon 20 px][text]
        plus_circle(p, QPointF(self.hits["add"].center().x() - (tw + 20) / 2 + 8, self.hits["add"].center().y()))
        self.hits["edit"] = QRectF(L + 124, T + 141, 82, 29)
        pill(p, island, self.hits["edit"], "Done" if self.editing else "Edit Task",
             CHIP if tasks else CHIP_DARK, WHITE if tasks else DIM, "")
        panel = QRectF(L + 212, T + 64, 206, 106)
        p.setPen(Qt.NoPen)
        p.setBrush(CHIP_DARK)
        p.drawRoundedRect(panel, 16, 16)
        if not tasks:
            p.setBrush(CHIP)
            p.drawRoundedRect(QRectF(panel.center().x() - 19, panel.top() + 18, 38, 38), 9, 9)
            glyph(p, island, QRectF(panel.center().x() - 19, panel.top() + 18, 38, 38), "", 20, GREY)
            island._text(p, QRectF(panel.left(), panel.top() + 62, panel.width(), 24), "No tasks.", 11, GREY,
                         Qt.AlignCenter)
            return
        for n, t in enumerate(tasks[:self.ROWS]):
            row = QRectF(panel.left() + 10, panel.top() + 8 + n * 23, panel.width() - 20, 23)
            self.hits[n] = row
            c = QPointF(row.left() + 8, row.center().y())
            p.setPen(QPen(GREEN if t.done else GREY, 1.5))
            p.setBrush(GREEN if t.done else Qt.NoBrush)
            p.drawEllipse(c, 6, 6)
            if self.editing:
                glyph(p, island, QRectF(c.x() - 6, c.y() - 6, 12, 12), "", 8, QColor(255, 69, 58))
            right = "" if t.at is None else f"{t.at // 60:02d}:{t.at % 60:02d}"
            island._text(p, row.adjusted(20, 0, -40, 0), t.text, 10, GREY if t.done else WHITE, Qt.AlignLeft)
            island._text(p, row, right, 9, GREY, Qt.AlignRight)

    def click(self, pos, button, island):
        from island.todo import ordered
        tasks = ordered(self.todo.tasks)
        if self.hits.get("add", QRectF()).contains(pos):
            self.todo.click(len(tasks), Qt.LeftButton)  # past the end: the add path
        elif self.hits.get("edit", QRectF()).contains(pos) and tasks:
            self.editing = not self.editing
        else:
            n = next((k for k, rect in self.hits.items() if isinstance(k, int) and rect.contains(pos)), None)
            if n is None:
                return False
            self.todo.click(n, Qt.RightButton if self.editing or button == Qt.RightButton else Qt.LeftButton)
        self.changed()
        return True


class TodayPage(Page):
    icon = "\uE787"
    """Rows from feature sections (weather, prayer, water, calendar), at most MAX_ROWS in total."""
    title = "Today"
    MAX_ROWS, TOP, ROW_H = 5, 52.0, 22.0

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
                row = QRectF(r.left() + 37, r.top() + self.TOP + len(self.hits) * self.ROW_H, r.width() - 74, self.ROW_H)
                right_w = fm.horizontalAdvance(right) + 12 if right else 0
                island._text(p, row.adjusted(0, 0, -right_w, 0), left, 10, WHITE, Qt.AlignLeft)
                island._text(p, row, right, 10, GREY, Qt.AlignRight)
                self.hits.append((row, on_click, i))
        if not self.hits:
            island._text(p, QRectF(r.left(), r.top() + 44, r.width(), r.height() - 60), "Nothing today", 11, GREY,
                         Qt.AlignCenter)

    def click(self, pos, button, island):
        for row, on_click, i in self.hits:
            if on_click and row.contains(pos):
                on_click(i, button)
                return True
        return False
