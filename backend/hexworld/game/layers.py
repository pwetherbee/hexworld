"""Navigation across layers: enter a tile (its region grid is built on first entry), look at a tile
up close (a painted scene, made once), and the player's avatar.

The overworld is a world at depth 0. Entering one of its tiles opens a child world: a full hexagon
of finer tiles planned as the inside of that tile (same style and lore, its own finer terrains). A
tile of any layer can be looked at: a layered pixel-art scene painted from the tile's own data.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from hexworld.art.grid import TileCanvas
from hexworld.art.paint import pixelize_sprite, style_frame
from hexworld.art.pixelize import crisp_tile
from hexworld.art.procedural import render_ground_full
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
    ParentLink,
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
from hexworld.hex import DIRECTION_NAMES, ORIGIN, Hex, ring
from hexworld.telemetry import Tracer, new_id

if TYPE_CHECKING:
    from hexworld.orchestrator.runtime import Runtime

DEFAULT_RADIUS = 3
SCENE_VERSION = 2  # 2: painted from a map of the surroundings and a described view
AVATAR = "traveller"
SCALE_NOTES = {
    1: "one tile is about a tenth of the overworld tile it lies in: a street corner, a clearing, a "
    "stretch of shore, a single building's lot or courtyard",
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
        vocab = [t for t in dict.fromkeys([tile.biome or "", *[e.terrain for e in tile.edges or []]]) if t]
        conns = sorted({c for e in tile.edges or [] for c in e.connectors})
        name = f"{parent.name} › {_pretty(tile.biome).title()}"
        child = World(
            id=new_id("w"),
            name=name,
            radius=radius,
            created_at=time.time(),
            parent=ParentLink(world_id=world_id, q=q, r=r, context=self._parent_context(parent, tile)),
            depth=depth,
            scale_note=SCALE_NOTES.get(depth, SCALE_NOTES[2]),
            spec=parent.spec.model_copy(
                update={
                    "title": name,
                    "terrain_vocabulary": vocab,
                    "connector_vocabulary": conns or list(parent.spec.connector_vocabulary[:2]),
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
