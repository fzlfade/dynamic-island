"""Media session thread and LRCLIB synced lyrics."""
import asyncio
import bisect
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SessionManager
from winrt.windows.storage.streams import DataReader

PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
LRCLIB = "https://lrclib.net/api/search?"
LRC_STAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")



def parse_lrc(text):
    """'[01:02.50] words' lines -> sorted [(62.5, 'words')]. One line may carry several stamps."""
    out = []
    for line in text.splitlines():
        words = LRC_STAMP.sub("", line).strip()
        out += [(int(m) * 60 + float(s), words) for m, s in LRC_STAMP.findall(line)]
    return sorted(out)


def line_at(lyrics, pos):
    i = bisect.bisect_right(lyrics, pos, key=lambda l: l[0]) - 1
    return lyrics[i][1] if i >= 0 else ""


def fetch_lyrics(title, artist, duration):
    """Best synced match from LRCLIB, or [] when none fits this track's length."""
    artist = artist.split(" — ")[0]  # Apple Music reports "Artist — Album" as the artist
    q = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
    req = urllib.request.Request(LRCLIB + q, headers={"User-Agent": "DynamicIsland/0.1"})
    with urllib.request.urlopen(req, timeout=10) as r:
        hits = [h for h in json.load(r) if h.get("syncedLyrics")]
    if not hits:
        return []
    best = min(hits, key=lambda h: abs((h.get("duration") or 0) - duration))
    if abs((best.get("duration") or 0) - duration) > 5:  # another cut of the song: its timings would be off
        return []
    return parse_lrc(best["syncedLyrics"])


class Media(QObject):
    """Polls the current media session on its own asyncio thread."""
    changed = Signal(dict)

    def __init__(self, autostart=True):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.session = None
        self.pick = None  # app id of the source chosen with the dots under the cover; None: Windows' current one
        self.ids = []
        self._last_title = None
        self._art_for = None  # title whose cover was already sent
        self.lyrics = []
        self._lyrics_task = None  # strong ref: the loop only holds tasks weakly
        if autostart:  # tests drive _read() themselves
            self.start()

    def start(self):
        """Begin polling. Connect `changed` first: the first update is the only one carrying the cover."""
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(self._poll(), self.loop)

    async def _poll(self):
        manager = await SessionManager.request_async()
        while True:
            # shortcut: 1 s polling instead of WinRT change events, upgrade if 1 s lag on track change bothers you
            try:
                await self._read(manager)
            except Exception as e:  # session can vanish mid-read when a player closes
                print("media:", e, file=sys.stderr)
            await asyncio.sleep(1)

    async def _read(self, manager):
        current = manager.get_current_session()
        sessions = list(manager.get_sessions()) if hasattr(manager, "get_sessions") else ([current] if current else [])
        self.ids = [getattr(x, "source_app_user_model_id", "") for x in sessions]
        s = self.session = next((x for x, i in zip(sessions, self.ids) if i == self.pick), current)
        if not s:
            self._last_title = None
            self.changed.emit({})
            return
        props = await s.try_get_media_properties_async()
        playing = s.get_playback_info().playback_status == PLAYING
        tl = s.get_timeline_properties()
        duration = (tl.end_time - tl.start_time).total_seconds()
        # players only report position now and then; extrapolate from their last report
        pos = tl.position.total_seconds()
        if playing:
            pos += (datetime.now(timezone.utc) - tl.last_updated_time).total_seconds()
        shown = props.artist or ""  # Nusa shows Apple Music's "Artist — Album" line as it comes
        artist = shown.split(" — ")[0]  # the lyrics search needs the artist alone
        info = {"title": props.title or "", "artist": shown, "playing": playing, "duration": duration,
                "sessions": len(sessions), "source": sessions.index(s) if s in sessions else 0,
                "pos": max(0.0, min(pos, duration)), "pos_at": time.monotonic()}
        new_track = props.title != self._last_title
        if new_track:  # lyrics only when the track changes
            self._last_title, self._art_for = props.title, None
            self.lyrics = []
            info["thumb"] = b""  # clear the previous song's cover until this one's arrives
            if duration > 0:  # no timeline (some players) means nothing to sync against
                self._lyrics_task = asyncio.create_task(self._load_lyrics(props.title, artist, duration))
        if self._art_for != props.title:  # players often publish the cover after the title: keep asking
            try:
                art = await self._thumb(props.thumbnail)
            except Exception as e:  # e.g. the image stream isn't ready yet: try again next poll
                print("media cover:", type(e).__name__, file=sys.stderr)
                art = b""
            if art:
                info["thumb"], self._art_for = art, props.title
        info["lyrics"] = self.lyrics
        self.changed.emit(info)

    async def _load_lyrics(self, title, artist, duration):
        try:
            lyrics = await asyncio.get_running_loop().run_in_executor(None, fetch_lyrics, title, artist, duration)
        except (OSError, ValueError) as e:  # offline, LRCLIB down or bad JSON: just no lyrics
            print("lyrics:", e, file=sys.stderr)
            return
        if title == self._last_title:  # track may have changed while we waited
            self.lyrics = lyrics

    @staticmethod
    async def _thumb(ref):
        if not ref:
            return b""
        stream = await ref.open_read_async()
        reader = DataReader(stream.get_input_stream_at(0))
        n = await reader.load_async(stream.size)
        return bytes(reader.read_buffer(n))

    def select(self, n):
        """Follow media source n (the dots under the cover); takes effect on the next 1 s poll."""
        if 0 <= n < len(self.ids):
            self.pick = self.ids[n]

    def send(self, action):
        if self.session:
            coro = {"prev": self.session.try_skip_previous_async,
                    "toggle": self.session.try_toggle_play_pause_async,
                    "next": self.session.try_skip_next_async}[action]()
            asyncio.run_coroutine_threadsafe(_await(coro), self.loop)


async def _await(op):
    await op
