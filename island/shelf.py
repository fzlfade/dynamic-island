"""File shelf: drop files, text or links on the notch and drag them back out later (Nusa: Shelf)."""
import os
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFileInfo, QMimeData, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import QFileIconProvider

from island import store
from island.pages import Page

MAX_CHIPS = 6


@dataclass
class ShelfItem:
    path: Path
    kind: str  # "file" | "text" | "url"


def store_dir():
    """Where dropped text and links are written: %LOCALAPPDATA%\\DynamicIsland\\Shelf."""
    base = store.DIR_OVERRIDE or Path(os.environ["LOCALAPPDATA"]) / "DynamicIsland"
    d = Path(base) / "Shelf"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(folder, suffix, content):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000}{suffix}"
    path.write_text(content, encoding="utf-8")
    return path


def _url_item(folder, url):
    return ShelfItem(_write(folder, ".url", f"[InternetShortcut]\nURL={url}\n"), "url")


def items_from_mime(mime: QMimeData, store_dir: Path):
    """Files are referenced in place; links become .url shortcuts; other text becomes a .txt file."""
    items = []
    for u in mime.urls() if mime.hasUrls() else []:
        if u.isLocalFile():
            items.append(ShelfItem(Path(u.toLocalFile()), "file"))
        elif u.scheme() in ("http", "https"):
            items.append(_url_item(store_dir, u.toString()))
    if items:
        return items
    text = mime.text().strip() if mime.hasText() else ""
    if not text:
        return []
    if text.startswith(("http://", "https://")) and not any(c.isspace() for c in text):
        return [_url_item(store_dir, text)]
    return [ShelfItem(_write(store_dir, ".txt", text), "text")]


def load():
    items = []
    for line in store.load_lines("shelf.txt"):
        kind, _, path = line.partition("|")
        if kind in ("file", "text", "url") and path and Path(path).exists():
            items.append(ShelfItem(Path(path), kind))
    return items


def save(items):
    store.save_lines("shelf.txt", [f"{i.kind}|{i.path}" for i in items])


class ShelfPage(Page):
    title = "Shelf"
    COLS, CHIP_W, CHIP_H, GAP = 3, 112.0, 40.0, 8.0

    def __init__(self, items=None):
        self.items = items or []  # newest first
        self.hits = []  # (chip rect, index), rebuilt on every draw
        self._icons = QFileIconProvider()

    def add(self, new):
        known = {i.path for i in new}
        self.items = new + [i for i in self.items if i.path not in known]
        save(self.items)

    def draw(self, p, r, island):
        self.hits = []
        if not self.items:
            island._text(p, QRectF(r), "Drop files here", 11, QColor(140, 140, 140), Qt.AlignCenter)
            return
        left = r.center().x() - (self.COLS * self.CHIP_W + (self.COLS - 1) * self.GAP) / 2
        for n, item in enumerate(self.items[:MAX_CHIPS]):
            row, col = divmod(n, self.COLS)
            chip = QRectF(left + col * (self.CHIP_W + self.GAP), r.top() + 14 + row * (self.CHIP_H + self.GAP),
                          self.CHIP_W, self.CHIP_H)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(38, 38, 42))
            p.drawRoundedRect(chip, 10, 10)
            icon = self._icons.icon(QFileInfo(str(item.path))).pixmap(20, 20)
            p.drawPixmap(int(chip.left() + 8), int(chip.center().y() - 10), icon)
            island._text(p, chip.adjusted(34, 0, -6, 0), item.path.name, 9, QColor(230, 230, 230), Qt.AlignLeft)
            self.hits.append((chip, n))

    def _at(self, pos):
        return next((n for chip, n in self.hits if chip.contains(pos)), None)

    def click(self, pos, button, island):
        n = self._at(pos)
        if n is None or button != Qt.RightButton:
            return False
        del self.items[n]  # removes it from the shelf only; the file stays on disk
        save(self.items)
        return True

    def drag(self, pos, island):
        """Start dragging the chip under `pos` out of the island as a file."""
        n = self._at(pos)
        if n is None:
            return False
        d = QDrag(island)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.items[n].path))])
        d.setMimeData(mime)
        d.exec(Qt.CopyAction)
        return True
