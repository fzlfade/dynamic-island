from island import focus, store


def test_pomodoro_cycle():
    p = focus.Pomodoro()
    assert p.phase == "idle"
    p.start(0)
    assert p.phase == "focus" and p.remaining(60) == 1440
    assert p.tick(100) is None
    assert p.tick(1500) == "short_break"
    t = 1500
    for _ in range(3):  # rounds 2..4 each: break ends -> focus, focus ends
        t += 300
        assert p.tick(t) == "focus"
        t += 1500
        nxt = p.tick(t)
    assert nxt == "long_break"
    t += 900
    assert p.tick(t) == "idle" and p.phase == "idle"


def test_stop_resets():
    p = focus.Pomodoro()
    p.start(0)
    p.tick(1500)
    p.stop()
    assert p.phase == "idle" and p.round == 0 and p.tick(99999) is None


def test_late_tick_advances_once():
    p = focus.Pomodoro()
    p.start(0)
    assert p.tick(10000) == "short_break"
    assert p.phase == "short_break"


def test_page_compact_text(qapp, island, monkeypatch):
    page = focus.FocusPage(island.notify)
    assert page.compact_text() is None and not page.animating()
    monkeypatch.setattr(focus.time, "monotonic", lambda: 100.0)
    page.start()
    monkeypatch.setattr(focus.time, "monotonic", lambda: 100.0 + 47)
    assert page.compact_text() == "● 24:13" and page.animating()
    page.stop()
    assert page.compact_text() is None


def test_page_popups_and_settings(qapp, tmp_path, monkeypatch):
    store.DIR_OVERRIDE = tmp_path
    try:
        store.save_kv("settings.txt", {"focus": "1", "short_break": "7"})
        sent, beeps = [], []
        monkeypatch.setattr(focus.winsound, "MessageBeep", lambda *a: beeps.append(1))
        page = focus.FocusPage(sent.append)
        monkeypatch.setattr(focus.time, "monotonic", lambda: 0.0)
        page.start()
        assert page.pomo.remaining(0) == 60
        page._tick(60.0)
        assert sent[-1] == ("popup", "\uE916", "Focus done", "Take a 7 min break")
        page._tick(60.0 + 420)
        assert sent[-1] == ("popup", "\uE916", "Break over", "Back to focus")
        assert len(beeps) == 2
        page.stop()
    finally:
        store.DIR_OVERRIDE = None
