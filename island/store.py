"""Data files in %APPDATA%/DynamicIsland: key=value or one-record-per-line text, written atomically."""
import os
import tempfile
from pathlib import Path

DIR_OVERRIDE = None  # tests point this at tmp_path


def data_dir():
    d = DIR_OVERRIDE or Path(os.environ["APPDATA"]) / "DynamicIsland"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_lines(name):
    try:
        text = (data_dir() / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()


def save_lines(name, lines):
    d = data_dir()
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(line + "\n" for line in lines))
        os.replace(tmp, d / name)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_kv(name):
    return dict(line.split("=", 1) for line in load_lines(name) if "=" in line)


def save_kv(name, values):
    save_lines(name, [f"{k}={v}" for k, v in values.items()])


def get_int(values, key, default):
    try:
        return int(values[key])
    except (KeyError, ValueError):
        return default
