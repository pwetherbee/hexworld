"""Ground renderer: interprets agent-written MaterialSpecs into crisp pixel-art ground layers.

Each pixel gets a *material*: the tile's biome in the middle and the edge contract's terrain in a
band along each edge, with a noise-perturbed boundary. Connectors (roads, rivers...) are materials
painted along curved paths to the edge midpoints. Every pattern op is evaluated in world pixel
coordinates, with seeds derived from the material name. Two tiles that agree on an edge therefore
paint identical pixels on both sides of it.

This module holds no content. What a material looks like comes from the material sub-agent
(`agents/artist.py`), via the world's session library.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np

from hexworld.agents.themes import base_color, hex_to_rgb, shade
from hexworld.domain.art import MaterialSpec, PatternOp
from hexworld.hex import DIRECTION_ANGLES, SQRT3, Hex

RAMP_FACTORS = {"outline": 0.42, "dark": 0.72, "base": 1.0, "light": 1.24, "hi": 1.5}


def ramp_hexes(color: str) -> list[str]:
    return [shade(color, f) for f in RAMP_FACTORS.values()]


@dataclass
class Ramp:
    tones: dict[str, np.ndarray]
    accent: np.ndarray

    def __getitem__(self, tone: str) -> np.ndarray:
        return self.accent if tone == "accent" else self.tones[tone]


def ramp_for(spec: MaterialSpec, palette: list[str] | None = None) -> Ramp:
    """Exact ramp colours. Deliberately NOT snapped to the (growing) world palette: a material must
    render identically before and after later runs extend the palette, or old/new tiles won't meet."""

    def snap(c: str) -> np.ndarray:
        return np.array(hex_to_rgb(c), dtype=np.float32)

    return Ramp(
        tones={t: snap(shade(spec.base_color, f)) for t, f in RAMP_FACTORS.items()},
        accent=snap(spec.accent_color),
    )


def fallback_material(name: str) -> MaterialSpec:
    """Used only if the library has no spec yet (e.g. the material agent failed): a plain,
    lightly patterned fill in a colour derived from the name."""
    return MaterialSpec(
        base_color=base_color(name),
        accent_color=shade(base_color(name), 1.4),
        base_tone="base",
        liquid=False,
        rank=4,
        boundary="lip",
        ops=[
            PatternOp(op="patches", tone="light", scale=7, amount=0.3, angle=0, pixels=[]),
            PatternOp(op="patches", tone="dark", scale=9, amount=0.25, angle=0, pixels=[]),
        ],
        scatter=[],
    )


def _seed(name: str, i: int) -> float:
    return (zlib.crc32(f"{name}:{i}".encode()) % 10_000) / 7.3


# ----------------------------------------------------------------------------- world-space noise


def _hash(ix, iy, seed: float) -> np.ndarray:
    v = np.sin(np.asarray(ix) * 127.1 + np.asarray(iy) * 311.7 + seed * 74.7) * 43758.5453
    return v - np.floor(v)


def value_noise(wx: np.ndarray, wy: np.ndarray, cell: float, seed: float) -> np.ndarray:
    gx, gy = wx / cell, wy / cell
    x0, y0 = np.floor(gx), np.floor(gy)
    fx, fy = gx - x0, gy - y0
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash(x0, y0, seed), _hash(x0 + 1, y0, seed)
    c, d = _hash(x0, y0 + 1, seed), _hash(x0 + 1, y0 + 1, seed)
    return (a + (b - a) * sx) * (1 - sy) + (c + (d - c) * sx) * sy


def voronoi(wx: np.ndarray, wy: np.ndarray, cell: float, seed: float):
    """(d1, d2, cell_rand, dx, dy): nearest/second-nearest site distances in px, a per-cell random
    value, and the offset from the nearest site (for per-cell bevels)."""
    gx, gy = wx / cell, wy / cell
    ix, iy = np.floor(gx), np.floor(gy)
    d1 = np.full(wx.shape, 1e9)
    d2 = np.full(wx.shape, 1e9)
    cid = np.zeros(wx.shape)
    ddx = np.zeros(wx.shape)
    ddy = np.zeros(wx.shape)
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            cx, cy = ix + ox, iy + oy
            px = cx + 0.15 + 0.7 * _hash(cx, cy, seed)
            py = cy + 0.15 + 0.7 * _hash(cx, cy, seed + 1.7)
            dx, dy = (gx - px) * cell, (gy - py) * cell
            d = np.hypot(dx, dy)
            closer = d < d1
            d2 = np.where(closer, d1, np.minimum(d2, d))
            d1 = np.where(closer, d, d1)
            cid = np.where(closer, _hash(cx, cy, seed + 3.1), cid)
            ddx = np.where(closer, dx, ddx)
            ddy = np.where(closer, dy, ddy)
    return d1, d2, cid, ddx, ddy


@dataclass
class Ctx:
    P: int
    s: float
    wx: np.ndarray
    wy: np.ndarray
    wx0: float
    wy0: float


def grid_points(ctx: Ctx, cell: float, density: float, seed: float, jitter: float = 0.8):
    """World-space jittered grid points inside this canvas -> [(col, row)]."""
    out = []
    x_min, x_max = ctx.wx0 - ctx.s - 3, ctx.wx0 + ctx.s + 3
    y_min, y_max = ctx.wy0 - ctx.s - 3, ctx.wy0 + ctx.s + 3
    for cy in range(math.floor(y_min / cell), math.floor(y_max / cell) + 1):
        for cx in range(math.floor(x_min / cell), math.floor(x_max / cell) + 1):
            if float(_hash(cx, cy, seed + 9.3)) > density:
                continue
            px = (cx + 0.5 + (float(_hash(cx, cy, seed)) - 0.5) * jitter) * cell
            py = (cy + 0.5 + (float(_hash(cx, cy, seed + 1.1)) - 0.5) * jitter) * cell
            col = int(math.floor(px - ctx.wx0 + ctx.s))
            row = int(math.floor(py - ctx.wy0 + ctx.s))
            if -3 <= col < ctx.P + 3 and -3 <= row < ctx.P + 3:
                out.append((col, row))
    return out


# ----------------------------------------------------------------------------- op interpreter


def paint_material(img: np.ndarray, m: np.ndarray, ctx: Ctx, spec: MaterialSpec, R: Ramp, name: str) -> None:
    img[m] = R[spec.base_tone]
    for i, op in enumerate(spec.ops):
        seed = _seed(name, i)
        color = R[op.tone]
        if op.op == "patches":
            n = value_noise(ctx.wx, ctx.wy, op.scale, seed)
            img[m & (n > 1 - op.amount * 0.8)] = color
        elif op.op == "speckle":
            h = _hash(np.floor(ctx.wx), np.floor(ctx.wy), seed)
            img[m & (h < op.amount * 0.5)] = color
        elif op.op == "stripes":
            a = math.radians(op.angle)
            warp = value_noise(ctx.wx, ctx.wy, op.scale * 1.5, seed) * 4
            v = np.sin((ctx.wx * math.cos(a) + ctx.wy * math.sin(a)) * (2 * math.pi / op.scale) + warp)
            img[m & (v > 1 - 2 * op.amount * 0.5)] = color
        elif op.op == "cells":
            d1, d2, *_ = voronoi(ctx.wx, ctx.wy, op.scale, seed)
            img[m & (d2 - d1 < 0.4 + op.amount * 1.6)] = color
        elif op.op == "cellfill":
            d1, d2, cid, *_ = voronoi(ctx.wx, ctx.wy, op.scale, seed)
            img[m & (cid < op.amount) & (d2 - d1 > 1.0)] = color
        elif op.op == "bevel":
            j = _cells_index(spec, i)
            scale = spec.ops[j].scale if j != i else op.scale
            _, _, _, dx, dy = voronoi(ctx.wx, ctx.wy, scale, _seed(name, j))
            k = scale * (0.55 - 0.3 * op.amount)
            img[m & (dx + dy < -k)] = R["light"]
            img[m & (dx + dy < -k * 1.5)] = R["hi"]
            img[m & (dx + dy > k * 1.1)] = R["dark"]
        elif op.op == "decals" and op.pixels:
            P = ctx.P
            for col, row in grid_points(ctx, op.scale, op.amount, seed):
                # Centres just outside the canvas still stamp their visible part (material taken
                # from the nearest canvas pixel), so decals straddling an edge appear on both tiles.
                if not m[min(P - 1, max(0, row)), min(P - 1, max(0, col))]:
                    continue
                for px in op.pixels:
                    c, r = col + px.dx, row + px.dy
                    if 0 <= c < P and 0 <= r < P and m[r, c]:
                        img[r, c] = R[px.tone]


def _cells_index(spec: MaterialSpec, i: int) -> int:
    """A bevel shares its voronoi layout with the nearest preceding 'cells' op, so stones line up
    with their mortar."""
    for j in range(i - 1, -1, -1):
        if spec.ops[j].op in ("cells", "cellfill"):
            return j
    return i


# ----------------------------------------------------------------------------- main entry


def render_ground(
    *,
    tile_px: int,
    palette: list[str],
    biome: str,
    edges: list[dict],
    coord: tuple[int, int],
    materials: dict[str, MaterialSpec | dict] | None = None,
) -> np.ndarray:
    """RGB uint8 (P, P, 3) ground texture for the full square canvas (the caller applies the hex mask)."""
    P = tile_px
    s = P / 2.0
    c = (np.arange(P) + 0.5) - s
    x, y = np.meshgrid(c, c)
    wx0, wy0 = Hex(*coord).to_pixel(s)
    ctx = Ctx(P=P, s=s, wx=x + wx0, wy=y + wy0, wx0=wx0, wy0=wy0)
    apothem = s * SQRT3 / 2
    lib = {
        k: (v if isinstance(v, MaterialSpec) else MaterialSpec.model_validate(v))
        for k, v in (materials or {}).items()
    }

    def spec_of(name: str) -> MaterialSpec:
        return lib.get(name) or fallback_material(name)

    # --- material map
    dots = np.stack(
        [(x * math.cos(math.radians(a)) + y * math.sin(math.radians(a))) / apothem for a in DIRECTION_ANGLES],
        axis=-1,
    )
    nearest_edge = dots.argmax(-1)
    d = dots.max(-1)
    wobble = value_noise(ctx.wx, ctx.wy, 6.0, 7.0) * 2 - 1
    band = d > 0.56 + 0.16 * wobble
    names: list[str] = [biome]
    for e in edges:
        if e["terrain"] not in names:
            names.append(e["terrain"])
    edge_idx = np.array([names.index(e["terrain"]) for e in edges])
    mat = np.where(band, edge_idx[nearest_edge], 0)

    # --- connectors: curved paths from the center to each connector edge's midpoint
    conns = [(i, cn) for i, e in enumerate(edges) for cn in e.get("connectors", [])]
    for cname in sorted({cn for _, cn in conns}):
        idx = len(names)
        names.append(cname)
        width = max(1.6, P / (9.0 if spec_of(cname).liquid else 13.0))
        dist = np.full((P, P), 1e9)
        mine = [i for i, cn in conns if cn == cname]
        for i in mine:
            ang = math.radians(DIRECTION_ANGLES[i])
            mx, my = math.cos(ang) * apothem, math.sin(ang) * apothem
            nx, ny = -math.sin(ang), math.cos(ang)
            amp = width * 0.9 * (1 if (coord[0] * 7 + coord[1] * 13 + i) % 2 else -1)
            for t in np.linspace(0, 1, 28):
                # zero offset AND zero slope at the edge: both tiles cross the shared edge identically
                off = amp * 1.6 * math.sin(math.pi * t) * (1 - t)
                dist = np.minimum(dist, np.hypot(x - (mx * t + nx * off), y - (my * t + ny * off)))
        if len(mine) == 1:  # dead end: pond / plaza
            dist = np.minimum(dist, np.hypot(x, y) - width * 0.8)
        mat = np.where(dist <= width, idx, mat)

    specs = [spec_of(n) for n in names]
    ramps = [ramp_for(sp, palette) for sp in specs]
    img = np.zeros((P, P, 3), dtype=np.float32)
    for k, name in enumerate(names):
        m = mat == k
        if m.any():
            paint_material(img, m, ctx, specs[k], ramps[k], name)

    # --- crisp boundaries between materials
    out = img.copy()
    for dy_, dx_ in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nb = np.roll(np.roll(mat, dy_, axis=0), dx_, axis=1)
        valid = np.ones((P, P), bool)
        if dy_:
            valid[0 if dy_ == 1 else -1, :] = False
        if dx_:
            valid[:, 0 if dx_ == 1 else -1] = False
        for r_, c_ in zip(*np.nonzero(valid & (nb != mat)), strict=True):
            own, other = specs[mat[r_, c_]], specs[nb[r_, c_]]
            R = ramps[mat[r_, c_]]
            if own.boundary == "foam" and not other.liquid:
                out[r_, c_] = R["hi"]
            elif own.boundary == "glow" and other.boundary != "glow":
                out[r_, c_] = R["hi"]
            elif other.boundary == "glow" and own.boundary != "glow":
                out[r_, c_] = R["outline"]
            elif not own.liquid and other.liquid:
                out[r_, c_] = R["dark"]
            elif own.boundary == "lip" and own.rank > other.rank:
                out[r_, c_] = R["dark"]
    return np.clip(out, 0, 255).astype(np.uint8)
