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

from hexworld.art.paint import pixelize_sprite, style_frame
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
    Tile,
    TileStatus,
    World,
)
from hexworld.domain.art import SpriteEntry
from hexworld.hex import DIRECTION_NAMES
from hexworld.telemetry import Tracer, new_id

if TYPE_CHECKING:
    from hexworld.orchestrator.runtime import Runtime

DEFAULT_RADIUS = 5
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

    async def enter(
        self, world_id: str, q: int, r: int, radius: int = DEFAULT_RADIUS
    ) -> tuple[World, Run | None]:
        """The world inside tile (q, r) of `world_id`; created and built on the first entry."""
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

    # ------------------------------------------------------------------ looking at a tile

    def _place(self, world: World, tile: Tile) -> dict[str, Any]:
        tiles = {t.hex: t for t in self.store.list_tiles(world.id)}
        around = []
        for i in range(6):
            n = tiles.get(tile.hex.neighbor(i))
            if n and n.biome and n.biome != tile.biome:
                around.append(f"{_pretty(n.biome)} to the {DIRECTION_NAMES[i]}")
        sprites = [la.label for la in tile.layers if la.kind == "sprite" and la.label]
        mats = world.materials
        b = mats.get(tile.biome or "")
        buildings = ""
        if b is not None and b.buildings is not None:
            bb = b.buildings
            buildings = (
                f"Buildings: {bb.layout} of {bb.floors_min}-{bb.floors_max} floors, {bb.facade} facades, "
                f"{bb.roof} roofs."
            )
        high = max((getattr(mats.get(e.terrain), "elevation", 0) for e in tile.edges or []), default=0)
        own = getattr(b, "elevation", 0) if b else 0
        relief = (
            "The land rises steeply here (mountains or cliffs)."
            if max(high, own) >= 15
            else "Hilly ground."
            if max(high, own) >= 5
            else ""
        )
        region = ""
        if world.parent is not None:
            ctx = world.parent.context
            region = f"{_pretty(ctx.get('biome'))} ({ctx.get('summary', '')})".strip()
        return {
            "biome": tile.biome or "",
            "summary": tile.summary or "",
            "landmarks": sprites,
            "buildings": buildings,
            "relief": relief,
            "around": around,
            "region": region or (world.spec.title if world.spec else ""),
            "near": [s for s in sprites if s][-3:],
            "sky": "a clear day",
        }

    async def scene(self, world_id: str, q: int, r: int) -> Scene:
        existing = self.store.get_scene(world_id, q, r)
        if existing is not None:
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
            (bg, _), (fg, _) = await asyncio.gather(
                painter.paint(backdrop_prompt(world.style, place), size=PAINT_SIZE, background="opaque"),
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
        while world.parent is not None:  # layers share the overworld's traveller
            up = self.store.get_world(world.parent.world_id)
            if up is None:
                break
            world = up
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
