"""Pomodoro: focus/break cycle driven by its own 1 s timer, so phases end on time even when the island is collapsed."""
import time
import winsound

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor

from island import store
from island.pages import Page

GLYPH = "\uE916"  # stopwatch
NAMES = {"idle": "Ready", "focus": "Focus", "short_break": "Short break", "long_break": "Long break"}


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
    title = "Focus"

    def __init__(self, notify, repaint=lambda: None):
        self.notify = notify
        self.repaint = repaint
        self.pomo = Pomodoro()
        self.minutes = {"short_break": 5, "long_break": 15}
        self.idle_m = self._settings()["focus"]
        self.button = QRectF()
        self.timer = QTimer(interval=1000, timeout=lambda: self._tick(time.monotonic()))

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
        self.idle_m = self._settings()["focus"]

    def _tick(self, now):
        was = self.pomo.phase
        new = self.pomo.tick(now)
        self.repaint()  # refreshes the "● MM:SS" countdown once a second
        if new is None:
            return
        if was == "focus":
            popup = ("Focus done", f"Take a {self.minutes[new]} min break")
        elif new == "focus":
            popup = ("Break over", "Back to focus")
        else:
            popup = ("Cycle complete", "Nice work")
        if new == "idle":
            self.timer.stop()
        winsound.MessageBeep()
        self.notify(("popup", GLYPH, *popup))

    def animating(self):
        return False  # the 1 s tick repaints; no frame timer needed for a countdown

    def compact_text(self):
        if self.pomo.phase == "idle":
            return None
        s = int(self.pomo.remaining(time.monotonic()) + 0.999)  # round up: shows 25:00 at the start
        return f"● {s // 60:02d}:{s % 60:02d}"

    def draw(self, p, r, island):
        running = self.pomo.phase != "idle"
        s = int(self.pomo.remaining(time.monotonic()) + 0.999)
        text = f"{s // 60:02d}:{s % 60:02d}" if running else f"{self.idle_m:02d}:00"
        island._text(p, QRectF(r.left(), r.top() + 8, r.width(), 44), text, 28, QColor(255, 255, 255), Qt.AlignCenter, bold=True)
        island._text(p, QRectF(r.left(), r.top() + 52, r.width(), 18), NAMES[self.pomo.phase], 10, QColor(160, 160, 160), Qt.AlignCenter)
        self.button = QRectF(r.center().x() - 36, r.bottom() - 46, 72, 26)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(60, 60, 60))
        p.drawRoundedRect(self.button, 13, 13)
        island._text(p, self.button, "Stop" if running else "Start", 10, QColor(255, 255, 255), Qt.AlignCenter)

    def click(self, pos, button, island):
        if not self.button.contains(pos):
            return False
        self.stop() if self.pomo.phase != "idle" else self.start()
        island.update()
        island._update_frame()
        return True
