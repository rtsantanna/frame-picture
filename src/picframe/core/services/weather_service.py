"""Current weather + today's max/min for the HDMI HUD (Open-Meteo, no API key).

One process-wide instance is shared by the renderer (which only ever reads the
cached value, so the render loop never blocks on the network) and the web API
(place search and the panel preview). A daemon thread refreshes the cache for
the configured coordinates every ``REFRESH_S`` seconds; on failure the last
good reading is kept and retried sooner.

Only the configured coordinates (or the typed place name, for the search) are
sent to Open-Meteo; nothing about the photos ever leaves the frame.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
USER_AGENT = "FramePicture/1.0 (digital photo frame)"
REFRESH_S = 20 * 60
RETRY_S = 5 * 60
STALE_S = 3 * 60 * 60

# WMO weather code -> (day glyph, night glyph). Glyphs exist in DejaVu Sans.
_SUN, _MOON, _CLOUD, _FOG = "☀", "☾", "☁", "≋"
_RAIN, _SHOWER, _SNOW, _STORM = "☂", "☔", "❄", "⚡"


def icon_for(code: int | None, is_day: bool = True) -> str:
    """Map a WMO weather code to a single glyph."""
    if code is None:
        return ""
    if code in (0, 1):
        return _SUN if is_day else _MOON
    if code in (2, 3):
        return _CLOUD
    if code in (45, 48):
        return _FOG
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67):
        return _RAIN
    if code in (80, 81, 82):
        return _SHOWER
    if code in (71, 73, 75, 77, 85, 86):
        return _SNOW
    if code in (95, 96, 99):
        return _STORM
    return _CLOUD


def _http_json(url: str, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class WeatherService:
    _instance: WeatherService | None = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> WeatherService:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._coords: tuple[float, float] | None = None
        self._data: dict[str, Any] | None = None
        self._data_coords: tuple[float, float] | None = None
        self._error: str | None = None
        self._next_fetch = 0.0
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # -- configuration -------------------------------------------------------

    def set_location(self, lat: Any, lon: Any) -> None:
        """Point the service at new coordinates (None disables fetching)."""
        try:
            coords = (round(float(lat), 4), round(float(lon), 4))
        except (TypeError, ValueError):
            coords = None
        with self._lock:
            if coords == self._coords:
                return
            self._coords = coords
            self._next_fetch = 0.0
        if coords is not None:
            self._ensure_thread()
            self._wake.set()

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="WeatherService", daemon=True)
        self._thread.start()

    # -- reads -----------------------------------------------------------------

    def current(self) -> dict[str, Any] | None:
        """Cached reading for the configured coordinates (None if unknown/stale)."""
        with self._lock:
            if self._data is None or self._data_coords != self._coords:
                return None
            if time.time() - float(self._data.get("fetched_at", 0)) > STALE_S:
                return None
            return dict(self._data)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "coords": self._coords,
                "data": dict(self._data) if self._data else None,
                "error": self._error,
            }

    # -- fetching --------------------------------------------------------------

    def _run(self) -> None:
        while True:
            with self._lock:
                coords = self._coords
                due = self._next_fetch
            if coords is not None and time.time() >= due:
                self.refresh_now(coords)
            self._wake.wait(timeout=30)
            self._wake.clear()

    def refresh_now(self, coords: tuple[float, float] | None = None) -> dict[str, Any] | None:
        coords = coords or self._coords
        if coords is None:
            return None
        try:
            data = self.fetch(*coords)
        except Exception as exc:
            logger.warning("Weather fetch failed for %s: %s", coords, exc)
            with self._lock:
                self._error = str(exc)
                self._next_fetch = time.time() + RETRY_S
            return None
        with self._lock:
            self._data = data
            self._data_coords = coords
            self._error = None
            self._next_fetch = time.time() + REFRESH_S
        return data

    @staticmethod
    def fetch(lat: float, lon: float) -> dict[str, Any]:
        params = urllib.parse.urlencode(
            {
                "latitude": f"{lat:.4f}",
                "longitude": f"{lon:.4f}",
                "current": "temperature_2m,weather_code,is_day",
                "daily": "temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "forecast_days": 1,
            }
        )
        payload = _http_json(f"{FORECAST_URL}?{params}")
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}

        def first(values: Any) -> Any:
            return values[0] if isinstance(values, list) and values else None

        from picframe.core.renderers.components.weather_icons import kind_for

        code = current.get("weather_code")
        is_day = bool(current.get("is_day", 1))
        return {
            "temp": current.get("temperature_2m"),
            "code": code,
            "is_day": is_day,
            "icon": icon_for(code, is_day),
            "kind": kind_for(code, is_day),
            "tmax": first(daily.get("temperature_2m_max")),
            "tmin": first(daily.get("temperature_2m_min")),
            "fetched_at": time.time(),
        }

    @staticmethod
    def search_places(query: str, language: str = "pt", count: int = 8) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if len(query) < 2:
            return []
        params = urllib.parse.urlencode(
            {"name": query[:80], "count": count, "language": language, "format": "json"}
        )
        payload = _http_json(f"{GEOCODE_URL}?{params}")
        out: list[dict[str, Any]] = []
        for item in payload.get("results") or []:
            name = item.get("name") or ""
            admin = item.get("admin1") or ""
            country = item.get("country") or ""
            label = ", ".join(p for p in (name, admin, country) if p)
            out.append(
                {
                    "label": label,
                    "name": name,
                    "lat": item.get("latitude"),
                    "lon": item.get("longitude"),
                }
            )
        return out


def format_temp(value: Any) -> str:
    try:
        return f"{round(float(value))}°"
    except (TypeError, ValueError):
        return "--°"
