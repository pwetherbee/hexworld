"""Ground renderer: interprets agent-written MaterialSpecs into Terraria-style block terrain.

Art style (engine-level, not content): the world is one pixel grid (see art/grid.py) divided into
square BLOCKS (8px at the default 64px tiles). Materials are assigned per block, so regions,
roads and coastlines have clean block-grid edges instead of noisy pixel soup. Each block is drawn
in its material's block style ('bevel': lit top-left edge, shaded bottom-right; 'outline': dark
1px frame; 'flat'). Pattern ops add chunky block-level variation (patches/cellfill/stripes) and
pixel-level detail (speckle/decals/cracks). Every cell also gets a relief level (material base
height + height ops), exported as the heightmap layer (see art/relief.py): the ground colours are
flat surfaces; the 3D view extrudes the heightmap and 2D previews shade it in.

Each pixel's block takes the tile's biome in the middle and the edge contract's terrain in a
band along each edge. All ops are evaluated in world coordinates with seeds derived from the
material name, so tiles that agree on an edge paint identical blocks on both sides of it.

This module holds no content: how a material looks comes from the material artist agent.
"""

from __future__ import annotations

import colorsys
import math
import zlib
from dataclasses import dataclass

import numpy as np

from hexworld.agents.themes import base_color, hex_to_rgb, rgb_to_hex, shade
from hexworld.art.grid import TileCanvas
from hexworld.art.relief import LIQUID_BIT, MAX_LEVEL, relief_shade
from hexworld.domain.art import MaterialSpec, PatternOp
from hexworld.hex import DIRECTION_ANGLES, SQRT3, Hex

RAMP_FACTORS = {"outline": 0.42, "dark": 0.72, "base": 1.0, "light": 1.24, "hi": 1.5}


def block_size(tile_px: int) -> int:
    """Size of an art 'cell': shapes, patches and relief are evaluated on 2px cells (chunky
    Terraria-scale pixels) with organic noise-warped contours, never on a coarse square grid."""
    return 2


def unit(tile_px: int) -> float:
    """Feature scale (road width, wobble) relative to the tile."""
    return tile_px / 8


MAX_BASE_LUM = 0.8


def ramp_base(color: str) -> str:
    """Very pale bases (snow, sugar, marble) are pulled down to leave room for highlight tones;
    otherwise their light/hi tones collapse into flat white and the texture disappears."""
    r, g, b = hex_to_rgb(color)
    h, lum, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    if lum <= MAX_BASE_LUM:
        return color
    # keep the chroma (HLS saturation means more colour at lower lightness): a creamy white must
    # stay a pale cream, not turn lime
    sat *= (1 - abs(2 * lum - 1)) / (1 - abs(2 * MAX_BASE_LUM - 1))
    r2, g2, b2 = colorsys.hls_to_rgb(h, MAX_BASE_LUM, min(1.0, sat))
    return rgb_to_hex((round(r2 * 255), round(g2 * 255), round(b2 * 255)))


def ramp_hexes(color: str) -> list[str]:
    return [shade(ramp_base(color), f) for f in RAMP_FACTORS.values()]


@dataclass
class Ramp:
    tones: dict[str, np.ndarray]
    accent: np.ndarray

    def __getitem__(self, tone: str) -> np.ndarray:
        return self.accent if tone == "accent" else self.tones[tone]


def ramp_for(spec: MaterialSpec, palette: list[str] | None = None) -> Ramp:
    """Exact ramp colours. Deliberately NOT snapped to the (growing) world palette: a material must
    render identically before and after later runs extend the palette, or old/new tiles won't meet."""

    def col(c: str) -> np.ndarray:
        return np.array(hex_to_rgb(c), dtype=np.float32)

    return Ramp(
        tones={t: col(shade(ramp_base(spec.base_color), f)) for t, f in RAMP_FACTORS.items()},
        accent=col(spec.accent_color),
    )


def fallback_material(name: str) -> MaterialSpec:
    """Used only if the library has no spec yet (e.g. the material agent failed)."""
    return MaterialSpec(
        base_color=base_color(name),
        accent_color=shade(base_color(name), 1.4),
        base_tone="base",
        liquid=False,
        rank=4,
        boundary="lip",
        block_style="bevel",
        height=1,
        height_ops=[],
        ops=[PatternOp(op="patches", tone="light", scale=20, amount=0.35, angle=0, pixels=[])],
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
    """(d1, d2, cell_rand, dx, dy) for the nearest voronoi site in world space."""
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
    C: int
    B: int
    wx: np.ndarray  # pixel-centre world coords
    wy: np.ndarray
    bcx: np.ndarray  # world coords of the centre of each pixel's block
    bcy: np.ndarray
    lx: np.ndarray  # pixel position inside its block (0..B-1)
    ly: np.ndarray
    ox: int
    oy: int


def _ctx(canvas: TileCanvas, margin: int = 0) -> Ctx:
    """Pixel context for the canvas grown by `margin` world pixels on every side."""
    B = block_size(canvas.P)
    ox, oy = canvas.origin[0] - margin, canvas.origin[1] - margin
    C = canvas.C + 2 * margin
    idx = np.arange(C) + 0.5
    wx, wy = np.meshgrid(ox + idx, oy + idx)
    px, py = np.floor(wx), np.floor(wy)  # integer world pixel indices
    bx, by = np.floor(px / B), np.floor(py / B)
    return Ctx(
        C=C,
        B=B,
        wx=wx,
        wy=wy,
        bcx=(bx + 0.5) * B,
        bcy=(by + 0.5) * B,
        lx=(px - bx * B).astype(np.int32),
        ly=(py - by * B).astype(np.int32),
        ox=ox,
        oy=oy,
    )


def grid_points(ctx: Ctx, cell: float, density: float, seed: float, jitter: float = 0.8):
    """World-space jittered grid points in/near this canvas -> [(col, row)] canvas pixels."""
    out = []
    x0, x1 = ctx.ox - 3, ctx.ox + ctx.C + 3
    y0, y1 = ctx.oy - 3, ctx.oy + ctx.C + 3
    for cy in range(math.floor(y0 / cell), math.floor(y1 / cell) + 1):
        for cx in range(math.floor(x0 / cell), math.floor(x1 / cell) + 1):
            if float(_hash(cx, cy, seed + 9.3)) > density:
                continue
            px = (cx + 0.5 + (float(_hash(cx, cy, seed)) - 0.5) * jitter) * cell
            py = (cy + 0.5 + (float(_hash(cx, cy, seed + 1.1)) - 0.5) * jitter) * cell
            out.append((int(math.floor(px)) - ctx.ox, int(math.floor(py)) - ctx.oy))
    return out


# ----------------------------------------------------------------------------- material painting


TONES = list(RAMP_FACTORS)


def _lots(ctx: Ctx, scale: float, seed: float):
    """Building lots on a staggered grid (like city blocks), with 2px alleys on their north and
    west sides. -> (inside mask, lot hash, second lot hash); evaluated on 2px art cells."""
    sx, sy = max(6.0, scale), max(6.0, round(scale * 0.75))
    row = np.floor(ctx.bcy / sy)
    x = ctx.bcx + (row % 2) * sx * 0.5
    col = np.floor(x / sx)
    lx, ly = x - col * sx, ctx.bcy - row * sy
    inside = (lx > 2.0) & (ly > 2.0)
    return inside, _hash(col, row, seed), _hash(col, row, seed + 2.3)


def _lot_south(ctx: Ctx, scale: float) -> np.ndarray:
    """The southern half of each lot (a roof's shaded slope)."""
    sy = max(6.0, round(scale * 0.75))
    ly = ctx.bcy - np.floor(ctx.bcy / sy) * sy
    return ly > 2.0 + (sy - 2.0) / 2


def _walls(ctx: Ctx, scale: float, doors: float, seed: float) -> np.ndarray:
    """Wall lines of a room grid (2px thick) with a doorway in a share `doors` of wall segments."""
    s = max(8.0, scale)
    col, row = np.floor(ctx.bcx / s), np.floor(ctx.bcy / s)
    lx, ly = ctx.bcx - col * s, ctx.bcy - row * s
    vwall, hwall = lx < 2.0, ly < 2.0
    mid = s / 2
    vdoor = (_hash(col, row, seed + 1.1) < doors) & (np.abs(ly - mid) < 3.0)
    hdoor = (_hash(col, row, seed + 4.7) < doors) & (np.abs(lx - mid) < 3.0)
    return (vwall & ~vdoor) | (hwall & ~hdoor)


def _tiling(ctx: Ctx, kind: str, scale: float) -> np.ndarray:
    """Pixel-level floor/wall tilings: checker tiles, plank seams, brick mortar."""
    px, py = np.floor(ctx.wx), np.floor(ctx.wy)
    s = max(2.0, scale)
    if kind == "checker":
        return (np.floor(px / s) + np.floor(py / s)) % 2 == 0
    if kind == "planks":
        bh = max(2.0, round(s / 4))
        row = np.floor(py / bh)
        ends = (px + np.floor(_hash(row, 0, 3.3) * s)) % s == 0
        return (py % bh == 0) | ends
    rh = max(2.0, round(s / 3))  # bricks
    row = np.floor(py / rh)
    return (py % rh == 0) | ((px + (row % 2) * np.floor(s / 2)) % s == 0)


def _bands(ctx: Ctx, angle: float, period: float, seed: float) -> np.ndarray:
    """Meandering bands (dunes, strata, ridgelines): a sine across `angle`, domain-warped by
    low-frequency noise so the bands wander instead of ruling straight lines."""
    a = math.radians(angle)
    warp = (value_noise(ctx.bcx, ctx.bcy, period * 2.2, seed + 4.2) - 0.5) * period * 2.2
    warp += (value_noise(ctx.bcx, ctx.bcy, period * 0.9, seed + 7.7) - 0.5) * period * 0.5
    proj = ctx.bcx * math.cos(a) + ctx.bcy * math.sin(a) + warp
    return np.sin(proj * (2 * math.pi / period))


def paint_material(img: np.ndarray, m: np.ndarray, ctx: Ctx, spec: MaterialSpec, R: Ramp, name: str) -> None:
    img[m] = R[spec.base_tone]
    # engine-level texture so no block is a flat colour: 2px clusters one tone down/up (solids),
    # short horizontal glints (liquids). World-aligned, so it continues across tiles.
    t = TONES.index(spec.base_tone)
    down, up = R[TONES[max(0, t - 1)]], R[TONES[min(len(TONES) - 1, t + 1)]]
    if spec.liquid:
        cx, cy = np.floor(ctx.wx / 7), np.floor(ctx.wy / 4)
        lx, ly = np.floor(ctx.wx) - cx * 7, np.floor(ctx.wy) - cy * 4
        glint = (_hash(cx, cy, _seed(name, 998)) < 0.22) & (ly == 1) & (lx >= 2) & (lx <= 4)
        img[m & glint] = up
    else:
        g = _hash(np.floor(ctx.wx / 2), np.floor(ctx.wy / 2), _seed(name, 999))
        img[m & (g < 0.13)] = down
        img[m & (g > 0.93)] = up
    for i, op in enumerate(spec.ops):
        seed = _seed(name, i)
        color = R[op.tone]
        if op.op == "patches":  # block-level: whole blocks change colour (chunky)
            n = value_noise(ctx.bcx, ctx.bcy, max(op.scale, ctx.B * 1.5), seed)
            img[m & (n > 1 - op.amount * 0.8)] = color
        elif op.op == "cellfill":
            _, _, cid, _, _ = voronoi(ctx.bcx, ctx.bcy, max(op.scale, ctx.B * 1.5), seed)
            img[m & (cid < op.amount)] = color
        elif op.op == "stripes":
            v = _bands(ctx, op.angle, max(op.scale, ctx.B * 2), seed)
            img[m & (v > 1 - 2 * op.amount * 0.5)] = color
        elif op.op == "speckle":  # pixel-level detail
            h = _hash(np.floor(ctx.wx), np.floor(ctx.wy), seed)
            img[m & (h < op.amount * 0.35)] = color
        elif op.op == "cells":  # pixel-level cracks
            d1, d2, *_ = voronoi(ctx.wx, ctx.wy, op.scale, seed)
            img[m & (d2 - d1 < 0.4 + op.amount * 1.2)] = color
        elif op.op == "bevel":  # per-voronoi-stone bevel (cobbles inside blocks)
            _, _, _, dx, dy = voronoi(ctx.wx, ctx.wy, op.scale, seed)
            k = op.scale * (0.55 - 0.3 * op.amount)
            img[m & (dx + dy < -k)] = R["light"]
            img[m & (dx + dy > k * 1.1)] = R["dark"]
        elif op.op == "lots":  # built: rooftops / stalls on a staggered lot grid
            inside, lid, lid2 = _lots(ctx, op.scale, seed)
            sel = m & inside & (lid < op.amount)
            south = _lot_south(ctx, op.scale)
            if op.tone == "accent":
                img[sel] = color
            else:
                t0 = TONES.index(op.tone)
                for k, shift in enumerate((-1, 0, 1)):
                    tone = TONES[min(len(TONES) - 1, max(0, t0 + shift))]
                    img[sel & (np.floor(lid2 * 3) == k)] = R[tone]
            img[sel & south] = img[sel & south] * 0.84  # roof ridge: the south slope is in shade
        elif op.op == "rooms":
            img[m & _walls(ctx, op.scale, op.amount, seed)] = color
        elif op.op in ("checker", "planks", "bricks"):
            img[m & _tiling(ctx, op.op, op.scale)] = color
        elif op.op == "decals" and op.pixels:
            C = ctx.C
            for col, row in grid_points(ctx, op.scale, op.amount, seed):
                if not m[min(C - 1, max(0, row)), min(C - 1, max(0, col))]:
                    continue
                for px in op.pixels:
                    c, r = col + px.dx, row + px.dy
                    if 0 <= c < C and 0 <= r < C and m[r, c]:
                        img[r, c] = R[px.tone]


def _shift(arr: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """arr value at (row + dy, col + dx), edge-clamped."""
    H, W = arr.shape
    p = np.pad(arr, 1, mode="edge")
    return p[1 + dy : 1 + dy + H, 1 + dx : 1 + dx + W]


def frame_blocks(img: np.ndarray, mat: np.ndarray, heights: np.ndarray, ctx: Ctx, specs, ramps) -> None:
    """Terraria-style framing: blocks of the same material and level MERGE into one surface; a
    block's frame (bevel light/shade, or outline) is drawn only on faces exposed to a different
    material or level."""
    B = ctx.B
    key = mat.astype(np.int32) * 64 + heights.astype(np.int32)
    up = (ctx.ly == 0) & (_shift(key, -1, 0) != key)
    left = (ctx.lx == 0) & (_shift(key, 0, -1) != key)
    down = (ctx.ly == B - 1) & (_shift(key, 1, 0) != key)
    right = (ctx.lx == B - 1) & (_shift(key, 0, 1) != key)
    for k, spec in enumerate(specs):
        m = mat == k
        if spec.liquid or spec.block_style == "flat" or not m.any():
            continue
        if spec.block_style == "bevel":
            lit, shade_ = m & (up | left), m & (down | right)
            img[lit] = np.minimum(255, img[lit] * 1.18 + 10)
            img[shade_] = img[shade_] * 0.72
        else:  # outline
            img[m & (up | left | down | right)] = ramps[k]["outline"]


def material_heights(ctx: Ctx, spec: MaterialSpec, name: str) -> np.ndarray:
    h = np.full(ctx.wx.shape, float(spec.height))
    for i, op in enumerate(spec.height_ops):
        seed = _seed(name, 100 + i)
        scale = max(op.scale, ctx.B * 2)
        if op.op == "patches":
            sel = value_noise(ctx.bcx, ctx.bcy, scale, seed) > 1 - op.amount * 0.8
        elif op.op == "cellfill":
            sel = voronoi(ctx.bcx, ctx.bcy, scale, seed)[2] < op.amount
        elif op.op == "stripes":
            sel = _bands(ctx, 30.0, scale, seed) > 1 - 2 * op.amount * 0.5
        elif op.op == "lots":  # buildings: lots rise, some a level taller than the rest
            inside, lid, lid2 = _lots(ctx, op.scale, seed)
            sel = inside & (lid < op.amount)
            h = np.where(sel, h + op.delta + (lid2 < 0.35) * np.sign(op.delta), h)
            continue
        elif op.op == "rooms":  # interior walls
            sel = _walls(ctx, op.scale, op.amount, seed)
        else:  # speckle, per block
            sel = _hash(np.floor(ctx.bcx), np.floor(ctx.bcy), seed) < op.amount * 0.4
        h = np.where(sel, h + op.delta, h)
    return h


# ----------------------------------------------------------------------------- main entry


def render_ground(
    *,
    tile_px: int,
    biome: str,
    edges: list[dict],
    coord: tuple[int, int],
    materials: dict[str, MaterialSpec | dict] | None = None,
    palette: list[str] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """(RGB uint8 (C, C, 3), relief levels uint8 (C, C)) for the tile's canvas on the world grid."""
    canvas = TileCanvas(Hex(*coord), tile_px)
    U = unit(tile_px)
    margin = 2 * MAX_LEVEL + 4  # so contours/cliffs at the rim see what lies beyond it
    ctx = _ctx(canvas, margin)
    s = canvas.s
    cx, cy = canvas.center
    apothem = s * SQRT3 / 2
    lib = {
        k: (v if isinstance(v, MaterialSpec) else MaterialSpec.model_validate(v))
        for k, v in (materials or {}).items()
    }

    def spec_of(name: str) -> MaterialSpec:
        return lib.get(name) or fallback_material(name)

    # --- material per BLOCK (evaluated at block centres, relative to this hex)
    # domain warp: band borders (and corners where two edge terrains meet) become organic, not
    # straight bisectors. Evaluated in world space, so neighbours agree near shared edges.
    wx_ = value_noise(ctx.bcx, ctx.bcy, U * 1.6, 3.1) - 0.5
    wy_ = value_noise(ctx.bcx, ctx.bcy, U * 1.6, 5.3) - 0.5
    bx0, by0 = ctx.bcx - cx, ctx.bcy - cy  # unwarped (for straight, built connectors)
    bx, by = bx0 + wx_ * U * 1.2, by0 + wy_ * U * 1.2
    dots = np.stack(
        [
            (bx * math.cos(math.radians(a)) + by * math.sin(math.radians(a))) / apothem
            for a in DIRECTION_ANGLES
        ],
        axis=-1,
    )
    nearest_edge = dots.argmax(-1)
    d = dots.max(-1)
    wobble = (
        value_noise(ctx.bcx, ctx.bcy, U * 2.2, 7.0) * 0.7 + value_noise(ctx.bcx, ctx.bcy, U, 8.0) * 0.3
    ) * 2 - 1
    band = d > 0.5 + 0.14 * wobble  # stays well inside the edge, so neighbours agree near it
    names: list[str] = [biome]
    for e in edges:
        if e["terrain"] not in names:
            names.append(e["terrain"])
    edge_idx = np.array([names.index(e["terrain"]) for e in edges])
    mat = np.where(band, edge_idx[nearest_edge], 0)

    # --- connectors: blocky paths from the centre to each connector edge's midpoint
    conns = [(i, cn) for i, e in enumerate(edges) for cn in e.get("connectors", [])]
    for cname in sorted({cn for _, cn in conns}):
        idx = len(names)
        names.append(cname)
        cspec = spec_of(cname)
        straight = cspec.edges == "straight"
        px_, py_ = (bx0, by0) if straight else (bx, by)
        width = U * (0.75 if cspec.liquid else 0.55)
        dist = np.full(bx.shape, 1e9)
        mine = [i for i, cn in conns if cn == cname]
        for i in mine:
            ang = math.radians(DIRECTION_ANGLES[i])
            mx, my = math.cos(ang) * apothem, math.sin(ang) * apothem
            nx, ny = -math.sin(ang), math.cos(ang)
            amp = 0.0 if straight else U * 0.9 * (1 if (coord[0] * 7 + coord[1] * 13 + i) % 2 else -1)
            for t in np.linspace(0, 1, 32):
                off = amp * 1.6 * math.sin(math.pi * t) * (1 - t)  # zero offset & slope at the edge
                dist = np.minimum(dist, np.hypot(px_ - (mx * t + nx * off), py_ - (my * t + ny * off)))
        if len(mine) == 1:  # a dead end (spring, road end): a small bulb, not a pond
            dist = np.minimum(dist, np.hypot(px_, py_) - width * 0.3)
        elif straight and len(mine) > 2:  # a junction: a small square
            dist = np.minimum(dist, np.maximum(np.abs(px_), np.abs(py_)) - width * 0.6)
        mat = np.where(dist <= width, idx, mat)

    specs = [spec_of(n) for n in names]
    ramps = [ramp_for(sp) for sp in specs]
    img = np.zeros((ctx.C, ctx.C, 3), dtype=np.float32)
    heights = np.zeros((ctx.C, ctx.C), dtype=np.float32)
    for k, name in enumerate(names):
        m = mat == k
        if m.any():
            paint_material(img, m, ctx, specs[k], ramps[k], name)
            heights[m] = material_heights(ctx, specs[k], name)[m]
    heights = np.clip(np.rint(heights), 0, MAX_LEVEL)
    frame_blocks(img, mat, heights, ctx, specs, ramps)

    # --- crisp boundaries between materials (they follow the block grid)
    out = img.copy()
    C = ctx.C
    for dy_, dx_ in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nb = np.roll(np.roll(mat, dy_, axis=0), dx_, axis=1)
        valid = np.ones((C, C), bool)
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

    liquid = np.array([sp.liquid for sp in specs])[mat]
    heights = np.where(liquid, heights.astype(np.int32) | LIQUID_BIT, heights)
    crop = slice(margin, margin + canvas.C)
    return np.clip(out[crop, crop], 0, 255).astype(np.uint8), heights[crop, crop].astype(np.uint8)


def material_preview_png(
    name: str, spec: MaterialSpec, tile_px: int, contrast: MaterialSpec | None = None
) -> bytes:
    """What the material artist sees: a patch of this material (4 tiles, showing seamless tiling
    and relief shading) plus one tile bordering a contrasting material (the boundary treatment)."""
    import io

    from hexworld.art.composite import render_region

    other = contrast or fallback_material("neutral_stone")
    mats = {name: spec, "__contrast": other}
    same = [{"terrain": name, "connectors": []}] * 6
    mixed = [{"terrain": name if i in (0, 1, 5) else "__contrast", "connectors": []} for i in range(6)]
    tiles: dict[Hex, np.ndarray] = {}
    for h, edges in (
        (Hex(0, 0), same),
        (Hex(1, 0), same),
        (Hex(0, 1), same),
        (Hex(1, -1), same),
        (Hex(2, 0), mixed),
    ):
        rgb, levels = render_ground(
            tile_px=tile_px, biome=name, edges=edges, coord=(h.q, h.r), materials=mats
        )
        rgb = relief_shade(rgb, levels)
        canvas = TileCanvas(h, tile_px)
        rgba = np.zeros((canvas.C, canvas.C, 4), np.uint8)
        m = canvas.mask()
        rgba[m, :3] = rgb[m]
        rgba[m, 3] = 255
        tiles[h] = rgba
    img = render_region(tiles, tile_px=tile_px, scale=3)  # (relief shaded per tile above)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
