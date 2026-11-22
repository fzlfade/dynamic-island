"""Copy text from any part of the screen with Windows OCR (Nusa: Ctrl+Alt+T, Windows.Media.Ocr)."""
import asyncio

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from island import theme

GLYPH = ""  # Copy
HOTKEY_ID = 1


async def _recognize(png):
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png)
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)
    bitmap = await (await BitmapDecoder.create_async(stream)).get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OSError("no OCR language pack for the user's languages")
    return (await engine.recognize_async(bitmap)).text


def ocr_png(png: bytes) -> str:
    """Text Windows OCR reads in a PNG. Blocking: call it from a worker thread."""
    return asyncio.run(_recognize(png))


def max_dimension():
    from winrt.windows.media.ocr import OcrEngine
    return OcrEngine.max_image_dimension


def result_popup(text):
    text = text.strip()
    if not text:
        return ("popup", GLYPH, "No text found", "")
    return ("popup", GLYPH, "Copied text", f"{len(text)} characters")


class RegionPicker(QWidget):
    """Full-screen dim overlay: drag to select an area, Esc or a tiny drag cancels."""
    picked = Signal(QRect)  # in global screen coordinates
    cancelled = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(QGuiApplication.primaryScreen().geometry())
        self.start = self.end = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self.start is not None:
            sel = QRect(self.start, self.end).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Source)
            p.fillRect(sel, QColor(0, 0, 0, 1))  # looks clear; alpha 0 would let clicks fall through on Windows
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(theme.PRIMARY, 1))
            p.drawRect(sel)

    def mousePressEvent(self, e):
        self.start = self.end = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self.start is not None:
            self.end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if self.start is None:
            return
        sel = QRect(self.start, e.position().toPoint()).normalized()
        self.close()
        if sel.width() < 4 or sel.height() < 4:
            self.cancelled.emit()
        else:
            self.picked.emit(sel.translated(self.geometry().topLeft()))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            self.cancelled.emit()
