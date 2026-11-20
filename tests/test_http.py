import asyncio

import pytest

import importlib

from island import http as island_http


def test_get_maps_timeout_and_errors(monkeypatch):
    http = importlib.reload(island_http)  # undo the conftest network block
    import winrt.windows.web.http as wh

    class Slow:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        async def send_request_async(self, req):
            await asyncio.sleep(5)

    monkeypatch.setattr(wh, "HttpClient", Slow)
    with pytest.raises(OSError, match="timeout"):
        http.get("https://example.com/", timeout=0.05)

    class Broken(Slow):
        async def send_request_async(self, req):
            raise RuntimeError("boom")
    monkeypatch.setattr(wh, "HttpClient", Broken)
    with pytest.raises(OSError, match="RuntimeError"):
        http.get("https://example.com/")
