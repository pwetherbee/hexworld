"""Relief: the ground layer is flat colour (surfaces only); height lives in the heightmap layer.

- In 3D, the frontend extrudes the heightmap into terraces with real walls.
- In 2D (review contact sheets, thumbnails, the material artist's preview) `relief_shade` paints
  the same relief in a 3/4 view: below every rise its cliff face is drawn (LEVEL_PX pixels per
  level), coloured from the surface above it, with a dark foot and a soft shadow.

Heightmap PNGs are RGB on the tile canvas: R = level * LEVEL_SCALE, G = 255 where the surface is
a liquid (the 3D view animates it). In memory, `render_ground` returns levels with LIQUID_BIT set
on liquid pixels; `split_levels` separates them.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

LEVEL_SCALE = 40
MAX_LEVEL = 6
LEVEL_PX = 2
LIQUID_BIT = 64


def split_levels(h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h = h.astype(np.int32)
    return h & (LIQUID_BIT - 1), (h & LIQUID_BIT) > 0


def levels_to_png(levels: np.ndarray) -> bytes:
    lv, liquid = split_levels(levels)
    rgb = np.zeros((*lv.shape, 3), np.uint8)
    rgb[..., 0] = np.clip(lv, 0, MAX_LEVEL) * LEVEL_SCALE
    rgb[..., 1] = np.where(liquid, 255, 0)
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="PNG")
    return buf.getvalue()


def load_levels(png: bytes) -> np.ndarray:
    """Relief levels (without the liquid flag). Reads both RGB and older greyscale heightmaps."""
    img = Image.open(io.BytesIO(png))
    a = np.asarray(img.convert("RGB"), dtype=np.int32)[..., 0]
    return np.rint(a / LEVEL_SCALE).astype(np.int32)


def relief_shade(rgba: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """3/4-view cliffs painted onto a flat ground (RGBA or RGB, same canvas as `levels`)."""
    H, W = levels.shape
    out = rgba.astype(np.float32).copy()
    lv = split_levels(levels)[0]
    wall_at = np.zeros((H, W), np.int32)  # 1-based row inside the wall of the rise above
    wall_rows = np.zeros((H, W), np.int32)
    for dy in range(1, LEVEL_PX * MAX_LEVEL + 2):
        above = np.pad(lv, ((dy, 0), (0, 0)), mode="edge")[:H]
        rows = LEVEL_PX * (above - lv) + 1
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
    foot = (wall_at[jj, ii] == wall_rows[jj, ii])[:, None]
    face = np.where(foot, src * 0.36, face)
    out[jj, ii, :3] = face
    below = np.pad(wall, ((1, 0), (0, 0)))[:H] & ~wall
    out[below, :3] *= 0.72
    if rgba.shape[-1] == 4:
        out[..., 3] = rgba[..., 3]
    return np.clip(out, 0, 255).astype(np.uint8)
