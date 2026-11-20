import ctypes
from ctypes import wintypes

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QKeyEvent, QMouseEvent, QPainter

from island import ocr


def _png(text=None):
    img = QImage(640, 120, QImage.Format_RGB32)
    img.fill(QColor("white"))
    if text:
        p = QPainter(img)
        f = QFont("Segoe UI")
        f.setPixelSize(48)
        p.setFont(f)
        p.setPen(QColor("black"))
        p.drawText(img.rect(), Qt.AlignCenter, text)
        p.end()
    buf = QBuffer(ba := QByteArray())
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def test_reads_rendered_text(qapp):
    assert "HELLO" in ocr.ocr_png(_png("HELLO 2026"))


def test_blank_image_reads_nothing(qapp):
    assert ocr.ocr_png(_png()) == ""


def test_result_popups():
    assert ocr.result_popup("hello world") == ("popup", "", "Copied text", "11 characters")
    assert ocr.result_popup("  \n") == ("popup", "", "No text found", "")


def _mouse(kind, x, y, button=Qt.LeftButton):
    pos = QPointF(x, y)
    return QMouseEvent(kind, pos, pos, button, button, Qt.NoModifier)


def test_picker_emits_dragged_rect(qapp):
    picker = ocr.RegionPicker()
    got = []
    picker.picked.connect(got.append)
    picker.mousePressEvent(_mouse(QEvent.MouseButtonPress, 10, 20))
    picker.mouseMoveEvent(_mouse(QEvent.MouseMove, 110, 70))
    picker.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, 110, 70))
    origin = picker.geometry().topLeft()
    assert got == [QRect(origin + QPoint(10, 20), origin + QPoint(110, 70)).normalized()]


def test_picker_selection_is_clear_but_not_click_through(qapp):
    picker = ocr.RegionPicker()
    picker.start, picker.end = QPoint(100, 80), QPoint(420, 220)
    img = picker.grab().toImage()
    assert img.pixelColor(20, 20).alpha() == 90, "dimmed outside the selection"
    assert img.pixelColor(200, 150).alpha() == 1, "alpha 0 would let clicks fall through on Windows"


def test_picker_escape_or_tiny_drag_cancels(qapp):
    for act in ("esc", "click"):
        picker = ocr.RegionPicker()
        got = []
        picker.cancelled.connect(lambda: got.append("cancelled"))
        picker.picked.connect(got.append)
        if act == "esc":
            picker.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        else:
            picker.mousePressEvent(_mouse(QEvent.MouseButtonPress, 10, 10))
            picker.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, 11, 11))
        assert got == ["cancelled"], act


def test_too_large_area_is_refused_without_grabbing(island, monkeypatch):
    monkeypatch.setattr(ocr, "max_dimension", lambda: 2600)
    monkeypatch.setattr(QGuiApplication, "primaryScreen", lambda: (_ for _ in ()).throw(AssertionError("grabbed")))
    island._ocr_region(QRect(0, 0, 3000, 100))
    assert island.hud == ("popup", "", "That area is too large", "Select a smaller part")


def test_finished_text_goes_to_clipboard(island, qapp):
    island._ocr_finished("copied words")
    assert QGuiApplication.clipboard().text() == "copied words"
    assert island.hud == ("popup", "", "Copied text", "12 characters")


def test_hotkey_message_starts_picker(island, monkeypatch):
    started = []
    monkeypatch.setattr(island, "start_ocr", lambda: started.append(1))
    msg = wintypes.MSG(message=0x312, wParam=1)  # WM_HOTKEY, id 1
    island.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))
    assert started == [1]
