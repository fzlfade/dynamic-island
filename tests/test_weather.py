import io
import json
from pathlib import Path

import pytest

from island import http, store, weather

MET = (Path(__file__).parent / "data" / "met.json").read_bytes()


def test_parse_met_fixture():
    assert weather.parse_met(json.loads(MET)) == (27.3, "Partly cloudy")


@pytest.mark.parametrize("code,word", [
    ("clearsky_night", "Clear"), ("fair_day", "Mostly clear"), ("partlycloudy_night", "Partly cloudy"),
    ("cloudy", "Cloudy"), ("fog", "Fog"), ("lightrain", "Light rain"), ("rain", "Rain"),
    ("heavyrain", "Heavy rain"), ("sleet", "Sleet"), ("snow", "Snow"),
    ("rainandthunder", "Thunderstorm"), ("heavyrainshowersandthunder_day", "Thunderstorm"),
    ("rainshowers_day", "Rain"), ("lightrainshowers_night", "Light rain"), ("heavyrainshowers_day", "Heavy rain"),
])
def test_symbol_words(code, word):
    assert weather.describe(code) == word


def test_url_rounds_to_4_decimals():
    assert weather.Weather(-6.20881234, 106.84559999).url == \
        "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=-6.2088&lon=106.8456"


def test_fetch_sets_now_sends_ua_and_honours_expires(monkeypatch):
    seen = []

    def fake(url, headers=None, timeout=10):
        seen.append((url, timeout))
        return 200, {"expires": "Sat, 21 Nov 2036 12:00:00 GMT"}, MET
    monkeypatch.setattr(http, "get", fake)
    w = weather.Weather(-6.2088, 106.8456)
    w.fetch_once()
    assert w.now == (27.3, "Partly cloudy")
    assert seen[0][1] == 10 and "lat=-6.2088&lon=106.8456" in seen[0][0]
    w.fetch_once()  # before Expires: no second request
    assert len(seen) == 1


def test_minimum_30_minutes_between_fetches(monkeypatch):
    monkeypatch.setattr(http, "get", lambda url, headers=None, timeout=10: (200, {"expires": "Mon, 01 Jan 2001 00:00:00 GMT"}, MET))
    clock = [2_000_000_000.0]
    monkeypatch.setattr(weather.time, "time", lambda: clock[0])
    w = weather.Weather(0, 0)
    w.fetch_once()
    assert w.next_ok == 2_000_000_000.0 + 1800


def test_weather_failure_keeps_last(monkeypatch, capsys):
    monkeypatch.setattr(http, "get", lambda url, headers=None, timeout=10: (200, {}, MET))
    w = weather.Weather(-6.2088, 106.8456)
    w.fetch_once()
    w.next_ok = 0

    def boom(url, headers=None, timeout=10):
        raise OSError("down -6.2088")
    monkeypatch.setattr(http, "get", boom)
    w.fetch_once()
    assert w.now == (27.3, "Partly cloudy")
    err = capsys.readouterr().err
    assert "OSError" in err and "6.2088" not in err


def test_location_geolocator_failure_is_jakarta(monkeypatch):
    def boom():
        raise OSError("denied")
    monkeypatch.setattr(weather, "_geolocate", boom)
    assert weather.location({}) == (-6.2088, 106.8456, "Jakarta")


def test_location_uses_settings_then_saves_geolocator(monkeypatch):
    monkeypatch.setattr(weather, "_geolocate", lambda: (1.234567, 2.345678))
    assert weather.location({"lat": "5", "lon": "6", "place": "Home"}) == (5.0, 6.0, "Home")
    assert weather.location({}) == (1.2346, 2.3457, "My location")
    assert store.load_kv("settings.txt") == {"lat": "1.2346", "lon": "2.3457", "place": "My location"}
