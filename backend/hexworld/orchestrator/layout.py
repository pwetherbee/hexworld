"""Rasterize the super's Layout (regions of shape primitives + landmarks + routes) into tiles.

The planner describes the map's SHAPE, not every tile: this is what lets it draw long coasts,
archipelagos, patchwork districts or floor plans at any size without writing hundreds of tile
entries. The result is a list of PlannedTile the orchestrator treats like any other plan.

Rules:
- Regions are painted in order (a later region overrides an earlier one); 'void' regions carve
  tiles out. Landmarks force their tile in. The origin tile is always included.
- Occupied tiles (already built) and tiles outside the world are skipped.
- The plan is capped at `max_tiles`, keeping tiles in breadth-first order from the origin, so a
  plan that is too big is trimmed at its far ends, never punched full of holes.
- Routes become edge hints: consecutive tiles on a route share the connector on their common edge.
- A region's features are scattered over its tiles by feature_density (deterministic per tile).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from hexworld.domain import (
    Coord,
    CopySpec,
    EdgeHint,
    Landmark,
    Layout,
    PlannedTile,
    Region,
    Route,
    ShapeSpec,
)
from hexworld.domain.art import is_building_kind
from hexworld.hex import ORIGIN, Hex, opposite, within


@dataclass
class Rasterized:
    tiles: list[PlannedTile]
    dropped_over_cap: int = 0
    skipped_occupied: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def compactness(self) -> float:
        return compactness([Hex(t.q, t.r) for t in self.tiles])


COMPACT_ENOUGH = 0.3  # below this a plan reads as a snake/ribbon rather than a region


def compactness(hexes: list[Hex]) -> float:
    """How much of its enclosing hexagon a shape fills: tiles / area of the smallest hexagon,
    centred on the tile nearest the shape's centroid, that contains every tile. A solid hexagon is
    1.0, a blob with a ragged coast ~0.6-0.8, a 2:1 region ~0.45, a long one-tile ribbon ~0.05."""
    if len(hexes) < 7:
        return 1.0
    pts = [h.to_pixel(1.0) for h in hexes]
    cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    centre = min(hexes, key=lambda h: (h.to_pixel(1.0)[0] - cx) ** 2 + (h.to_pixel(1.0)[1] - cy) ** 2)
    R = max(h.distance(centre) for h in hexes)
    return len(hexes) / (3 * R * (R + 1) + 1)


def _hash(q: int, r: int, salt: float) -> float:
    v = math.sin(q * 127.1 + r * 311.7 + salt * 74.7) * 43758.5453
    return v - math.floor(v)


def _noise(h: Hex, scale: float, salt: float) -> float:
    """Smooth value noise over hex centres (0..1)."""
    x, y = h.to_pixel(1.0)
    gx, gy = x / scale, y / scale
    x0, y0 = math.floor(gx), math.floor(gy)
    fx, fy = gx - x0, gy - y0
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash(x0, y0, salt), _hash(x0 + 1, y0, salt)
    c, d = _hash(x0, y0 + 1, salt), _hash(x0 + 1, y0 + 1, salt)
    return (a + (b - a) * sx) * (1 - sy) + (c + (d - c) * sx) * sy


def hex_line(a: Hex, b: Hex) -> list[Hex]:
    n = a.distance(b)
    if n == 0:
        return [a]
    out = []
    for i in range(n + 1):
        t = i / n
        q = a.q + (b.q - a.q) * t + 1e-6
        r = a.r + (b.r - a.r) * t + 1e-6
        s = -q - r
        rq, rr, rs = round(q), round(r), round(s)
        dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
        if dq > dr and dq > ds:
            rq = -rr - rs
        elif dr > ds:
            rr = -rq - rs
        h = Hex(rq, rr)
        if not out or out[-1] != h:
            out.append(h)
    return out


GUIDED_DENSITY = 0.3  # ambient features per tile up close (the parent's own props come on top)


def guided_hints(routes: list[Route], radius: int, centre: Hex = ORIGIN) -> dict[Hex, dict[int, set[str]]]:
    """Edge connectors of a drilled region's tiles from the parent's traced streets (tile -> edge ->
    connectors). Both tiles sharing an edge get it; a street leaving the region leads out of its rim
    tile. The same for the early origin tile as for the rest of the plan."""
    hints: dict[Hex, dict[int, set[str]]] = {}
    for route in routes:
        path = _polyline(route.points)
        for a, b in zip(path, path[1:], strict=False):
            if a.distance(centre) > radius:
                a, b = b, a
            if a.distance(centre) > radius:
                continue
            i = next((k for k in range(6) if a.neighbor(k) == b), None)
            if i is not None:
                hints.setdefault(a, {}).setdefault(i, set()).add(route.connector)
                if b.distance(centre) <= radius:
                    hints.setdefault(b, {}).setdefault(opposite(i), set()).add(route.connector)
    return hints


def _polyline(points: list[Coord]) -> list[Hex]:
    cells: list[Hex] = []
    for a, b in zip(points, points[1:], strict=False):
        for h in hex_line(a.hex, b.hex):
            if not cells or cells[-1] != h:
                cells.append(h)
    if len(points) == 1:
        cells.append(points[0].hex)
    return cells


def shape_cells(s: ShapeSpec, salt: float) -> set[Hex]:
    c = s.center.hex if s.center is not None else ORIGIN
    if s.kind == "hex":
        return set(within(c, s.radius))
    if s.kind == "blob":
        out = set()
        reach = s.radius + max(1, math.ceil(s.radius * s.roughness * 0.7))
        for h in within(c, reach):
            n = _noise(h, 2.2 + s.radius * 0.35, salt) * 2 - 1
            if h == c or h.distance(c) <= s.radius + s.roughness * s.radius * 0.7 * n:
                out.add(h)
        return out
    if s.kind == "path":
        out = set()
        for h in _polyline(s.points or ([s.center] if s.center else [])):
            out.update(within(h, s.width - 1))
        return out
    # rect: w columns x h rows in odd-r offset coordinates, centred on `center`
    col0 = c.q + (c.r - (c.r & 1)) // 2 - (s.w - 1) // 2
    row0 = c.r - (s.h - 1) // 2
    out = set()
    for row in range(row0, row0 + s.h):
        for col in range(col0, col0 + s.w):
            out.add(Hex(col - (row - (row & 1)) // 2, row))
    return out


def rasterize(
    layout: Layout,
    *,
    origin: Hex,
    origin_tile: PlannedTile | None,
    max_tiles: int,
    world_radius: int,
    occupied: set[Hex],
    connectors: set[str],
    fill_radius: bool = False,
    guide: dict[Hex, str] | None = None,
    guide_routes: list[Route] | None = None,
    guide_notes: dict[Hex, str] | None = None,
    guide_props: dict[Hex, list[str]] | None = None,
) -> Rasterized:
    res = Rasterized(tiles=[])
    owner: dict[Hex, int] = {}  # tile -> region index
    for i, reg in enumerate(layout.regions):
        cells: set[Hex] = set()
        for k, s in enumerate(reg.shapes):
            cells |= shape_cells(s, salt=i * 7.3 + k * 1.9)
        for h in cells:
            if reg.mode == "void":
                owner.pop(h, None)
            else:
                owner[h] = i
    if guide:  # the layout is the parent tile zoomed in: each tile's terrain is given
        regions = list(layout.regions)
        by_biome = {r.biome: i for i, r in enumerate(regions) if r.mode == "add"}
        for h, name in guide.items():
            if name not in by_biome:
                by_biome[name] = len(regions)
                regions.append(
                    Region(
                        name=name, biome=name, intent=name.replace("_", " "), shapes=[], feature_density=0.3
                    )
                )
            owner[h] = by_biome[name]
        # streets are the parent's too (traced); the planner's own routes would invent new ones
        layout = layout.model_copy(update={"regions": regions, "routes": list(guide_routes or [])})
    marks: dict[Hex, Landmark] = {}
    for lm in layout.landmarks:
        h = Hex(lm.q, lm.r)
        marks[h] = lm
        if h not in owner:
            owner[h] = _nearest_region(h, owner)
    # the origin is always part of the plan
    if origin not in owner:
        owner[origin] = _nearest_region(origin, owner)

    if fill_radius and owner:  # a drilled layer is a whole hexagon: gaps take the nearest region
        painted = dict(owner)
        for h in within(ORIGIN, world_radius):
            if h not in owner:
                owner[h] = _nearest_region(h, painted)

    # drop what can't be built
    before = len(owner)
    owner = {
        h: i
        for h, i in owner.items()
        if h.distance(ORIGIN) <= world_radius and (h not in occupied or h == origin)
    }
    res.skipped_occupied = before - len(owner)

    # stray fragments (a tile or two cut off by a void or a shape's rough outline) read as bugs;
    # real islands are bigger or carry a landmark (an islet lighthouse)
    comp_of: dict[Hex, int] = {}
    comps: list[list[Hex]] = []
    for h0 in owner:
        if h0 in comp_of:
            continue
        comp, dq = [h0], deque([h0])
        comp_of[h0] = len(comps)
        while dq:
            for n in dq.popleft().neighbors():
                if n in owner and n not in comp_of:
                    comp_of[n] = len(comps)
                    comp.append(n)
                    dq.append(n)
        comps.append(comp)
    main = next((c for c in comps if origin in c), [origin])
    main_set = set(main)
    for comp in comps:
        if origin in comp:
            continue
        # a fragment one or two tiles off the main map was meant to be part of it (a headland, a
        # lighthouse point): bridge the gap with the nearest region's terrain (often the sea)
        a, b = min(((x, y) for x in comp for y in main), key=lambda p: p[0].distance(p[1]))
        if a.distance(b) <= 3:
            for h in hex_line(a, b):
                if h not in owner and h.distance(ORIGIN) <= world_radius and h not in occupied:
                    owner[h] = _nearest_region(h, {k: v for k, v in owner.items() if k in main_set})
            res.notes.append(f"joined a detached {len(comp)}-tile fragment at {comp[0].q},{comp[0].r}")
        elif len(comp) < 3 and not any(h in marks for h in comp):
            for h in comp:
                owner.pop(h)
            res.notes.append(f"dropped a stray {len(comp)}-tile fragment at {comp[0].q},{comp[0].r}")

    # cap: landmarks first (with the tiles linking them to the origin), then breadth-first from
    # the origin (then any other component, nearest first)
    kept: set[Hex] = {origin}
    keep: list[Hex] = [origin]

    def take(h: Hex) -> None:
        if h not in kept and len(keep) < max_tiles:
            kept.add(h)
            keep.append(h)

    for lm_hex in marks:
        if lm_hex in owner:
            for h in _path_within(origin, lm_hex, owner):
                take(h)
    seen: set[Hex] = set()
    starts = [origin] + sorted((h for h in owner if h != origin), key=lambda h: h.distance(origin))
    total = 0
    for s0 in starts:
        if s0 in seen:
            continue
        dq = deque([s0])
        seen.add(s0)
        while dq:
            h = dq.popleft()
            total += 1
            take(h)
            for n in h.neighbors():
                if n in owner and n not in seen:
                    seen.add(n)
                    dq.append(n)
    res.dropped_over_cap = total - len(keep)
    keep.sort(key=lambda h: (h.distance(origin), h.q, h.r))

    # routes -> edge hints
    hints: dict[Hex, dict[int, set[str]]] = {}
    if guide:
        hints = guided_hints(layout.routes, world_radius, origin)
    for route in [] if guide else layout.routes:
        if route.connector not in connectors:
            res.notes.append(f"route connector '{route.connector}' is not in connector_vocabulary")
            continue
        path = _polyline(route.points)
        for a, b in zip(path, path[1:], strict=False):
            if a in kept and b in kept:
                i = next((k for k in range(6) if a.neighbor(k) == b), None)
                if i is not None:
                    hints.setdefault(a, {}).setdefault(i, set()).add(route.connector)
                    hints.setdefault(b, {}).setdefault(opposite(i), set()).add(route.connector)

    # prototypes for copy-filled regions: the region's kept tile nearest the origin without extras
    # (landmarks, routes)
    protos: dict[int, Hex] = {}
    for h in keep:
        i = owner[h]
        plain = h not in marks and h not in hints and h != origin  # copies must not carry its routes
        if layout.regions[i].fill != "generate" and i not in protos and plain:
            protos[i] = h

    for h in keep:
        reg: Region = layout.regions[owner[h]]
        lm = marks.get(h)
        if h == origin and origin_tile is not None:
            pt = origin_tile.model_copy(update={"q": h.q, "r": h.r, "leave_empty": False})
            res.tiles.append(pt)
            continue
        if guide:  # up close: the parent's own props where they stood, and a light scatter
            reg = reg.model_copy(update={"feature_density": min(reg.feature_density, GUIDED_DENSITY)})
        feats = [f for f in lm.features if not is_building_kind(f)] if lm else _scatter(reg, h)
        feats = [*(guide_props or {}).get(h, []), *feats][:3]
        biome = reg.biome if guide else (lm.biome if lm and lm.biome else None) or reg.biome
        note = (guide_notes or {}).get(h)
        edge_hints = [
            EdgeHint(edge=i, terrain=biome, connectors=sorted(cs))
            for i, cs in sorted(hints.get(h, {}).items())
        ]
        dup = CopySpec(mode="none", source_q=0, source_r=0)
        proto = protos.get(owner[h])
        if proto is not None and proto != h and not lm and not feats and not edge_hints:
            dup = CopySpec(mode=reg.fill.split("_")[0], source_q=proto.q, source_r=proto.r)  # type: ignore[arg-type]
        res.tiles.append(
            PlannedTile(
                q=h.q,
                r=h.r,
                leave_empty=False,
                biome=biome,
                intent=(lm.intent if lm else reg.intent)
                + (f" Up close, this tile is {note}." if note else ""),
                features=feats,
                edge_hints=edge_hints,
                priority=5 if lm else reg.priority,
                duplicate=dup,
            )
        )
    return res


def _path_within(a: Hex, b: Hex, cells: dict[Hex, int]) -> list[Hex]:
    """Shortest path a -> b through planned cells (empty if b is in another component)."""
    prev: dict[Hex, Hex | None] = {a: None}
    dq = deque([a])
    while dq:
        h = dq.popleft()
        if h == b:
            out = []
            cur: Hex | None = h
            while cur is not None:
                out.append(cur)
                cur = prev[cur]
            return out[::-1]
        for n in h.neighbors():
            if n in cells and n not in prev:
                prev[n] = h
                dq.append(n)
    return [b]


def _nearest_region(h: Hex, owner: dict[Hex, int]) -> int:
    if not owner:
        return 0
    return min(owner.items(), key=lambda kv: kv[0].distance(h))[1]


def _scatter(reg: Region, h: Hex) -> list[str]:
    feats = [f for f in reg.features if not is_building_kind(f)]
    if not feats or reg.feature_density <= 0:
        return []
    reg = reg.model_copy(update={"features": feats})
    roll = _hash(h.q, h.r, 3.3 + len(reg.name))
    if roll >= reg.feature_density:
        return []
    # busy regions get a little crowd; each tile a different slice of the region's cast
    n = 1 + (reg.feature_density > 0.4) + (reg.feature_density > 0.75 and _hash(h.q, h.r, 9.1) < 0.6)
    start = int(_hash(h.q, h.r, 5.7) * len(reg.features))
    return [reg.features[(start + k) % len(reg.features)] for k in range(min(n, len(reg.features)))]
