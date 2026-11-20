"""
HUD Renderer Component.

Draws the HDMI texts laid out by :mod:`picframe.core.services.hud_config`:
per-photo elements (description, location, photo date) that fade with each
photo, and live elements (clock, today's date, weather) that stay on screen.

Every element sits on one of six anchors (top/bottom x left/centre/right);
elements sharing an anchor stack vertically in ``STACK_ORDER``. All texts use
one shared style (font, colour, opacity); only the size is per element.

GL objects (FixedString textures, band sprites) are only created inside
``draw()``, i.e. on the render thread; ``set_*`` calls just mark the layout
dirty, so they are safe from any thread.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any

import numpy as np
import pi3d

from picframe.core.renderers.components.clock_renderer import hex_rgb
from picframe.core.services.hud_config import (
    FONTS,
    LIVE_ELEMENTS,
    PHOTO_ELEMENTS,
    STACK_ORDER,
    default_hud,
    format_dt,
)
from picframe.core.services.weather_service import WeatherService, format_temp

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SHADOW_RADIUS = 3

# A line is a tuple of segments; a segment is (text, font_path, colour, opacity).
# colour None = the shared style colour; opacity None = the shared style opacity.
# A text starting with ICON_PREFIX is a colour weather icon (kind after the prefix).
ICON_PREFIX = "\x00icon:"
Segment = tuple[str, str, str | None, float | None]
Line = tuple[Segment, ...]


class _Block:
    """One drawable piece of a line: a FixedString or an icon sprite."""

    __slots__ = ("sprite", "width", "height", "sprite_w", "holder")

    def __init__(self, sprite: Any, width: float, height: float, holder: Any = None,
                 sprite_w: float | None = None) -> None:
        self.sprite = sprite
        self.width = width  # horizontal space taken in the line (may include a gap)
        self.height = height
        self.sprite_w = width if sprite_w is None else sprite_w  # drawn width
        self.holder = holder  # keeps the FixedString/texture alive


class _BuiltLine:
    __slots__ = ("blocks", "width", "height", "live")

    def __init__(self, blocks: list[Any], width: float, height: float, live: bool) -> None:
        self.blocks = blocks
        self.width = width
        self.height = height
        self.live = live


class HudRenderer:
    """Renders the HUD texts on the pi3d display."""

    def __init__(
        self,
        display: Any,
        shader: Any,
        fonts_dir: str,
        fallback_font: str,
        render_rect: tuple[int, int, int, int] | None = None,
        locale: str = "en_US.utf8",
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._display = display
        self._shader = shader
        self._fonts_dir = fonts_dir
        self._fallback_font = fallback_font
        self._render_rect = render_rect
        self._locale = locale
        self._lock = threading.Lock()

        self._hud: dict[str, Any] = default_hud()
        self._photo_fields: dict[str, str] = {}
        self._photo_visible = True

        self._dirty = True
        self._live_signature: tuple[Any, ...] | None = None
        self._built: list[tuple[str, _BuiltLine]] = []  # (anchor, line)
        self._bands: list[tuple[Any, bool]] = []  # (sprite, live)
        self._band_textures: dict[tuple[Any, ...], Any] = {}

    # -- configuration (any thread) -----------------------------------------

    def set_hud(self, hud: dict[str, Any], locale: str | None = None) -> None:
        with self._lock:
            self._hud = hud or default_hud()
            if locale:
                self._locale = locale
            self._dirty = True
        weather = self._hud.get("weather") or {}
        if self._hud["elements"]["weather"]["enabled"]:
            WeatherService.instance().set_location(weather.get("lat"), weather.get("lon"))

    def set_photo_fields(self, fields: dict[str, str], visible: bool) -> None:
        with self._lock:
            if fields != self._photo_fields or visible != self._photo_visible:
                self._photo_fields = dict(fields)
                self._photo_visible = visible
                self._dirty = True

    def has_photo_text(self) -> bool:
        with self._lock:
            els = self._hud["elements"]
            return self._photo_visible and any(
                els[name]["enabled"] and self._photo_fields.get(name) for name in PHOTO_ELEMENTS
            )

    # -- live content --------------------------------------------------------

    def _fmt_now(self, fmt: str) -> str:
        return format_dt(datetime.now(), fmt, self._hud.get("lang", "pt"))

    def _live_texts(self) -> dict[str, Any]:
        els = self._hud["elements"]
        formats = self._hud.get("formats", {})
        out: dict[str, Any] = {}
        if els["clock"]["enabled"]:
            out["clock"] = self._fmt_now(formats.get("clock", "%H:%M"))
        if els["today_date"]["enabled"]:
            out["today_date"] = self._fmt_now(formats.get("today_date", "%d/%m/%Y"))
        if els["weather"]["enabled"]:
            data = WeatherService.instance().current()
            if data:
                out["weather"] = (
                    data.get("icon") or "",
                    data.get("kind") or "",
                    format_temp(data.get("temp")),
                    format_temp(data.get("tmax")),
                    format_temp(data.get("tmin")),
                )
        return out

    def has_changed(self) -> bool:
        """True when a live text changed (minute tick, new weather) or layout is dirty."""
        with self._lock:
            if self._dirty:
                return True
            return tuple(sorted(self._live_texts().items())) != self._live_signature

    # -- layout --------------------------------------------------------------

    def _font(self) -> str:
        name = self._hud["style"].get("font", "noto")
        path = FONTS.get(name, FONTS["noto"])
        if not os.path.isabs(path):
            path = os.path.join(self._fonts_dir, path)
        return path if os.path.isfile(path) else self._fallback_font

    def _lines_for(self, name: str, live: dict[str, Any], font: str) -> list[Line]:
        if name == "weather":
            reading = live.get("weather")
            if not reading:
                return []
            glyph, kind, temp, tmax, tmin = reading
            cfg = self._hud.get("weather") or {}
            opacity = cfg.get("opacity")  # None = follow the shared style
            first: list[Segment] = []
            if cfg.get("icon_style", "color") == "color" and kind:
                first.append((ICON_PREFIX + kind, "", None, opacity))
            elif glyph:
                first.append((glyph + " ", DEJAVU, None, opacity))
            first.append((temp, font, None, opacity))
            second: Line = (
                ("↑", DEJAVU, cfg.get("max_color") or "#ef4444", opacity),
                (f"{tmax}  ", font, None, opacity),
                ("↓", DEJAVU, cfg.get("min_color") or "#3b82f6", opacity),
                (tmin, font, None, opacity),
            )
            return [tuple(first), second]
        if name in LIVE_ELEMENTS:
            text = live.get(name)
            return [((text, font, None, None),)] if text else []
        if not self._photo_visible:
            return []
        text = " ".join(str(self._photo_fields.get(name) or "").split())
        return [((text, font, None, None),)] if text else []

    def _render_bounds(self) -> tuple[float, float, float, float]:
        """(center_x, center_y, width, height) in pi3d coordinates."""
        if self._render_rect is None:
            return 0.0, 0.0, float(self._display.width), float(self._display.height)
        x, y, width, height = self._render_rect
        center_x = -int(self._display.width) / 2 + x + width / 2
        center_y = int(self._display.height) / 2 - y - height / 2
        return center_x, center_y, float(width), float(height)

    def _icon_block(self, kind: str, size: int, opacity: float) -> _Block | None:
        """Colour weather icon as a textured sprite, sized like a text line."""
        try:
            from picframe.core.renderers.components.weather_icons import render_icon

            px = max(12, int(size * 1.35))
            image = render_icon(kind, px, round(opacity, 2))
            texture = pi3d.Texture(np.array(image), blend=True, mipmap=False)
            try:
                camera = pi3d.Camera.instance()
            except AttributeError:
                camera = None
            if camera is None:
                camera = pi3d.Camera(is_3d=False)
            sprite = pi3d.Sprite(camera=camera, w=px, h=px)
            sprite.set_shader(self._shader)
            sprite.set_textures([texture])
            # a little breathing room before the temperature
            return _Block(sprite, px + size * 0.15, px, holder=texture, sprite_w=px)
        except Exception as exc:
            self._logger.error("HUD: could not draw weather icon %r: %s", kind, exc)
            return None

    def _build_line(self, line: Line, size: int, live: bool) -> _BuiltLine | None:
        style = self._hud["style"]
        style_opacity = max(0.0, min(1.0, float(style.get("opacity", 1.0))))
        blocks: list[_Block] = []
        width = height = 0.0
        for text, font, colour, seg_opacity in line:
            if not text:
                continue
            opacity = style_opacity if seg_opacity is None else float(seg_opacity)
            if text.startswith(ICON_PREFIX):
                block = self._icon_block(text[len(ICON_PREFIX):], size, opacity)
                if block is None:
                    continue
            else:
                rgba = (*hex_rgb(colour or style.get("color", "#f8fafc")), int(255 * opacity))
                try:
                    fixed = pi3d.FixedString(
                        font,
                        text,
                        font_size=int(size),
                        shadow_radius=SHADOW_RADIUS,
                        shader=self._shader,
                        justify="L",
                        color=rgba,
                    )
                except Exception as exc:
                    self._logger.error("HUD: could not render %r: %s", text, exc)
                    continue
                block = _Block(fixed.sprite, float(fixed.sprite.width),
                               float(fixed.sprite.height), holder=fixed)
            blocks.append(block)
            width += block.width
            height = max(height, block.height)
        if not blocks:
            return None
        return _BuiltLine(blocks, width, height, live)

    def _rebuild(self, live: dict[str, Any]) -> None:
        hud = self._hud
        els = hud["elements"]
        font = self._font()
        center_x, center_y, width, height = self._render_bounds()
        margin_pct = float(hud.get("margin_pct", 3.0)) / 100.0
        margin_x, margin_y = width * margin_pct, height * margin_pct

        stacks: dict[str, list[_BuiltLine]] = {}
        for name in STACK_ORDER:
            element = els[name]
            if not element["enabled"]:
                continue
            is_live = name in LIVE_ELEMENTS
            for index, line in enumerate(self._lines_for(name, live, font)):
                size = element["size"]
                if name == "weather" and index == 1:
                    size = max(12, int(size * 0.6))
                built = self._build_line(line, size, is_live)
                if built is not None:
                    stacks.setdefault(element["position"], []).append(built)

        self._built = []
        edge_heights = {"T": [0.0, False, False], "B": [0.0, False, False]}  # height, live, photo
        for anchor, lines in stacks.items():
            vertical, horizontal = anchor[0], anchor[1]
            total = sum(line.height for line in lines)
            if vertical == "T":
                cursor = center_y + height / 2 - margin_y
            else:
                cursor = center_y - height / 2 + margin_y + total
            for line in lines:
                y = cursor - line.height / 2
                cursor -= line.height
                if horizontal == "L":
                    left = center_x - width / 2 + margin_x
                elif horizontal == "R":
                    left = center_x + width / 2 - margin_x - line.width
                else:
                    left = center_x - line.width / 2
                for block in line.blocks:
                    block.sprite.position(left + block.sprite_w / 2, y, 0.1)
                    left += block.width
                self._built.append((anchor, line))
            edge = edge_heights[vertical]
            edge[0] = max(edge[0], total + 2 * margin_y)
            edge[1] = edge[1] or any(line.live for line in lines)
            edge[2] = edge[2] or any(not line.live for line in lines)

        self._bands = []
        bg_opacity = float(hud["style"].get("bg_opacity", 0.0))
        if bg_opacity > 0:
            for vertical, (band_h, has_live, has_photo) in edge_heights.items():
                if band_h <= 0:
                    continue
                sprite = self._band_sprite(vertical, band_h, bg_opacity, center_x, center_y,
                                           width, height)
                if sprite is not None:
                    self._bands.append((sprite, has_live))

    def _band_sprite(
        self, vertical: str, band_h: float, bg_opacity: float,
        center_x: float, center_y: float, width: float, height: float,
    ) -> Any:
        rgb = hex_rgb(self._hud["style"].get("bg_color", "#000000"), (0, 0, 0))
        key = (vertical, int(height), round(bg_opacity, 3), rgb)
        texture = self._band_textures.get(key)
        if texture is None:
            rows = max(2, int(height))
            alpha = np.linspace(0.0, 255.0 * bg_opacity, rows, dtype=np.float32)
            if vertical == "T":
                alpha = alpha[::-1]  # opaque at the top edge, fading downwards
            rgba = np.zeros((rows, 1, 4), dtype=np.uint8)
            rgba[:, :, 0], rgba[:, :, 1], rgba[:, :, 2] = rgb
            rgba[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)[:, np.newaxis]
            texture = pi3d.Texture(rgba, blend=True, free_after_load=True)
            self._band_textures = {key: texture}
        try:
            camera = pi3d.Camera.instance()
        except AttributeError:
            camera = None
        if camera is None:
            camera = pi3d.Camera(is_3d=False)
        sprite = pi3d.Sprite(camera=camera, w=1, h=1)
        sprite.set_shader(self._shader)
        sprite.set_textures([texture])
        band_h = min(band_h, height)
        if vertical == "T":
            y = center_y + height / 2 - band_h / 2
        else:
            y = center_y - height / 2 + band_h / 2
        sprite.position(center_x, y, 0.3)
        sprite.scale(width, band_h, 1.0)
        return sprite

    # -- drawing (render thread) ---------------------------------------------

    def draw(self, photo_alpha: float) -> None:
        with self._lock:
            live = self._live_texts()
            signature = tuple(sorted(live.items()))
            if self._dirty or signature != self._live_signature:
                try:
                    self._rebuild(live)
                except Exception as exc:
                    self._logger.error("HUD rebuild failed: %s", exc)
                    self._built, self._bands = [], []
                self._live_signature = signature
                self._dirty = False
            built, bands = self._built, self._bands

        photo_alpha = max(0.0, min(1.0, float(photo_alpha)))
        for sprite, live_band in bands:
            alpha = 1.0 if live_band else photo_alpha
            if alpha <= 0.0:
                continue
            sprite.set_alpha(alpha)
            sprite.draw()
        for _anchor, line in built:
            alpha = 1.0 if line.live else photo_alpha
            if alpha <= 0.0:
                continue
            for block in line.blocks:
                block.sprite.set_alpha(alpha)
                block.sprite.draw()
