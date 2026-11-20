# Nusa Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Dynamic Island app up to Nusa's remaining features: Wi-Fi and audio-device popups, Pomodoro, to-do, water, calendar, weather, prayer times, file shelf, notifications, screen OCR and an Ask box.

**Architecture:** Split the single `dynamic_island.py` into an `island/` package (one module per feature) and add two shared mechanisms. First, expanded *pages* that the scroll wheel switches between (Media, Today, Focus, Shelf, Ask). Second, a *notify queue* that holds timed reminders until the island is visible and free. Each feature is a pure-logic core with tests, plus a thin Windows/Qt binding verified live.

**Tech Stack:** Python 3.11, PySide6 6.10.1, pywinrt (`winrt-*` 4.x), ctypes Win32/COM, `tzdata`, `anthropic` SDK, pytest 9.

**Spec:** `NUSA_REVERSE_ENGINEERING.md` (sections 1-6). Nusa's own setting keys and popup texts quoted there are the source for the names and copy below.

## Global Constraints

- Windows 10 1809+ / 11, Python 3.11 (`C:\laragon\bin\python\python311\python.exe`), run from the project root.
- New dependencies allowed: `winrt-Windows.*` packages at the installed pywinrt line (`4!10.0.28000.2957`), `tzdata`, `anthropic`. Nothing else; standard library first.
- Island window keeps `WS_EX_NOACTIVATE | TOPMOST | TOOLWINDOW`. Anything that needs typing opens its own activating dialog (`QInputDialog`), never focuses the island.
- Data files live in `%APPDATA%\DynamicIsland\` (`settings.txt`, `tasks.txt`, `water.txt`, `shelf.txt`) as Nusa-style `key=value` or one-record-per-line text. Stored shelf text/URLs live in `%LOCALAPPDATA%\DynamicIsland\Shelf\`.
- There is no settings UI. The tray menu has "Open settings file" and "Quit", and every value has a default in its feature module.
- HTTP: stdlib `urllib`, 10 s timeout, `User-Agent: DynamicIsland/0.1`, never any personal data in URLs or headers. Network failures log to stderr and keep the last good data; they never crash or pop up.
- Every HUD/popup goes through `Island._show_hud` (instant, replaces) or `Island.notify` (queued reminder). Popup copy is the exact strings given in each task.
- Tests: `python -m pytest -q` must pass after every task. Nothing in the test suite may change system state (volume, brightness, layouts) without restoring it in the same test.
- Commits: one per task, message `feat(<module>): …`, ending with the repository's Co-Authored-By trailer.

## Review Focus

1. **A reminder fires while a fullscreen game hides the island.** The user expects to see it when they leave the game, not lose it. Reminders up to 10 minutes old are delivered on show (Task 3 test `test_notify_queues_while_hidden`).
2. **Two reminders fall due at once** (prayer time = to-do time). Both show, one after the other (Task 3 test `test_notify_serializes`).
3. **The PC sleeps overnight or the clock crosses midnight.** On wake, one catch-up reminder per feature, not a burst, and no crash on `prev > now` (Task 7 test `test_due_across_midnight_and_gap`).
4. **A hand-edited data file has a bad line** (`focus=abc`, garbage in `tasks.txt`). Defaults or skips apply, and the file is not wiped (Task 2 `test_bad_values_fall_back`, Task 7 `test_bad_task_lines_skipped`).
5. **Offline at startup, or the calendar/weather server is down.** Last cached data is shown, with no popup and no exception (Task 9 `test_calendar_fetch_failure_keeps_events`, Task 10 `test_weather_failure_keeps_last`).

---

## File Structure

```
dynamic_island.py          launcher only: from island.app import main; main()
island/__init__.py
island/app.py              Island widget, HUD/popup drawing, notify queue, tray, main()
island/media.py            Media session thread, parse_lrc, line_at, fetch_lyrics
island/system.py           COM helpers, Volume, keyboard hook, brightness, battery, language, fullscreen
island/store.py            data_dir, load_kv/save_kv, load_lines/save_lines
island/pages.py            Page base, MediaPage, TodayPage
island/network.py          Wi-Fi state + popup rule
island/focus.py            Pomodoro + FocusPage
island/todo.py             tasks + reminders
island/water.py            water reminder
island/ics.py              iCal parsing / recurrence (not "calendar": stdlib clash)
island/weather.py          location + MET Norway
island/prayer.py           prayer-time math + reminders
island/shelf.py            drop/drag shelf + ShelfPage
island/notifications.py    toast mirror (gated by a spike)
island/ocr.py              hotkey, region picker, Windows OCR
island/ask.py              Ask page + Claude streaming
tests/conftest.py          qapp, island, FakeMedia fixtures
tests/test_<module>.py     one per module
requirements.txt, .gitignore
```

Rule for testability: `app.py` and the feature modules call `system.foo()` / `store.foo()` through the module (`from island import system`), never `from island.system import foo`, so tests can `monkeypatch.setattr(island.system, "foo", fake)`.

---

## Phase A: Foundation

### Task 1: Package split, git, pytest

**Files:**
- Create: `island/__init__.py`, `island/app.py`, `island/media.py`, `island/system.py`, `tests/conftest.py`, `tests/test_app.py`, `tests/test_media.py`, `tests/test_system.py`, `requirements.txt`, `.gitignore`
- Modify: `dynamic_island.py` (becomes a 2-line launcher)
- Delete: `test_island.py`, `shot_*.png`

**Interfaces:**
- Produces: `island.app.Island(media)`, `island.app.main()`, `island.media.{Media, parse_lrc, line_at, fetch_lyrics}`, `island.system.{Volume, install_keys, install_brightness, battery_status, battery_popup, foreground_layout, language_name, fullscreen_app_running, VK_CAPITAL, GUID_VIDEO_BRIGHTNESS}`. Fixtures `qapp`, `fake_media`, `island` (fresh `Island(FakeMedia())`, closed after the test).

- [ ] **Step 1:** `git init`. Write `.gitignore` (`__pycache__/`, `*.png`, `.pytest_cache/`) and `requirements.txt` pinning what is installed now: `PySide6==6.10.1`, `winrt-runtime==4.2.0`, `winrt-Windows.Media.Control`, `winrt-Windows.Foundation`, `winrt-Windows.Foundation.Collections`, `winrt-Windows.Storage.Streams` (each `==4!10.0.28000.2957`), `typing_extensions`. Commit the current files as the baseline.
- [ ] **Step 2:** Port every assertion block of `test_island.py` into pytest functions grouped by module (`test_media.py`: lrc parse/line_at/artist cleanup; `test_system.py`: battery rules, volume fake/roundtrip, language names; `test_app.py`: rendering, HUD expiry, brightness, caps, language, battery HUD). Screenshots go to `tmp_path`. `conftest.py` sets `QT_QPA_PLATFORM=offscreen` via `setdefault`.
- [ ] **Step 3:** Run `python -m pytest -q`. Expected: import errors (package doesn't exist yet).
- [ ] **Step 4:** Move code by the File Structure map, with no behaviour change. Right-click still quits until Task 2.
- [ ] **Step 5:** Run `python -m pytest -q`. Expected: all pass. Launch `python dynamic_island.py`. Expected: a window of class `Qt6101QWindowToolSaveBits` at top centre, as before.
- [ ] **Step 6:** Delete `test_island.py` and `shot_*.png`, then commit `refactor: split into island package with pytest suite`.

### Task 2: Settings store and tray icon

**Files:**
- Create: `island/store.py`, `tests/test_store.py`
- Modify: `island/app.py` (tray; right-click no longer quits)

**Interfaces:**
- Produces:
  - `store.data_dir() -> Path`: `%APPDATA%\DynamicIsland`, created on first call.
  - `store.load_kv(name: str) -> dict[str, str]` and `store.save_kv(name: str, values: dict) -> None`: atomic, temp file + `os.replace`.
  - `store.load_lines(name) -> list[str]` and `store.save_lines(name, lines)`.
  - `store.get_int(values: dict, key: str, default: int) -> int`.
  - `store.DIR_OVERRIDE: Path | None`: tests point it at `tmp_path`.
  - `app.set_autostart(on: bool, key_name: str = "DynamicIsland") -> None` and `app.autostart_enabled(key_name="DynamicIsland") -> bool`: write the `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value `"<pythonw.exe>" "<abs path>\dynamic_island.py"` (Nusa: `StartupTask`).

- [ ] **Step 1: Write the failing tests** in `tests/test_store.py`:
  - `test_roundtrip`: `save_kv("s.txt", {"a": "1", "url": "x=y"})` then `load_kv` returns the same dict. Values split on the first `=` only.
  - `test_missing_file_is_empty`: `load_kv("nope.txt") == {}`.
  - `test_bad_values_fall_back`: a file with lines `focus=abc`, `garbage`, `short_break=7`. `get_int(v, "focus", 25) == 25`, `get_int(v, "short_break", 5) == 7`, and the original file bytes are unchanged after loading.
  - `test_atomic_write_leaves_no_temp`: after `save_kv`, the directory contains only `s.txt`.
  - `test_autostart_roundtrip` (in `tests/test_app.py`, with `key_name="DynamicIslandTest"`): `set_autostart(True)` makes `autostart_enabled()` True and the value ends with `dynamic_island.py"`; `set_autostart(False)` makes it False. The test deletes the value in a `finally`.
- [ ] **Step 2:** `python -m pytest tests/test_store.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `island/store.py` per the Interfaces. Reads use `encoding="utf-8"` with `errors="replace"`.
- [ ] **Step 4:** Add a `QSystemTrayIcon` in `main()`. Icon: a 16×16 black rounded pill drawn on a `QPixmap`. Menu: "Open settings file" (`os.startfile` on `settings.txt`, created empty if missing), "Start with Windows" (checkable, bound to `set_autostart`), "About" (a message box with the LRCLIB and MET Norway attributions from the spec), "Quit". Remove the right-click quit from `mouseReleaseEvent`.
- [ ] **Step 5:** `python -m pytest -q`. Expected: pass. Launch the app. Expected: tray icon present; Quit exits; right-clicking the island does nothing.
- [ ] **Step 6:** Commit `feat(store): settings files and tray menu`.

### Task 3: Pages and notify queue

**Files:**
- Create: `island/pages.py`, `tests/test_pages.py`
- Modify: `island/app.py`, `tests/test_app.py`

**Interfaces:**
- Produces:
  - `pages.Page`. Attributes: `title: str`. Methods:
    - `draw(p: QPainter, r: QRectF, island) -> None`
    - `click(pos: QPointF, button: Qt.MouseButton, island) -> bool`: default `False`
    - `animating() -> bool`: default `False`
    - `compact_text() -> str | None`: default `None`
  - `pages.MediaPage(Page)`: today's expanded player, moved here.
  - `pages.TodayPage(Page)` with `add_section(rows: Callable[[], list[tuple[str, str]]]) -> None`. It draws each section's rows as left text and right text, up to 5 rows in total, and shows "Nothing today" when all sections are empty.
  - `Island.add_page(page) -> None`, `Island.page: int`.
  - `Island.notify(hud: tuple, seconds: float = 4.0) -> None`: queued.
  - Constants: `EXPANDED = (400.0, 150.0)`, `WIN_H = 170`.

- [ ] **Step 1: Write the failing tests:**
  - `test_wheel_switches_pages`: with pages [Media, Today], expand to 1.0. A wheel event with `angleDelta().y() = -120` makes `island.page == 1`; again wraps to `0`.
  - `test_page_dots_drawn`: grab at expand 1.0. The pixel at the second dot centre `(WIN_W/2 + 5, EXPANDED[1] - 8)` is non-black.
  - `test_compact_text_wins`: a stub page returning `"● 24:13"` from `compact_text()`. With media playing, the collapsed draw path uses that text (`island._compact_label() == "● 24:13"`).
  - `test_notify_queues_while_hidden`: `island.setVisible(False)`, then `notify(("popup", "x", "Due", "now"))`. `_hud_active()` is False. `setVisible(True)` + `_drain()` makes `island.hud[2] == "Due"`.
  - `test_notify_drops_stale`: monkeypatch `island.app.time.monotonic` so that 11 minutes pass between notify and show. Nothing shows.
  - `test_notify_serializes`: two notifies while visible. The first shows; after `hud_until` passes and `_drain()`, the second shows.
- [ ] **Step 2:** `python -m pytest tests/test_pages.py tests/test_app.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement the pages and the queue (`collections.deque` of `(hud, seconds, created)`, drained by `hud_timer` and by `_check_fullscreen` when visibility turns on, 600 s max age). Implement `_compact_label()`: the first page `compact_text()` that isn't `None`, else the lyric line. Wheel only switches pages while `expand > 0.5`. The frame timer runs while media plays or any page is `animating()`. Add a generic popup kind `("popup", glyph: str, title: str, subtitle: str)` drawn like the battery popup (glyph instead of the battery icon), size `BATTERY_POPUP`.
- [ ] **Step 4:** `python -m pytest -q`. Expected: pass. Launch, hover, scroll. Expected: page dots switch between Media and an empty Today.
- [ ] **Step 5:** Commit `feat(pages): expanded pages and queued reminders`.

---

## Phase B: Popups

### Task 4: Wi-Fi popup

**Files:** Create `island/network.py`, `tests/test_network.py`. Modify `island/app.py`, `requirements.txt` (`winrt-Windows.Networking.Connectivity`).

**Interfaces:**
- Consumes: `Island._show_hud`, generic `"popup"` kind (Task 3).
- Produces: `network.network_state() -> tuple[bool, str | None]` (has internet, profile name or `None`) and `network.network_popup(prev, cur) -> tuple[str, str] | None`.

- [ ] **Step 1: Write the failing tests:**
  - `network_popup(None, (True, "Home"))` is `None`.
  - `((False, None), (True, "Home"))` returns `("Connected", "Home")`.
  - `((True, "Home"), (False, None))` returns `("Disconnected", "No internet")`.
  - `((True, "Home"), (True, "Office"))` returns `("Connected", "Office")`.
  - Unchanged state returns `None`.
  - `network_state()` live returns a `bool` and a `str` or `None`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with `NetworkInformation.get_internet_connection_profile()`. Connected means `get_network_connectivity_level() == NetworkConnectivityLevel.INTERNET_ACCESS`; the name is `profile.profile_name`. Poll from `_check_fullscreen` (1 s). Glyph `\uE701` (Wi-Fi), white when connected, grey when not.
- [ ] **Step 4:** Tests pass. Live check: toggle Wi-Fi off and on from the taskbar. Expected: both popups.
- [ ] **Step 5:** Commit `feat(network): wifi popup`.

### Task 5: Audio output device popup (headsets)

**Files:** Modify `island/system.py`, `island/app.py`, `tests/test_system.py`.

**Interfaces:**
- Produces:
  - `Volume.default_device() -> tuple[str, str]`: endpoint id and friendly name.
  - `system.audio_popup(prev: tuple | None, cur: tuple) -> tuple[str, str] | None`.

- [ ] **Step 1: Write the failing tests:**
  - `audio_popup(None, ("a", "Speakers"))` is `None`.
  - `(("a", "Speakers"), ("b", "Buds Pro"))` returns `("Audio output", "Buds Pro")`.
  - Same id returns `None`.
  - Live `Volume().default_device()` returns two non-empty strings.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement through the existing `_com` helper:
  - `IMMDevice::GetId` (slot 5; free with `CoTaskMemFree`).
  - `IMMDevice::OpenPropertyStore(STGM_READ=0)` (slot 4) → `IPropertyStore::GetValue` (slot 5) with `PKEY_Device_FriendlyName` = `{A45C254E-DF1C-4EFD-8020-67D146A850E0}, 14`. Read the `VT_LPWSTR` (31) string at PROPVARIANT offset 8, then `PropVariantClear`.
  - Poll in `_check_fullscreen`. Glyph `\uE7F6` (headphone).
- [ ] **Step 4:** Tests pass. Live check: connect or switch output device. Expected: popup with its name.
- [ ] **Step 5:** Commit `feat(system): audio output popup`.

---

## Phase C: Productivity

### Task 6: Pomodoro (Focus page)

**Files:** Create `island/focus.py`, `tests/test_focus.py`. Modify `island/app.py`.

**Interfaces:**
- Consumes: `Page`, `Island.notify`, `store.load_kv("settings.txt")`, `store.get_int`.
- Produces:
  - `focus.Pomodoro(focus_s=1500, short_s=300, long_s=900, rounds=4)` with:
    - `.phase`: one of `"idle" | "focus" | "short_break" | "long_break"`
    - `start(now)`, `stop()`
    - `remaining(now) -> float`
    - `tick(now) -> str | None`: the new phase when one ends
  - `focus.FocusPage(Page)`.
  - Settings keys (minutes): `focus=25`, `short_break=5`, `long_break=15`.

- [ ] **Step 1: Write the failing tests:**
  - `start(0)` gives phase `"focus"` and `remaining(60) == 1440`.
  - `tick(1500) == "short_break"`.
  - After 4 focus rounds the break is `"long_break"`; when it ends, `tick` returns `"idle"`.
  - `stop()` resets to `"idle"` with round 0.
  - `tick` called late (now far past several boundaries) advances one phase per call, not several.
  - `FocusPage.compact_text()` is `"● 24:13"` while running, `None` when idle.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the state machine and the Focus page:
  - The page shows a big `mm:ss`, the phase name, and a Start/Stop button.
  - Transitions: focus→break auto-continues, break→focus auto-continues, long break→idle.
  - Phase-end popups go through `notify`, glyph `\uE916` (stopwatch):
    - focus ends → `("Focus done", "Take a 5 min break")`, with the minutes from settings
    - break ends → `("Break over", "Back to focus")`
    - cycle ends → `("Cycle complete", "Nice work")`
  - Play `winsound.MessageBeep()` at each popup.
  - `FocusPage.animating()` is True while running.
- [ ] **Step 4:** Tests pass. Live check: set `focus=1` and `short_break=1` in settings, then start. Expected: the collapsed timer counts down and the popup appears at 0.
- [ ] **Step 5:** Commit `feat(focus): pomodoro`.

### Task 7: To-do with timed reminders

**Files:** Create `island/todo.py`, `tests/test_todo.py`. Modify `island/app.py`.

**Interfaces:**
- Consumes: `TodayPage.add_section`, `Island.notify`, `store.load_lines/save_lines("tasks.txt")`.
- Produces:
  - `todo.Task(done: bool, at: int | None, text: str)`, where `at` is minutes after midnight.
  - `todo.parse_task(s) -> Task`: `"09:30 Call mom"` → `Task(False, 570, "Call mom")`; `"Buy milk"` → `Task(False, None, "Buy milk")`.
  - `todo.load_tasks() -> list[Task]` and `todo.save_tasks(tasks)`. Line format: `done|at|text`, with `at=-1` for untimed.
  - `todo.due(tasks, prev_min: int, now_min: int) -> list[Task]`: undone timed tasks with `at` in `(prev_min, now_min]`. The window wraps past midnight when `prev_min > now_min`. If the window is longer than 120 min (sleep, clock jump), return only the latest such task.
  - `todo.ordered(tasks) -> list[Task]`: timed tasks by time first, then untimed, done tasks last (Nusa `todo_ordered`).

- [ ] **Step 1: Write the failing tests:**
  - `parse_task` cases above, plus `"25:00 x"`, which stays untimed with the text `"25:00 x"`.
  - Save/load roundtrip, including a `|` inside the text.
  - `test_bad_task_lines_skipped`: the line `garbage` is skipped and the valid lines load.
  - `due(tasks, 569, 570)` returns the 09:30 task; done tasks are never due.
  - `test_due_across_midnight_and_gap`:
    - `due(tasks, 1430, 5)` (across midnight) returns tasks at 1435 and at 3, at most one per task.
    - `due(tasks, 300, 900)` after a sleep gap returns only the latest task in the window.
  - `ordered` puts 08:00 before 09:30 before untimed before done.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Today section rows: `(text, "09:30" or "")`.
  - Clicking a row toggles done.
  - Right-click removes the row.
  - A `+` row opens `QInputDialog.getText(None, "New task", "e.g. 09:30 Call mom")`.
  - Check once a minute (`QTimer` 60 s, plus on wake when the gap is > 120 s). Reminders go through `notify(("popup", "\uE73E", "To-do", text))`.
- [ ] **Step 4:** Tests pass. Live check: add a task due 1 minute from now. Expected: the popup fires.
- [ ] **Step 5:** Commit `feat(todo): tasks and reminders`.

### Task 8: Water reminder

**Files:** Create `island/water.py`, `tests/test_water.py`. Modify `island/app.py`.

**Interfaces:**
- Consumes: `notify`, `TodayPage.add_section`, `store.load_kv/save_kv("water.txt")`.
- Produces: `water.Water(values: dict)` with:
  - `.taken: int`
  - `due(now: datetime) -> bool`
  - `drink(now) -> tuple[str, str] | None`: the refill popup if one is due
  - `to_kv() -> dict`

  Keys and defaults (Nusa's `water.txt`): `bottle=500`, `goal=1500`, `start=480`, `end=1440` (minutes), `glass=250`, `every=60`, `day=YYYYMMDD`, `taken=0`, `last=<minute>`.

- [ ] **Step 1: Write the failing tests:**
  - At 09:00 with `last` at 08:00: `due` is True. At 08:30: False.
  - Before `start` or after `end`: False.
  - With `taken >= goal`: False.
  - `drink` adds `glass`. Crossing a multiple of `bottle` (250 → 500) returns `("Time to Refill", "Your bottle is probably empty")`.
  - A new `day` resets `taken` to 0.
  - Bad values fall back to the defaults.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
  - Due check once a minute → `notify(("popup", "\uE9CA", "Time to Drink", f"{taken} / {goal} ml"))`, glyph = drop.
  - Clicking the island while this popup shows calls `drink`.
  - Today row: `("Water", "500 / 1500 ml")`.
  - Save after every change.
- [ ] **Step 4:** Tests pass. Live check: set `every=1`. Expected: a popup within a minute; clicking it logs 250 ml.
- [ ] **Step 5:** Commit `feat(water): water reminder`.

### Task 9: Calendar from an iCal link

**Files:** Create `island/ics.py`, `tests/test_ics.py`, `tests/data/sample.ics`. Modify `island/app.py`, `requirements.txt` (`tzdata`).

**Interfaces:**
- Consumes: `TodayPage.add_section`, `notify`, settings key `calendar_url` (Google Calendar → Settings → "Secret address in iCal format").
- Produces:
  - `ics.Event(start: datetime, end: datetime, summary: str, all_day: bool)`: aware datetimes.
  - `ics.parse_ics(text: str) -> list[ics.Series]`: one per VEVENT, keeping RRULE/EXDATE.
  - `ics.events_on(series: list, day: date, tz) -> list[Event]`: sorted, recurrences expanded.
  - `ics.Calendar(url)` with:
    - `fetch_once() -> None`: synchronous; keeps the old `.series` on any `OSError`/`ValueError`
    - `refresh() -> None`: runs `fetch_once` in a daemon thread
    - `.series`

- [ ] **Step 1: Write the failing tests** against `sample.ics`, which contains the following events:
  - a UTC `Z` event
  - a `TZID=Asia/Jakarta` event
  - a `TZID=America/New_York` event
  - an all-day `VALUE=DATE` event
  - a folded long SUMMARY line
  - `RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4`
  - `RRULE:FREQ=DAILY;INTERVAL=2;UNTIL=…`
  - `FREQ=MONTHLY` and `FREQ=YEARLY` events
  - an `EXDATE` that removes one weekly occurrence

  Assertions:
  - Exact start times on chosen dates, in local `Asia/Jakarta`.
  - The weekly series stops after 4 occurrences.
  - The EXDATE day has no occurrence.
  - The folded summary is joined.
  - `test_calendar_fetch_failure_keeps_events`: monkeypatch `urllib.request.urlopen` to return `sample.ics`, then to raise `URLError` on the second `fetch_once()`. `.series` is unchanged.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with `zoneinfo` (+ `tzdata`).
  - Unfold continuation lines that start with a space or tab.
  - Support exactly the RRULE parts `FREQ`, `INTERVAL`, `COUNT`, `UNTIL` and `BYDAY` (weekly), as the spec lists. Ignore other parts and treat such events as single.
  - Refresh every 15 min.
  - Today rows: `(summary, "13:00")`, or `"All day"`.
  - Reminder 10 min before start: `notify(("popup", "\uE787", f"In 10 min", summary))`.
- [ ] **Step 4:** Tests pass. Live check: paste your iCal link into `calendar_url`. Expected: today's events on the Today page.
- [ ] **Step 5:** Commit `feat(ics): calendar on Today page`.

---

## Phase D: Location features

### Task 10: Location and weather

**Files:** Create `island/weather.py`, `tests/test_weather.py`, `tests/data/met.json`. Modify `island/app.py`, `requirements.txt` (`winrt-Windows.Devices.Geolocation`).

**Interfaces:**
- Produces:
  - `weather.location(values: dict) -> tuple[float, float, str]`: settings `lat`/`lon`/`place` if set; otherwise one Windows Geolocator read, saved back; otherwise Jakarta `(-6.2088, 106.8456, "Jakarta")`.
  - `weather.parse_met(data: dict) -> tuple[float, str]`: °C and description.
  - `weather.Weather(lat, lon)` with:
    - `fetch_once()`: synchronous; keeps `.now` on failure
    - `refresh()`: thread; honours the `Expires` response header, minimum 30 min between fetches
    - `.now: tuple[float, str] | None`

- [ ] **Step 1: Write the failing tests:**
  - `parse_met` on the fixture (a trimmed real MET compact response) returns `(27.3, "Partly cloudy")`.
  - Symbol mapping drops the `_day`/`_night` suffix, with these words: `clearsky` Clear, `fair` Mostly clear, `partlycloudy` Partly cloudy, `cloudy` Cloudy, `fog` Fog, `lightrain` Light rain, `rain` Rain, `heavyrain` Heavy rain, `sleet` Sleet, `snow` Snow, any `*thunder*` Thunderstorm, `*showers` same as its base word.
  - The URL rounds lat/lon to 4 decimals (MET requirement).
  - `test_weather_failure_keeps_last`: one good `fetch_once()` from the fixture, then `urlopen` raises on the next → `.now` is unchanged.
  - `location({})` with Geolocator monkeypatched to raise → Jakarta.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Endpoint: `https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=…&lon=…`. Today top row: `(place, "27° Partly cloudy")`.
- [ ] **Step 4:** Tests pass. Live check: the Today page shows the current temperature.
- [ ] **Step 5:** Commit `feat(weather): MET Norway weather`.

### Task 11: Prayer times

**Files:** Create `island/prayer.py`, `tests/test_prayer.py`. Modify `island/app.py`.

**Interfaces:**
- Consumes: `weather.location`, `notify`, `TodayPage.add_section`, the Media page's media `send("toggle")`.
- Produces:
  - `prayer.METHODS: dict[str, tuple[float, float | str]]` (fajr angle, isha angle or `"+90"` minutes):
    - `"Kemenag RI": (20, 18)`
    - `"JAKIM": (20, 18)`
    - `"MUIS": (20, 18)`
    - `"Muslim World League": (18, 17)`
    - `"Umm al-Qura": (18.5, "+90")`
  - `prayer.times(day: date, lat, lon, tz_hours: float, method: str, asr_factor: int = 1) -> dict[str, time]`, keyed `Subuh, Dzuhur, Ashar, Maghrib, Isya`.
  - Settings: `prayer=0/1` (off by default), `prayer_method="Kemenag RI"`, `prayer_early=0` (minutes), `prayer_pause_media=0`, `prayer_adj_<name>=0` (minutes per prayer).

- [ ] **Step 1: Get reference times.** Look up Kemenag's published schedule for DKI Jakarta, 21 Nov 2026 (bimasislam.kemenag.go.id, Jadwal Sholat) and put the five times in `test_kemenag_jakarta` with a ±2 min tolerance. Add `test_umm_al_qura_isha_is_maghrib_plus_90` and `test_hanafi_asr_later_than_shafii`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement `times()`.** It is the standard sun-position method; this is the algorithm:
  ```
  d = julian_day(day) - 2451545.0
  g = 357.529 + 0.98560028 d;  q = 280.459 + 0.98564736 d
  L = q + 1.915 sin g + 0.020 sin 2g;  e = 23.439 - 0.00000036 d
  RA = atan2(cos e sin L, cos L) / 15;  decl = asin(sin e sin L)
  EqT = q/15 - fixhour(RA)
  dhuhr = 12 + tz - lon/15 - EqT
  T(a) = acos((-sin a - sin decl sin lat) / (cos decl cos lat)) / 15     (degrees in, hours out)
  sunrise/maghrib = dhuhr ∓ T(0.833);  subuh = dhuhr - T(fajr);  isha = dhuhr + T(isha) or maghrib + 90 min
  asr = dhuhr + T(-acot(asr_factor + tan|lat - decl|))
  ```
  Kemenag adds a +2 min ihtiyat to every time; apply it only for that method. Then add `prayer_adj_*`.
  - At each time (minus `prayer_early`): `notify(("popup", "\uE706", name, "12:03"))`. If `prayer_pause_media=1` and media is playing, pause it.
  - Today row: `("Next prayer", "Ashar 15:06")`.
- [ ] **Step 4:** Tests pass. Live check: set `prayer=1`. Expected: the Today row matches your usual schedule.
- [ ] **Step 5:** Commit `feat(prayer): prayer times`.

---

## Phase E: System integrations

### Task 12: File shelf

**Files:** Create `island/shelf.py`, `tests/test_shelf.py`. Modify `island/app.py`.

**Interfaces:**
- Produces:
  - `shelf.ShelfItem(path: Path, kind: str)`, where `kind` is `"file" | "text" | "url"`.
  - `shelf.items_from_mime(mime: QMimeData, store_dir: Path) -> list[ShelfItem]`:
    - local file URLs are referenced in place
    - text is written to `<store_dir>/<timestamp>.txt`
    - http(s) URLs are written as `.url` files: `[InternetShortcut]\nURL=…`
  - `shelf.load() / save(items)` via `shelf.txt`, dropping paths that no longer exist.
  - `shelf.ShelfPage(Page)`.

- [ ] **Step 1: Write the failing tests:**
  - A mime with 2 file URLs gives 2 `"file"` items with the same paths.
  - A mime with text `"hello"` gives 1 `"text"` item whose file contains `hello`.
  - A mime with text `"https://x.dev"` gives 1 `"url"` item whose file contains `URL=https://x.dev`.
  - `load()` drops a deleted file.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
  - `setAcceptDrops(True)`. `dragEnterEvent` accepts urls or text, expands, and switches to the Shelf page.
  - The Shelf page shows up to 6 chips (icon from `QFileIconProvider`, elided name).
  - Dragging a chip out starts a `QDrag` with `setUrls([path])`.
  - Right-click removes the item from the shelf only, never the file.
  - `shelf_clear=1` empties the shelf at startup.
- [ ] **Step 4:** Tests pass. Live check: drag a file from Explorer onto the notch, then drag it into another folder. Expected: it copies.
- [ ] **Step 5:** Commit `feat(shelf): file shelf`.

### Task 13: Notification pill (spike-gated)

**Files:** Create `island/notifications.py`, `tests/test_notifications.py`. Modify `requirements.txt` (`winrt-Windows.UI.Notifications`, `winrt-Windows.UI.Notifications.Management`).

**Interfaces:**
- Produces: `notifications.Listener` with:
  - `poll() -> list[tuple[str, str, str]]`: (app name, title, body), new since the last poll
  - `available: bool`

- [ ] **Step 1: Spike.** From plain Python, call `UserNotificationListener.current.request_access_async()` and print the status.
  - If it raises or does not return `ALLOWED`: **stop this task**, set `available=False` permanently, and record in `NUSA_REVERSE_ENGINEERING.md` that the API needs package identity. Nusa gets it from its MSIX manifest's `userNotificationListener` capability.
  - Otherwise continue.
- [ ] **Step 2:** Write the failing test: `Listener` with a fake `get_notifications_async` returning ids 1 and 2, then 1, 2 and 3. The second `poll()` returns only notification 3.
- [ ] **Step 3:** Implement. Poll every 2 s. Read text from the `KnownNotificationBindings.toast_generic` binding. Show `("popup", "\uEA8F", app, title)` via `_show_hud`.
- [ ] **Step 4:** Tests pass. Live check: send yourself a message in any app. Expected: the pill shows it.
- [ ] **Step 5:** Commit `feat(notifications): notification pill`, or `docs: notification listener needs package identity` if the spike stopped the task.

### Task 14: Screen OCR (Ctrl+Alt+T)

**Files:** Create `island/ocr.py`, `tests/test_ocr.py`. Modify `island/app.py`, `requirements.txt` (`winrt-Windows.Media.Ocr`, `winrt-Windows.Graphics.Imaging`, `winrt-Windows.Globalization`).

**Interfaces:**
- Produces:
  - `ocr.ocr_png(png: bytes) -> str`: blocking; run it on the media asyncio loop or a worker thread.
  - `ocr.RegionPicker(QWidget)`: emits `picked(QRect)` or `cancelled()`.
  - Hotkey id `1` on the island HWND.

- [ ] **Step 1: Write the failing tests:**
  - Render `"HELLO 2026"` at 48 px black on white into a `QImage`, save it as PNG bytes, and check that `"HELLO" in ocr_png(png)`.
  - A blank image returns `""`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
  - **Recognition:** PNG bytes → `InMemoryRandomAccessStream` via `DataWriter` → `BitmapDecoder.create_async` → `get_software_bitmap_async` → `OcrEngine.try_create_from_user_profile_languages().recognize_async(bmp)` → `.text`.
  - **Hotkey:** `RegisterHotKey(hwnd, 1, MOD_CONTROL|MOD_ALT|MOD_NOREPEAT, ord('T'))`; handle `WM_HOTKEY` (0x312) in `nativeEvent`.
  - **Picker:** a fullscreen, frameless, translucent window with a dim overlay, drag to select, Esc to cancel. Grab with `QScreen.grabWindow(0, *rect)`.
  - **Size limit:** if width or height > `OcrEngine.max_image_dimension`, show `("popup", "\uE8C8", "That area is too large", "Select a smaller part")` (Nusa's copy).
  - **Result:** copy the text to the clipboard, then show `("popup", "\uE8C8", "Copied text", f"{n} characters")`, or `"No text found"`.
- [ ] **Step 4:** Tests pass. Live check: press Ctrl+Alt+T and select a paragraph. Expected: the text pastes.
- [ ] **Step 5:** Commit `feat(ocr): copy text from screen`.

### Task 15: Ask Claude (Ctrl+Alt+Space)

**Files:** Create `island/ask.py`, `tests/test_ask.py`. Modify `island/app.py`, `requirements.txt` (`anthropic`).

**Interfaces:**
- Consumes: `Page`, hotkey plumbing from Task 14 (hotkey id `2`, `ord(' ')`).
- Produces:
  - `ask.AskPage(Page)` with `.text: str` and `.state`, one of `"idle" | "streaming" | "done" | "error"`.
  - `ask.Asker(QObject)` with signals `chunk(str)`, `finished(str)`, `failed(str)`, and `ask(question: str, client=None)`, which runs in a worker thread. The `client` parameter lets tests inject a fake.

- [ ] **Step 1: Write the failing tests** with a fake client whose `.beta.messages.stream(**kw)` is a context manager exposing `text_stream` (yields `"Hel"`, `"lo"`) and `get_final_message()` (returns an object with `stop_reason="end_turn"`).
  - `test_streams_into_page`: the page text becomes `"Hello"`, then the state is `"done"`.
  - `test_request_shape`: the captured kwargs include:
    - `model == "claude-opus-5-5"`
    - `output_config == {"effort": "low"}`
    - `betas == ["server-side-fallback-2026-07-01"]`
    - `fallbacks == "default"`
    - `max_tokens == 64000`
    - a single user message
  - `test_refusal`: `stop_reason="refusal"` gives the state `"error"` and the text `"Claude declined this one."`
  - `test_error_messages`: the fake raises each of these, and the page shows the matching text:
    - `anthropic.AuthenticationError` → `"Set ANTHROPIC_API_KEY or run: ant auth login"`
    - `anthropic.RateLimitError` → `"Busy right now, try again shortly"`
    - `anthropic.APIConnectionError` → `"No connection"`
    - `anthropic.APIStatusError` → `"Error <status>"`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with the official SDK: `anthropic.Anthropic()` (default credential resolution: env var or `ant auth login` profile; never store a key in our files).
  ```python
  with client.beta.messages.stream(
      model="claude-opus-5-5", max_tokens=64000,
      betas=["server-side-fallback-2026-07-01"], fallbacks="default",
      output_config={"effort": "low"},
      system=ASK_SYSTEM, messages=[{"role": "user", "content": question}],
  ) as stream:
      for text in stream.text_stream: emit chunk
      final = stream.get_final_message()   # check final.stop_reason == "refusal"
  ```
  - `ASK_SYSTEM = "You answer inside a small notch at the top of a Windows desktop. Reply in at most three short sentences of plain text, no Markdown."`
  - Catch the errors most-specific-first, as in the test list.
  - The hotkey opens `QInputDialog.getText(None, "Ask", "")`, then expands the island on the Ask page.
  - The page wraps text and keeps the last lines visible. A click on the page closes it.
- [ ] **Step 4:** Tests pass (no network). Live check, only after the user confirms they're fine spending API credit: ask "what is 2+2". Expected: the answer streams in.
- [ ] **Step 5:** Commit `feat(ask): ask Claude from the notch`.

---

## Out of scope (named, not planned)

Clipboard history, translation, currency rates, moon phase, Bluetooth headset battery level, multi-monitor placement, a settings UI. Each is a separate plan if wanted.
