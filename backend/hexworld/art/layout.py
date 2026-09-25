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
from dataclasses import dataclass

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


@dataclass
class PropSlot:
    kind: str
    x: float
    y: float
    scale: float  # final pixel scale of the art
    w: float  # radii
    h: float
    role: str


def half_width_at(y: float) -> float:
    """Half the hex's width at height y (0 outside)."""
    ay = abs(y)
    if ay >= 1:
        return 0.0
    return min(SQRT3 / 2, SQRT3 * (1 - ay))


def top_at(x: float) -> float:
    """The hex's northern outline at x (negative y)."""
    return -(1 - abs(x) / SQRT3)


def _fits(x: float, y: float, w: float, h: float) -> bool:
    hw = half_width_at(y) - MARGIN
    if y > 1 - MARGIN * 1.5 or abs(x) + w / 2 > hw:
        return False
    # the sprite's top edge must stay inside the tile's northern outline (top-down preview)
    return all(y - h >= top_at(px) + 0.04 for px in (x - w / 2, x, x + w / 2))


def _overlap(a: PropSlot, x: float, y: float, w: float, h: float) -> float:
    """Overlap of two sprite boxes as a fraction of the smaller box."""
    ox = max(0.0, min(a.x + a.w / 2, x + w / 2) - max(a.x - a.w / 2, x - w / 2))
    oy = max(0.0, min(a.y, y) - max(a.y - a.h, y - h))
    return (ox * oy) / max(1e-6, min(a.w * a.h, w * h))


def layout_props(reqs: list[PropRequest], tile_px: int) -> tuple[list[PropSlot], list[str]]:
    """-> (placed slots, kinds that could not be fitted)."""
    r_px = tile_px / 2.0
    order = sorted(
        reqs,
        key=lambda q: ({"landmark": 0, "prop": 1, "scatter": 2}[q.role], -q.art_w * q.art_h * q.scale**2),
    )
    placed: list[PropSlot] = []
    dropped: list[str] = []
    for q in order:
        cap = {"landmark": MAX_W_LANDMARK, "prop": MAX_W_PROP, "scatter": MAX_W_SCATTER}[q.role]
        scale = min(q.scale, cap * r_px / max(1, q.art_w))
        slot = None
        for _ in range(4):  # shrink a little if nothing fits
            w, h = q.art_w * scale / r_px, q.art_h * scale / r_px
            tol = 0.35 if q.role == "scatter" else 0.18
            best = None
            for ring in range(0, 7):
                rad = ring * 0.08
                steps = 1 if ring == 0 else 10
                for k in range(steps):
                    ang = k / steps * math.tau
                    x, y = q.x + math.cos(ang) * rad, q.y + math.sin(ang) * rad
                    if not _fits(x, y, w, h):
                        continue
                    if any(_overlap(p, x, y, w, h) > tol for p in placed):
                        continue
                    best = (x, y)
                    break
                if best:
                    break
            if best:
                slot = PropSlot(q.kind, best[0], best[1], scale, w, h, q.role)
                break
            scale *= 0.85
        if slot is None:
            dropped.append(q.kind)
        else:
            placed.append(slot)
    return placed, dropped
