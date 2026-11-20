import pytest

from island import store


@pytest.fixture(autouse=True)
def tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DIR_OVERRIDE", tmp_path)
    return tmp_path


def test_roundtrip():
    store.save_kv("s.txt", {"a": "1", "url": "x=y"})
    assert store.load_kv("s.txt") == {"a": "1", "url": "x=y"}


def test_missing_file_is_empty():
    assert store.load_kv("nope.txt") == {}


def test_bad_values_fall_back(tmp_dir):
    f = tmp_dir / "s.txt"
    f.write_bytes(b"focus=abc\ngarbage\nshort_break=7\n")
    v = store.load_kv("s.txt")
    assert store.get_int(v, "focus", 25) == 25
    assert store.get_int(v, "short_break", 5) == 7
    assert f.read_bytes() == b"focus=abc\ngarbage\nshort_break=7\n"


def test_kv_strips_spaces(tmp_dir):
    (tmp_dir / "s.txt").write_text("focus = 30\n  name=  a b \n")
    assert store.load_kv("s.txt") == {"focus": "30", "name": "a b"}


def test_atomic_write_leaves_no_temp(tmp_dir):
    store.save_kv("s.txt", {"a": "1"})
    assert [p.name for p in tmp_dir.iterdir()] == ["s.txt"]


def test_lines_roundtrip():
    store.save_lines("l.txt", ["one", "two"])
    assert store.load_lines("l.txt") == ["one", "two"]
    assert store.load_lines("none.txt") == []
