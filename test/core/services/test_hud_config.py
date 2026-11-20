"""Tests for the HDMI HUD layout config."""

from datetime import datetime
from typing import Any

from picframe.core.services.hud_config import (
    HUD_KEY,
    default_hud,
    format_dt,
    load_hud,
    normalize_hud,
    save_hud,
)


class FakeRepo:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = dict(values or {})

    def get_app_config(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def get_app_config_bool(self, key: str, default: bool = False) -> bool:
        value = self.values.get(key, default)
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def set_app_config(self, key: str, value: Any) -> None:
        self.values[key] = value


def test_legacy_keys_become_the_initial_layout() -> None:
    repo = FakeRepo(
        {
            "viewer.text_overlay_format": "description date",
            "viewer.show_clock": True,
            "viewer.clock_top_bottom": "B",
            "viewer.clock_justify": "R",
            "viewer.clock_text_sz": 120,
            "viewer.clock_opacity": 0.4,
            "viewer.show_text_sz": 40,
        }
    )
    hud = load_hud(repo)
    els = hud["elements"]
    assert els["description"]["enabled"] and els["photo_date"]["enabled"]
    assert not els["location"]["enabled"]
    assert els["clock"] == {"enabled": True, "size": 120, "position": "BR"}
    # Item 1: the clock's translucency is the shared style.
    assert hud["style"]["opacity"] == 0.4


def test_normalize_rejects_bad_values() -> None:
    hud = normalize_hud(
        {
            "style": {"font": "comic", "color": "red", "opacity": 7},
            "elements": {
                "clock": {"size": 5000, "position": "XX"},
                "weather": {"enabled": "yes", "position": "tl"},
                "bogus": {"enabled": True},
            },
            "weather": {"lat": 200, "lon": "-38.5"},
        }
    )
    base = default_hud()
    assert hud["style"]["font"] == base["style"]["font"]
    assert hud["style"]["color"] == base["style"]["color"]
    assert hud["style"]["opacity"] == 1.0
    assert hud["elements"]["clock"]["size"] == 400
    assert hud["elements"]["clock"]["position"] == base["elements"]["clock"]["position"]
    assert hud["elements"]["weather"] == {"enabled": True, "size": 48, "position": "TL"}
    assert "bogus" not in hud["elements"]
    assert hud["weather"]["lat"] == 90.0 and hud["weather"]["lon"] == -38.5


def test_save_merges_and_mirrors_legacy_keys() -> None:
    repo = FakeRepo({"viewer.show_clock": True})
    save_hud(repo, {"elements": {"location": {"enabled": True}, "clock": {"enabled": False}}})
    stored = repo.values[HUD_KEY]
    assert stored["elements"]["location"]["enabled"] is True
    assert repo.values["viewer.show_clock"] is False
    assert repo.values["viewer.text_overlay_format"] == "description date location"
    # A later partial patch keeps earlier choices.
    save_hud(repo, {"style": {"color": "#FFCC00"}})
    hud = load_hud(repo)
    assert hud["style"]["color"] == "#ffcc00"
    assert hud["elements"]["location"]["enabled"] is True


def test_legacy_switches_stay_authoritative_for_on_off() -> None:
    repo = FakeRepo()
    save_hud(repo, {})
    repo.values["viewer.show_clock"] = False  # e.g. Home Assistant switch
    repo.values["viewer.show_text_enabled"] = False
    hud = load_hud(repo)
    assert hud["elements"]["clock"]["enabled"] is False
    assert not hud["elements"]["description"]["enabled"]


def test_format_dt_uses_portuguese_names() -> None:
    dt = datetime(2026, 11, 20, 18, 5)
    assert format_dt(dt, "%a, %d %b", "pt") == "sex, 20 nov"
    assert format_dt(dt, "%A %d de %B", "pt") == "sexta-feira 20 de novembro"
    assert format_dt(dt, "%H:%M", "pt") == "18:05"
    assert format_dt(dt, "100%% %d", "pt") == "100% 20"
