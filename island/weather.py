"""Weather from MET Norway. Location stays on the device; only 4-decimal lat/lon go to api.met.no."""
import asyncio
import email.utils
import json
import sys
import threading
import time

from island import http, store

JAKARTA = (-6.2088, 106.8456, "Jakarta")
MIN_GAP = 1800  # MET asks clients not to poll faster
WORDS = {"clearsky": "Clear", "fair": "Mostly clear", "partlycloudy": "Partly cloudy", "cloudy": "Cloudy", "fog": "Fog",
         "lightrain": "Light rain", "rain": "Rain", "heavyrain": "Heavy rain", "sleet": "Sleet", "snow": "Snow"}


def describe(code):
    base = code.rsplit("_", 1)[0] if code.endswith(("_day", "_night", "_polartwilight")) else code
    if "thunder" in base:
        return "Thunderstorm"
    base = base.removesuffix("showers")
    return WORDS.get(base, base.capitalize())


def parse_met(data):
    first = data["properties"]["timeseries"][0]["data"]
    code = (first.get("next_1_hours") or first.get("next_6_hours") or first["next_12_hours"])["summary"]["symbol_code"]
    return first["instant"]["details"]["air_temperature"], describe(code)


def _geolocate():
    """One Windows Geolocator read (blocking, <= 10 s); raises when denied or unavailable."""
    from winrt.windows.devices.geolocation import Geolocator

    async def read():
        pos = (await Geolocator().get_geoposition_async()).coordinate.point.position
        return pos.latitude, pos.longitude
    return asyncio.run(asyncio.wait_for(read(), 10))


def location(values):
    try:
        return round(float(values["lat"]), 4), round(float(values["lon"]), 4), values.get("place") or "My location"
    except (KeyError, ValueError):
        pass
    try:
        lat, lon = _geolocate()
        loc = (round(lat, 4), round(lon, 4), "My location")
    except Exception:  # denied, no sensor, timeout: any failure falls back
        return JAKARTA
    store.save_kv("settings.txt", {**store.load_kv("settings.txt"), "lat": loc[0], "lon": loc[1], "place": loc[2]})
    return loc


class Weather:
    def __init__(self, lat, lon):
        self.url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat:.4f}&lon={lon:.4f}"
        self.now = None  # (°C, description); rebound atomically, the Qt side only reads it
        self.next_ok = 0.0

    def fetch_once(self):
        if time.time() < self.next_ok:
            return
        try:
            status, headers, body = http.get(self.url, timeout=10)
            if status != 200:
                raise OSError(f"HTTP {status}")
            now = parse_met(json.loads(body.decode("utf-8")))
            expires = headers.get("expires")
            try:
                exp = email.utils.parsedate_to_datetime(expires).timestamp()
            except (TypeError, ValueError):
                exp = 0
            self.next_ok = max(time.time() + MIN_GAP, exp)
            self.now = now
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            print(f"weather fetch failed: {type(e).__name__}", file=sys.stderr)  # never the coordinates

    def refresh(self):
        threading.Thread(target=self.fetch_once, daemon=True).start()
