"""Behaviour copied from measurements of Nusa 1.3.1 (sizes, hover dwell, water's hourly log and switch)."""
from datetime import datetime

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from island import app, store
from island.water import Water


def test_sizes_match_nusa():
    assert app.EXPANDED == (455.0, 197.0) and app.MINIMAL == (53.0, 4.0)
    assert (app.EAR, app.CORNER) == (22.0, 36.0)


def test_notch_path_has_flared_ears():
    from PySide6.QtCore import QRectF
    r = QRectF(100, 0, 455, 197)
    path = app.notch_path(r, app.EAR, app.CORNER)
    assert path.contains(QPointF(r.left() - 14, 1)), "ear flares out at the bezel (Nusa: 16 px at y=1)"
    assert not path.contains(QPointF(r.left() - 18, 20)), "and curves back in below"
    assert not path.contains(QPointF(r.left() + 2, r.bottom() - 2)), "bottom corners are rounded"


def test_hover_waits_and_swells_before_opening(island):
    move = lambda y: island.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(app.WIN_W / 2, y), QPointF(0, 0),
                                                       Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    move(2)
    assert island.dwell.isActive() and island.expand == 0.0, "no instant open: the pointer must rest a moment"
    assert island.peek_anim.endValue() == 1.0, "the pill swells while it waits"
    assert island.dwell.interval() == 200 and island.leave_delay.interval() == 90


def test_water_logs_each_hour_and_keeps_the_switch(tmp_path):
    w = Water({"goal": "1500"})
    now = datetime(2026, 11, 22, 10, 15)
    w.drink(now)
    w.drink(datetime(2026, 11, 22, 10, 50))
    assert w.hours[10] == 500 and sum(w.hours) == 500
    kv = {k: str(v) for k, v in w.to_kv().items()}
    again = Water(kv)
    assert again.hours[10] == 500 and again.on, "hours and switch survive a save"
    again.on = False
    assert not again.due(datetime(2026, 11, 22, 12, 0)), "reminders off: never due"
    again.roll(datetime(2026, 11, 23, 9, 0))
    assert sum(again.hours) == 0, "a new day starts an empty chart"


def test_water_switch_on_the_page_saves(island):
    was = island.water.on
    island.toggle_water()
    assert island.water.on is not was and store.load_kv("water.txt")["on"] == str(int(island.water.on))


def _drawn_texts(island, monkeypatch):
    seen = []
    real = island._text
    monkeypatch.setattr(island, "_text", lambda p, rect, s, *a, **k: seen.append(s) or real(p, rect, s, *a, **k))
    return seen


def test_not_playing_keeps_the_player(island, monkeypatch):
    island._set_expand(1.0)
    seen = _drawn_texts(island, monkeypatch)
    island.grab()
    assert "Not Playing" in seen and {"prev", "toggle", "next", "volume"} <= set(island.buttons)


def test_source_dots_switch_media_source(island, fake_media, monkeypatch):
    picked = []
    fake_media.select = picked.append
    fake_media.changed.emit({"title": "Song", "artist": "A", "playing": False, "sessions": 2, "source": 0})
    island._set_expand(1.0)
    island.grab()
    assert {"src0", "src1"} <= set(island.buttons)
    island.media_page.click(island.buttons["src1"].center(), Qt.LeftButton, island)
    assert picked == [1]


def test_media_select_follows_the_chosen_session(qapp):
    import asyncio
    from datetime import timedelta, timezone
    from types import SimpleNamespace as NS
    from island import media

    def session(app_id, title):
        async def props():
            return NS(title=title, artist="", thumbnail=None)
        zero = timedelta(0)
        return NS(source_app_user_model_id=app_id, try_get_media_properties_async=props,
                  get_playback_info=lambda: NS(playback_status=media.PLAYING),
                  get_timeline_properties=lambda: NS(start_time=zero, end_time=zero, position=zero,
                                                     last_updated_time=datetime.now(timezone.utc)))
    a, b = session("music", "From music"), session("browser", "From browser")
    manager = NS(get_current_session=lambda: a, get_sessions=lambda: [a, b])
    m = media.Media(autostart=False)
    got = []
    m.changed.connect(got.append)
    asyncio.run(m._read(manager))
    assert got[-1]["title"] == "From music" and got[-1]["sessions"] == 2
    m.select(1)
    asyncio.run(m._read(manager))
    assert got[-1]["title"] == "From browser" and got[-1]["source"] == 1


def test_page_icons_bar_with_gear(island, monkeypatch):
    opened = []
    monkeypatch.setattr(island, "open_settings", lambda *a: opened.append(1))
    island._set_expand(1.0)
    base = island._island_rect().height()
    island._set_bar(1.0)
    assert island._island_rect().height() == base + app.BAR_EXTRA, "Nusa grows to fit the bar"
    island.grab()
    assert "gear" in island.page_hits and all(i in island.page_hits for i in range(len(island.pages)))
    from tests.test_pages import _click_at
    _click_at(island, island.page_hits[2].center())
    assert island.page == 2, "an icon jumps to its page"
    island.grab()
    _click_at(island, island.page_hits["gear"].center())
    assert opened == [1]


def test_hovering_the_dots_reveals_the_bar(island):
    island._set_expand(1.0)
    r = island._island_rect()
    island.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(r.center().x(), r.bottom() - 8), QPointF(0, 0),
                                      Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    assert island.bar_anim.endValue() == 1.0


def test_volume_slider_appears_on_hover_and_sets_level(island, monkeypatch):
    written = []
    monkeypatch.setattr(island, "read_volume", lambda: (0.3, False))
    monkeypatch.setattr(island, "write_volume", written.append)
    island._set_expand(1.0)
    island.grab()
    island.hover_pos = island.buttons["volume"].center()
    island.grab()
    slider = island.buttons["slider"]
    assert island.media_page.level == 0.3
    island.media_page.click(QPointF(slider.left() + slider.width() / 2, slider.center().y()), Qt.LeftButton, island)
    assert written and abs(written[-1] - 0.5) < 0.02


def test_window_fits_the_island_with_the_icons_bar():
    assert app.WIN_H >= app.EXPANDED[1] + app.BAR_EXTRA, "otherwise the bar is clipped"


LRC3 = [(0.0, "first line"), (10.0, "second line"), (20.0, "third line")]


def _red_song(island):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage, QColor
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor(200, 30, 30))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    island._on_media({"title": "Song", "artist": "Artist", "playing": False, "pos": 11.0, "pos_at": 0,
                      "duration": 100.0, "lyrics": LRC3, "thumb": bytes(buf.data())})


def test_album_colour_is_taken_from_the_art(island):
    _red_song(island)
    c = island.art_color
    assert c.red() > 150 and c.green() < 80, "the glow takes the cover's colour"


def test_lyrics_button_opens_the_wide_lyrics_view(island):
    _red_song(island)
    island._set_expand(1.0)
    island.grab()
    island.media_page.click(island.buttons["lyrics"].center(), Qt.LeftButton, island)
    assert island.media_page.lyrics_view
    island.grab()  # paint starts the widen animation
    island._set_wide(1.0)
    assert island._island_rect().width() == app.LYRICS_EXPANDED[0], "Nusa widens the island for lyrics"
    img = island.grab().toImage()
    assert "volume" not in island.buttons and {"lyrics", "prev", "toggle", "next"} <= set(island.buttons)
    assert not island.page_hits, "no page dots or arrows in the lyrics view"
    bottom = img.pixelColor(app.WIN_W // 2, 192)
    assert bottom.red() > bottom.green() + 20, "album-coloured glow at the bottom"
    island.media_page.click(island.buttons["lyrics"].center(), Qt.LeftButton, island)
    island.grab()
    assert not island.media_page.lyrics_view and island.wide_anim.endValue() == 0.0, "the button closes it again"


def test_collapsed_lyric_pill_glows_and_shows_a_note(island):
    _red_song(island)
    island.media_page.lyrics_view = True
    island._on_media({**island.info, "playing": True, "pos_at": None})
    island._set_expand(0.0)
    img = island.grab().toImage()
    r = island._island_rect()
    assert island._lyric_pill()
    low = img.pixelColor(int(r.center().x()) + 60, int(r.bottom()) - 3)
    assert low.red() > low.green() + 20, "the pill glows in the album colour"


def test_collapsed_pill_shows_clock_then_wave_then_lyrics(island):
    island.info = {}
    island._set_expand(0.0)
    assert island._island_rect().width() == app.CLOCK_PILL[0], "idle: ring and time"
    island._on_media({"title": "Song", "artist": "A", "playing": True, "pos": 0, "pos_at": None, "lyrics": []})
    assert island._island_rect().width() == app.COLLAPSED_PLAYING[0], "playing: ring, time and waveform"
    island.media_page.lyrics_view = True
    assert island._island_rect().width() == app.COLLAPSED_LYRICS[0], "lyrics mode"
    island.grab()  # no lyrics found: "Lyrics not available" (drawn without error)


def test_floating_gap_still_opens_on_hover(island):
    island.info = {}
    island._set_expand(0.0)
    r = island._island_rect()
    island.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(r.center().x(), 2), QPointF(0, 0),
                                      Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    assert island.hovered, "pointer flung to the top edge, above a floating island, still counts"


def test_widgets_settings_and_helpers(island):
    from datetime import date, datetime, timezone
    from island import settings, widgets
    assert widgets.parse("moon,clock") == ("moon", "clock")
    assert widgets.parse("bogus") == ("week", "prayer")
    assert widgets.moon(datetime(2024, 1, 25, 17, 54, tzinfo=timezone.utc))[2] == "Full Moon"
    assert widgets.moon(datetime(2024, 2, 9, 22, 59, tzinfo=timezone.utc))[2] == "New Moon"
    assert widgets.countdown({}, date(2026, 11, 22)) == ("New Year", date(2027, 1, 1), 40)
    w = settings.SettingsWindow(island, "Widgets")
    picker = w.widgets["widgets"]
    picker.side.setCurrentText("Right")
    picker._pick("moon")
    w.save()
    assert island.widgets_page.right == "moon" and store.load_kv("settings.txt")["widgets"] == "week,moon"
    island._set_expand(1.0)
    island.page = island.pages.index(island.widgets_page)
    for kind, _ in widgets.KINDS:  # every widget draws without error
        island.widgets_page.left = kind
        island.grab()


def test_old_saved_pages_get_the_widgets_page_once(island):
    store.save_kv("settings.txt", {"pages": "media,focus"})
    app._add_widgets_page_once()
    assert store.load_kv("settings.txt")["pages"] == "media,widgets,focus"
    store.save_kv("settings.txt", {**store.load_kv("settings.txt"), "pages": "media,focus"})
    app._add_widgets_page_once()
    assert store.load_kv("settings.txt")["pages"] == "media,focus", "turning it off later sticks"


def test_focus_today_log(qapp):
    from datetime import date
    from island.focus import FocusPage
    f = FocusPage(lambda hud: None)
    d = date(2026, 11, 22)
    f._log_focus(25, d)
    f._log_focus(25, d)
    assert f.today(d) == (50, 2) and f.today(date(2026, 11, 23)) == (0, 0)
