"""Navigation across layers: enter a tile (its region grid is built on first entry), look at a tile
up close (a painted scene, made once), and the player's avatar.

The overworld is a world at depth 0. Entering one of its tiles opens a child world: a full hexagon
of finer tiles planned as the inside of that tile (same style and lore, its own finer terrains). A
tile of any layer can be looked at: a layered pixel-art scene painted from the tile's own data.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from hexworld.art.grid import TileCanvas
from hexworld.art.paint import pixelize_sprite, style_frame
from hexworld.art.pixelize import crisp_tile
from hexworld.art.procedural import lattice, render_ground_full, street_half
from hexworld.art.relief import facade_codes, split_levels
from hexworld.art.scene import (
    PAINT_SIZE,
    SCENE_H,
    SCENE_W,
    backdrop_prompt,
    fallback_backdrop,
    foreground_prompt,
    pixelize_scene,
    scene_fx,
)
from hexworld.domain import (
    Coord,
    ParentLink,
    Route,
    Run,
    RunOptions,
    Scene,
    SceneLayer,
    SkirtTile,
    Tile,
    TileStatus,
    World,
)
from hexworld.domain.art import SpriteEntry
from hexworld.hex import DIRECTION_NAMES, ORIGIN, SQRT3, Hex, ring, within
from hexworld.orchestrator.layout import hex_line
from hexworld.telemetry import Tracer, new_id

if TYPE_CHECKING:
    from hexworld.orchestrator.runtime import Runtime

DEFAULT_RADIUS = 3
SCENE_VERSION = 2  # 2: painted from a map of the surroundings and a described view
AVATAR = "traveller"
SCALE_NOTES = {
    1: "one tile is about a tenth of the overworld tile it lies in: a street corner, a clearing, a "
    "stretch of shore, a single building's lot or courtyard. The streets are the map above's streets "
    "(connectors through the tiles they cross), so buildings here use street_grid 0 and fill their block",
    2: "one tile is a room, a yard or a corner of a street",
}


def _pretty(name: str | None) -> str:
    return (name or "").replace("_", " ")


def hex_count(radius: int) -> int:
    return 3 * radius * (radius + 1) + 1


class Layers:
    def __init__(self, rt: Runtime):
        self.rt = rt
        self._inflight: dict[str, asyncio.Future] = {}
        self._skirts: dict[tuple[str, int, int], list[SkirtTile]] = {}

    @property
    def store(self):
        return self.rt.store

    def _painter(self) -> Any:
        p = self.rt.painter
        return getattr(p, "painter", p)  # packs/sheets wrap the raw painter

    async def _single_flight(self, key: str, make):
        fut = self._inflight.get(key)
        if fut is not None:
            return await asyncio.shield(fut)
        fut = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            res = await make()
            fut.set_result(res)
            return res
        except BaseException as e:
            fut.set_exception(e)
            fut.exception()
            raise
        finally:
            self._inflight.pop(key, None)

    # ------------------------------------------------------------------ entering a tile

    def _parent_context(self, world: World, tile: Tile) -> dict[str, Any]:
        tiles = {t.hex: t for t in self.store.list_tiles(world.id)}
        edges = {}
        for i, e in enumerate(tile.edges or []):
            n = tiles.get(tile.hex.neighbor(i))
            edges[DIRECTION_NAMES[i]] = {
                "terrain": e.terrain,
                "connectors": list(e.connectors),
                "beyond": _pretty(n.biome) if n and n.biome else "the edge of the world",
            }
        return {
            "world": world.spec.title if world.spec else world.name,
            "lore": world.spec.lore if world.spec else "",
            "biome": tile.biome,
            "summary": tile.summary,
            "attributes": tile.attributes,
            "edges": edges,
            "sprites": [la.label for la in tile.layers if la.kind == "sprite" and la.label],
            "depth": world.depth,
        }

    def _root(self, world: World) -> World:
        while world.parent is not None and (up := self.store.get_world(world.parent.world_id)) is not None:
            world = up
        return world

    async def enter(
        self, world_id: str, q: int, r: int, radius: int | None = None
    ) -> tuple[World, Run | None]:
        """The world inside tile (q, r) of `world_id`; created and built on the first entry. Its size
        is the overworld's region radius (chosen when the world was created) unless given."""
        if radius is None:
            w = self.store.get_world(world_id)
            radius = self._root(w).region_radius if w else DEFAULT_RADIUS
        return await self._single_flight(
            f"enter:{world_id}:{q},{r}", lambda: self._enter(world_id, q, r, radius)
        )

    async def _enter(self, world_id: str, q: int, r: int, radius: int) -> tuple[World, Run | None]:
        parent = self.store.get_world(world_id)
        if parent is None:
            raise KeyError(world_id)
        child_id = self.store.get_drill(world_id, q, r)
        if child_id is not None and (child := self.store.get_world(child_id)) is not None:
            run_id = self.rt.active_run(child_id)
            run = self.store.get_run(run_id) if run_id else None
            if run is None and not self.store.list_tiles(child_id):  # never built (e.g. a crash): build now
                run = await self._build(child, self.store.get_tile(world_id, q, r))
            return child, run
        tile = self.store.get_tile(world_id, q, r)
        if tile.status != TileStatus.accepted:
            raise ValueError(f"tile ({q},{r}) isn't built yet")
        assert parent.spec is not None and parent.style is not None
        depth = parent.depth + 1
        g = await asyncio.to_thread(self._guide, parent, tile, radius)
        guide, routes, marks = g.terrain, g.routes, g.marks
        counts: dict[str, int] = {}
        for v in guide.values():
            counts[v] = counts.get(v, 0) + 1
        terrains = ", ".join(
            f"{_pretty(n)} ({c} tiles)" for n, c in sorted(counts.items(), key=lambda kv: -kv[1])
        )
        street_names = sorted({rt.connector for rt in routes})
        context = self._parent_context(parent, tile)
        context["layout"] = {
            "note": "fixed by the parent tile: its own map zoomed up (terrain -> number of tiles)",
            "terrains": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        }
        if routes:
            n_street = len({(p.q, p.r) for rt in routes for p in rt.points})
            context["layout"]["streets"] = (
                f"the parent's streets run through {n_street} tiles as the {', '.join(street_names)} "
                "connector (given: don't add routes); the tiles either side are the blocks"
            )
        context["landmarks"] = marks
        context["scale"] = g.scale
        if g.props:
            context["props"] = {
                "note": "the parent tile's props, at the region tiles where they stood (tile -> kinds)",
                "at": g.props,
            }
        vocab = [
            t for t in dict.fromkeys([*counts, tile.biome or "", *[e.terrain for e in tile.edges or []]]) if t
        ]
        conns = sorted({c for e in tile.edges or [] for c in e.connectors} | set(street_names))
        up_close = (
            f"The inside of one tile of the map above, up close: {(tile.summary or _pretty(tile.biome)).rstrip('.')}. "
            f"Its layout is that tile's own map zoomed in: {terrains}"
            + (f", crossed by the parent's {', '.join(map(_pretty, street_names))}" if routes else "")
            + ". Nothing else from the wider map (its coasts, parks, districts) is inside this region."
        )
        name = f"{parent.name} › {_pretty(tile.biome).title()}"
        child = World(
            id=new_id("w"),
            name=name,
            radius=radius,
            created_at=time.time(),
            parent=ParentLink(
                world_id=world_id,
                q=q,
                r=r,
                context=context,
                guide=guide,
                routes=routes,
                notes=g.notes,
                props=g.props,
            ),
            depth=depth,
            scale_note=SCALE_NOTES.get(depth, SCALE_NOTES[2]),
            spec=parent.spec.model_copy(
                update={
                    "title": name,
                    "terrain_vocabulary": vocab,
                    "connector_vocabulary": conns or list(parent.spec.connector_vocabulary[:2]),
                    # the parent's notes describe the wider map; here they would mislead every agent
                    "directional_notes": up_close,
                    "prop_scale": max(parent.spec.prop_scale, 1.0),  # people and things are big up close
                }
            ),
            style=parent.style.model_copy(deep=True),
            tile_attributes=list(parent.tile_attributes),
            region_radius=parent.region_radius,
        )
        self.store.put_world(child)
        self.store.put_drill(world_id, q, r, child.id)
        Tracer(child.id, None, self.store.append_event).emit(
            "world.created", data={"name": child.name, "radius": radius, "parent": world_id, "q": q, "r": r}
        )
        return child, await self._build(child, tile)

    def _guide(self, parent: World, tile: Tile, radius: int) -> Guide:
        """The parent tile's own map, zoomed up to the region: which terrain lies under each region tile
        (thin water, like rivers and shores, wins a tile once it covers half of it), the parent's
        streets and paths traced as connector routes through the tiles they cross (streets run on the
        world's street lattice, so each is a straight run; paths wind from tile to tile), and where the
        parent's landmarks stood. The region is then the tile up close, not a reinvention."""
        P = parent.style.tile_px if parent.style else 64
        labels: list = []
        edges = [{"terrain": e.terrain, "connectors": list(e.connectors)} for e in tile.edges or []]
        _, packed, _ = render_ground_full(
            tile_px=P,
            biome=tile.biome or "",
            edges=edges,
            coord=(tile.q, tile.r),
            materials=parent.materials,
            labels_out=labels,
        )
        names, mat = labels[0]
        conns = list(parent.spec.connector_vocabulary) if parent.spec else []
        street = next((c for c in conns if re.search(r"street|road|avenue|boulevard|lane", c)), "street")

        def straight(n: str) -> bool:  # streets: on the lattice, traced as routes rather than terrain
            spec = parent.materials.get(n)
            if n.startswith("__"):  # the engine's own asphalt (built districts' street grid)
                return True
            return n in conns and spec is not None and spec.edges == "straight" and not spec.liquid

        streets = {n: (street if n.startswith("__") else n) for n in names if straight(n)}
        paths = {  # winding connectors (trails, lanes, coastal roads): traced tile to tile
            n
            for n in names
            if n in conns and n not in streets and not getattr(parent.materials.get(n), "liquid", False)
        }
        thin = {n for n in names if n in conns or getattr(parent.materials.get(n), "liquid", False)}
        canvas = TileCanvas(tile.hex, P)
        (cx, cy), (ox, oy) = canvas.center, canvas.origin
        C = mat.shape[0]
        k = (P / 2) * SQRT3 / 2 / (SQRT3 * (radius + 0.5))  # parent pixels per region tile unit
        offs = [(dx * 0.3, dy * 0.3) for dx in range(-2, 3) for dy in range(-2, 3) if dx * dx + dy * dy <= 5]
        guide: dict[str, str] = {}
        for h in within(ORIGIN, radius):
            x, y = h.to_pixel(1.0)
            counts: dict[str, int] = {}
            for dx, dy in offs:
                px = min(C - 1, max(0, int(cx + (x + dx) * k - ox)))
                py = min(C - 1, max(0, int(cy + (y + dy) * k - oy)))
                n = names[int(mat[py, px])]
                if n not in streets and n not in paths:  # a street tile is the land it runs through
                    counts[n] = counts.get(n, 0) + 1
            total = sum(counts.values())
            strong = [(c, n) for n, c in counts.items() if n in thin and c / total >= 0.5]
            if strong:
                guide[f"{h.q},{h.r}"] = max(strong)[1]
            elif counts:
                guide[f"{h.q},{h.r}"] = max(counts.items(), key=lambda kv: kv[1])[0]
        fill = max(set(guide.values()), key=list(guide.values()).count) if guide else tile.biome or ""
        for h in within(ORIGIN, radius):  # all street (a crossing): the neighbours' block
            key = f"{h.q},{h.r}"
            if key not in guide:
                around = [guide[f"{n.q},{n.r}"] for n in h.neighbors() if f"{n.q},{n.r}" in guide]
                guide[key] = max(set(around), key=around.count) if around else fill
        routes: list[Route] = []
        idx = np.array([n in streets for n in names])
        by_name: dict[str, np.ndarray] = {}
        for i, n in enumerate(names):
            if idx[i]:
                by_name[streets[n]] = by_name.get(streets[n], np.zeros(mat.shape, bool)) | (mat == i)
        for cname, mask in by_name.items():
            for chain in street_chains(mask, (ox, oy), (cx, cy), k, radius, P):
                routes.append(Route(connector=cname, points=[Coord(q=h.q, r=h.r) for h in chain]))
        for cname in sorted(paths):
            mask = mat == names.index(cname)
            exits = [i for i, e in enumerate(tile.edges or []) if cname in e.connectors]
            for a, b in path_links(mask, (ox, oy), (cx, cy), k, radius, exits):
                routes.append(Route(connector=cname, points=[Coord(q=a.q, r=a.r), Coord(q=b.q, r=b.r)]))
        marks = []
        for la in tile.layers:
            if la.kind == "sprite" and la.label and la.role == "landmark":
                x, y = la.x * (P / 2) / k, la.y * (P / 2) / k  # parent tile units -> region units
                marks.append({"kind": la.label, **_nearest_hex(x, y, radius)})
        notes, scale = _tile_notes(packed, guide, routes, (ox, oy), (cx, cy), k, radius, offs)
        props: dict[str, list[str]] = {}
        for la in tile.layers:
            if la.kind == "sprite" and la.label and la.role != "landmark":
                h = _nearest_hex(la.x * (P / 2) / k, la.y * (P / 2) / k, radius)
                props.setdefault(f"{h['q']},{h['r']}", []).append(la.label)
        scale["parent_props"] = sum(len(v) for v in props.values())
        return Guide(terrain=guide, routes=routes, marks=marks, notes=notes, props=props, scale=scale)

    async def _build(self, child: World, tile: Tile) -> Run:
        prompt = (
            f"Up close: the inside of this place from the map above. {tile.summary or _pretty(tile.biome)}"
        )
        opts = RunOptions(
            max_tiles=hex_count(child.radius),
            fill_radius=True,
            tile_px=child.style.tile_px if child.style else None,
        )
        return await self.rt.start_run(child.id, 0, 0, prompt, opts)

    # ------------------------------------------------------------------ the skirt around a region

    SKIRT_RINGS = 2

    async def skirt(self, world_id: str) -> list[SkirtTile]:
        """Two rings of ground outside a region, continuing its rim terrain (and roads, rivers) so the
        region blends into the surroundings the viewer draws around it. Cached per built state."""
        world = self.store.get_world(world_id)
        if world is None:
            raise KeyError(world_id)
        if world.parent is None:
            return []
        tiles = {t.hex: t for t in self.store.list_tiles(world_id) if t.status == TileStatus.accepted}
        key = (world_id, len(tiles), len(world.materials))
        if key not in self._skirts:
            self._skirts[key] = await asyncio.to_thread(self._render_skirt, world, tiles)
        return self._skirts[key]

    def _render_skirt(self, world: World, tiles: dict[Hex, Tile]) -> list[SkirtTile]:
        import io

        from PIL import Image

        R = world.radius
        P = world.style.tile_px if world.style else 64
        mats = world.materials
        out: list[SkirtTile] = []
        for k in range(1, self.SKIRT_RINGS + 1):
            for h in ring(ORIGIN, R + k):
                src = tiles.get(_toward_centre(h, R))
                if src is None or not src.biome:
                    continue
                edges = []
                for i in range(6):
                    n = tiles.get(h.neighbor(i))
                    if n is not None and n.edges:  # facing the region: match its rim exactly
                        e = n.edges[(i + 3) % 6]
                        edges.append({"terrain": e.terrain, "connectors": list(e.connectors)})
                    else:
                        edges.append({"terrain": src.biome, "connectors": []})
                rgb, _, _ = render_ground_full(
                    tile_px=P, biome=src.biome, edges=edges, coord=(h.q, h.r), materials=mats
                )
                buf = io.BytesIO()
                Image.fromarray(rgb, "RGB").save(buf, format="PNG")
                pix = crisp_tile(buf.getvalue(), TileCanvas(h, P))
                asset = self.store.put_asset(
                    pix.png, {"kind": "skirt", "world": world.id, "q": h.q, "r": h.r}
                )
                out.append(SkirtTile(q=h.q, r=h.r, ring=k, biome=src.biome, asset_id=asset))
        return out

    # ------------------------------------------------------------------ looking at a tile

    def _describe(self, world: World, t: Tile, own_elev: float) -> str:
        """One neighbour as the viewer sees it: what it is, its landmarks, and whether it rises."""
        text = _pretty(t.biome) + (f" ({t.summary.rstrip('.')})" if t.summary else "")
        marks = [la.label for la in t.layers if la.kind == "sprite" and la.role == "landmark" and la.label]
        if marks:
            text += f", with {', '.join(marks[:2])}"
        m = world.materials.get(t.biome or "")
        if m is not None:
            d = (m.elevation + m.height) - own_elev
            if m.liquid:
                text += ", open water"
            elif d >= 8:
                text += ", rising high above you"
            elif d >= 3:
                text += ", on higher ground"
            elif d <= -3:
                text += ", lower down"
            if m.buildings is not None:
                text += f", buildings of {m.buildings.floors_min}-{m.buildings.floors_max} floors"
        return text

    def _place(self, world: World, tile: Tile) -> dict[str, Any]:
        """What the painter needs to know: the spot itself and what the viewer sees from it looking
        north (the map's up): ahead, left and right, further ahead, and the far horizon (for a region,
        the overworld beyond it)."""
        tiles = {t.hex: t for t in self.store.list_tiles(world.id) if t.status == TileStatus.accepted}
        own = world.materials.get(tile.biome or "")
        own_elev = (own.elevation + own.height) if own else 1
        h = tile.hex
        # hex directions: E=0, NE=1, NW=2, W=3, SW=4, SE=5; north is up, between NW and NE
        view: dict[str, list[str]] = {"ahead": [], "left": [], "right": [], "beyond": [], "horizon": []}
        for key, dirs in (("ahead", (2, 1)), ("left", (3,)), ("right", (0,))):
            for i in dirs:
                n = tiles.get(h.neighbor(i))
                if n is not None and n.biome:
                    view[key].append(self._describe(world, n, own_elev))
        for dq, dr in ((0, -2), (1, -2), (2, -2)):
            n = tiles.get(Hex(h.q + dq, h.r + dr))
            if n is not None and n.biome:
                view["beyond"].append(self._describe(world, n, own_elev))
        if world.parent is not None:  # the overworld around the region, toward the north
            ctx = world.parent.context
            ptiles = {t.hex: t for t in self.store.list_tiles(world.parent.world_id)}
            ph = Hex(world.parent.q, world.parent.r)
            for i in (2, 1, 3, 0):
                n = ptiles.get(ph.neighbor(i))
                if n is not None and n.biome:
                    view["horizon"].append(f"{self._describe(world, n, own_elev)} ({DIRECTION_NAMES[i]})")
            region = f"{_pretty(ctx.get('biome'))} ({ctx.get('summary', '')})".strip()
        else:
            for dq, dr in ((0, -3), (1, -3), (2, -3), (-1, -2)):
                n = tiles.get(Hex(h.q + dq, h.r + dr))
                if n is not None and n.biome:
                    view["horizon"].append(self._describe(world, n, own_elev))
            region = world.spec.title if world.spec else ""
        sprites = [la.label for la in tile.layers if la.kind == "sprite" and la.label]
        here = _pretty(tile.biome) + (f": {tile.summary.rstrip('.')}" if tile.summary else "")
        if sprites:
            here += f" (with {', '.join(sprites[:4])})"
        buildings = ""
        if own is not None and own.buildings is not None:
            bb = own.buildings
            buildings = (
                f"Around you: {bb.layout} of {bb.floors_min}-{bb.floors_max} floors, {bb.facade} facades, "
                f"{bb.roof} roofs."
            )
        return {
            "biome": tile.biome or "",
            "here": here,
            "buildings": buildings,
            "view": view,
            "region": region,
            "near": [x for x in sprites if x][-3:],
            "landmarks": sprites,
            "sky": "a clear day",
        }

    def _map_png(self, world: World, tile: Tile) -> bytes | None:
        """A top-down map of the spot and two rings around it, the viewer's hex marked YOU."""
        import io

        from hexworld.art.composite import render_region
        from hexworld.art.pixelize import load_tile

        P = world.style.tile_px if world.style else 64
        arrays = {}
        for t in self.store.list_tiles(world.id):
            if t.status == TileStatus.accepted and t.asset_id and t.hex.distance(tile.hex) <= 2:
                png = self.store.get_asset(t.asset_id)
                if png:
                    arrays[t.hex] = load_tile(png)
        if not arrays:
            return None
        img = render_region(
            arrays,
            tile_px=P,
            scale=3,
            labels={tile.hex: "YOU"},  # type: ignore[dict-item]
            center=tile.hex,
            extent_px=int(P * 4.6),
        )
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    async def scene(self, world_id: str, q: int, r: int) -> Scene:
        existing = self.store.get_scene(world_id, q, r)
        if existing is not None and existing.version >= SCENE_VERSION:
            return existing
        return await self._single_flight(
            f"scene:{world_id}:{q},{r}", lambda: self._paint_scene(world_id, q, r)
        )

    async def _paint_scene(self, world_id: str, q: int, r: int) -> Scene:
        world = self.store.get_world(world_id)
        if world is None:
            raise KeyError(world_id)
        tile = self.store.get_tile(world_id, q, r)
        if tile.status != TileStatus.accepted:
            raise ValueError(f"tile ({q},{r}) isn't built yet")
        place = self._place(world, tile)
        painter = self._painter()
        layers: list[SceneLayer] = []
        if painter is not None:
            ref = await asyncio.to_thread(self._map_png, world, tile)
            if ref is not None and hasattr(painter, "paint_ref"):
                back = painter.paint_ref(
                    backdrop_prompt(world.style, place, with_map=True),
                    [ref],
                    size=PAINT_SIZE,
                    background="opaque",
                )
            else:
                back = painter.paint(
                    backdrop_prompt(world.style, place), size=PAINT_SIZE, background="opaque"
                )
            (bg, _), (fg, _) = await asyncio.gather(
                back,
                painter.paint(
                    foreground_prompt(world.style, place), size=PAINT_SIZE, background="transparent"
                ),
            )
            bg_png = await asyncio.to_thread(pixelize_scene, bg, transparent=False)
            fg_png = await asyncio.to_thread(pixelize_scene, fg, transparent=True)
            layers.append(self._layer("backdrop", bg_png, world_id, q, r))
            layers.append(self._layer("foreground", fg_png, world_id, q, r))
        else:
            mat = world.materials.get(tile.biome or "")
            ground = mat.base_color if mat else "#4a6a3a"
            pal = world.style.palette if world.style else ["#7fb2e5"]
            layers.append(
                self._layer("backdrop", fallback_backdrop("#7fb2e5", ground, pal[0]), world_id, q, r)
            )
        words = [tile.biome or "", *[e.terrain for e in tile.edges or []], *place["landmarks"]]
        scene = Scene(
            world_id=world_id,
            q=q,
            r=r,
            title=_pretty(tile.biome).title() or "Somewhere",
            caption=tile.summary or "",
            layers=layers,
            fx=scene_fx(words),
            created_at=time.time(),
            version=SCENE_VERSION,
        )
        self.store.put_scene(scene)
        return scene

    def _layer(self, role: str, png: bytes, world_id: str, q: int, r: int) -> SceneLayer:
        asset = self.store.put_asset(png, {"kind": "scene", "role": role, "world": world_id, "q": q, "r": r})
        return SceneLayer(role=role, asset_id=asset, px_w=SCENE_W, px_h=SCENE_H)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ the player's avatar

    async def avatar(self, world_id: str) -> SpriteEntry | None:
        """The traveller the player walks around as, painted once per overworld in its style."""
        world = self.store.get_world(world_id)
        if world is None:
            raise KeyError(world_id)
        world = self._root(world)  # layers share the overworld's traveller
        if AVATAR in world.sprites:
            return world.sprites[AVATAR]
        painter = self._painter()
        if painter is None:
            return None
        return await self._single_flight(f"avatar:{world.id}", lambda: self._paint_avatar(world.id))

    async def _paint_avatar(self, world_id: str) -> SpriteEntry:
        world = self.store.get_world(world_id)
        assert world is not None
        spec = world.spec
        theme = f"{spec.title}: {spec.theme}" if spec else world.name
        subject = (
            f"the player character: a young traveller exploring {theme}. Practical travel clothes in "
            "colours from the world palette, a satchel, boots, full body, side view facing right, "
            "standing, a clear readable silhouette"
        )
        png, _ = await self._painter().paint(style_frame(world.style, subject))
        art = await asyncio.to_thread(pixelize_sprite, png, "small")
        art.motion = "sway"
        asset = self.store.put_asset(art.strip_png(), {"kind": "sprite", "sprite": AVATAR, "world": world_id})
        entry = SpriteEntry(
            kind=AVATAR,
            prompt=subject,
            asset_id=asset,
            px_w=art.w,
            px_h=art.h,
            frames=len(art.frames),
            fps=art.fps,
            motion=art.motion,
        )
        fresh = self.store.get_world(world_id)  # re-read: a run may have saved the world meanwhile
        assert fresh is not None
        fresh.sprites[AVATAR] = entry
        self.store.put_world(fresh)
        return entry


def _toward_centre(h: Hex, radius: int) -> Hex:
    """The region tile nearest to a hex outside it, along the line to the centre (cube rounding)."""
    d = h.distance(ORIGIN)
    if d <= radius:
        return h
    t = radius / d
    x, z = h.q * t, h.r * t
    y = -x - z
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy <= dz:
        rz = -rx - ry
    return Hex(rx, rz)


def _nearest_hex(x: float, y: float, radius: int) -> dict[str, int]:
    """The hex (pointy-top, circumradius 1) containing a point, clamped inside the region."""
    fq, fr = (SQRT3 / 3 * x - y / 3), (2 / 3 * y)
    h = _round_hex(fq, fr)
    while h.distance(ORIGIN) > radius:
        h = _toward_centre(h, radius)
    return {"q": h.q, "r": h.r}


def _round_hex(fq: float, fr: float) -> Hex:
    fs = -fq - fr
    q, r, s_ = round(fq), round(fr), round(fs)
    dq, dr, ds = abs(q - fq), abs(r - fr), abs(s_ - fs)
    if dq > dr and dq > ds:
        q = -r - s_
    elif dr > ds:
        r = -q - s_
    return Hex(q, r)


@dataclass
class Guide:
    """A region's parent tile, zoomed up (see Layers._guide)."""

    terrain: dict[str, str]  # "q,r" -> terrain
    routes: list[Route]  # traced streets and paths
    marks: list[dict[str, Any]]  # the parent's landmarks, placed
    notes: dict[str, str]  # "q,r" -> what this tile is within the parent (agents read it)
    props: dict[str, list[str]]  # "q,r" -> the parent's props that stood there
    scale: dict[str, Any]  # the zoom in numbers (agents read it)


def _tile_notes(
    packed: np.ndarray,
    guide: dict[str, str],
    routes: list[Route],
    origin: tuple[float, float],
    centre: tuple[float, float],
    k: float,
    radius: int,
    offs: list[tuple[float, float]],
) -> tuple[dict[str, str], dict[str, Any]]:
    """What each region tile is within the parent tile, in words for the agents: part of which of
    the parent's buildings (they keep their size, so one spans several tiles here), a street or
    path, or the open ground between; plus the zoom in numbers."""
    (ox, oy), (cx, cy) = origin, centre
    C = packed.shape[0]
    levels, _ = split_levels(packed)
    built = facade_codes(packed) > 0
    comp = _components(built)
    ground = float(np.median(levels[~built])) if (~built).any() else 0.0
    under: dict[str, int] = {}
    for key in guide:
        q, r = map(int, key.split(","))
        x, y = Hex(q, r).to_pixel(1.0)
        ids: dict[int, int] = {}
        for dx, dy in offs:
            px = min(C - 1, max(0, int(cx + (x + dx) * k - ox)))
            py = min(C - 1, max(0, int(cy + (y + dy) * k - oy)))
            ids[int(comp[py, px])] = ids.get(int(comp[py, px]), 0) + 1
        best, n = max(ids.items(), key=lambda kv: kv[1])
        if best >= 0 and n >= 0.4 * len(offs):
            under[key] = best
    span: dict[int, int] = {}
    for b in under.values():
        span[b] = span.get(b, 0) + 1
    order = {b: i + 1 for i, b in enumerate(sorted(span, key=lambda b: (-span[b], b)))}
    floors = {b: max(1, round(float(levels[comp == b].max()) - ground)) for b in span}
    on_route: dict[str, set[str]] = {}
    for rt in routes:
        for p in rt.points:
            on_route.setdefault(f"{p.q},{p.r}", set()).add(rt.connector)
    notes = {}
    for key, terrain in guide.items():
        if key in under:
            b = under[key]
            notes[key] = (
                f"inside the footprint of the parent's building #{order[b]} (about {floors[b]} floors, "
                f"it covers {span[b]} tiles here): its roof and walls fill this tile"
            )
        elif key in on_route:
            notes[key] = (
                f"the parent's {' and '.join(sorted(_pretty(c) for c in on_route[key]))} runs through"
            )
        else:
            notes[key] = f"open {_pretty(terrain)} (a yard, pavement or gap around the parent's buildings)"
    scale = {
        "tiles_across_parent": 2 * radius + 1,
        "one_tile": f"about 1/{2 * radius + 1} of the parent tile across",
        "parent_buildings": len(span),
        "tiles_per_parent_building": round(sum(span.values()) / len(span), 1) if span else 0,
        "note": "the parent's buildings keep their true size: each spans several tiles here, and the "
        "engine raises them from the parent's own map (never add buildings, blocks or streets)",
    }
    return notes, scale


def _components(mask: np.ndarray) -> np.ndarray:
    """4-connected component ids of a boolean mask (-1 outside it)."""
    comp = np.full(mask.shape, -1, np.int32)
    H, W = mask.shape
    n = 0
    for y0, x0 in zip(*np.nonzero(mask), strict=False):
        if comp[y0, x0] >= 0:
            continue
        stack = [(y0, x0)]
        comp[y0, x0] = n
        while stack:
            y, x = stack.pop()
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < H and 0 <= xx < W and mask[yy, xx] and comp[yy, xx] < 0:
                    comp[yy, xx] = n
                    stack.append((yy, xx))
        n += 1
    return comp


def street_chains(
    mask: np.ndarray,
    origin: tuple[float, float],
    centre: tuple[float, float],
    k: float,
    radius: int,
    tile_px: int,
) -> list[list[Hex]]:
    """The streets of a parent tile (`mask`: its street pixels on the tile canvas at `origin`), as
    chains of region tiles (`k` parent pixels per region unit, region centred on `centre`). Every
    street runs on the world lattice (art.procedural.lattice), so walking each lattice line across the
    tile finds the centre lines: long runs of street pixels (short ones are a perpendicular street's
    crossing). Horizontal runs follow a row of region tiles; vertical ones zig-zag up a column (the
    engine's straight connectors draw those legs as right angles). A street reaching the region's rim
    keeps one tile beyond it, so the rim tile's connector leads out of the region."""
    (ox, oy), (cx, cy) = origin, centre
    C = mask.shape[0]
    lx, ly = lattice(tile_px)
    step = 0.5
    min_run = 2 * street_half(tile_px) + 2

    def runs(xs: np.ndarray, ys: np.ndarray) -> list[tuple[int, int]]:
        px, py = np.floor(xs - ox).astype(int), np.floor(ys - oy).astype(int)
        ok = (px >= 0) & (px < C) & (py >= 0) & (py < C)
        on = np.zeros(len(xs), bool)
        on[ok] = mask[py[ok], px[ok]]
        out, start = [], None
        for i, v in enumerate([*on, False]):
            if v and start is None:
                start = i
            elif not v and start is not None:
                if (i - 1 - start) * step >= min_run:
                    out.append((start, i - 1))
                start = None
        return out

    chains = []
    ts_y, ts_x = np.arange(oy, oy + C, step), np.arange(ox, ox + C, step)
    for i in range(math.ceil(ox / lx), math.floor((ox + C) / lx) + 1):
        for a, b in runs(np.full_like(ts_y, i * lx), ts_y):
            chains.append(_walk((i * lx - cx) / k, (ts_y[a] - cy) / k, (ts_y[b] - cy) / k, radius, True))
    for j in range(math.ceil(oy / ly), math.floor((oy + C) / ly) + 1):
        for a, b in runs(ts_x, np.full_like(ts_x, j * ly)):
            chains.append(_walk((j * ly - cy) / k, (ts_x[a] - cx) / k, (ts_x[b] - cx) / k, radius, False))
    # streets along the parent's own rim are shared with its neighbours: they stay outside
    return [c for c in chains if sum(h.distance(ORIGIN) <= radius for h in c) >= 2]


def _walk(fixed: float, t0: float, t1: float, radius: int, vertical: bool) -> list[Hex]:
    """Region tiles along one straight street (region units), snapped to a tile row or column."""
    if vertical:  # a column of half-tiles; nudged off the vertical edges between tiles
        fixed = round(fixed / (SQRT3 / 2)) * (SQRT3 / 2) + 0.01
    else:
        fixed = round(fixed / 1.5) * 1.5

    def at(t: float) -> Hex:
        x, y = (fixed, t) if vertical else (t, fixed)
        return _round_hex(SQRT3 / 3 * x - y / 3, 2 / 3 * y)

    lo, hi = min(t0, t1), max(t0, t1)
    if at(lo).distance(ORIGIN) >= radius:  # leaving the region: on to the tile beyond the rim
        lo -= 1.0
    if at(hi).distance(ORIGIN) >= radius:
        hi += 1.0
    cells: list[Hex] = []
    for t in np.arange(lo, hi + 1e-9, 0.1):
        h = at(float(t))
        if h.distance(ORIGIN) <= radius + 1 and (not cells or cells[-1] != h):
            cells.append(h)
    return cells


def path_links(
    mask: np.ndarray,
    origin: tuple[float, float],
    centre: tuple[float, float],
    k: float,
    radius: int,
    exits: list[int],
) -> list[tuple[Hex, Hex]]:
    """A winding path of a parent tile (`mask`: its pixels on the tile canvas at `origin`) as links
    between region tiles: tiles the path mostly covers, joined where it runs from one centre to the
    next, kept as a tree (a band two tiles wide must not become a ladder). Where the parent's path
    leaves through its edge i (`exits`), the region's path leaves through the corner tile that way
    (the parent's edge midpoint lands there), so it reaches the neighbouring region."""
    (ox, oy), (cx, cy) = origin, centre
    C = mask.shape[0]

    def frac(pts: list[tuple[float, float]]) -> float:
        on = 0
        for x, y in pts:
            px = min(C - 1, max(0, int(cx + x * k - ox)))
            py = min(C - 1, max(0, int(cy + y * k - oy)))
            on += bool(mask[py, px])
        return on / len(pts)

    def along(a: Hex, b: Hex) -> float:
        (ax, ay), (bx, by) = a.to_pixel(1.0), b.to_pixel(1.0)
        return frac([(ax + (bx - ax) * t, ay + (by - ay) * t) for t in np.linspace(0, 1, 9)])

    offs = [(dx * 0.3, dy * 0.3) for dx in range(-2, 3) for dy in range(-2, 3) if dx * dx + dy * dy <= 5]
    cells = set()
    for h in within(ORIGIN, radius):
        x, y = h.to_pixel(1.0)
        if frac([(x + dx, y + dy) for dx, dy in offs]) >= 0.35:
            cells.add(h)
    corners = []
    for i in exits:
        c = ORIGIN
        for _ in range(radius):
            c = c.neighbor(i)
        corners.append((c, c.neighbor(i)))
        cells.add(c)
    cand = sorted(
        ((along(a, b), a, b) for a in cells for b in a.neighbors() if b in cells and (a.q, a.r) < (b.q, b.r)),
        key=lambda x: -x[0],
    )
    root = {h: h for h in cells}

    def find(h: Hex) -> Hex:
        while root[h] != h:
            root[h] = root[root[h]]
            h = root[h]
        return h

    out: list[tuple[Hex, Hex]] = []
    for f, a, b in cand:  # the strongest links first, never closing a loop
        if f >= 0.6 and find(a) != find(b):
            root[find(a)] = find(b)
            out.append((a, b))
    linked = {h for pair in out for h in pair}
    for c, beyond in corners:
        if c not in linked and linked:  # join the exit to the path by the shortest way
            near = min(linked, key=lambda h: (h.distance(c), h.q, h.r))
            line = hex_line(c, near)
            out += [(p, q) for p, q in zip(line, line[1:], strict=False) if find(p) != find(q)]
            for p, q in zip(line, line[1:], strict=False):
                root[find(p)] = find(q)
            linked |= set(line)
        out.append((c, beyond))
    return out
