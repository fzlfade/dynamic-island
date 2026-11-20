from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl

from island import shelf, store


def _mime(urls=(), text=None):
    m = QMimeData()
    if urls:
        m.setUrls([QUrl.fromLocalFile(str(u)) if isinstance(u, Path) else QUrl(u) for u in urls])
    if text is not None:
        m.setText(text)
    return m


def test_file_urls_are_referenced_in_place(qapp, tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.png"
    a.write_text("x"), b.write_text("y")
    items = shelf.items_from_mime(_mime(urls=[a, b]), tmp_path / "store")
    assert [(i.path, i.kind) for i in items] == [(a, "file"), (b, "file")]


def test_text_is_saved_to_a_txt_file(qapp, tmp_path):
    [item] = shelf.items_from_mime(_mime(text="hello"), tmp_path)
    assert item.kind == "text" and item.path.suffix == ".txt" and item.path.read_text(encoding="utf-8") == "hello"


def test_link_text_is_saved_as_url_shortcut(qapp, tmp_path):
    [item] = shelf.items_from_mime(_mime(text="https://x.dev"), tmp_path)
    assert item.kind == "url" and item.path.suffix == ".url"
    assert "URL=https://x.dev" in item.path.read_text(encoding="utf-8")


def test_browser_link_drag_becomes_url_item(qapp, tmp_path):
    [item] = shelf.items_from_mime(_mime(urls=["https://x.dev/page"], text="https://x.dev/page"), tmp_path)
    assert item.kind == "url" and "URL=https://x.dev/page" in item.path.read_text(encoding="utf-8")


def test_empty_drop_gives_nothing(qapp, tmp_path):
    assert shelf.items_from_mime(_mime(text="   "), tmp_path) == []


def test_load_drops_deleted_files(qapp, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("x"), b.write_text("y")
    shelf.save([shelf.ShelfItem(a, "file"), shelf.ShelfItem(b, "file")])
    b.unlink()
    assert shelf.load() == [shelf.ShelfItem(a, "file")]


def test_right_click_removes_from_shelf_not_disk(island, tmp_path):
    a = tmp_path / "keep.txt"
    a.write_text("x")
    page = island.shelf_page
    page.items = [shelf.ShelfItem(a, "file")]
    island._set_expand(1.0)
    island.page = island.pages.index(page)
    island.grab()
    page.click(page.hits[0][0].center(), Qt.RightButton, island)
    assert page.items == [] and shelf.load() == [] and a.exists()


def test_drop_adds_items_and_opens_shelf(island, tmp_path):
    a = tmp_path / "a.pdf"
    a.write_text("x")
    island.drop_mime(_mime(urls=[a]))
    assert island.shelf_page.items[0].path == a
    assert island.pages[island.page] is island.shelf_page
    assert shelf.load()[0].path == a


def test_shelf_clear_setting_empties_at_startup(qapp, fake_media, tmp_path):
    from island import app
    a = tmp_path / "a.txt"
    a.write_text("x")
    shelf.save([shelf.ShelfItem(a, "file")])
    store.save_kv("settings.txt", {"shelf_clear": "1"})
    isl = app.Island(fake_media)
    try:
        assert isl.shelf_page.items == [] and shelf.load() == []
    finally:
        isl._weather_thread.join(5)
        isl.close()
