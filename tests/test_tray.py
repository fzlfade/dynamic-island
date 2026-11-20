from island import app


def test_tray_menu_offers_ask_and_ocr_without_hotkeys(island, monkeypatch):
    # Ctrl+Alt+Space / Ctrl+Alt+T can be taken by another app, so both features need a way in that always works
    called = []
    monkeypatch.setattr(island, "start_ask", lambda: called.append("ask"))
    monkeypatch.setattr(island, "start_ocr", lambda: called.append("ocr"))
    tray = app.make_tray(island)
    try:
        actions = {a.text(): a for a in tray.contextMenu().actions()}
        actions["Ask Claude…"].trigger()
        actions["Copy text from screen"].trigger()
        assert called == ["ask", "ocr"]
    finally:
        tray.hide()
