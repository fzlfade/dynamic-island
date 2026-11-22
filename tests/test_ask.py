import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from types import SimpleNamespace as NS

import anthropic
import httpx2
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QInputDialog

from island import ask


class FakeClient:
    """Stands in for anthropic.Anthropic(): beta.messages.stream(**kw) streams "Hel", "lo"."""

    def __init__(self, stop_reason="end_turn", raises=None):
        self.kwargs, self.stop_reason, self.raises = None, stop_reason, raises
        self.beta = NS(messages=NS(stream=self._stream))

    @contextmanager
    def _stream(self, **kw):
        self.kwargs = kw
        if self.raises:
            raise self.raises
        yield NS(text_stream=iter(["Hel", "lo"]), get_final_message=lambda: NS(stop_reason=self.stop_reason))


def _ask(island, qapp, client, question="what is 2+2"):
    island.ask_page.start(question)
    island.asker.ask(question, client=client)
    island.asker.thread.join(5)
    qapp.processEvents()  # deliver the worker's queued signals to the UI thread


def test_streams_into_page(island, qapp):
    _ask(island, qapp, FakeClient())
    assert island.ask_page.text == "Hello" and island.ask_page.state == "done"


def test_request_shape(island, qapp):
    client = FakeClient()
    _ask(island, qapp, client, "what is 2+2")
    kw = client.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "low"}
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["fallbacks"] == "default"
    assert kw["max_tokens"] == 64000
    assert kw["messages"] == [{"role": "user", "content": "what is 2+2"}]
    assert kw["system"] == ask.ASK_SYSTEM


def test_refusal(island, qapp):
    _ask(island, qapp, FakeClient(stop_reason="refusal"))
    assert island.ask_page.state == "error" and island.ask_page.text == "Claude declined this one."


def _status_error(cls, code):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("x", response=httpx2.Response(code, request=req), body=None)


def test_error_messages(island, qapp):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    cases = [
        (_status_error(anthropic.AuthenticationError, 401), "Set ANTHROPIC_API_KEY or run: ant auth login"),
        (_status_error(anthropic.RateLimitError, 429), "Busy right now, try again shortly"),
        (anthropic.APIConnectionError(request=req), "No connection"),
        (_status_error(anthropic.APIStatusError, 529), "Error 529"),
    ]
    for exc, text in cases:
        _ask(island, qapp, FakeClient(raises=exc))
        assert (island.ask_page.state, island.ask_page.text) == ("error", text), type(exc).__name__


def test_hotkey_opens_dialog_and_ask_page(island, qapp, monkeypatch):
    asked = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("what is 2+2", True))
    monkeypatch.setattr(island.asker, "ask", lambda q, client=None: asked.append(q))
    msg = wintypes.MSG(message=0x312, wParam=ask.HOTKEY_ID)  # WM_HOTKEY
    island.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))
    assert asked == ["what is 2+2"]
    assert island.pages[island.page] is island.ask_page and island.ask_page.state == "streaming"


def test_cancelled_dialog_asks_nothing(island, monkeypatch):
    asked = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    monkeypatch.setattr(island.asker, "ask", lambda q, client=None: asked.append(q))
    island.start_ask()
    assert asked == []


def test_click_closes_answer(island, qapp):
    _ask(island, qapp, FakeClient())
    island._set_expand(1.0)
    island.pages.append(island.ask_page)
    island.page = island.pages.index(island.ask_page)
    island.grab()
    island.ask_page.click(QPointF(200, 50), Qt.LeftButton, island)
    assert island.ask_page.state == "idle"
    assert island.ask_page not in island.pages, "Ask leaves the page row once closed"


def test_long_answer_keeps_last_lines_visible(island, qapp):
    page = island.ask_page
    page.start("q")
    page.add(" ".join(f"word{i}" for i in range(300)))
    page.finish()
    island._set_expand(1.0)
    island.pages.append(page)
    island.page = island.pages.index(page)
    island.grab()
    assert page.shown.endswith("word299") and not page.shown.startswith("word0")
