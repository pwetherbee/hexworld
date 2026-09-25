"""Render map regions: neighbor-context canvases (for inpainting + tile-agent vision) and
labeled review composites (for the super's batched vision review)."""

from __future__ import annotations

import io
import math
from collections.abc import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from hexworld.art.grid import TileCanvas
from hexworld.hex import SQRT3, Hex

EMPTY_FILL = (24, 26, 34, 255)
BG = (10, 11, 16, 255)
CANDIDATE_OUTLINE = (255, 0, 220, 255)


def hex_polygon(cx: float, cy: float, s: float) -> list[tuple[float, float]]:
    return [
        (cx + s * math.cos(math.radians(-30 + 60 * i)), cy + s * math.sin(math.radians(-30 + 60 * i)))
        for i in range(6)
    ]


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def render_region(
    tiles: dict[Hex, np.ndarray],
    *,
    tile_px: int,
    slots: Iterable[Hex] = (),
    labels: dict[Hex, int] | None = None,
    scale: int = 4,
    center: Hex | None = None,
    extent_px: int | None = None,
) -> Image.Image:
    """Draw tile canvases (world-grid RGBA, see art/grid.py) at their exact world pixel origins,
    so the result is a pixel-perfect mosaic of the shared world grid.

    - `slots`: hexes drawn as dark empty hexes when they have no tile (holes / target slot)
    - `labels`: candidate hexes to outline in magenta with a number
    - `center` + `extent_px`: fixed square window (in tile pixels) centered on a hex; otherwise
      the canvas fits everything.
    """
    labels = labels or {}
    s = tile_px / 2.0
    hexes = set(tiles) | set(slots) | set(labels)
    if center is not None and extent_px is not None:
        cx0, cy0 = center.to_pixel(s)
        x0, y0 = math.floor(cx0 - extent_px / 2), math.floor(cy0 - extent_px / 2)
        w = h = extent_px
    else:
        xs, ys = zip(*(hx.to_pixel(s) for hx in hexes), strict=True) if hexes else ((0.0,), (0.0,))
        pad = tile_px * 0.6
        x0, y0 = math.floor(min(xs) - pad), math.floor(min(ys) - pad)
        w, h = int(max(xs) - x0 + pad), int(max(ys) - y0 + pad)

    canvas = Image.new("RGBA", (int(w), int(h)), BG)
    draw = ImageDraw.Draw(canvas)
    for hx in slots:
        if hx not in tiles:
            cx, cy = hx.to_pixel(s)
            draw.polygon(hex_polygon(cx - x0, cy - y0, s - 0.5), fill=EMPTY_FILL)
    for hx, arr in sorted(tiles.items(), key=lambda kv: kv[0].r):
        ox, oy = TileCanvas(hx, tile_px).origin
        canvas.alpha_composite(Image.fromarray(arr, "RGBA"), (ox - x0, oy - y0))

    if scale != 1:
        canvas = canvas.resize((canvas.width * scale, canvas.height * scale), Image.Resampling.NEAREST)
    if labels:
        draw = ImageDraw.Draw(canvas)
        font = _font(max(12, int(s * scale * 0.55)))
        for hx, label in labels.items():
            cx, cy = hx.to_pixel(s)
            cx, cy = (cx - x0) * scale, (cy - y0) * scale
            draw.polygon(
                hex_polygon(cx, cy, (s - 0.5) * scale), outline=CANDIDATE_OUTLINE, width=max(2, scale)
            )
            text = str(label)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad = 3 * scale // 2
            draw.rectangle(
                (cx - tw / 2 - pad, cy - th / 2 - pad, cx + tw / 2 + pad, cy + th / 2 + pad),
                fill=(0, 0, 0, 200),
            )
            draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), text, font=font, fill=CANDIDATE_OUTLINE)
    return canvas


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------- inpainting context

CONTEXT_TILES = 3  # context window = 3 x 3 tile widths around the target (covers ring 1)


def context_canvas(
    target: Hex, neighbors: dict[Hex, np.ndarray], tile_px: int, out_px: int
) -> tuple[bytes, bytes]:
    """(context PNG, mask PNG) at out_px: accepted neighbors drawn around an empty target hex;
    mask is white where the generator should paint (the target hex, slightly dilated so the
    model can blend a pixel or two into the seam)."""
    extent = tile_px * CONTEXT_TILES
    img = render_region(neighbors, tile_px=tile_px, slots=[target], center=target, extent_px=extent, scale=1)
    img = img.resize((out_px, out_px), Image.Resampling.NEAREST)
    f = out_px / extent
    mask = Image.new("L", (out_px, out_px), 0)
    ImageDraw.Draw(mask).polygon(hex_polygon(out_px / 2, out_px / 2, (tile_px / 2 + 1) * f), fill=255)
    return to_png(img.convert("RGB")), to_png(mask)


def crop_target(generated_png: bytes, tile_px: int) -> bytes:
    """Crop the target hex's square (tile_px equivalent) out of a context-window generation."""
    img = Image.open(io.BytesIO(generated_png)).convert("RGBA")
    f = img.width / (tile_px * CONTEXT_TILES)
    half = tile_px / 2 * f
    c = img.width / 2
    return to_png(img.crop((int(c - half), int(c - half), int(c + half), int(c + half))))


def neighborhood_png(target: Hex, neighbors: dict[Hex, np.ndarray], tile_px: int, scale: int = 3) -> bytes:
    """Small image for the tile agent's vision input: its slot (dark) with neighbors around."""
    slots = [target, *target.neighbors()]
    return to_png(
        render_region(
            neighbors, tile_px=tile_px, slots=slots, center=target, extent_px=int(tile_px * 2.9), scale=scale
        )
    )


def hex_width_px(tile_px: int) -> float:
    return SQRT3 / 2 * tile_px
