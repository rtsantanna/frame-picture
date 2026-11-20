"""Colour weather icons drawn with PIL (no icon font or emoji font needed).

Shapes are drawn at 4x and downsampled for clean edges, with soft vertical
gradients and a light drop shadow so they read on any photo. The same images
are used by the HDMI HUD (as pi3d textures) and by the web panel preview
(served as PNG by the API).
"""

from __future__ import annotations

import io
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SS = 4  # supersampling factor

# WMO weather code -> icon kind
KINDS = (
    "clear_day", "clear_night", "partly_day", "partly_night", "cloudy", "fog",
    "drizzle", "rain", "showers_day", "snow", "storm",
)


def kind_for(code: int | None, is_day: bool = True) -> str:
    if code is None:
        return "cloudy"
    if code == 0:
        return "clear_day" if is_day else "clear_night"
    if code in (1, 2):
        return "partly_day" if is_day else "partly_night"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67):
        return "rain"
    if code in (80, 81, 82):
        return "showers_day" if is_day else "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    return "cloudy"


def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int],
              box: tuple[int, int, int, int] | None = None) -> Image.Image:
    """Vertical gradient (RGBA, opaque) spanning ``box`` (y0..y1) inside ``size``."""
    w, h = size
    y0, y1 = (box[1], box[3]) if box else (0, h)
    span = max(1, y1 - y0)
    column = Image.new("RGBA", (1, h))
    for y in range(h):
        t = min(1.0, max(0.0, (y - y0) / span))
        column.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    return column.resize((w, h))


def _paint(canvas: Image.Image, mask: Image.Image, top: tuple[int, int, int],
           bottom: tuple[int, int, int]) -> None:
    box = mask.getbbox()
    if not box:
        return
    canvas.alpha_composite(Image.composite(_gradient(canvas.size, top, bottom, box),
                                           Image.new("RGBA", canvas.size), mask))


def _mask(n: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    m = Image.new("L", (n, n), 0)
    return m, ImageDraw.Draw(m)


def _sun(canvas: Image.Image, cx: float, cy: float, r: float) -> None:
    n = canvas.size[0]
    m, d = _mask(n)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    _paint(canvas, m, (255, 214, 79), (255, 143, 0))


def _moon(canvas: Image.Image, cx: float, cy: float, r: float) -> None:
    n = canvas.size[0]
    m, d = _mask(n)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    cut, dc = _mask(n)
    dc.ellipse((cx - r * 0.35, cy - r * 1.15, cx + r * 1.45, cy + r * 0.65), fill=255)
    _paint(canvas, ImageChops.subtract(m, cut), (255, 226, 120), (255, 170, 40))


def _cloud(canvas: Image.Image, x: float, y: float, w: float,
           top: tuple[int, int, int] = (255, 255, 255),
           bottom: tuple[int, int, int] = (190, 205, 228)) -> None:
    """Cloud whose bounding box starts at (x, y) with width ``w`` (height ~0.62w)."""
    n = canvas.size[0]
    m, d = _mask(n)
    h = w * 0.62
    base_top = y + h * 0.45
    d.rounded_rectangle((x, base_top, x + w, y + h), radius=h * 0.28, fill=255)
    d.ellipse((x + w * 0.08, y + h * 0.28, x + w * 0.48, y + h * 0.92), fill=255)
    d.ellipse((x + w * 0.30, y, x + w * 0.80, y + h * 0.80), fill=255)
    d.ellipse((x + w * 0.62, y + h * 0.30, x + w * 0.98, y + h * 0.95), fill=255)
    _paint(canvas, m, top, bottom)


def _drops(canvas: Image.Image, xs: list[float], y: float, r: float) -> None:
    n = canvas.size[0]
    m, d = _mask(n)
    for x in xs:
        d.ellipse((x - r, y, x + r, y + 2 * r), fill=255)
        d.polygon([(x - r * 0.95, y + r * 0.9), (x + r * 0.95, y + r * 0.9), (x, y - r * 1.3)],
                  fill=255)
    _paint(canvas, m, (110, 180, 255), (30, 110, 230))


def _flakes(canvas: Image.Image, xs: list[float], y: float, r: float) -> None:
    n = canvas.size[0]
    m, d = _mask(n)
    for i, x in enumerate(xs):
        cy = y + (r * 0.9 if i % 2 else 0)
        for dx, dy in ((1, 0), (0.5, 0.87), (-0.5, 0.87)):
            d.line((x - dx * r, cy - dy * r, x + dx * r, cy + dy * r), fill=255, width=max(2, int(r / 3)))
    _paint(canvas, m, (255, 255, 255), (170, 210, 255))


def _bolt(canvas: Image.Image, x: float, y: float, s: float) -> None:
    n = canvas.size[0]
    m, d = _mask(n)
    d.polygon([(x + s * 0.55, y), (x + s * 0.1, y + s * 0.6), (x + s * 0.42, y + s * 0.6),
               (x + s * 0.25, y + s * 1.15), (x + s * 0.85, y + s * 0.42), (x + s * 0.52, y + s * 0.42),
               (x + s * 0.75, y)], fill=255)
    _paint(canvas, m, (255, 230, 90), (255, 160, 0))


def _fog_lines(canvas: Image.Image, x: float, y: float, w: float, s: float) -> None:
    n = canvas.size[0]
    m, d = _mask(n)
    for i, (a, b) in enumerate(((0.05, 0.85), (0.2, 1.0), (0.0, 0.7))):
        yy = y + i * s * 0.11
        d.rounded_rectangle((x + w * a, yy, x + w * b, yy + s * 0.055), radius=s * 0.03, fill=255)
    _paint(canvas, m, (235, 240, 248), (190, 200, 215))


def _draw(kind: str, n: int) -> Image.Image:
    c = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    s = float(n)
    if kind == "clear_day":
        _sun(c, s * 0.5, s * 0.5, s * 0.34)
    elif kind == "clear_night":
        _moon(c, s * 0.5, s * 0.5, s * 0.34)
    elif kind in ("partly_day", "partly_night", "showers_day"):
        if kind == "partly_night":
            _moon(c, s * 0.62, s * 0.34, s * 0.24)
        else:
            _sun(c, s * 0.64, s * 0.33, s * 0.24)
        _cloud(c, s * 0.08, s * 0.36, s * 0.70)
        if kind == "showers_day":
            _drops(c, [s * 0.32, s * 0.52], s * 0.83, s * 0.055)
    elif kind == "cloudy":
        _cloud(c, s * 0.30, s * 0.18, s * 0.62, (215, 222, 235), (160, 172, 192))
        _cloud(c, s * 0.06, s * 0.36, s * 0.72)
    elif kind == "fog":
        _cloud(c, s * 0.12, s * 0.16, s * 0.74)
        _fog_lines(c, s * 0.12, s * 0.70, s * 0.76, s)
    elif kind in ("drizzle", "rain"):
        _cloud(c, s * 0.12, s * 0.14, s * 0.76)
        xs = [s * 0.42, s * 0.62] if kind == "drizzle" else [s * 0.30, s * 0.50, s * 0.70]
        _drops(c, xs, s * 0.70, s * 0.06)
    elif kind == "snow":
        _cloud(c, s * 0.12, s * 0.14, s * 0.76)
        _flakes(c, [s * 0.32, s * 0.52, s * 0.72], s * 0.76, s * 0.07)
    elif kind == "storm":
        _cloud(c, s * 0.12, s * 0.12, s * 0.76, (205, 212, 228), (120, 132, 156))
        _bolt(c, s * 0.36, s * 0.56, s * 0.36)
    else:
        _cloud(c, s * 0.12, s * 0.22, s * 0.76)
    return c


@lru_cache(maxsize=64)
def render_icon(kind: str, size: int, opacity: float = 1.0) -> Image.Image:
    """RGBA icon of ``size`` px with a soft shadow; ``opacity`` scales alpha."""
    size = max(8, int(size))
    n = size * SS
    art = _draw(kind if kind in KINDS else "cloudy", n)
    alpha = art.getchannel("A")
    shadow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda a: int(a * 0.45)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(n * 0.025))
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.alpha_composite(shadow, (int(n * 0.012), int(n * 0.02)))
    out.alpha_composite(art)
    resample = getattr(Image, "Resampling", Image).LANCZOS
    out = out.resize((size, size), resample)
    if opacity < 1.0:
        a = out.getchannel("A").point(lambda v: int(v * max(0.0, opacity)))
        out.putalpha(a)
    return out


def icon_png(kind: str, size: int = 64) -> bytes:
    buf = io.BytesIO()
    render_icon(kind, size).save(buf, format="PNG")
    return buf.getvalue()
