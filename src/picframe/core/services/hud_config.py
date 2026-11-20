"""HDMI HUD layout: which texts the frame shows, how big and where.

The HUD is the set of texts drawn on top of the photo on the HDMI output:

* per-photo elements (fade in/out with each photo): ``description`` (the
  approved catalog description), ``location`` (the GPS place of the photo) and
  ``photo_date`` (when the photo was taken);
* live elements (always on screen): ``clock``, ``today_date`` and ``weather``.

All elements share one text style (font, colour, opacity and the optional
background band); each element has its own on/off switch, size and anchor
(``TL``, ``TC``, ``TR``, ``BL``, ``BC``, ``BR``). Elements on the same anchor
stack vertically in a fixed order.

The whole layout is stored as one JSON value under ``viewer.hud``. When it does
not exist yet it is derived from the legacy per-element keys, so an upgrade
keeps what the operator already had on screen. Saving also mirrors the legacy
keys (``viewer.show_clock``, ``viewer.text_overlay_format`` ...) so MQTT/Home
Assistant and older code paths keep seeing a consistent state.
"""

from __future__ import annotations

import copy
import re
from typing import Any

HUD_KEY = "viewer.hud"

ANCHORS = ("TL", "TC", "TR", "BL", "BC", "BR")
PHOTO_ELEMENTS = ("description", "location", "photo_date")
LIVE_ELEMENTS = ("weather", "clock", "today_date")
# Top-to-bottom order of elements sharing one anchor.
STACK_ORDER = ("weather", "clock", "today_date", "description", "location", "photo_date")
ELEMENTS = STACK_ORDER

FONTS = {
    "noto": "NotoSans-Regular.ttf",
    "noto_bold": "NotoSans-Bold.ttf",
    "dejavu": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "dejavu_bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}

MIN_SIZE = 12
MAX_SIZE = 400

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def default_hud() -> dict[str, Any]:
    """Factory defaults (used when nothing legacy is available either)."""
    return {
        "style": {
            "font": "noto",
            "color": "#f8fafc",
            "opacity": 0.4,
            "bg_color": "#000000",
            "bg_opacity": 0.0,
        },
        "elements": {
            "description": {"enabled": True, "size": 40, "position": "BL"},
            "location": {"enabled": False, "size": 32, "position": "BL"},
            "photo_date": {"enabled": True, "size": 32, "position": "BL"},
            "clock": {"enabled": True, "size": 120, "position": "BR"},
            "today_date": {"enabled": False, "size": 36, "position": "BR"},
            "weather": {"enabled": False, "size": 48, "position": "TR"},
        },
        "formats": {
            "clock": "%H:%M",
            "today_date": "%d/%m/%Y",
            "photo_date": "%d/%m/%Y",
        },
        "weather": {"lat": None, "lon": None, "place": ""},
        "margin_pct": 3.0,
        "lang": "pt",
    }


def _get(repo: Any, key: str, default: Any) -> Any:
    try:
        value = repo.get_app_config(key, default)
    except Exception:
        return default
    return default if value in (None, "") else value


def _get_bool(repo: Any, key: str, default: bool) -> bool:
    try:
        return bool(repo.get_app_config_bool(key, default))
    except Exception:
        return default


def _legacy_hud(repo: Any) -> dict[str, Any]:
    """Build a HUD dict from the pre-HUD keys so an upgrade looks the same."""
    hud = default_hud()
    fmt = str(_get(repo, "viewer.text_overlay_format", "description date")).lower()
    show_text = _get_bool(repo, "viewer.show_text_enabled", True)
    top_bottom = str(_get(repo, "viewer.clock_top_bottom", "T")).upper()[:1] or "T"
    justify = str(_get(repo, "viewer.clock_justify", "R")).upper()[:1] or "R"
    clock_pos = f"{'B' if top_bottom == 'B' else 'T'}{justify if justify in 'LCR' else 'R'}"
    text_size = int(_get(repo, "viewer.show_text_sz", 40))
    els = hud["elements"]
    els["description"].update(enabled=show_text and "description" in fmt, size=text_size)
    els["photo_date"].update(enabled=show_text and "date" in fmt, size=max(MIN_SIZE, int(text_size * 0.8)))
    els["location"].update(enabled=show_text and "location" in fmt, size=max(MIN_SIZE, int(text_size * 0.8)))
    els["clock"].update(
        enabled=_get_bool(repo, "viewer.show_clock", True),
        size=int(_get(repo, "viewer.clock_text_sz", 120)),
        position=clock_pos,
    )
    els["today_date"]["position"] = clock_pos
    # Item 1 of the request: the clock's look (colour + translucency) becomes
    # the single style for every HUD text.
    hud["style"].update(
        color=str(_get(repo, "viewer.clock_color", "#f8fafc")),
        opacity=float(_get(repo, "viewer.clock_opacity", 0.4)),
        bg_color=str(_get(repo, "viewer.text_bg_color", "#000000")),
    )
    hud["formats"]["clock"] = str(_get(repo, "viewer.clock_format", "%H:%M"))
    hud["formats"]["photo_date"] = str(_get(repo, "viewer.show_text_fm", "%d/%m/%Y"))
    hud["margin_pct"] = float(_get(repo, "viewer.clock_wdt_offset_pct", 3.0))
    return hud


def _clamp(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(lo, min(hi, number))


def normalize_hud(raw: Any, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge ``raw`` over ``base`` (or the defaults) and coerce every field.

    Unknown keys are dropped; invalid values fall back to the base value, so a
    bad request can never leave the renderer with an unusable layout.
    """
    hud = copy.deepcopy(base) if base else default_hud()
    if not isinstance(raw, dict):
        return hud

    style = raw.get("style")
    if isinstance(style, dict):
        cur = hud["style"]
        if style.get("font") in FONTS:
            cur["font"] = style["font"]
        for key in ("color", "bg_color"):
            if isinstance(style.get(key), str) and _HEX.match(style[key].strip()):
                cur[key] = style[key].strip().lower()
        for key in ("opacity", "bg_opacity"):
            if key in style:
                cur[key] = _clamp(style[key], 0.0, 1.0, cur[key])

    elements = raw.get("elements")
    if isinstance(elements, dict):
        for name, patch in elements.items():
            if name not in hud["elements"] or not isinstance(patch, dict):
                continue
            cur = hud["elements"][name]
            if "enabled" in patch:
                cur["enabled"] = bool(patch["enabled"])
            if "size" in patch:
                cur["size"] = int(_clamp(patch["size"], MIN_SIZE, MAX_SIZE, cur["size"]))
            pos = str(patch.get("position", "")).upper()
            if pos in ANCHORS:
                cur["position"] = pos

    formats = raw.get("formats")
    if isinstance(formats, dict):
        for name in hud["formats"]:
            value = formats.get(name)
            if isinstance(value, str) and value.strip() and len(value) <= 40:
                hud["formats"][name] = value.strip()

    weather = raw.get("weather")
    if isinstance(weather, dict):
        cur = hud["weather"]
        if "lat" in weather or "lon" in weather:
            lat, lon = weather.get("lat"), weather.get("lon")
            if lat in (None, "") or lon in (None, ""):
                cur["lat"] = cur["lon"] = None
            else:
                cur["lat"] = round(_clamp(lat, -90.0, 90.0, 0.0), 4)
                cur["lon"] = round(_clamp(lon, -180.0, 180.0, 0.0), 4)
        if isinstance(weather.get("place"), str):
            cur["place"] = weather["place"].strip()[:120]

    if "margin_pct" in raw:
        hud["margin_pct"] = _clamp(raw["margin_pct"], 0.0, 20.0, hud["margin_pct"])
    if raw.get("lang") in ("pt", "en"):
        hud["lang"] = raw["lang"]
    return hud


def load_hud(repo: Any) -> dict[str, Any]:
    """Return the effective HUD layout (stored, or derived from legacy keys)."""
    stored = None
    try:
        stored = repo.get_app_config(HUD_KEY, None)
    except Exception:
        stored = None
    if isinstance(stored, dict):
        hud = normalize_hud(stored, default_hud())
        # The legacy switches stay authoritative for on/off, so the Home
        # Assistant "clock"/"text" switches (MQTT) keep working.
        els = hud["elements"]
        els["clock"]["enabled"] = _get_bool(repo, "viewer.show_clock", els["clock"]["enabled"])
        if not _get_bool(repo, "viewer.show_text_enabled", True):
            for name in PHOTO_ELEMENTS:
                els[name]["enabled"] = False
        return hud
    return _legacy_hud(repo)


def save_hud(repo: Any, patch: Any) -> dict[str, Any]:
    """Merge ``patch`` into the stored layout, persist it and mirror legacy keys."""
    hud = normalize_hud(patch, load_hud(repo))
    repo.set_app_config(HUD_KEY, hud)
    els = hud["elements"]
    tokens = [
        token
        for token, element in (("description", "description"), ("date", "photo_date"),
                               ("location", "location"))
        if els[element]["enabled"]
    ]
    repo.set_app_config("viewer.text_overlay_format", " ".join(tokens))
    repo.set_app_config("viewer.show_text_enabled", bool(tokens))
    repo.set_app_config("viewer.show_clock", bool(els["clock"]["enabled"]))
    repo.set_app_config("viewer.clock_text_sz", int(els["clock"]["size"]))
    repo.set_app_config("viewer.clock_color", hud["style"]["color"])
    repo.set_app_config("viewer.clock_opacity", float(hud["style"]["opacity"]))
    repo.set_app_config("viewer.clock_format", hud["formats"]["clock"])
    repo.set_app_config("viewer.show_text_fm", hud["formats"]["photo_date"])
    return hud


def any_enabled(hud: dict[str, Any]) -> bool:
    return any(element.get("enabled") for element in hud.get("elements", {}).values())


_NAMES = {
    "pt": {
        "a": ("seg", "ter", "qua", "qui", "sex", "sáb", "dom"),
        "A": ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira",
              "sábado", "domingo"),
        "b": ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"),
        "B": ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
              "setembro", "outubro", "novembro", "dezembro"),
    },
}


def format_dt(value: Any, fmt: str, lang: str = "pt") -> str:
    """strftime with weekday/month names in ``lang`` (no process locale switch).

    The container only ships the en_US locale, and the clock is formatted many
    times a second, so names are substituted here instead of via setlocale.
    """
    names = _NAMES.get(lang)
    if names:
        out: list[str] = []
        i = 0
        while i < len(fmt):
            ch = fmt[i]
            if ch == "%" and i + 1 < len(fmt):
                code = fmt[i + 1]
                if code in ("a", "A"):
                    out.append(names[code][value.weekday()].replace("%", "%%"))
                elif code in ("b", "B"):
                    out.append(names[code][value.month - 1].replace("%", "%%"))
                else:
                    out.append(fmt[i:i + 2])
                i += 2
                continue
            out.append(ch)
            i += 1
        fmt = "".join(out)
    try:
        return value.strftime(fmt)
    except (ValueError, TypeError):
        return value.strftime("%d/%m/%Y")
