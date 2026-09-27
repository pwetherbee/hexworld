"""Relief: the ground layer is flat colour (surfaces only); height lives in the heightmap layer.

- In 3D, the frontend extrudes the heightmap into terraces with real walls; building walls get
  pixel-art facades (windows per floor) from the facade layer and the facade codes below.
- In 2D (review contact sheets, thumbnails, the material artist's preview) `relief_shade` paints
  the same relief in a 3/4 view: below every rise its wall is drawn (LEVEL_PX pixels per level,
  capped for tall buildings), coloured from the surface above it or from the building's facade.

Heightmap PNG (RGB, tile canvas):
  R = relief level 0..MAX_LEVEL (terrain plus buildings: towers reach high)
  G = flags: FLAG_FORMAT (always set in this format) | FLAG_LIQUID (liquid surface, animated)
  B = facade code of a building pixel: style << 5 | lit (0 = not a building)
  G's low 6 bits = relief levels per floor of a building pixel (0 = 1: the overworld; a drilled
  layer's buildings are the parent's, zoomed, so one floor spans several levels)
Older heightmaps (R = level * 40, G = 0/255) are still read.

In memory, levels are int32 with the level in the low bits, LIQUID_BIT for liquids and the facade
code in FACADE_SHIFT..; `split_levels` / `facade_codes` separate them.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

MAX_LEVEL = 250
LEVEL_PX = 2
MAX_WALL_PX = 14  # 2D previews cap tall walls so a tower doesn't paint over the tile to its north
LEVEL_MASK = 1023
LIQUID_BIT = 1 << 10
FACADE_SHIFT = 12
FLOOR_SHIFT = FACADE_SHIFT + 8  # levels per floor (6 bits), above the facade code
FLAG_FORMAT, FLAG_LIQUID = 64, 128
LEGACY_SCALE = 40

# facade styles (code >> 5); the frontend shader draws the same set
FACADE_STYLES = ("none", "punched", "glass", "bands", "victorian", "industrial", "stone")


def facade_code(style: str, lit: float) -> int:
    s = FACADE_STYLES.index(style) if style in FACADE_STYLES else 1
    return (s << 5) | int(round(max(0.0, min(1.0, lit)) * 31))


def split_levels(h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h = h.astype(np.int32)
    return h & LEVEL_MASK, (h & LIQUID_BIT) > 0


def facade_codes(h: np.ndarray) -> np.ndarray:
    return (h.astype(np.int32) >> FACADE_SHIFT) & 0xFF


def floor_scales(h: np.ndarray) -> np.ndarray:
    return (h.astype(np.int32) >> FLOOR_SHIFT) & 63


def levels_to_png(levels: np.ndarray) -> bytes:
    lv, liquid = split_levels(levels)
    rgb = np.zeros((*lv.shape, 3), np.uint8)
    rgb[..., 0] = np.clip(lv, 0, MAX_LEVEL)
    rgb[..., 1] = FLAG_FORMAT | np.where(liquid, FLAG_LIQUID, 0) | floor_scales(levels)
    rgb[..., 2] = facade_codes(levels)
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="PNG")
    return buf.getvalue()


def _decode(png: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(levels, liquid, facade code | levels per floor << 8)."""
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.int32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    if ((g & FLAG_FORMAT) > 0).all() and not (g == 255).any():
        return r, (g & FLAG_LIQUID) > 0, b | ((g & 63) << 8)
    return np.rint(r / LEGACY_SCALE).astype(np.int32), g > 127, np.zeros_like(r)  # legacy


def load_levels(png: bytes) -> np.ndarray:
    """Relief levels (without flags)."""
    return _decode(png)[0]


def load_heightmap(png: bytes) -> np.ndarray:
    """Levels with the liquid bit and facade codes packed back in (the in-memory form)."""
    lv, liquid, code = _decode(png)
    return lv | np.where(liquid, LIQUID_BIT, 0) | (code << FACADE_SHIFT)


def relief_shade(
    rgba: np.ndarray, levels: np.ndarray, level_px: int = LEVEL_PX, facade: np.ndarray | None = None
) -> np.ndarray:
    """3/4-view walls painted onto a flat ground (RGBA or RGB, same canvas as `levels`). With a
    facade image (wall colours of buildings) and facade codes in `levels`, building walls get
    windows, so reviewers see buildings rather than cliffs."""
    H, W = levels.shape
    out = rgba.astype(np.float32).copy()
    lv = split_levels(levels)[0]
    codes = facade_codes(levels)
    wall_at = np.zeros((H, W), np.int32)  # 1-based row inside the wall of the rise above
    wall_rows = np.zeros((H, W), np.int32)
    for dy in range(1, MAX_WALL_PX + 2):
        above = np.pad(lv, ((dy, 0), (0, 0)), mode="edge")[:H]
        rows = np.minimum(level_px * (above - lv), MAX_WALL_PX) + 1
        hit = (above > lv) & (rows >= dy) & (wall_at == 0)
        wall_at[hit] = dy
        wall_rows[hit] = rows[hit]
    wall = wall_at > 0
    if not wall.any():
        return rgba.copy()
    jj, ii = np.nonzero(wall)
    src_rows = np.clip(jj - wall_at[jj, ii] - 1, 0, H - 1)  # the top surface just above the wall
    if rgba.shape[-1] == 4:  # the rise lies outside this (masked) tile: nothing to colour it from
        keep = rgba[src_rows, ii, 3] > 0
        jj, ii, src_rows = jj[keep], ii[keep], src_rows[keep]
        wall = np.zeros_like(wall)
        wall[jj, ii] = True
    src = out[src_rows, ii, :3]
    face = src * 0.6
    stripe = ((ii % 4) == 0)[:, None]
    face = np.where(stripe, face * 0.85, face)
    top = (wall_at[jj, ii] == 1)[:, None]
    face = np.where(top, np.minimum(255, src * 0.78), face)
    if facade is not None:
        code = codes[src_rows, ii]
        bld = code > 0
        wallc = facade[src_rows, ii, :3].astype(np.float32) * 0.82
        row = wall_at[jj, ii]
        win = bld & (ii % 3 == 1) & (row % 3 == 2) & (row < wall_rows[jj, ii])
        lit = (np.sin(ii * 12.9898 + row * 78.233) * 43758.5453) % 1.0 < (code & 31) / 31.0
        winc = np.where(lit[:, None], np.array([255.0, 214.0, 120.0]), np.array([40.0, 52.0, 70.0]))
        face = np.where(bld[:, None], np.where(win[:, None], winc, wallc), face)
    foot = (wall_at[jj, ii] == wall_rows[jj, ii])[:, None]
    face = np.where(foot, face * 0.6, face)
    out[jj, ii, :3] = face
    below = np.pad(wall, ((1, 0), (0, 0)))[:H] & ~wall
    out[below, :3] *= 0.72
    if rgba.shape[-1] == 4:
        out[..., 3] = rgba[..., 3]
    return np.clip(out, 0, 255).astype(np.uint8)
