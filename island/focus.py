"""Pomodoro: focus/break cycle driven by its own 1 s timer, so phases end on time even when the island is collapsed."""
import time
from datetime import datetime
import winsound

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPen

from island import store, theme
from island.pages import CHIP, GREY, PURPLE, WHITE, Page, bar, glyph

GLYPH = "\uE916"  # stopwatch
NAMES = {"idle": "Ready", "focus": "Focus", "short_break": "Short break", "long_break": "Long break"}
PHASE_LABEL = {"idle": "Focus", "focus": "Focus", "short_break": "Break", "long_break": "Long break"}


class Pomodoro:
    def __init__(self, focus_s=1500, short_s=300, long_s=900, rounds=4):
        self.durations = {"focus": focus_s, "short_break": short_s, "long_break": long_s}
        self.rounds = rounds
        self.stop()

    def stop(self):
        self.phase, self.round, self.end = "idle", 0, 0.0

    def _enter(self, phase, now):
        self.phase, self.end = phase, now + self.durations[phase]

    def start(self, now):
        self.round = 1
        self._enter("focus", now)

    def remaining(self, now):
        return max(0.0, self.end - now) if self.phase != "idle" else 0.0

    def tick(self, now):
        """Advance one phase if the current one ended (even if late); returns the new phase."""
        if self.phase == "idle" or now < self.end:
            return None
        if self.phase == "focus":
            self._enter("long_break" if self.round >= self.rounds else "short_break", now)
        elif self.phase == "short_break":
            self.round += 1
            self._enter("focus", now)
        else:
            self.stop()
        return self.phase


class FocusPage(Page):
    icon = ""  # page-icons bar
    title = "Pomodoro"
    status_icon = "wave"

    def __init__(self, notify, repaint=lambda: None):
        self.notify = notify
        self.repaint = repaint
        self.pomo = Pomodoro()
        self.minutes = {"short_break": 5, "long_break": 15}
        self.cfg = self._settings()  # cached: draw() runs every frame and must not read the disk
        self.idle_m = self.cfg["focus"]
        self.button = self.reset = QRectF()
        self.timer = QTimer(interval=1000, timeout=lambda: self._tick(time.monotonic()))
        self.log = store.load_kv("focus.txt")  # {"day", "minutes", "sessions"}: today's finished focus rounds

    @staticmethod
    def _settings():
        v = store.load_kv("settings.txt")
        return {k: max(1, store.get_int(v, k, d)) for k, d in (("focus", 25), ("short_break", 5), ("long_break", 15))}

    def start(self):
        m = self.minutes = self._settings()  # read now so edits apply to the next run
        self.idle_m = m["focus"]
        self.pomo = Pomodoro(m["focus"] * 60, m["short_break"] * 60, m["long_break"] * 60)
        self.pomo.start(time.monotonic())
        self.timer.start()

    def stop(self):
        self.pomo.stop()
        self.timer.stop()
        self.cfg = self._settings()
        self.idle_m = self.cfg["focus"]

    def _tick(self, now):
        was = self.pomo.phase
        new = self.pomo.tick(now)
        self.repaint()  # refreshes the "● MM:SS" countdown once a second
        if new is None:
            return
        if was == "focus":
            self._log_focus(self.pomo.durations["focus"] // 60)
            popup = ("Focus done", f"Take a {self.minutes[new]} min break")
        elif new == "focus":
            popup = ("Break over", "Back to focus")
        else:
            popup = ("Cycle complete", "Nice work")
        if new == "idle":
            self.timer.stop()
        winsound.MessageBeep()
        self.notify(("popup", GLYPH, *popup))

    def today(self, day=None):
        """(minutes, sessions) of focus finished today; the Focus today widget shows it."""
        day = (day or datetime.now().date()).isoformat()
        if self.log.get("day") != day:
            return 0, 0
        return store.get_int(self.log, "minutes", 0), store.get_int(self.log, "sessions", 0)

    def _log_focus(self, minutes, day=None):
        m, n = self.today(day)
        self.log = {"day": (day or datetime.now().date()).isoformat(), "minutes": str(m + minutes), "sessions": str(n + 1)}
        store.save_kv("focus.txt", self.log)

    def animating(self):
        return False  # the 1 s tick repaints; no frame timer needed for a countdown

    def compact_text(self):
        if self.pomo.phase == "idle":
            return None
        s = int(self.pomo.remaining(time.monotonic()) + 0.999)  # round up: shows 25:00 at the start
        return f"● {s // 60:02d}:{s % 60:02d}"

    def draw(self, p, r, island):
        """Nusa's Pomodoro page: the cycle on the left, this round's segments and Start/reset on the right."""
        L, T, now = r.left(), r.top(), time.monotonic()
        phase, running = self.pomo.phase, self.pomo.phase != "idle"
        m = self.minutes if running else self.cfg
        rnd, rounds = max(1, self.pomo.round), self.pomo.rounds
        island._text(p, QRectF(L + 37, T + 52, 160, 20), f"{PHASE_LABEL[phase]} · {rnd} of {rounds}", 10, GREY,
                     Qt.AlignLeft)
        left = self.pomo.remaining(now) if running else m["focus"] * 60
        s = int(left + 0.999)  # round up: shows 25:00 at the start
        island._text(p, QRectF(L + 37, T + 68, 170, 48), f"{s // 60:02d}:{s % 60:02d}", 26, WHITE, Qt.AlignLeft, bold=True)
        phase_m = m["focus" if phase == "idle" else phase]
        label = f"{phase_m} min"
        lw = QFontMetrics(theme.font(12, QFont.Bold)).horizontalAdvance(label)
        island._text(p, QRectF(L + 37, T + 122, lw + 4, 24), label, 12, WHITE, Qt.AlignLeft, bold=True)
        island._text(p, QRectF(L + 45 + lw, T + 122, 90, 24), NAMES[phase] if running else "Ready", 12, PURPLE,
                     Qt.AlignLeft, bold=True)
        total = self.pomo.durations[phase] if running else 1
        bar(p, QRectF(L + 37, T + 153, 148, 5), 1 - left / total if running else 0.0, PURPLE)
        p.setPen(QPen(theme.LINE, 1))
        p.drawLine(QPointF(L + 207, T + 60), QPointF(L + 207, T + 165))
        island._text(p, QRectF(L + 223, T + 60, 100, 20), "This round", 10, GREY, Qt.AlignLeft)
        self.button = QRectF(L + 321, T + 62, 70, 24)
        grad = QLinearGradient(self.button.topLeft(), self.button.topRight())
        grad.setColorAt(0, theme.PRIMARY_FILL)
        grad.setColorAt(1, theme.SECONDARY_FILL)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(self.button, theme.RADIUS_MD, theme.RADIUS_MD)
        island._text(p, self.button, "Stop" if running else "Start", 10, theme.ON_ACCENT, Qt.AlignCenter, bold=True)
        self.reset = QRectF(L + 397, T + 63, 22, 22)
        p.setBrush(CHIP)
        p.drawEllipse(self.reset)
        glyph(p, island, self.reset, "\uE777", 11)
        bw, dot, gap = 28.0, 5.0, 6.0  # four focus segments and the long break, dots between
        x = L + 223
        for n in range(rounds + 1):
            seg = QRectF(x, T + 107, bw, 6)
            current = running and (n == rnd - 1 if n < rounds else phase == "long_break")
            past = running and (n < rnd - 1 if n < rounds else False)
            frac = 1.0 if past else (1 - left / total if current else 0.0)
            bar(p, seg, frac, PURPLE, CHIP)
            name = str(n + 1) if n < rounds else "Long"
            island._text(p, QRectF(seg.left() - 4, T + 120, bw + 8, 16), name, 8,
                         WHITE if n == rnd - 1 else GREY, Qt.AlignCenter, bold=n == rnd - 1)
            if n < rounds:
                p.setPen(Qt.NoPen)
                p.setBrush(CHIP)
                p.drawEllipse(QPointF(x + bw + gap / 2 + dot / 2 - 0.5, T + 110), dot / 2, dot / 2)
            x += bw + gap + dot
        whole = rounds * m["focus"] + (rounds - 1) * m["short_break"] + m["long_break"]
        island._text(p, QRectF(L + 223, T + 140, 195, 18), f"{whole // 60} h {whole % 60} min · {rounds} sessions", 9,
                     GREY, Qt.AlignLeft)

    def click(self, pos, button, island):
        if not self.button.contains(pos):
            return False
        self.stop() if self.pomo.phase != "idle" else self.start()
        island.update()
        island._update_frame()
        return True
