"""Prop layout: fit several sprites on one hex without overlaps or spilling out of the tile.

Coordinates are tile-local in hex circumradius units (pointy-top, x east, y south); a sprite is
anchored at its bottom centre. Requests come from the tile agent (kind + rough position + scale);
the engine keeps each footprint inside the hex, keeps the sprite's top inside the tile's own
outline in the top-down preview (so it never reads as part of the tile to the north), and nudges
or shrinks props so they don't cover each other. Larger props are placed first; a prop that can't
be fitted is dropped (reported to the caller).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

# (x, y, w, surface) -> may a sprite of width w stand with its feet at (x, y)? surface is 'land'
# (people, trees, carts: not on rooftops or water) or 'water' (boats and other floating things)
GroundOk = Callable[[float, float, float, str], bool]

SQRT3 = math.sqrt(3)
MARGIN = 0.1  # keep footprints this far inside the rim
MAX_W_LANDMARK = 0.95  # widths in radii
MAX_W_PROP = 0.6
MAX_W_SCATTER = 0.4


@dataclass
class PropRequest:
    kind: str
    x: float
    y: float
    scale: float
    art_w: int  # sprite pixels
    art_h: int
    role: str = "prop"  # landmark | prop | scatter
    surface: str = "land"  # land | water (floating things)


@dataclass
class PropSlot:
    kind: str
    x: float
    y: float
    scale: float  # final pixel scale of the art
    w: float  # radii
    h: float
    role: str
    surface: str = "land"


def half_width_at(y: float) -> float:
    """Half the hex's width at height y (0 outside)."""
    ay = abs(y)
    if ay >= 1:
        return 0.0
    return min(SQRT3 / 2, SQRT3 * (1 - ay))


def top_at(x: float) -> float:
    """The hex's northern outline at x (negative y)."""
    return -(1 - abs(x) / SQRT3)


def _fits(
    x: float, y: float, w: float, h: float, ground_ok: GroundOk | None = None, surface: str = "land"
) -> bool:
    hw = half_width_at(y) - MARGIN
    if y > 1 - MARGIN * 1.5 or abs(x) + w / 2 > hw:
        return False
    # the sprite's top edge must stay inside the tile's northern outline (top-down preview)
    if not all(y - h >= top_at(px) + 0.04 for px in (x - w / 2, x, x + w / 2)):
        return False
    return ground_ok is None or ground_ok(x, y, w, surface)


def _overlap(a: PropSlot, x: float, y: float, w: float, h: float) -> float:
    """Overlap of two sprite boxes as a fraction of the smaller box."""
    ox = max(0.0, min(a.x + a.w / 2, x + w / 2) - max(a.x - a.w / 2, x - w / 2))
    oy = max(0.0, min(a.y, y) - max(a.y - a.h, y - h))
    return (ox * oy) / max(1e-6, min(a.w * a.h, w * h))


def _nearest_free(
    x0: float,
    y0: float,
    w: float,
    h: float,
    placed: list[PropSlot],
    tol: float,
    ground_ok: GroundOk | None = None,
    step: float = 0.07,
    surface: str = "land",
) -> tuple[float, float] | None:
    """The valid anchor closest to (x0, y0): spiral outwards over the whole hex."""
    rings = int(1.1 / step) + 1
    for ring in range(0, rings):
        rad = ring * step
        steps = 1 if ring == 0 else 8 + ring * 2
        for k in range(steps):
            ang = k / steps * math.tau
            x, y = x0 + math.cos(ang) * rad, y0 + math.sin(ang) * rad
            if _fits(x, y, w, h, ground_ok, surface) and all(_overlap(p, x, y, w, h) <= tol for p in placed):
                return x, y
    return None


def _order(role: str) -> int:
    return {"landmark": 0, "prop": 1, "scatter": 2}.get(role, 1)


def layout_props(
    reqs: list[PropRequest], tile_px: int, size: float = 1.0, ground_ok: GroundOk | None = None
) -> tuple[list[PropSlot], list[str]]:
    """-> (placed slots, kinds that could not be fitted). `size` scales every sprite (the world's
    prop_scale); `ground_ok` restricts where feet may stand (streets and yards, not rooftops)."""
    r_px = tile_px / 2.0
    order = sorted(reqs, key=lambda q: (_order(q.role), -q.art_w * q.art_h * q.scale**2))
    placed: list[PropSlot] = []
    dropped: list[str] = []
    for q in order:
        cap = {"landmark": MAX_W_LANDMARK, "prop": MAX_W_PROP, "scatter": MAX_W_SCATTER}[q.role] * size
        scale = min(q.scale * size, cap * r_px / max(1, q.art_w))
        tol = 0.35 if q.role == "scatter" else 0.18
        # fine search steps for small sprites: city streets are narrow
        step = min(0.07, max(0.025, 0.07 * size))
        slot = None
        for _ in range(6):  # shrink a little if nothing fits
            w, h = q.art_w * scale / r_px, q.art_h * scale / r_px
            best = _nearest_free(q.x, q.y, w, h, placed, tol, ground_ok, step, q.surface)
            if best is None and q.role == "landmark":  # a landmark is never dropped
                best = _nearest_free(
                    0.0, 0.3, w, h, placed, 1.0, ground_ok, step, q.surface
                ) or _nearest_free(0.0, 0.3, w, h, placed, 1.0)
            if best is not None:
                slot = PropSlot(q.kind, best[0], best[1], scale, w, h, q.role, q.surface)
                break
            scale *= 0.85
        if slot is None:
            dropped.append(q.kind)
        else:
            placed.append(slot)
    return placed, dropped


def relocate(slots: list[PropSlot], ground_ok: GroundOk) -> tuple[list[PropSlot], list[str]]:
    """Re-seat already sized sprites after the ground under them changed (a repainted material
    raised buildings where a prop stood): each one moves to the nearest open spot, or is dropped."""
    kept: list[PropSlot] = []
    dropped: list[str] = []
    for sl in sorted(slots, key=lambda s: (_order(s.role), -s.w * s.h)):
        tol = 1.0 if sl.role == "landmark" else 0.35 if sl.role == "scatter" else 0.18
        best = _nearest_free(sl.x, sl.y, sl.w, sl.h, kept, tol, ground_ok, 0.03, sl.surface)
        if best is None and sl.role == "landmark":
            best = (sl.x, sl.y)
        if best is None:
            dropped.append(sl.kind)
            continue
        kept.append(PropSlot(sl.kind, best[0], best[1], sl.scale, sl.w, sl.h, sl.role, sl.surface))
    return kept, dropped
