"""Hex grid math: pointy-top axial coordinates.

Conventions (shared with the frontend, see frontend/src/board/hexMath.ts):
- Axial (q, r); cube s = -q - r.
- Pixel/world layout, y (screen) grows downward / maps to +z in three.js:
    x = size * sqrt(3) * (q + r / 2)
    y = size * 1.5 * r
- Direction / edge index i (0..5) names the neighbor across edge i:
    0 E (+1, 0)   1 NE (+1, -1)   2 NW (0, -1)
    3 W (-1, 0)   4 SW (-1, +1)   5 SE (0, +1)
  Edge i of a tile touches edge (i + 3) % 6 of its neighbor.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

SQRT3 = math.sqrt(3.0)

DIRECTIONS: tuple[tuple[int, int], ...] = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
DIRECTION_NAMES: tuple[str, ...] = ("E", "NE", "NW", "W", "SW", "SE")
# Screen angle (degrees, y down) from a hex center to the neighbor across edge i.
DIRECTION_ANGLES: tuple[float, ...] = (0.0, -60.0, -120.0, 180.0, 120.0, 60.0)


@dataclass(frozen=True, slots=True, order=True)
class Hex:
    q: int
    r: int

    @property
    def s(self) -> int:
        return -self.q - self.r

    @property
    def key(self) -> str:
        return f"{self.q},{self.r}"

    @classmethod
    def parse(cls, key: str) -> Hex:
        q, r = key.split(",")
        return cls(int(q), int(r))

    def __add__(self, other: Hex) -> Hex:
        return Hex(self.q + other.q, self.r + other.r)

    def __sub__(self, other: Hex) -> Hex:
        return Hex(self.q - other.q, self.r - other.r)

    def neighbor(self, direction: int) -> Hex:
        dq, dr = DIRECTIONS[direction % 6]
        return Hex(self.q + dq, self.r + dr)

    def neighbors(self) -> list[Hex]:
        return [self.neighbor(i) for i in range(6)]

    def distance(self, other: Hex) -> int:
        d = self - other
        return max(abs(d.q), abs(d.r), abs(d.s))

    def direction_to(self, other: Hex) -> int | None:
        """Edge index shared with an adjacent hex, or None if not adjacent."""
        d = other - self
        try:
            return DIRECTIONS.index((d.q, d.r))
        except ValueError:
            return None

    def color3(self) -> int:
        """A proper 3-coloring of the hex grid: adjacent hexes never share a color.

        Every neighbor offset changes (q - r) by ±1 or ±2, never by a multiple of 3.
        """
        return (self.q - self.r) % 3

    def to_pixel(self, size: float) -> tuple[float, float]:
        return (size * SQRT3 * (self.q + self.r / 2.0), size * 1.5 * self.r)


ORIGIN = Hex(0, 0)


def opposite(edge: int) -> int:
    return (edge + 3) % 6


def ring(center: Hex, radius: int) -> list[Hex]:
    if radius == 0:
        return [center]
    results: list[Hex] = []
    # Start at the hex `radius` steps in direction 4 (SW), then walk the six sides.
    h = Hex(center.q + DIRECTIONS[4][0] * radius, center.r + DIRECTIONS[4][1] * radius)
    for side in range(6):
        for _ in range(radius):
            results.append(h)
            h = h.neighbor(side)
    return results


def spiral(center: Hex, radius: int) -> list[Hex]:
    out: list[Hex] = []
    for k in range(radius + 1):
        out.extend(ring(center, k))
    return out


def within(center: Hex, radius: int) -> Iterator[Hex]:
    for q in range(-radius, radius + 1):
        for r in range(max(-radius, -q - radius), min(radius, -q + radius) + 1):
            yield Hex(center.q + q, center.r + r)


def corner(size: float, i: int) -> tuple[float, float]:
    """Corner i of a pointy-top hex centered at the origin (screen coords, y down).

    Corners sit at angles -30 + 60*i degrees. Edge e runs between the corners at
    DIRECTION_ANGLES[e] - 30 and DIRECTION_ANGLES[e] + 30.
    """
    a = math.radians(-30.0 + 60.0 * i)
    return (size * math.cos(a), size * math.sin(a))


def edge_endpoints(size: float, edge: int) -> tuple[tuple[float, float], tuple[float, float]]:
    base = DIRECTION_ANGLES[edge]
    a0, a1 = math.radians(base - 30.0), math.radians(base + 30.0)
    return (
        (size * math.cos(a0), size * math.sin(a0)),
        (size * math.cos(a1), size * math.sin(a1)),
    )
