from PySide6.QtCore import Qt

from island import focus, store, todo
from island.todo import Task


def test_parse_task():
    assert todo.parse_task("09:30 Call mom") == Task(False, 570, "Call mom")
    assert todo.parse_task("Buy milk") == Task(False, None, "Buy milk")
    assert todo.parse_task("25:00 x") == Task(False, None, "25:00 x")


def test_roundtrip_with_pipe(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DIR_OVERRIDE", tmp_path)
    ts = [Task(True, 570, "a|b"), Task(False, None, "milk")]
    todo.save_tasks(ts)
    assert todo.load_tasks() == ts


def test_bad_task_lines_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DIR_OVERRIDE", tmp_path)
    store.save_lines("tasks.txt", ["garbage", "0|x|bad", "0|570|ok", "1|-1|done"])
    assert todo.load_tasks() == [Task(False, 570, "ok"), Task(True, None, "done")]
    store.save_lines("tasks.txt", ["0|570|", "0|570|x"])
    assert todo.load_tasks() == [Task(False, 570, "x")], "empty text skipped"


def test_due_basic():
    a, b = Task(False, 570, "a"), Task(True, 570, "done")
    assert todo.due([a, b, Task(False, None, "u")], 569, 570) == [a]
    assert todo.due([a], 570, 571) == []


def test_due_across_midnight_and_gap():
    ts = [Task(False, 1435, "late"), Task(False, 3, "early"), Task(False, 600, "no")]
    assert {t.text for t in todo.due(ts, 1430, 5)} == {"late", "early"}
    ts = [Task(False, 400, "x"), Task(False, 800, "y"), Task(False, 1000, "z")]
    assert [t.text for t in todo.due(ts, 300, 900)] == ["y"]


def test_ordered():
    ts = [Task(True, 1, "d"), Task(False, None, "u"), Task(False, 570, "b"), Task(False, 480, "a")]
    assert [t.text for t in todo.ordered(ts)] == ["a", "b", "u", "d"]


def make(island, monkeypatch, minute=100):
    monkeypatch.setattr(todo, "now_min", lambda: minute)
    sent = []
    t = todo.Todo(island, sent.append)
    return t, sent


def test_rows_click_remove_and_persist(island, monkeypatch):
    t, _ = make(island, monkeypatch)
    t.tasks = [Task(False, 570, "a"), Task(False, None, "b")]
    assert t.rows() == [("a", "09:30"), ("b", ""), ("+ Add task", "")]
    t.click(0, Qt.LeftButton)
    assert t.rows()[:2] == [("b", ""), ("✓ a", "09:30")]  # done goes last
    assert store.load_lines("tasks.txt") == ["1|570|a", "0|-1|b"]
    t.click(1, Qt.RightButton)
    assert [x.text for x in t.tasks] == ["b"] and len(store.load_lines("tasks.txt")) == 1


def test_add_via_dialog(island, monkeypatch):
    t, _ = make(island, monkeypatch)
    monkeypatch.setattr(todo.QInputDialog, "getText", staticmethod(lambda *a: ("08:15 Run", True)))
    t.click(0, Qt.LeftButton)  # only the + row
    assert t.tasks == [Task(False, 495, "Run")] and store.load_lines("tasks.txt") == ["0|495|Run"]
    monkeypatch.setattr(todo.QInputDialog, "getText", staticmethod(lambda *a: ("", False)))
    t.click(1, Qt.LeftButton)
    assert len(t.tasks) == 1


def test_check_fires_and_gap(island, monkeypatch):
    t, sent = make(island, monkeypatch, 569)
    t.tasks = [Task(False, 570, "Call mom")]
    monkeypatch.setattr(todo, "now_min", lambda: 570)
    t.check()
    assert sent == [("popup", "\uE73E", "To-do", "Call mom")]
    t.check()
    assert len(sent) == 1
    # wake gap: tick() checks once monotonic jumps > 120 s
    t.tasks = [Task(False, 600, "later")]
    monkeypatch.setattr(todo, "now_min", lambda: 601)
    t.tick()
    assert len(sent) == 1
    monkeypatch.setattr(todo.time, "monotonic", lambda: t.last + 500)
    t.tick()
    assert sent[-1][3] == "later"


def test_focus_not_animating_and_countdown_ticks(island, monkeypatch):
    repaints = []
    page = focus.FocusPage(island.notify, lambda: repaints.append(1))
    monkeypatch.setattr(focus.time, "monotonic", lambda: 100.0)
    page.start()
    assert not page.animating()
    monkeypatch.setattr(focus.time, "monotonic", lambda: 101.0)
    page._tick(101.0)
    assert repaints and page.compact_text() == "● 24:59"
    page.stop()


def test_focus_draw_does_not_read_settings(island, monkeypatch):
    page = focus.FocusPage(island.notify)
    monkeypatch.setattr(store, "load_kv", lambda n: (_ for _ in ()).throw(AssertionError("read on paint")))
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    img = QImage(300, 100, QImage.Format_ARGB32)
    p = QPainter(img)
    page.draw(p, QRectF(0, 0, 300, 100), island)
    p.end()


def test_store_isolated(tmp_path):
    assert store.DIR_OVERRIDE is not None


def test_six_tasks_add_row_still_clickable(island, monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    island.todo.tasks = [Task(False, None, f"t{i}") for i in range(6)]
    img = QImage(400, 200, QImage.Format_ARGB32)
    p = QPainter(img)
    island.todo_page.draw(p, QRectF(0, 0, 400, 200), island)
    p.end()
    hits = island.todo_page.hits
    assert len(hits) == 5 and [h[2] for h in hits] == [0, 1, 2, 3, 6]
    called = []
    monkeypatch.setattr(todo.QInputDialog, "getText", staticmethod(lambda *a: (called.append(1) or "new", True)))
    assert island.todo_page.click(hits[-1][0].center(), Qt.LeftButton, island)
    assert called and island.todo.tasks[-1].text == "new"
