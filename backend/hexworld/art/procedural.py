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
from hexworld.art.relief import FACADE_SHIFT, LIQUID_BIT, MAX_LEVEL, facade_code, relief_shade
from hexworld.domain.art import BuildingsSpec, MaterialSpec, PatternOp
from hexworld.hex import DIRECTION_ANGLES, SQRT3, Hex

RAMP_FACTORS = {"outline": 0.42, "dark": 0.72, "base": 1.0, "light": 1.24, "hi": 1.5}


def block_size(tile_px: int) -> int:
    """Size of an art 'cell': shapes, patches and relief are evaluated on 2px cells (chunky
    Terraria-scale pixels) with organic noise-warped contours, never on a coarse square grid."""
    return 2


def unit(tile_px: int) -> float:
    """Feature scale (road width, wobble) relative to the tile."""
    return tile_px / 8


# The world's street lattice: vertical lines through every tile centre column (x = i * sqrt3/2 * s)
# and horizontal lines through every tile centre and midway between rows (y = j * 0.75 * s), in world
# pixels (hex (0, 0) is centred on the origin). Straight connectors run on it (see
# straight_segments) and so do the street grids of built materials, so every road joins up.
def lattice(tile_px: int) -> tuple[float, float]:
    s = tile_px / 2
    return s * SQRT3 / 2, 0.75 * s


def street_half(tile_px: int) -> float:
    """Half the width of a street (connector or grid), in pixels."""
    return unit(tile_px) * 0.36


def _line_dist(v: np.ndarray, period: float) -> np.ndarray:
    return np.abs(v - np.round(v / period) * period)


ASPHALT = "__asphalt__"


def asphalt_material() -> MaterialSpec:
    """The engine's plain street, for built materials that don't name a street connector."""
    return MaterialSpec(
        base_color="#3e4047",
        accent_color="#e8d9a0",
        base_tone="base",
        liquid=False,
        rank=5,
        boundary="none",
        block_style="flat",
        edges="straight",
        markings="dashed",
        height=1,
        height_ops=[],
        ops=[PatternOp(op="speckle", tone="light", scale=2, amount=0.08, angle=0, pixels=[])],
        scatter=[],
    )


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
    k: float  # tile resolution / 64: pattern sizes scale with it, the pixel grain does not
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
        k=canvas.P / 64,
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
        sc = op.scale * ctx.k
        color = R[op.tone]
        if op.op == "patches":  # block-level: whole blocks change colour (chunky)
            n = value_noise(ctx.bcx, ctx.bcy, max(sc, ctx.B * 1.5), seed)
            img[m & (n > 1 - op.amount * 0.8)] = color
        elif op.op == "cellfill":
            _, _, cid, _, _ = voronoi(ctx.bcx, ctx.bcy, max(sc, ctx.B * 1.5), seed)
            img[m & (cid < op.amount)] = color
        elif op.op == "stripes":
            v = _bands(ctx, op.angle, max(sc, ctx.B * 2), seed)
            img[m & (v > 1 - 2 * op.amount * 0.5)] = color
        elif op.op == "speckle":  # pixel-level detail
            h = _hash(np.floor(ctx.wx), np.floor(ctx.wy), seed)
            img[m & (h < op.amount * 0.35)] = color
        elif op.op == "cells":  # pixel-level cracks
            d1, d2, *_ = voronoi(ctx.wx, ctx.wy, sc, seed)
            img[m & (d2 - d1 < 0.4 + op.amount * 1.2)] = color
        elif op.op == "bevel":  # per-voronoi-stone bevel (cobbles inside blocks)
            _, _, _, dx, dy = voronoi(ctx.wx, ctx.wy, sc, seed)
            k = sc * (0.55 - 0.3 * op.amount)
            img[m & (dx + dy < -k)] = R["light"]
            img[m & (dx + dy > k * 1.1)] = R["dark"]
        elif op.op == "lots":  # built: rooftops / stalls on a staggered lot grid
            inside, lid, lid2 = _lots(ctx, sc, seed)
            sel = m & inside & (lid < op.amount)
            south = _lot_south(ctx, sc)
            if op.tone == "accent":
                img[sel] = color
            else:
                t0 = TONES.index(op.tone)
                for k, shift in enumerate((-1, 0, 1)):
                    tone = TONES[min(len(TONES) - 1, max(0, t0 + shift))]
                    img[sel & (np.floor(lid2 * 3) == k)] = R[tone]
            img[sel & south] = img[sel & south] * 0.84  # roof ridge: the south slope is in shade
        elif op.op == "rooms":
            img[m & _walls(ctx, sc, op.amount, seed)] = color
        elif op.op in ("checker", "planks", "bricks"):
            img[m & _tiling(ctx, op.op, sc)] = color
        elif op.op == "decals" and op.pixels:
            C = ctx.C
            for col, row in grid_points(ctx, sc, op.amount, seed):
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
    key = mat.astype(np.int32) * 1024 + heights.astype(np.int32)
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


FLOOR_LEVELS = 1  # relief levels per building floor (1 level = 0.055 world units in 3D)


def _hex_rgb(c: str) -> np.ndarray:
    return np.array(hex_to_rgb(c), dtype=np.float32)


def paint_buildings(
    img: np.ndarray,
    heights: np.ndarray,
    facade: np.ndarray,
    codes: np.ndarray,
    m: np.ndarray,
    ctx: Ctx,
    b: BuildingsSpec,
    name: str,
) -> None:
    """Raise buildings out of this material's ground: footprints on a world-aligned lot grid (so
    buildings continue across tiles), floors per lot (skewed low, with a skyline share of tall ones),
    roofs painted into the ground, wall colours and facade codes for the 3D facades."""
    seed = _seed(name, 777)
    k = ctx.k
    px, py = np.floor(ctx.wx), np.floor(ctx.wy)
    lot = max(6.0, round(b.lot_px * k))
    gap = max(1.0, round(b.gap_px * k))
    if b.layout == "rows":
        sx, sy, stagger = max(4.0, round(lot * 0.45)), lot, 0.0
    elif b.layout == "detached":
        sx = sy = lot + 2 * gap
        stagger = sx / 2
    elif b.layout == "towers":
        sx = sy = round(lot * 1.6)
        stagger = 0.0
    elif b.layout == "compound":
        sx = sy = round(lot * 2)
        stagger = 0.0
    else:  # blocks
        sx, sy, stagger = lot, max(6.0, round(lot * 0.8)), lot / 2
    if b.street_grid > 0:  # blocks between the lattice streets (painted by the caller), lots inside
        P = round(ctx.k * 64)
        X, Y = lattice(P)
        half = street_half(P)
        cw, ch = X * b.street_grid, Y * b.street_grid
        # lattice lines pass through world 0, so block i spans [i*cw + half, (i+1)*cw - half]
        bx, by = np.floor(ctx.wx / cw), np.floor(ctx.wy / ch)
        ix, iy = ctx.wx - bx * cw - half, ctx.wy - by * ch - half
        iw, ih = cw - 2 * half, ch - 2 * half
        nx, ny = max(1, round(iw / sx)), max(1, round(ih / sy))  # whole lots per block, no slivers
        sx, sy = iw / nx, ih / ny
        col = bx * 64 + np.clip(np.floor(ix / sx), 0, nx - 1)
        row = by * 64 + np.clip(np.floor(iy / sy), 0, ny - 1)
        lx, ly = ix - (col - bx * 64) * sx, iy - (row - by * 64) * sy
    else:
        row = np.floor(py / sy)
        x = px + (row % 2) * stagger
        col = np.floor(x / sx)
        lx, ly = x - col * sx, py - row * sy
    # footprint bounds inside the lot
    if b.layout == "rows":
        x0, x1, y0, y1 = 0.0, sx, gap, sy
    elif b.layout == "blocks":
        x0, x1, y0, y1 = gap, sx, gap, sy
    else:
        x0, x1, y0, y1 = gap, sx - gap, gap, sy - gap
    inside = (lx >= x0) & (lx < x1) & (ly >= y0) & (ly < y1)
    if b.layout == "compound":  # a walled ring around a courtyard, taller corners
        w = max(3.0, round(lot / 4))
        court = (lx >= x0 + w) & (lx < x1 - w) & (ly >= y0 + w) & (ly < y1 - w)
        inside &= ~court
    lid = _hash(col, row, seed)
    built = m & inside & (lid < b.coverage)
    if not built.any():
        return
    h2, h3 = _hash(col, row, seed + 1.3), _hash(col, row, seed + 2.9)
    span = b.floors_max - b.floors_min
    tall = h2 < b.tall_share
    floors = np.where(
        tall, b.floors_max - np.floor(h3 * 0.25 * span), b.floors_min + np.floor(span * 0.6 * h3**2)
    )
    # edge distance inside the footprint (parapets, ridges, stepped terraces)
    dl = np.minimum(np.minimum(lx - x0, x1 - 1 - lx), np.minimum(ly - y0, y1 - 1 - ly))
    extra = np.zeros_like(heights)
    if b.layout == "compound":
        corner = (np.minimum(lx - x0, x1 - 1 - lx) < w) & (np.minimum(ly - y0, y1 - 1 - ly) < w)
        extra += np.where(corner, 2 * FLOOR_LEVELS, 0)
    if b.roof == "parapet":
        extra += np.where(dl < 1, 1, 0)
    elif b.roof == "terrace":
        extra += np.where(dl >= max(2.0, round(2 * k)), FLOOR_LEVELS * 2, 0)
    elif b.roof == "gabled":
        mid = (y0 + y1 - 1) / 2
        extra += np.where(np.abs(ly - mid) < 1.0, 1, 0)
    if b.clutter > 0 and b.roof in ("flat", "parapet", "terrace"):  # vents, tanks, AC boxes
        cx_, cy_ = np.floor(px / 4), np.floor(py / 4)
        box = (_hash(cx_, cy_, seed + 5.5) < b.clutter * 0.18) & (px % 4 < 2) & (py % 4 < 2) & (dl >= 2)
        extra += np.where(box, 1, 0)
    heights[built] += floors[built] * FLOOR_LEVELS + extra[built]

    # roofs
    roofs = [_hex_rgb(c) for c in b.roof_colors]
    ridx = np.floor(_hash(col, row, seed + 4.1) * len(roofs)).astype(int)
    roof = np.stack(roofs)[ridx]
    shade_ = np.ones(heights.shape, np.float32)
    if b.roof == "gabled":
        mid = (y0 + y1 - 1) / 2
        shade_ = np.where(ly > mid, 0.8, 1.08)  # north slope lit, south slope in shade
    shade_ = np.where(dl < 1, shade_ * 0.82, shade_)  # the roof's rim
    shade_ = np.where(extra >= 1, shade_ * 1.12, shade_)
    img[built] = np.minimum(255, roof[built] * shade_[built][:, None])

    # facades (for the 3D walls and 2D previews)
    walls = [_hex_rgb(c) for c in b.wall_colors]
    widx = np.floor(_hash(col, row, seed + 6.7) * len(walls)).astype(int)
    facade[built] = np.stack(walls)[widx][built].astype(np.uint8)
    lit = np.clip(b.lit + (_hash(col, row, seed + 8.2) - 0.5) * 0.3, 0, 1)
    style_code = facade_code(b.facade, 0.0)
    codes[built] = style_code | np.rint(lit[built] * 31).astype(np.int32)


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    r = int(math.ceil(sigma * 2.5))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(a, r, mode="edge")
    out = np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 0, pad)
    return np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 1, out)


ELEV_SIGMA = 2.0  # blend width between terrains' elevations, in pixels (see elevation_field)


def elevation_field(ctx: Ctx, mat: np.ndarray, specs: list[MaterialSpec]) -> np.ndarray:
    """Large-scale landforms: each terrain's `elevation` target, blended across terrain borders and
    shaped by ridged world-space noise (peaks, saddles, spurs). The blend only reaches ~7px, which
    both tiles sharing an edge render identically, so relief stays continuous across the seam.
    Liquids stay flat."""
    target = np.array([float(sp.elevation) for sp in specs])[mat]
    if not target.any():
        return np.zeros(mat.shape, np.float32)
    wet = np.array([sp.liquid for sp in specs])[mat]
    smooth = _blur(target, ELEV_SIGMA)
    s = 18.0 * ctx.k
    n1 = value_noise(ctx.wx, ctx.wy, s * 2.2, 71.0)
    n2 = value_noise(ctx.wx, ctx.wy, s, 73.0)
    ridge = 1 - np.abs(2 * (0.65 * n1 + 0.35 * n2) - 1)  # 0..1, sharp crests
    shape = 0.45 + 0.55 * ridge**1.5
    elev = smooth * shape
    return np.where(wet, 0.0, elev).astype(np.float32)


def material_heights(ctx: Ctx, spec: MaterialSpec, name: str) -> np.ndarray:
    h = np.full(ctx.wx.shape, float(spec.height))
    for i, op in enumerate(spec.height_ops):
        seed = _seed(name, 100 + i)
        sc = op.scale * ctx.k
        scale = max(sc, ctx.B * 2)
        if op.op == "patches":
            sel = value_noise(ctx.bcx, ctx.bcy, scale, seed) > 1 - op.amount * 0.8
        elif op.op == "cellfill":
            sel = voronoi(ctx.bcx, ctx.bcy, scale, seed)[2] < op.amount
        elif op.op == "stripes":
            sel = _bands(ctx, 30.0, scale, seed) > 1 - 2 * op.amount * 0.5
        elif op.op == "lots":  # buildings: lots rise, some a level taller than the rest
            inside, lid, lid2 = _lots(ctx, sc, seed)
            sel = inside & (lid < op.amount)
            h = np.where(sel, h + op.delta + (lid2 < 0.35) * np.sign(op.delta), h)
            continue
        elif op.op == "rooms":  # interior walls
            sel = _walls(ctx, sc, op.amount, seed)
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
    """(RGB uint8 (C, C, 3), packed relief int32 (C, C)) for the tile's canvas on the world grid."""
    rgb, heights, _ = render_ground_full(
        tile_px=tile_px, biome=biome, edges=edges, coord=coord, materials=materials, palette=palette
    )
    return rgb, heights


def render_ground_full(
    *,
    tile_px: int,
    biome: str,
    edges: list[dict],
    coord: tuple[int, int],
    materials: dict[str, MaterialSpec | dict] | None = None,
    palette: list[str] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """-> (ground RGB uint8 (C, C, 3); packed relief int32 (C, C): level | LIQUID_BIT | facade code
    << FACADE_SHIFT; facade RGB uint8 (C, C, 3): wall colour of each building pixel)."""
    canvas = TileCanvas(Hex(*coord), tile_px)
    U = unit(tile_px)
    margin = 16  # so framing and connectors at the rim see what lies beyond it
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
    # the warp fades out toward the rim: a point on a shared edge then belongs to that edge's
    # terrain in both tiles, even near a corner where three tiles (and three edge terrains) meet
    d0 = np.max(
        [
            (bx0 * math.cos(math.radians(a)) + by0 * math.sin(math.radians(a))) / apothem
            for a in DIRECTION_ANGLES
        ],
        axis=0,
    )
    fade = np.clip((1.0 - d0) / 0.3, 0.0, 1.0)
    bx, by = bx0 + wx_ * U * 1.2 * fade, by0 + wy_ * U * 1.2 * fade
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

    # --- zoning: where built (straight-edged) terrain meets anything but liquid, whole lattice blocks
    # change hands, so district borders run along the streets instead of wandering through blocks.
    # Natural transitions (forest/grass) and coastlines keep their organic borders.
    X, Y = lattice(tile_px)
    zx = (np.floor(ctx.wx / X) + 0.5) * X - cx
    zy = (np.floor(ctx.wy / Y) + 0.5) * Y - cy
    zdots = np.stack(
        [
            (zx * math.cos(math.radians(a)) + zy * math.sin(math.radians(a))) / apothem
            for a in DIRECTION_ANGLES
        ],
        axis=-1,
    )
    matz = np.where(zdots.max(-1) > 0.5, edge_idx[zdots.argmax(-1)], 0)
    # only blocks wholly inside this hex: a block touching an edge is shared with (or borders) the
    # neighbour, which can't know this tile's zoning; there the organic borders (computed identically
    # by both tiles) decide, so seams stay continuous
    reach = np.zeros_like(zx)
    for sx_, sy_ in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        cxs, cys = zx + sx_ * X / 2, zy + sy_ * Y / 2
        for a in DIRECTION_ANGLES:
            reach = np.maximum(
                reach, (cxs * math.cos(math.radians(a)) + cys * math.sin(math.radians(a))) / apothem
            )
    built_n = np.array([spec_of(n).edges == "straight" for n in names])
    wet_n = np.array([spec_of(n).liquid for n in names])
    zoned = (built_n[mat] | built_n[matz]) & ~wet_n[mat] & ~wet_n[matz] & (reach < 0.985)
    mat = np.where(zoned, matz, mat)

    # --- connectors: blocky paths from the centre to each connector edge's midpoint
    conns = [(i, cn) for i, e in enumerate(edges) for cn in e.get("connectors", [])]
    for cname in sorted({cn for _, cn in conns}):
        idx = len(names)
        names.append(cname)
        cspec = spec_of(cname)
        straight = cspec.edges == "straight"
        # straight connectors are cut per pixel on the lattice (they must meet grid streets exactly)
        px_, py_ = (ctx.wx - cx, ctx.wy - cy) if straight else (bx, by)
        width = U * (0.75 if cspec.liquid else 0.55)
        if straight and not cspec.liquid:
            width = street_half(tile_px)
        dist = np.full(bx.shape, 1e9)
        mine = [i for i, cn in conns if cn == cname]
        segs = straight_segments(mine, apothem) if straight else []
        for x0, y0, x1, y1 in segs:
            dist = np.minimum(dist, _seg_dist(px_, py_, x0, y0, x1, y1))
        for i in [] if straight else mine:
            ang = math.radians(DIRECTION_ANGLES[i])
            mx, my = math.cos(ang) * apothem, math.sin(ang) * apothem
            nx, ny = -math.sin(ang), math.cos(ang)
            amp = 0.0 if straight else U * 0.9 * (1 if (coord[0] * 7 + coord[1] * 13 + i) % 2 else -1)
            for t in np.linspace(0, 1, 32):
                off = amp * 1.6 * math.sin(math.pi * t) * (1 - t)  # zero offset & slope at the edge
                dist = np.minimum(dist, np.hypot(px_ - (mx * t + nx * off), py_ - (my * t + ny * off)))
        if len(mine) == 1 and not straight:  # a dead end (spring, trail end): a small bulb, not a pond
            dist = np.minimum(dist, np.hypot(px_, py_) - width * 0.3)
        mat = np.where(dist <= width, idx, mat)

    # --- city street grids: built materials give up their lattice-street pixels to a street material
    half = street_half(tile_px)
    for k in range(len(names)):
        b = spec_of(names[k]).buildings
        if b is None or b.street_grid <= 0:
            continue
        mk = mat == k
        if not mk.any():
            continue
        road = b.street_material if b.street_material in lib else ASPHALT
        if road == ASPHALT:
            lib.setdefault(ASPHALT, asphalt_material())
        if road not in names:
            names.append(road)
        g = b.street_grid
        on = (_line_dist(ctx.wx, X * g) <= half) | (_line_dist(ctx.wy, Y * g) <= half)
        mat = np.where(mk & on, names.index(road), mat)

    specs = [spec_of(n) for n in names]
    ramps = [ramp_for(sp) for sp in specs]
    img = np.zeros((ctx.C, ctx.C, 3), dtype=np.float32)
    heights = np.zeros((ctx.C, ctx.C), dtype=np.float32)
    facade = np.zeros((ctx.C, ctx.C, 3), dtype=np.uint8)
    codes = np.zeros((ctx.C, ctx.C), dtype=np.int32)
    for k, name in enumerate(names):
        m = mat == k
        if m.any():
            paint_material(img, m, ctx, specs[k], ramps[k], name)
            heights[m] = material_heights(ctx, specs[k], name)[m]
            if specs[k].buildings is not None:
                paint_buildings(img, heights, facade, codes, m, ctx, specs[k].buildings, name)
    heights += elevation_field(ctx, mat, specs)
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

    for k, sp in enumerate(specs):
        if sp.edges == "straight" and sp.markings != "none" and (mat == k).any():
            paint_markings(out, mat == k, ctx, sp, ramps[k], X, Y, half)

    liquid = np.array([sp.liquid for sp in specs])[mat]
    packed = heights.astype(np.int32) | np.where(liquid, LIQUID_BIT, 0) | (codes << FACADE_SHIFT)
    crop = slice(margin, margin + canvas.C)
    return (
        np.clip(out[crop, crop], 0, 255).astype(np.uint8),
        packed[crop, crop].astype(np.int32),
        facade[crop, crop],
    )


def straight_segments(legs: list[int], apothem: float) -> list[tuple[float, float, float, float]]:
    """Straight connectors (streets, canals, corridors) run on an axis-aligned grid: E/W legs go
    straight to the edge; a diagonal leg goes north/south from the centre to its edge midpoint's
    row, then east/west on to the neighbour's centre line (clipped by the hex). Two tiles sharing
    that edge draw the same horizontal run, so the network forms one continuous square grid."""
    segs = []
    for i in legs:
        ang = math.radians(DIRECTION_ANGLES[i])
        mx, my = math.cos(ang) * apothem, math.sin(ang) * apothem
        if abs(my) < 1e-6:
            segs.append((0.0, 0.0, mx, 0.0))
        else:
            segs.append((0.0, 0.0, 0.0, my))
            segs.append((0.0, my, 2 * mx, my))
    return segs


def _seg_dist(px: np.ndarray, py: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    dx, dy = x1 - x0, y1 - y0
    t = np.clip(((px - x0) * dx + (py - y0) * dy) / max(1e-9, dx * dx + dy * dy), 0, 1)
    return np.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def paint_markings(
    img: np.ndarray,
    road: np.ndarray,
    ctx: Ctx,
    spec: MaterialSpec,
    ramp: dict[str, np.ndarray],
    X: float,
    Y: float,
    half: float,
) -> None:
    """Markings on every straight road pixel of one material (connector legs and grid streets alike):
    a stretch of road runs north-south where it hugs a vertical lattice line and continues beyond
    its width both ways, east-west likewise; crossings stay clear. Dashes and sleepers are phased in
    world pixels, so neighbouring tiles agree."""
    dv, dh = _line_dist(ctx.wx, X), _line_dist(ctx.wy, Y)
    o = int(math.ceil(half)) + 1

    def cont(axis: int) -> np.ndarray:
        return np.roll(road, o, axis=axis) & np.roll(road, -o, axis=axis)

    vert = road & (dv <= half) & cont(0)
    horiz = road & (dh <= half) & cont(1)
    v, h = vert & ~horiz, horiz & ~vert
    if spec.markings == "dashed":
        edge = np.zeros_like(road)
        for ax, sh in ((0, 1), (0, -1), (1, 1), (1, -1)):
            edge |= ~np.roll(road, sh, axis=ax)
        img[road & edge] = ramp["light"]  # kerbs
        accent = _hex_rgb(spec.accent_color)
        img[v & (dv < 0.5) & (np.mod(np.floor(ctx.wy), 6) < 3)] = accent
        img[h & (dh < 0.5) & (np.mod(np.floor(ctx.wx), 6) < 3)] = accent
    else:  # rails on sleepers
        gauge = max(1.5, half * 0.6)
        img[v & (dv < gauge + 1) & (np.mod(np.floor(ctx.wy), 3) < 1)] = ramp["dark"]
        img[h & (dh < gauge + 1) & (np.mod(np.floor(ctx.wx), 3) < 1)] = ramp["dark"]
        img[v & (np.abs(dv - gauge) < 0.5)] = ramp["hi"]
        img[h & (np.abs(dh - gauge) < 0.5)] = ramp["hi"]


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
        rgb, levels, fac = render_ground_full(
            tile_px=tile_px, biome=name, edges=edges, coord=(h.q, h.r), materials=mats
        )
        rgb = relief_shade(rgb, levels, level_px=max(1, round(2 * tile_px / 64)), facade=fac)
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
