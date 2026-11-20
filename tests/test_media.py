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
