import io

from island import media


def test_parse_lrc_and_line_at():
    lrc = media.parse_lrc("[00:10.00] first\n[00:20.50][01:00.00] chorus\n[00:30.00]\n[00:05.00] intro\nno stamp")
    assert lrc == [(5.0, "intro"), (10.0, "first"), (20.5, "chorus"), (30.0, ""), (60.0, "chorus")]
    assert media.line_at(lrc, 4.9) == "" and media.line_at(lrc, 10.0) == "first" and media.line_at(lrc, 25) == "chorus"
    assert media.line_at(lrc, 999) == "chorus"


def test_artist_album_suffix_is_cleaned_before_query(monkeypatch):
    seen = []
    monkeypatch.setattr(media.urllib.request, "urlopen", lambda req, timeout: seen.append(req.full_url) or io.BytesIO(b"[]"))
    media.fetch_lyrics("Nutshell", "Alice In Chains — Jar of Flies - EP", 259)
    assert "artist_name=Alice+In+Chains" in seen[0] and "Jar" not in seen[0], seen


# --- reading the player: cover art arrives late, album in the artist field -----------------------------
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS


def _session(title, artist, cover):
    async def props():
        return NS(title=title, artist=artist, thumbnail=cover)
    zero = timedelta(0)
    return NS(try_get_media_properties_async=props,
              get_playback_info=lambda: NS(playback_status=media.PLAYING),
              get_timeline_properties=lambda: NS(start_time=zero, end_time=zero, position=zero,
                                                 last_updated_time=datetime.now(timezone.utc)))


def _poll(m, session):
    got = []
    m.changed.connect(got.append)
    asyncio.run(m._read(NS(get_current_session=lambda: session)))
    m.changed.disconnect(got.append)
    return got[-1]


def _player(qapp, monkeypatch, covers):
    """A Media that reads fake sessions; `covers` maps a cover ref to bytes or an exception."""
    async def thumb(ref):
        result = covers.get(ref, b"")
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(media.Media, "_thumb", staticmethod(thumb))
    return media.Media(autostart=False)


def test_cover_that_arrives_after_the_title_still_shows(qapp, monkeypatch):
    # Apple Music switches the title first and publishes the cover a moment later
    m = _player(qapp, monkeypatch, {"ref": b"JPEG"})
    first = _poll(m, _session("Song", "Artist", None))
    assert first["thumb"] == b"", "new song: the old cover is cleared"
    assert _poll(m, _session("Song", "Artist", "ref"))["thumb"] == b"JPEG", "cover is fetched once it exists"
    assert "thumb" not in _poll(m, _session("Song", "Artist", "ref")), "and only once"


def test_cover_read_error_is_retried_and_does_not_lose_the_update(qapp, monkeypatch, capsys):
    covers = {"ref": OSError("busy")}
    m = _player(qapp, monkeypatch, covers)
    info = _poll(m, _session("Song", "Artist", "ref"))
    assert info["title"] == "Song", "the rest of the update still arrives"
    covers["ref"] = b"JPEG"
    assert _poll(m, _session("Song", "Artist", "ref"))["thumb"] == b"JPEG"


def test_artist_drops_the_album_apple_music_appends(qapp, monkeypatch):
    m = _player(qapp, monkeypatch, {})
    info = _poll(m, _session("Song", "eleventwelfth — another night awake - Single", None))
    assert info["artist"] == "eleventwelfth"
