"""World-aligned pixel grid: the whole map is ONE pixel canvas; each hex tile is a window onto it.

Hex centres sit at irrational pixel offsets (horizontal spacing is sqrt(3) * s), so per-tile
canvases centred on the hex would each have their own sub-pixel grid, and neighbours' pixels and
blocks would never line up. Instead every tile's canvas starts at an integer world pixel:

    origin = (floor(cx - s) - 1, floor(cy - s) - 1),  size C = P + 3   (P = tile_px, s = P / 2)

so pixel (i, j) of any tile covers world pixel (origin + (i, j)). Two tiles that paint the same
world pixel paint it identically, and hex borders are clean geometric cuts through a shared grid.
The frontend computes the same origin to map texture UVs onto the hex face.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from hexworld.hex import DIRECTION_ANGLES, SQRT3, Hex

PAD = 1


@dataclass(frozen=True)
class TileCanvas:
    h: Hex
    P: int

    @property
    def s(self) -> float:
        return self.P / 2.0

    @property
    def C(self) -> int:
        return self.P + 2 * PAD + 1

    @property
    def center(self) -> tuple[float, float]:
        return self.h.to_pixel(self.s)

    @property
    def origin(self) -> tuple[int, int]:
        cx, cy = self.center
        return math.floor(cx - self.s) - PAD, math.floor(cy - self.s) - PAD

    def world_xy(self) -> tuple[np.ndarray, np.ndarray]:
        """World pixel-centre coordinates of every canvas pixel (C x C arrays)."""
        ox, oy = self.origin
        idx = np.arange(self.C) + 0.5
        return np.meshgrid(ox + idx, oy + idx)

    def local_xy(self) -> tuple[np.ndarray, np.ndarray]:
        """Pixel centres relative to the hex centre."""
        wx, wy = self.world_xy()
        cx, cy = self.center
        return wx - cx, wy - cy

    def mask(self) -> np.ndarray:
        return _mask(self.h.q, self.h.r, self.P)

    def to_canvas(self, wx: float, wy: float) -> tuple[int, int]:
        ox, oy = self.origin
        return int(math.floor(wx - ox)), int(math.floor(wy - oy))


@lru_cache(maxsize=4096)
def _mask(q: int, r: int, P: int) -> np.ndarray:
    """Pixels whose centres lie inside this hex (pointy-top, circumradius s)."""
    x, y = TileCanvas(Hex(q, r), P).local_xy()
    s = P / 2.0
    ax, ay = np.abs(x), np.abs(y)
    m = (ax <= SQRT3 / 2 * s + 1e-6) & (ay <= s - ax / SQRT3 + 1e-6)
    m.setflags(write=False)
    return m


def edge_band(
    rgba: np.ndarray, canvas: TileCanvas, edge: int, n: int = 3, depth: float | None = None
) -> list[np.ndarray]:
    """Opaque RGB pixels of the band just inside `edge`, split into `n` segments along it
    (dir-30 corner -> dir+30 corner). Each item is a (k, 3) float array."""
    depth = depth if depth is not None else max(3.0, canvas.P / 8)
    x, y = canvas.local_xy()
    ang = math.radians(DIRECTION_ANGLES[edge])
    nx, ny = math.cos(ang), math.sin(ang)
    apothem = canvas.s * SQRT3 / 2
    inward = apothem - (x * nx + y * ny)  # 0 on the edge line, growing towards the centre
    along = (-x * ny + y * nx) / canvas.s  # -0.5 .. 0.5 between the two corners
    k = np.floor((along + 0.5) * n).astype(int)
    ok = (rgba[..., 3] > 0) & (inward >= -0.5) & (inward <= depth) & (k >= 0) & (k < n)
    return [rgba[ok & (k == seg), :3].astype(np.float32) for seg in range(n)]


def _palette_gap(a: np.ndarray, b: np.ndarray) -> float:
    """Mean distance from each pixel of `a` to the nearest colour present in `b`."""
    cols, counts = np.unique(b.astype(np.uint8), axis=0, return_counts=True)
    cols = cols[counts >= 2] if (counts >= 2).any() else cols
    ua, inv = np.unique(a.astype(np.uint8), axis=0, return_inverse=True)
    d = np.linalg.norm(ua[:, None, :].astype(np.float32) - cols[None, :, :].astype(np.float32), axis=-1).min(
        1
    )
    return float(d[inv.ravel()].mean())


def seam_delta(a: np.ndarray, ca: TileCanvas, edge: int, b: np.ndarray, cb: TileCanvas) -> float:
    """0..1 discontinuity across the edge shared by tile a (its `edge`) and tile b.

    Per segment of the edge, the two sides' bands are compared as colour sets (symmetric nearest-
    colour distance): a texture that continues across the edge uses the same colours on both sides
    (~0) even though individual pixels differ, while a terrain change (grass | water) scores high."""
    sa = edge_band(a, ca, edge)
    sb = edge_band(b, cb, (edge + 3) % 6)[::-1]
    ds = [
        min(1.0, (_palette_gap(x, y) + _palette_gap(y, x)) / 2 / 150.0)
        for x, y in zip(sa, sb, strict=True)
        if len(x) >= 4 and len(y) >= 4
    ]
    return float(round(sum(ds) / len(ds), 4)) if ds else 1.0
