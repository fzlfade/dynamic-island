"""To-do list for the Today page, with a reminder popup when a timed task comes due."""
import re
import time
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QInputDialog

from island import store

GLYPH = "\uE73E"  # checkmark list
WAKE_GAP_S = 120


@dataclass
class Task:
    done: bool
    at: int | None  # minutes after midnight
    text: str


def parse_task(s):
    m = re.match(r"(\d{1,2}):(\d{2})\s+(\S.*)$", s.strip())
    if m and int(m[1]) < 24 and int(m[2]) < 60:
        return Task(False, int(m[1]) * 60 + int(m[2]), m[3])
    return Task(False, None, s.strip())


def load_tasks():
    out = []
    for line in store.load_lines("tasks.txt"):
        try:
            done, at, text = line.split("|", 2)
            if text:
                out.append(Task(done == "1", None if int(at) < 0 else int(at), text))
        except ValueError:
            continue
    return out


def save_tasks(tasks):
    store.save_lines("tasks.txt", [f"{int(t.done)}|{-1 if t.at is None else t.at}|{t.text}" for t in tasks])


def due(tasks, prev_min, now_min):
    span = (now_min - prev_min) % 1440  # window (prev, now], wrapping past midnight
    hit = [t for t in tasks if not t.done and t.at is not None and 1 <= (t.at - prev_min) % 1440 <= span]
    if span > 120 and hit:  # sleep or clock jump: don't flood, keep the latest
        return [max(hit, key=lambda t: (t.at - prev_min) % 1440)]
    return hit


def ordered(tasks):
    return sorted(tasks, key=lambda t: (t.done, t.at is None, t.at or 0))  # stable: insertion order within ties


def now_min():
    n = datetime.now()
    return n.hour * 60 + n.minute


class Todo:
    """Owns the in-memory task list; rows() is called on every paint so it never touches disk."""

    def __init__(self, parent, notify):
        self.notify = notify
        self.tasks = load_tasks()
        self.prev_min = now_min()
        self.last = time.monotonic()
        self.timer = QTimer(parent, interval=60_000, timeout=self.check)
        self.timer.start()

    def rows(self):
        return [(("✓ " if t.done else "") + t.text, "" if t.at is None else f"{t.at // 60:02d}:{t.at % 60:02d}")
                for t in ordered(self.tasks)] + [("+ Add task", "")]

    def click(self, i, button):
        shown = ordered(self.tasks)
        if i >= len(shown):
            text, ok = QInputDialog.getText(None, "New task", "e.g. 09:30 Call mom")
            if not ok or not text.strip():
                return
            self.tasks.append(parse_task(text))
        elif button == Qt.RightButton:
            self.tasks.remove(shown[i])
        else:
            shown[i].done = not shown[i].done
        save_tasks(self.tasks)

    def check(self):
        now = now_min()
        for t in due(self.tasks, self.prev_min, now):
            self.notify(("popup", GLYPH, "To-do", t.text))
        self.prev_min, self.last = now, time.monotonic()

    def tick(self):
        """Called every second: a long gap means the machine slept and the 60 s timer was late."""
        if time.monotonic() - self.last > WAKE_GAP_S:
            self.check()
