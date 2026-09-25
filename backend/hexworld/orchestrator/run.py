"""Run executor: one user prompt -> plan -> streaming growth with continuous review.

State machine per tile:
    planned -> generating -> reviewing -> accepted
                  ^              |
                  +--- retry ----+ (feedback to the same agent)  -> failed after max attempts (+1 simplified)

Growth (no rings, no wave barriers): a planned tile starts as soon as it touches an accepted tile
(the origin starts first and becomes the world's style anchor) and none of its neighbours is in
flight. Ready tiles are started in priority order: most accepted neighbours first, then the
super's priority, then closeness to the origin. So the world grows organically along the plan, and
every tile only ever sees settled neighbours. Candidates are reviewed in small batches while other
tiles keep generating, and each acceptance immediately unlocks its neighbours. The director checks
in every N accepted tiles.

Agents (Google ADK, see agents/kit.py) collaborate through this executor: tile agents keep a
session across attempts and receive the reviewer's feedback directly; artists revise their own
materials/sprites on the super's feedback; the director can re-plan pending tiles, commission
sprites or order redos. The executor exposes the facade those agents' tools call.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from hexworld.agents import artist, director
from hexworld.agents import super as super_agent
from hexworld.agents import tile as tile_agent
from hexworld.agents.kit import AgentKit
from hexworld.agents.llm import BudgetExceeded, RunBudget
from hexworld.agents.tile import TileAgent
from hexworld.art.backend import ImageRequest
from hexworld.art.composite import context_canvas, crop_target, neighborhood_png, render_region, to_png
from hexworld.art.grid import TileCanvas
from hexworld.art.layout import PropRequest, layout_props
from hexworld.art.pixelize import PixelTile, crisp_tile, load_tile, pixelize_to_canvas
from hexworld.art.procedural import fallback_material, ramp_hexes, render_ground
from hexworld.art.sprites import Placed, SpriteArt, flatten, preview_png, scatter_positions
from hexworld.domain import (
    NO_COPY,
    Attempt,
    Coord,
    CopySpec,
    Directive,
    EdgeSpec,
    PlannedTile,
    Run,
    RunStatus,
    Tile,
    TileDesign,
    TileLayer,
    TileStatus,
    Verdict,
    World,
    WorldPlan,
)
from hexworld.domain.art import MaterialSpec, SpriteEntry, kind_key
from hexworld.hex import DIRECTION_NAMES, ORIGIN, Hex, opposite, spiral
from hexworld.orchestrator.copies import apply_copy, copy_fits, resolve_root, sync_shallow_copies
from hexworld.orchestrator.validators import CheckResult, check_candidate
from hexworld.telemetry import Span, Tracer

if TYPE_CHECKING:
    from hexworld.orchestrator.runtime import Runtime

FREE_STATUSES = {TileStatus.empty, TileStatus.intentionally_empty, TileStatus.failed}
ACTIVE_STATUSES = {TileStatus.planned, TileStatus.generating, TileStatus.reviewing}


MAX_PROPS = 4  # agent-chosen props per tile (at most one of them a landmark)
MAX_SPRITES = 6  # props + ambient scatter


@dataclass
class Job:
    tile: Tile
    directive: Directive
    attempts_this_run: int = 0
    agent: TileAgent | None = None  # persistent tile-agent session across attempts
    feedback: str | None = None  # pending reviewer/validator feedback for the agent
    # edges neighbours were already built against while this tile was provisionally settled
    locked: dict[int, EdgeSpec] = field(default_factory=dict)


@dataclass
class Candidate:
    job: Job
    attempt: Attempt
    design: TileDesign
    pix: PixelTile  # ground layer
    asset_id: str  # flattened preview (ground + sprites)
    checks: CheckResult
    normalization: dict[str, Any] = field(default_factory=dict)
    ground_id: str = ""
    flat: np.ndarray | None = None
    flat_png: bytes = b""
    layers: list[TileLayer] = field(default_factory=list)
    material_versions: dict[str, int] = field(default_factory=dict)


class RunExecutor:
    def __init__(self, rt: Runtime, run: Run):
        self.rt = rt
        self.s = rt.settings
        self.store = rt.store
        self.run = run
        world = self.store.get_world(run.world_id)
        assert world is not None
        self.world: World = world
        self.tracer = Tracer(world.id, run.id, self.store.append_event)
        self.budget = RunBudget(
            run.stats,
            max_calls=run.options.max_llm_calls,
            max_cost_usd=run.options.max_cost_usd,
            max_seconds=run.options.max_seconds,
        )
        self.kit = AgentKit(
            tracer=self.tracer,
            budget=self.budget,
            model_factory=rt.model_factory,
            concurrency=self.s.llm_concurrency,
        )
        self.tiles: dict[Hex, Tile] = {t.hex: t for t in self.store.list_tiles(world.id)}
        self._arrays: dict[str, np.ndarray] = {}
        self._budget_error: BudgetExceeded | None = None
        self._plan_notes: list[str] = []
        self._inflight: dict[str, asyncio.Future] = {}  # single-flight library generation
        self._sprite_arts: dict[str, SpriteArt] = {}
        self._artists: dict[str, artist.SpriteArtist] = {}
        self._material_artists: dict[str, artist.MaterialArtist] = {}
        self._material_revisions: dict[str, int] = defaultdict(int)
        self._material_version: dict[str, int] = defaultdict(int)
        self._review_history: list[str] = []
        self._director_notes: list[str] = []
        self._redo: list[Tile] = []
        self._root: Span | None = None
        # Scheduling: a tile is BUSY while its design can still change (neighbours may not start
        # next to it). Once its candidate passes the deterministic checks it is PROVISIONALLY
        # settled: its edges are frozen, neighbours may build against it, and the (slower) review
        # runs off the critical path. A rejected tile keeps the edges neighbours used.
        self._busy: set[Hex] = set()
        self._provisional: dict[Hex, Candidate] = {}
        self._waiting: set[Hex] = set()  # rejected tiles waiting for busy neighbours before redesigning
        self._bg: set[asyncio.Task] = set()  # fire-and-forget library work (kept referenced)
        self.origin = run.origin.hex

    # ================================================================== lifecycle

    async def execute(self) -> None:
        run = self.run
        run.status = RunStatus.running
        self.store.put_run(run)
        try:
            async with self.tracer.span(
                "run",
                q=self.origin.q,
                r=self.origin.r,
                prompt=run.prompt,
                options=run.options.model_dump(),
                resumed=run.plan is not None,
                llm=self.rt.llm_name,
                image_backend=self.rt.image.name,
            ) as root:
                if run.plan is None:
                    await self._plan(root)
                else:
                    self._reset_inflight()
                self._root = root
                await self._grow(root)
            self._finish(RunStatus.completed)
        except BudgetExceeded as e:
            self._finish(RunStatus.completed, error=f"budget: {e}")
        except asyncio.CancelledError:
            if self.rt.shutting_down:
                # Leave it 'running' so it resumes on next start.
                self.tracer.emit("run.suspended")
                raise
            self._finish(RunStatus.cancelled)
            raise
        except Exception as e:  # noqa: BLE001 - a run must always reach a terminal state
            self._finish(RunStatus.failed, error=f"{type(e).__name__}: {e}")

    def _finish(self, status: RunStatus, error: str | None = None) -> None:
        released = 0
        for t in list(self.tiles.values()):
            if t.run_id == self.run.id and t.status in ACTIVE_STATUSES:
                t.status = TileStatus.empty
                t.preview_asset_id = None
                self._save_tile(t)
                released += 1
        self.run.status = status
        self.run.error = error
        self.run.finished_at = time.time()
        self.store.put_run(self.run)
        self._emit_stats()
        self.tracer.emit(
            f"run.{status.value}",
            data={"error": error, "released_tiles": released, "stats": self.run.stats.model_dump()},
        )

    def _reset_inflight(self) -> None:
        for t in self.tiles.values():
            if t.run_id == self.run.id and t.status in (TileStatus.generating, TileStatus.reviewing):
                t.status = TileStatus.planned
                t.preview_asset_id = None
                self._save_tile(t)

    # ================================================================== plan

    async def _plan(self, root: Span) -> None:
        w = self.world
        candidates = [
            h
            for h in spiral(self.origin, self.run.options.radius)
            if h.distance(ORIGIN) <= w.radius and self._tile(h).status in FREE_STATUSES
        ]
        cand_set = set(candidates)
        nearby = []
        for h, t in self.tiles.items():
            if t.status != TileStatus.accepted:
                continue
            touching = [i for i in range(6) if h.neighbor(i) in cand_set]
            if touching:
                nearby.append(
                    {
                        "q": h.q,
                        "r": h.r,
                        "biome": t.biome,
                        "summary": t.summary,
                        "edges_facing_new_area": {
                            DIRECTION_NAMES[i]: t.edges[i].model_dump() for i in touching
                        }
                        if t.edges
                        else {},
                    }
                )
        nearby_png = None
        if nearby:
            region = {
                Hex(n["q"], n["r"]): self._array(self.tiles[Hex(n["q"], n["r"])].asset_id) for n in nearby
            }
            nearby_png = to_png(render_region(region, tile_px=w.style.tile_px if w.style else 32, scale=3))
        async with self.tracer.span("super.plan", root, candidates=len(candidates)) as sp:
            plan = await super_agent.plan_world(
                self.kit,
                world=w,
                prompt=self.run.prompt,
                origin=self.origin,
                candidates=candidates,
                nearby=nearby,
                nearby_png=nearby_png,
                parent=sp,
            )
            plan = self._apply_plan(plan)
            sp.set(
                planned=sum(1 for t in plan.tiles if not t.leave_empty),
                left_empty=sum(1 for t in plan.tiles if t.leave_empty),
            )
        self.tracer.emit(
            "plan.created",
            data={
                "world": w.spec.model_dump() if w.spec else None,
                "style": w.style.model_dump() if w.style else None,
                "tile_attributes": [a.model_dump() for a in w.tile_attributes],
                "tiles": [t.model_dump() for t in plan.tiles],
                "duplicate_notes": self._plan_notes,
            },
        )
        self._emit_stats()

    def _apply_plan(self, plan: WorldPlan) -> WorldPlan:
        w = self.world
        if w.spec is None:
            w.spec, w.style, w.tile_attributes = plan.world, plan.style, plan.tile_attributes
            # engine resolution (64px tiles, 8px blocks), not an art-direction choice
            w.style = w.style.model_copy(update={"tile_px": 64})
            w.name = plan.world.title or w.name
        else:
            # Extension of an existing world: style + attributes are locked; vocabularies may grow.
            for t in plan.world.terrain_vocabulary:
                if t not in w.spec.terrain_vocabulary:
                    w.spec.terrain_vocabulary.append(t)
            for c in plan.world.connector_vocabulary:
                if c not in w.spec.connector_vocabulary:
                    w.spec.connector_vocabulary.append(c)
            # New terrains need new colours: the palette grows, the rest of the style stays locked.
            assert w.style is not None
            w.style.palette = _merge_palette(w.style.palette, plan.style.palette)
        self.store.put_world(w)
        vocab = w.spec.terrain_vocabulary
        conns = set(w.spec.connector_vocabulary)
        dups = self._sanitize_duplicates(plan)
        fixed: list[PlannedTile] = []
        for pt in plan.tiles:
            biome = pt.biome if pt.biome in vocab else vocab[len(vocab) // 2]
            hints = [
                h.model_copy(
                    update={
                        "terrain": h.terrain if h.terrain in vocab else biome,
                        "connectors": [c for c in h.connectors if c in conns],
                    }
                )
                for h in pt.edge_hints
                if 0 <= h.edge <= 5
            ]
            pt = pt.model_copy(update={"biome": biome, "edge_hints": hints, "duplicate": dups[pt.hex]})
            fixed.append(pt)
            tile = self._tile(pt.hex)
            tile.run_id = self.run.id
            tile.attempts = 0
            tile.preview_asset_id = None
            if pt.leave_empty:
                tile.status = TileStatus.intentionally_empty
                tile.directive = None
            else:
                tile.status = TileStatus.planned
                tile.biome = biome
                tile.directive = Directive(
                    coord=Coord(q=pt.q, r=pt.r),
                    biome=biome,
                    intent=pt.intent,
                    features=pt.features,
                    edge_hints=hints,
                    duplicate=pt.duplicate if pt.duplicate.mode != "none" else None,
                )
            self._save_tile(tile)
        plan = plan.model_copy(
            update={"tiles": fixed, "world": w.spec, "style": w.style, "tile_attributes": w.tile_attributes}
        )
        self.run.plan = plan
        self.run.stats.tiles_planned = sum(1 for t in fixed if not t.leave_empty)
        self.store.put_run(self.run)
        return plan

    def _sanitize_duplicates(self, plan: WorldPlan) -> dict[Hex, CopySpec]:
        """A duplicate's source must be a generated (non-copy) tile in this plan or an accepted tile
        in the world. Copies of copies collapse to their root prototype. The origin is always
        generated because it seeds the style anchor. Invalid specs fall back to generation and
        are reported."""
        planned = {pt.hex: pt for pt in plan.tiles if not pt.leave_empty}
        out: dict[Hex, CopySpec] = {}
        self._plan_notes = []
        for pt in plan.tiles:
            spec = pt.duplicate
            if spec.mode == "none" or pt.leave_empty:
                out[pt.hex] = NO_COPY
                continue
            src = spec.source
            note = None
            if pt.hex == self.origin:
                note = "origin is always generated"
            elif src == pt.hex:
                note = "tile cannot copy itself"
            elif src in planned:
                if planned[src].duplicate.mode != "none":
                    root = planned[src].duplicate.source
                    if root in planned and planned[root].duplicate.mode == "none" and root != pt.hex:
                        spec = spec.model_copy(update={"source_q": root.q, "source_r": root.r})
                    else:
                        note = f"source {src.key} is itself a copy"
            elif (t := self.tiles.get(src)) is not None and t.status == TileStatus.accepted:
                root = resolve_root(self.tiles, src)
                spec = spec.model_copy(update={"source_q": root.q, "source_r": root.r})
            else:
                note = f"source {src.key} is neither planned nor an accepted tile"
            if note:
                self._plan_notes.append(f"{pt.hex.key}: {note}; will generate instead")
                spec = NO_COPY
            out[pt.hex] = spec
        return out

    # ================================================================== session library

    async def _materials_for(self, biome: str, edges: list[EdgeSpec], parent: Span | None) -> dict[str, dict]:
        """On demand: make sure every material this tile paints exists in the library (the material
        artist designs any that don't yet, once per world), and return their specs."""
        names = {biome: False, **{e.terrain: False for e in edges}}
        for e in edges:
            for c in e.connectors:
                names[c] = True
        specs = await asyncio.gather(*[self._ensure_material(n, conn, parent) for n, conn in names.items()])
        return {n: spec.model_dump() for n, spec in zip(names, specs, strict=True)}

    async def _single_flight(self, key: str, make):
        """Concurrent requests for the same library item share one generation."""
        fut = self._inflight.get(key)
        if fut is not None:
            return await fut
        fut = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await make()
            fut.set_result(result)
            return result
        except BaseException as e:
            fut.set_exception(e)
            fut.exception()  # mark retrieved
            raise
        finally:
            self._inflight.pop(key, None)

    async def _ensure_material(self, name: str, is_connector: bool, parent: Span | None) -> MaterialSpec:
        w = self.world
        if name in w.materials:
            return w.materials[name]

        async def make() -> MaterialSpec:
            async with self.tracer.span("library.material", parent, material=name) as sp:
                try:
                    mat_artist = artist.MaterialArtist(
                        self.kit, world=w, name=name, is_connector=is_connector
                    )
                    self._material_artists[name] = mat_artist
                    spec = await mat_artist.design(parent=sp)
                except BudgetExceeded as e:
                    self._budget_error = e
                    return fallback_material(name)
                except Exception as e:  # noqa: BLE001 - render with a plain fallback, retry next run
                    sp.set(error=str(e)[:200], fallback=True)
                    return fallback_material(name)
                if spec is None:
                    sp.set(error="artist did not submit", fallback=True)
                    return fallback_material(name)
                w.materials[name] = spec
                assert w.style is not None
                w.style.palette = _merge_palette(
                    w.style.palette, [*ramp_hexes(spec.base_color), spec.accent_color]
                )
                self.store.put_world(w)
                sp.set(ops=len(spec.ops), scatter=[s.kind for s in spec.scatter])
                self.tracer.emit("library.material_added", data={"name": name, "spec": spec.model_dump()})
                return spec

        try:
            return await self._single_flight(f"m:{name}", make)
        except asyncio.CancelledError:
            raise
        except BudgetExceeded as e:
            self._budget_error = e
        except Exception as e:  # noqa: BLE001 - library failures never sink a run
            self.tracer.emit(
                "library.error", data={"material": name, "error": f"{type(e).__name__}: {e}"[:300]}
            )
        return fallback_material(name)

    async def _ensure_sprite(self, kind: str, context: str, parent: Span | None) -> SpriteEntry | None:
        w = self.world
        key = kind_key(kind)
        if key in w.sprites:
            return w.sprites[key]

        async def make() -> SpriteEntry | None:
            async with self.tracer.span("library.sprite", parent, kind=key) as sp:
                artist_agent = artist.SpriteArtist(self.kit, world=w, kind=key, painter=self.rt.painter)
                try:
                    result = await artist_agent.design(
                        context=context, anchor_png=self._anchor_png(), parent=sp
                    )
                except BudgetExceeded as e:
                    self._budget_error = e
                    return None
                except Exception as e:  # noqa: BLE001 - the tile simply goes without this prop
                    sp.set(error=str(e)[:200])
                    return None
                if result is None:
                    sp.set(error="artist did not submit")
                    return None
                self._artists[key] = artist_agent
                art = result["art"]
                asset_id = self.store.put_asset(
                    art.strip_png(), {"kind": "sprite", "sprite": key, "run_id": self.run.id}
                )
                entry = SpriteEntry(
                    kind=key,
                    program=result.get("program"),
                    prompt=result.get("prompt"),
                    asset_id=asset_id,
                    px_w=art.w,
                    px_h=art.h,
                    frames=len(art.frames),
                    fps=art.fps,
                    motion=art.motion,
                    run_id=self.run.id,
                )
                w.sprites[key] = entry
                self._sprite_arts[asset_id] = art
                self.store.put_world(w)
                sp.set(
                    asset_id=asset_id,
                    size=[art.w, art.h],
                    frames=len(art.frames),
                    painted=bool(result.get("prompt")),
                )
                self.tracer.emit(
                    "library.sprite_added",
                    data={
                        "kind": key,
                        "asset_id": asset_id,
                        "px_w": art.w,
                        "px_h": art.h,
                        "frames": len(art.frames),
                    },
                )
                return entry

        try:
            return await self._single_flight(f"s:{key}", make)
        except asyncio.CancelledError:
            raise
        except BudgetExceeded as e:
            self._budget_error = e
        except Exception as e:  # noqa: BLE001 - library failures never sink a run
            self.tracer.emit("library.error", data={"sprite": key, "error": f"{type(e).__name__}: {e}"[:300]})
        return None

    async def _render_copy_in_place(self, t: Tile, src: Tile) -> None:
        """Copy the design, not the pixels: re-render the ground at this tile's own world position
        (seamless with its neighbours) and keep the prototype's props. No LLM calls."""
        assert t.edges is not None
        # Copy the design, but honour the continuity contract of the neighbours that exist here.
        _, _, facing = self._neighbor_context(t.hex)
        t.edges = [facing.get(i, e) for i, e in enumerate(t.edges)]
        await self._repaint(t, src.biome or "", [layer for layer in src.layers if layer.kind == "sprite"])

    async def _repaint(self, t: Tile, biome: str, sprites: list[TileLayer]) -> None:
        """Re-render a tile's ground in place from the current library (deterministic, no LLM) and
        re-flatten its sprite layers on top."""
        style = self.world.style
        assert style is not None and t.edges is not None
        P = style.tile_px
        materials = await self._materials_for(biome, t.edges, self._root)
        req = ImageRequest(
            prompt="",
            negative="",
            seed=0,
            size=self.s.gen_px,
            hints={
                "tile_px": P,
                "palette": style.palette,
                "biome": biome,
                "edges": [e.model_dump() for e in t.edges],
                "coord": (t.q, t.r),
                "materials": materials,
            },
        )
        async with self.rt.gpu_sem:
            res = await self.rt.image.generate(req)
        canvas = TileCanvas(t.hex, P)
        pix = await asyncio.to_thread(crisp_tile, res.png, canvas)
        ground_id = self.store.put_asset(pix.png, {"kind": "ground", "run_id": self.run.id})
        self._arrays[ground_id] = pix.rgba
        height_id = self._height_asset(res.height_png, t, biome, t.edges, materials, P)
        placed = []
        for layer in sprites:
            art = self._sprite_arts.get(layer.asset_id) or SpriteArt.from_strip(
                self.store.get_asset(layer.asset_id), layer.frames, layer.motion, layer.fps
            )
            self._sprite_arts[layer.asset_id] = art
            placed.append(Placed(layer.label, art, layer.x, layer.y, layer.width / (art.w / (P / 2.0))))
        flat = flatten(pix.rgba, placed, canvas)
        flat[~canvas.mask()] = 0
        flat_id = self.store.put_asset(to_png(Image.fromarray(flat, "RGBA")), {"kind": "tile_preview"})
        self._arrays[flat_id] = flat
        t.ground_asset_id = ground_id
        t.asset_id = flat_id
        t.layers = [
            TileLayer(kind="ground", asset_id=ground_id, px_w=canvas.C, px_h=canvas.C),
            TileLayer(kind="height", asset_id=height_id, px_w=canvas.C, px_h=canvas.C),
            *[s.model_copy() for s in sprites],
        ]
        t.side_color = pix.side_color

    async def _refresh_if_stale(self, c: Candidate) -> None:
        """A material this tile painted with was revised while it was under review: repaint it now so
        it matches its (already repainted) neighbours."""
        stale = any(self._material_version[n] != v for n, v in c.material_versions.items())
        if stale and getattr(self.rt.image, "deterministic_ground", False):
            t = c.job.tile
            await self._repaint(t, t.biome or "", [layer for layer in t.layers if layer.kind == "sprite"])
            self._save_tile(t)

    async def _revise_material(self, name: str, feedback: str, parent: Span | None) -> None:
        """Agent-to-agent: the super's material_feedback goes to the artist who designed that terrain;
        the new version replaces the library entry and every procedurally painted tile using it is
        repainted in place (free, deterministic), so the fix spreads across the whole map."""
        spec = self.world.materials.get(name)
        if spec is None or self._material_revisions[name] >= 2:
            return
        self._material_revisions[name] += 1
        mat_artist = self._material_artists.get(name) or artist.MaterialArtist(
            self.kit,
            world=self.world,
            name=name,
            is_connector=name in (self.world.spec.connector_vocabulary if self.world.spec else []),
        )
        self._material_artists[name] = mat_artist
        async with self.tracer.span(
            "library.material_revise", parent, material=name, feedback=feedback[:300]
        ) as sp:
            try:
                new = await mat_artist.revise(feedback, parent=sp)
            except BudgetExceeded as e:
                self._budget_error = e
                return
            except Exception as e:  # noqa: BLE001
                sp.set(error=str(e)[:200])
                return
            if new is None:
                return
            self.world.materials[name] = new
            self._material_version[name] += 1
            assert self.world.style is not None
            self.world.style.palette = _merge_palette(
                self.world.style.palette, [*ramp_hexes(new.base_color), new.accent_color]
            )
            self.store.put_world(self.world)
            self.tracer.emit(
                "library.material_added", data={"name": name, "spec": new.model_dump(), "revised": True}
            )
            repainted = 0
            if getattr(self.rt.image, "deterministic_ground", False):
                for t in list(self.tiles.values()):
                    if t.status != TileStatus.accepted or not t.edges or not t.ground_asset_id:
                        continue
                    uses = {
                        t.biome,
                        *(e.terrain for e in t.edges),
                        *(c for e in t.edges for c in e.connectors),
                    }
                    if name in uses:
                        await self._repaint(
                            t, t.biome or "", [layer for layer in t.layers if layer.kind == "sprite"]
                        )
                        self._save_tile(t)
                        repainted += 1
            sp.set(tiles_repainted=repainted)

    async def _revise_sprite(self, kind: str, feedback: str, parent: Span | None) -> None:
        """Agent-to-agent: route the super's sprite feedback to the artist who drew it; swap the new
        version into the library and into every tile of this run that shows it."""
        key = kind_key(kind)
        old = self.world.sprites.get(key)
        if old is None:
            return
        artist_agent = self._artists.get(key) or artist.SpriteArtist(
            self.kit, world=self.world, kind=key, painter=self.rt.painter
        )
        self._artists[key] = artist_agent
        async with self.tracer.span("library.sprite_revise", parent, kind=key, feedback=feedback[:300]) as sp:
            try:
                result = await artist_agent.revise(feedback, parent=sp)
            except BudgetExceeded as e:
                self._budget_error = e
                return
            except Exception as e:  # noqa: BLE001
                sp.set(error=str(e)[:200])
                return
            if result is None:
                return
            art = result["art"]
            asset_id = self.store.put_asset(
                art.strip_png(), {"kind": "sprite", "sprite": key, "revision": True}
            )
            self._sprite_arts[asset_id] = art
            entry = old.model_copy(
                update={
                    "program": result.get("program"),
                    "prompt": result.get("prompt"),
                    "asset_id": asset_id,
                    "px_w": art.w,
                    "px_h": art.h,
                    "frames": len(art.frames),
                    "fps": art.fps,
                    "motion": art.motion,
                }
            )
            self.world.sprites[key] = entry
            self.store.put_world(self.world)
            self.tracer.emit(
                "library.sprite_added",
                data={
                    "kind": key,
                    "asset_id": asset_id,
                    "px_w": art.w,
                    "px_h": art.h,
                    "frames": len(art.frames),
                    "revised": True,
                },
            )
            swapped = 0
            for t in self.tiles.values():
                if t.status == TileStatus.accepted and any(
                    layer.kind == "sprite" and layer.asset_id == old.asset_id for layer in t.layers
                ):
                    self._swap_sprite(t, old.asset_id, entry, art)
                    swapped += 1
            sp.set(asset_id=asset_id, tiles_updated=swapped)

    def _swap_sprite(self, t: Tile, old_asset: str, entry: SpriteEntry, art: SpriteArt) -> None:
        style = self.world.style
        assert style is not None
        P = style.tile_px
        new_layers = []
        for layer in t.layers:
            if layer.kind == "sprite" and layer.asset_id == old_asset:
                scale = layer.width / max(1e-6, layer.px_w / (P / 2.0))
                layer = layer.model_copy(
                    update={
                        "asset_id": entry.asset_id,
                        "px_w": entry.px_w,
                        "px_h": entry.px_h,
                        "frames": entry.frames,
                        "fps": entry.fps,
                        "motion": entry.motion,
                        "width": art.w / (P / 2.0) * scale,
                    }
                )
            new_layers.append(layer)
        t.layers = new_layers
        if t.ground_asset_id:
            placed = [
                Placed(
                    layer.label,
                    self._layer_art(layer),
                    layer.x,
                    layer.y,
                    layer.width / (layer.px_w / (P / 2.0)),
                )
                for layer in t.layers
                if layer.kind == "sprite"
            ]
            canvas = TileCanvas(t.hex, P)
            flat = flatten(self._array(t.ground_asset_id), placed, canvas)
            flat[~canvas.mask()] = 0
            t.asset_id = self.store.put_asset(to_png(Image.fromarray(flat, "RGBA")), {"kind": "tile_preview"})
            self._arrays[t.asset_id] = flat
        self._save_tile(t)

    def _layer_art(self, layer: TileLayer) -> SpriteArt:
        art = self._sprite_arts.get(layer.asset_id)
        if art is None:
            art = SpriteArt.from_strip(
                self.store.get_asset(layer.asset_id), layer.frames, layer.motion, layer.fps
            )
            self._sprite_arts[layer.asset_id] = art
        return art

    # ================================================================== facade for agent tools

    def surroundings(self, q: int, r: int) -> tuple[list[dict[str, Any]], bytes | None]:
        h = Hex(q, r)
        info, arrays, _ = self._neighbor_context(h)
        style = self.world.style
        by_hex = {h.neighbor(i): a for i, a in arrays.items()}
        png = neighborhood_png(h, by_hex, style.tile_px) if by_hex and style else None
        return info, png

    def library(self) -> dict[str, Any]:
        return {
            "sprites": {
                k: {"size_px": [e.px_w, e.px_h], "frames": e.frames} for k, e in self.world.sprites.items()
            },
            "materials": sorted(self.world.materials),
        }

    def sprite_entry(self, kind: str) -> tuple[SpriteEntry | None, bytes | None]:
        e = self.world.sprites.get(kind_key(kind))
        return (e, preview_png(self._sprite_art(e), scale=6)) if e is not None else (None, None)

    def commission_sprite_later(self, kind: str, brief: str) -> None:
        """Start painting in the background; the tile's layer step joins it (single-flight)."""
        self._background(self._ensure_sprite(kind, brief, self._root))

    async def commission_sprite(self, kind: str, brief: str, q: int | None, r: int | None):
        entry = await self._ensure_sprite(kind, brief, self._root)
        if entry is None:
            return None, None
        return entry, preview_png(self._sprite_art(entry), scale=6)

    def progress(self) -> dict[str, Any]:
        mine = [t for t in self.tiles.values() if t.run_id == self.run.id]
        count = lambda st: sum(1 for t in mine if t.status == st)  # noqa: E731
        return {
            "planned_total": self.run.stats.tiles_planned,
            "accepted": count(TileStatus.accepted),
            "pending": count(TileStatus.planned),
            "failed": count(TileStatus.failed),
            "left_empty": count(TileStatus.intentionally_empty),
            "copies": self.run.stats.tiles_copied,
            "library": {"sprites": len(self.world.sprites), "materials": len(self.world.materials)},
            "cost_usd": round(self.run.stats.cost_usd, 4),
        }

    def map_png(self) -> bytes:
        style = self.world.style
        assert style is not None
        region = {
            t.hex: self._array(t.asset_id)
            for t in self.tiles.values()
            if t.status == TileStatus.accepted and t.asset_id
        }
        slots = [
            t.hex for t in self.tiles.values() if t.run_id == self.run.id and t.status == TileStatus.planned
        ]
        n = max(1, len(region) + len(slots))
        scale = 3 if n <= 40 else 2 if n <= 120 else 1
        return to_png(render_region(region, tile_px=style.tile_px, slots=slots, scale=scale))

    def pending(self) -> list[dict[str, Any]]:
        out = []
        for t in sorted(self.tiles.values(), key=lambda t: (t.hex.distance(self.origin), t.q, t.r)):
            if t.run_id == self.run.id and t.status == TileStatus.planned and t.directive and t.attempts == 0:
                d = t.directive
                out.append(
                    {
                        "q": t.q,
                        "r": t.r,
                        "ring": t.hex.distance(self.origin),
                        "biome": d.biome,
                        "intent": d.intent,
                        "features": d.features,
                    }
                )
        return out[:200]

    def update_tiles(self, changes: list[Any]) -> dict[str, Any]:
        assert self.world.spec is not None
        vocab = set(self.world.spec.terrain_vocabulary)
        applied, errors = 0, []
        for ch in changes:
            t = self.tiles.get(Hex(ch.q, ch.r))
            if not (
                t
                and t.run_id == self.run.id
                and t.status == TileStatus.planned
                and t.directive
                and t.attempts == 0
            ):
                errors.append(f"{ch.q},{ch.r}: not a pending tile of this run")
                continue
            if ch.leave_empty:
                t.status, t.directive = TileStatus.intentionally_empty, None
                self.run.stats.tiles_planned -= 1
            else:
                upd: dict[str, Any] = {}
                if ch.biome is not None:
                    if ch.biome not in vocab:
                        errors.append(f"{ch.q},{ch.r}: biome {ch.biome!r} not in terrain_vocabulary")
                        continue
                    upd["biome"] = ch.biome
                    t.biome = ch.biome
                if ch.intent is not None:
                    upd["intent"] = ch.intent[:200]
                if ch.features is not None:
                    upd["features"] = ch.features[:1]
                t.directive = t.directive.model_copy(update=upd)
            self._save_tile(t)
            applied += 1
        self.tracer.emit("director.update", data={"applied": applied, "errors": errors[:10]})
        return {"applied": applied, "errors": errors[:20]}

    def redo_tile(self, q: int, r: int, feedback: str) -> dict[str, Any]:
        t = self.tiles.get(Hex(q, r))
        if not (t and t.status == TileStatus.accepted and t.run_id == self.run.id and t.directive):
            return {"error": "only accepted tiles from this run can be redone"}
        t.directive = t.directive.model_copy(update={"feedback": [*t.directive.feedback, feedback]})
        t.status = TileStatus.planned
        self._save_tile(t)
        self.run.stats.tiles_accepted -= 1
        self._redo.append(t)
        self.tracer.emit("director.redo", q=q, r=r, data={"feedback": feedback})
        return {"status": "queued for regeneration after this check-in"}

    def _sprite_art(self, entry: SpriteEntry) -> SpriteArt:
        art = self._sprite_arts.get(entry.asset_id)
        if art is None:
            art = SpriteArt.from_strip(
                self.store.get_asset(entry.asset_id), entry.frames, entry.motion, entry.fps
            )
            self._sprite_arts[entry.asset_id] = art
        return art

    async def _compose_layers(
        self,
        design: TileDesign,
        t: Tile,
        ground: PixelTile,
        ground_id: str,
        height_id: str,
        variant: int,
        parent: Span,
    ) -> tuple[list[TileLayer], np.ndarray]:
        """Ground + prop sprites (designed on demand) + ambient scatter from the biome's material,
        laid out by the engine so nothing overlaps or spills out of the hex."""
        style = self.world.style
        assert style is not None
        P = style.tile_px
        ctx = f"{design.biome}: {design.summary}"
        wanted: list[tuple[str, float, float, float, str, str]] = [
            (p.kind, p.x, p.y, p.scale, ctx, "prop") for p in design.props[:MAX_PROPS]
        ]
        mat = self.world.materials.get(design.biome)
        if mat is not None and len(wanted) < MAX_SPRITES:
            for kind, x, y, sc in scatter_positions(mat.scatter, (t.q, t.r), variant):
                if len(wanted) >= MAX_SPRITES:
                    break
                wanted.append((kind, x, y, sc, f"ambient on {design.biome}", "scatter"))
        entries = await asyncio.gather(*[self._ensure_sprite(w[0], w[4], parent) for w in wanted])
        reqs: list[PropRequest] = []
        arts: dict[str, tuple[SpriteEntry, SpriteArt]] = {}
        landmark_taken = False
        for (_kind, x, y, sc, _ctx, role), e in zip(wanted, entries, strict=True):
            if e is None:
                continue
            art = self._sprite_art(e)
            arts[e.kind] = (e, art)
            if role == "prop" and art.h >= 30 and not landmark_taken:
                role, landmark_taken = "landmark", True
            reqs.append(PropRequest(e.kind, x, y, sc, art.w, art.h, role))
        slots, dropped = layout_props(reqs, P)
        if dropped:
            parent.set(dropped=dropped)
        canvas = TileCanvas(t.hex, P)
        layers = [
            TileLayer(kind="ground", asset_id=ground_id, px_w=canvas.C, px_h=canvas.C),
            TileLayer(kind="height", asset_id=height_id, px_w=canvas.C, px_h=canvas.C),
        ]
        placed: list[Placed] = []
        for sl in sorted(slots, key=lambda sl: sl.y):
            e, art = arts[sl.kind]
            placed.append(Placed(kind=e.kind, art=art, x=sl.x, y=sl.y, scale=sl.scale))
            layers.append(
                TileLayer(
                    kind="sprite",
                    asset_id=e.asset_id,
                    label=e.kind,
                    x=sl.x,
                    y=sl.y,
                    width=sl.w,
                    px_w=art.w,
                    px_h=art.h,
                    frames=e.frames,
                    fps=e.fps,
                    motion=e.motion,
                )
            )
        flat = flatten(ground.rgba, placed, canvas)
        flat[~canvas.mask()] = 0
        return layers, flat

    def _contact_sheet(self, cands: list[Candidate], labels: dict[Hex, int], P: int) -> bytes:
        """One small panel per candidate (it + its settled neighbours), in a grid: bounded size no
        matter how far apart the candidates are on the map."""
        panels = []
        for c in cands:
            h = c.job.tile.hex
            region = {h: c.flat if c.flat is not None else c.pix.rgba}
            for n in h.neighbors():
                nt = self.tiles.get(n)
                if nt and nt.status == TileStatus.accepted and nt.asset_id:
                    # context only: neighbours' GROUND, dimmed, so their landmarks are never
                    # mistaken for the candidate's (the candidate is the one bright tile)
                    ctx = self._array(nt.ground_asset_id or nt.asset_id).copy()
                    ctx[..., :3] = (ctx[..., :3] * 0.45).astype(np.uint8)
                    region[n] = ctx
            panels.append(
                render_region(
                    region,
                    tile_px=P,
                    slots=h.neighbors(),
                    labels={h: labels[h]},
                    center=h,
                    extent_px=int(P * 2.6),
                    scale=2,
                )
            )
        cols = min(4, len(panels))
        rows = (len(panels) + cols - 1) // cols
        w, hgt = panels[0].size
        sheet = Image.new("RGBA", (cols * w + (cols - 1) * 6, rows * hgt + (rows - 1) * 6), (20, 22, 30, 255))
        for i, pnl in enumerate(panels):
            sheet.alpha_composite(pnl, ((i % cols) * (w + 6), (i // cols) * (hgt + 6)))
        return to_png(sheet)

    def _height_asset(
        self, height_png: bytes | None, t: Tile, biome: str, edges: list[EdgeSpec], materials: dict, P: int
    ) -> str:
        """Relief layer: from the ground renderer when it provides one, otherwise computed from the
        same materials (relief never depends on how the colours were produced)."""
        if height_png is None:
            _, heights = render_ground(
                tile_px=P,
                biome=biome,
                edges=[e.model_dump() for e in edges],
                coord=(t.q, t.r),
                materials=materials,
            )
            height_png = to_png(Image.fromarray((heights * 40).astype(np.uint8), "L"))
        return self.store.put_asset(height_png, {"kind": "height", "q": t.q, "r": t.r})

    # ================================================================== anchor bootstrap

    # ================================================================== streaming growth

    def _settled(self, h: Hex) -> bool:
        nt = self.tiles.get(h)
        return h in self._provisional or (nt is not None and nt.status == TileStatus.accepted)

    def _background(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def _score(self, t: Tile) -> float:
        accepted_nb = sum(1 for n in t.hex.neighbors() if self._settled(n))
        prio = 3
        if self.run.plan:
            prio = next((pt.priority for pt in self.run.plan.tiles if (pt.q, pt.r) == (t.q, t.r)), 3)
        return (
            accepted_nb * 10
            + prio * 2
            - t.hex.distance(self.origin) * 0.6
            + (100 if t.hex == self.origin else 0)
        )

    def _ready(self, pending: dict[Hex, Tile], busy: set[Hex]) -> list[Tile]:
        world_started = bool(self._provisional) or any(
            t.status == TileStatus.accepted for t in self.tiles.values()
        )
        out = []
        for t in pending.values():
            if any(n in busy or n in self._waiting for n in t.hex.neighbors()):
                continue
            touching = any(self._settled(n) for n in t.hex.neighbors())
            if not (touching or (not world_started and t.hex == self.origin)):
                continue
            spec = t.directive.duplicate if t.directive else None
            if spec is not None:
                src = self.tiles.get(spec.source)
                if src is not None and src.status in ACTIVE_STATUSES:
                    continue  # a copy waits for its prototype to settle
            out.append(t)
        return sorted(out, key=self._score, reverse=True)

    async def _grow(self, root: Span) -> None:
        pending: dict[Hex, Tile] = {
            t.hex: t
            for t in self.tiles.values()
            if t.run_id == self.run.id and t.status == TileStatus.planned and t.directive is not None
        }
        inflight: dict[Hex, asyncio.Task] = {}
        self._wake = asyncio.Event()
        self._review_ready = asyncio.Event()
        self._review_q = []
        self._review_sem = asyncio.Semaphore(2)
        reviewer = asyncio.create_task(self._review_loop(root))
        cap = max(1, self.s.tile_concurrency)
        direct_every = max(6, len(pending) // 4)
        since_direct = 0
        self.tracer.emit(
            "growth.scheduled",
            data={"pending": len(pending), "concurrency": cap, "direct_every": direct_every},
        )
        try:
            while pending or inflight:
                self._raise_budget()
                busy = set(self._busy)
                for t in self._ready(pending, busy):
                    if len(inflight) >= cap:
                        break
                    if any(n in busy for n in t.hex.neighbors()):
                        continue
                    pending.pop(t.hex)
                    busy.add(t.hex)
                    self._busy.add(t.hex)
                    inflight[t.hex] = asyncio.create_task(self._job(t, root))
                if not inflight:
                    if not pending:
                        break
                    # Nothing touches the settled world (e.g. a separate island): seed the best one.
                    t = max(pending.values(), key=self._score)
                    pending.pop(t.hex)
                    self._busy.add(t.hex)
                    inflight[t.hex] = asyncio.create_task(self._job(t, root))
                    continue
                await self._wake.wait()
                self._wake.clear()
                for h, task in list(inflight.items()):
                    if not task.done():
                        continue
                    inflight.pop(h)
                    exc = task.exception()
                    if exc is not None:
                        raise exc
                    if task.result() == "accepted":
                        since_direct += 1
                    self.store.put_run(self.run)
                    self._emit_stats()
                if since_direct >= direct_every and pending:
                    since_direct = 0
                    await self._direct(root)
                    for t in self._redo:
                        pending[t.hex] = t
                    self._redo = []
                    for h in [h for h, t in pending.items() if t.status != TileStatus.planned]:
                        pending.pop(h)  # the director dropped it
        finally:
            for task in inflight.values():
                task.cancel()
            reviewer.cancel()
            for task in [*inflight.values(), reviewer]:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    async def _job(self, t: Tile, root: Span) -> str:
        """One tile from start to a terminal state; its agent session persists across attempts."""
        assert t.directive is not None
        job = Job(t, t.directive)
        try:
            async with self.tracer.span("tile.job", root, q=t.q, r=t.r) as jsp:
                if job.directive.duplicate is not None:
                    if await self._resolve_copy(job, jsp, final=True) == "copied":
                        jsp.set(outcome="copied")
                        return "accepted"
                if job.directive.biome not in self.world.materials:
                    # the material this tile will almost surely paint: design it while the agent designs
                    self._background(self._ensure_material(job.directive.biome, False, jsp))
                while True:
                    cand = await self._produce(job, jsp)
                    if self._budget_error is not None:
                        return "budget"
                    if cand is not None and cand.checks.ok:
                        fut: asyncio.Future = asyncio.get_running_loop().create_future()
                        self._review_q.append((cand, fut))
                        self._review_ready.set()
                        self._provisional[t.hex] = cand
                        self._busy.discard(t.hex)
                        self._wake.set()  # neighbours may start now
                        v = await fut
                        self._provisional.pop(t.hex, None)
                        last_chance = (
                            job.directive.simplified
                            and job.attempts_this_run >= self.run.options.max_attempts
                        )
                        if v is not None and not v.accept and last_chance:
                            # Out of attempts, but it passed every deterministic check: a settled tile
                            # the reviewer dislikes beats a hole in the world (the director or a later
                            # run can still redo it).
                            self.tracer.emit(
                                "tile.accepted_over_review",
                                q=job.tile.q,
                                r=job.tile.r,
                                data={"feedback": v.feedback},
                            )
                        if v is None or v.accept or last_chance:
                            self._accept(cand, v)
                            await self._refresh_if_stale(cand)
                            jsp.set(outcome="accepted", attempts=job.attempts_this_run)
                            return "accepted"
                        for i, n in enumerate(t.hex.neighbors()):
                            if n in self._busy or self._settled(n):
                                job.locked[i] = cand.design.edges[i]
                        cand.attempt.verdict = v
                        cand.attempt.outcome = "rejected"
                        self.store.put_attempt(cand.attempt)
                        self.run.stats.rejections_review += 1
                        job.feedback = v.feedback or "rejected by the reviewer; improve it"
                        job.directive.feedback.append(job.feedback)
                        if job.locked:
                            dirs = ", ".join(DIRECTION_NAMES[i] for i in sorted(job.locked))
                            job.feedback += (
                                f" (Keep your {dirs} edge(s) exactly as they were: neighbouring tiles "
                                "have already been built against them.)"
                            )
                    elif cand is not None:
                        job.feedback = f"automatic checks failed: {cand.checks.feedback}"
                        job.directive.feedback.append(cand.checks.feedback)
                    if not self._retry_or_fail(job, self.run.options.max_attempts):
                        jsp.set(outcome="failed", attempts=job.attempts_this_run)
                        return "failed"
                    await self._claim(t.hex)
        finally:
            self._busy.discard(t.hex)
            self._provisional.pop(t.hex, None)
            self._wake.set()

    async def _claim(self, h: Hex) -> None:
        """Before a retry: wait until no neighbour is mid-attempt, then mark this tile busy again, so
        neighbouring designs never overlap (a rejected tile redesigns against settled edges only)."""
        self._busy.discard(h)
        self._waiting.add(h)
        self._wake.set()
        try:
            while any(n in self._busy for n in h.neighbors()):
                await asyncio.sleep(0.05)
        finally:
            self._waiting.discard(h)
        self._busy.add(h)

    async def _review_loop(self, parent: Span) -> None:
        """Continuous reviewer: waits a moment so near-simultaneous candidates share one call, then
        reviews up to `review_batch` at a time (at most two batches in parallel)."""
        while True:
            await self._review_ready.wait()
            self._review_ready.clear()
            await asyncio.sleep(0.5)
            while self._review_q:
                batch = self._review_q[: self.run.options.review_batch]
                del self._review_q[: len(batch)]
                await self._review_sem.acquire()
                asyncio.create_task(self._review_batch(batch, parent))

    async def _review_batch(self, batch: list[tuple[Candidate, asyncio.Future]], parent: Span) -> None:
        try:
            verdicts: dict[Hex, Verdict] = {}
            try:
                verdicts = await self._review_chunk([c for c, _ in batch], parent)
            except BudgetExceeded as e:
                self._budget_error = e
            except Exception:  # noqa: BLE001 - deterministic checks already passed: accept
                verdicts = {}
            for c, fut in batch:
                if not fut.done():
                    fut.set_result(verdicts.get(c.job.tile.hex))
        finally:
            self._review_sem.release()

    async def _direct(self, root: Span) -> None:
        accepted = sum(
            1 for t in self.tiles.values() if t.run_id == self.run.id and t.status == TileStatus.accepted
        )
        async with self.tracer.span("super.direct", root, accepted=accepted) as sp:
            try:
                note = await director.direct(
                    self.kit,
                    api=self,
                    world=self.world,
                    ring=accepted,
                    rings_total=self.run.stats.tiles_planned,
                    notes=self._director_notes,
                    parent=sp,
                )
            except BudgetExceeded as e:
                self._budget_error = e
                return
            except Exception as e:  # noqa: BLE001 - the build continues as planned
                sp.set(error=str(e)[:200])
                return
            if note:
                self._director_notes.append(f"after {accepted} tiles: {note}")
                sp.set(note=note[:300])
                self.tracer.emit("director.note", data={"accepted": accepted, "note": note})

    async def _resolve_copy(self, job: Job, parent: Span, final: bool) -> str:
        t, spec = job.tile, job.directive.duplicate
        assert spec is not None
        src = self.tiles.get(spec.source)
        ready = src is not None and src.status == TileStatus.accepted
        if not ready and not final:
            return "deferred"
        async with self.tracer.span(
            "tile.copy", parent, q=t.q, r=t.r, mode=spec.mode, source=spec.source.key
        ) as sp:
            in_place = bool(getattr(self.rt.image, "deterministic_ground", False))
            if src is not None and ready:
                ok, reason, seams = copy_fits(
                    t.hex,
                    src,
                    self.tiles,
                    self._ground_array,
                    self.s.max_seam_delta,
                    check_pixels=not in_place,
                    check_edges=not in_place,  # re-rendered in place: adopt the neighbours' contracts
                )
            else:
                ok, reason, seams = False, "prototype was never accepted", {}
            sp.set(copied=ok, reason=reason, seam_delta=seams, in_place=in_place)
            if ok and src is not None:
                apply_copy(t, src, spec.mode)
                if in_place:
                    await self._render_copy_in_place(t, src)
                self._save_tile(t)
                self.run.stats.tiles_copied += 1
                self.run.stats.tiles_accepted += 1
                self.tracer.emit(
                    "tile.copied",
                    q=t.q,
                    r=t.r,
                    data={
                        "mode": spec.mode,
                        "source": spec.source.key,
                        "asset_id": t.asset_id,
                        "seam_delta": seams,
                    },
                )
                return "copied"
            self.run.stats.copy_fallbacks += 1
            self.tracer.emit(
                "copy.fallback",
                q=t.q,
                r=t.r,
                data={"mode": spec.mode, "source": spec.source.key, "reason": reason},
            )
            job.directive = job.directive.model_copy(update={"duplicate": None})
            t.directive = job.directive
            self._save_tile(t)
            return "fallback"

    def _retry_or_fail(self, job: Job, max_attempts: int) -> bool:
        t = job.tile
        if job.attempts_this_run < max_attempts:
            t.status = TileStatus.planned
            t.preview_asset_id = None
            self._save_tile(t)
            return True
        if not job.directive.simplified:
            # Last resort: one attempt with a stripped-down directive.
            job.directive = job.directive.model_copy(
                update={
                    "simplified": True,
                    "features": [],
                    "intent": f"plain {job.directive.biome.replace('_', ' ')} terrain, no props",
                    "feedback": job.directive.feedback[-1:],
                }
            )
            t.directive = job.directive
            job.agent, job.feedback = None, None  # fresh agent for the simplified brief
            t.status = TileStatus.planned
            t.preview_asset_id = None
            self._save_tile(t)
            self.tracer.emit("tile.simplified", q=t.q, r=t.r)
            return True
        t.status = TileStatus.failed
        t.preview_asset_id = None
        self._save_tile(t)
        self.run.stats.tiles_failed += 1
        self.tracer.emit(
            "tile.failed", q=t.q, r=t.r, data={"attempts": t.attempts, "feedback": job.directive.feedback}
        )
        return False

    # ================================================================== one attempt

    async def _produce(self, job: Job, parent: Span, variant: int = 0) -> Candidate | None:
        t = job.tile
        h = t.hex
        job.attempts_this_run += 1
        t.attempts += 1
        attempt_no = t.attempts
        self.run.stats.attempts += 1
        t.status = TileStatus.generating
        self._save_tile(t)
        attempt = Attempt(
            run_id=self.run.id,
            q=t.q,
            r=t.r,
            attempt=attempt_no,
            directive=job.directive.model_copy(deep=True),
            created_at=time.time(),
        )
        self.store.put_attempt(attempt)
        try:
            async with self.tracer.span(
                "tile.attempt", parent, q=t.q, r=t.r, attempt=attempt_no, simplified=job.directive.simplified
            ) as sp:
                world, style = self.world, self.world.style
                assert style is not None and world.spec is not None
                P = style.tile_px
                neighbors, accepted_arrays, facing = self._neighbor_context(h)
                facing = {**job.locked, **facing}
                arrays_by_hex = {h.neighbor(i): a for i, a in accepted_arrays.items()}
                anchor = self._anchor_png()

                # 1) tile agent designs (LLM)
                async with self.tracer.span("tile.design", sp, revision=job.feedback is not None) as dsp:
                    if job.agent is None:
                        job.agent = TileAgent(self.kit, world=world, directive=job.directive, api=self)
                        design = await job.agent.design(neighbors=neighbors, parent=dsp)
                    else:
                        design = await job.agent.revise(job.feedback or "try again", parent=dsp)
                    job.feedback = None
                    if design is None:
                        raise RuntimeError("tile agent did not submit a design")
                    design, norm = tile_agent.normalize_design(design, world, facing)
                    dsp.set(biome=design.biome, summary=design.summary, normalization=norm)
                attempt.design = design

                # 2) the ground's materials (designed on demand the first time any tile needs them)
                materials = await self._materials_for(design.biome, design.edges, sp)
                used_versions = {n: self._material_version[n] for n in materials}

                # 3) image generation (GPU-bounded)
                seed = _seed(self.run.prompt, t.key, attempt_no, variant)
                req = ImageRequest(
                    prompt=_image_prompt(design, world),
                    negative=_negative(design),
                    seed=seed,
                    size=self.s.gen_px,
                    mode="txt2img",
                    style_refs=[anchor] if anchor else [],
                    hints={
                        "tile_px": P,
                        "palette": style.palette,
                        "biome": design.biome,
                        "edges": [e.model_dump() for e in design.edges],
                        "coord": (t.q, t.r),
                        "materials": materials,
                    },
                )
                if arrays_by_hex:
                    req.mode = "inpaint"
                    req.context_png, req.mask_png = context_canvas(h, arrays_by_hex, P, self.s.gen_px)
                async with (
                    self.rt.gpu_sem,
                    self.tracer.span(
                        "image.generate", sp, backend=self.rt.image.name, mode=req.mode, seed=seed
                    ) as isp,
                ):
                    res = await self.rt.image.generate(req)
                    isp.set(served_by=res.backend, **{k: v for k, v in res.meta.items() if k != "seed"})
                self.run.stats.images += 1

                # 3) pixelize onto the master palette + hex mask
                canvas = TileCanvas(h, P)
                src = crop_target(res.png, P) if res.meta.get("framing") == "context" else res.png
                pix = (
                    await asyncio.to_thread(crisp_tile, src, canvas)
                    if res.meta.get("crisp")
                    else await asyncio.to_thread(pixelize_to_canvas, src, style.palette, canvas)
                )

                # 4) deterministic checks
                checks = check_candidate(
                    pix,
                    canvas,
                    accepted_arrays,
                    max_seam_delta=self.s.max_seam_delta,
                    min_coverage=self.s.min_coverage,
                    # procedural ground: texture is the material artist's call (it reviewed its own render)
                    min_distinct_colors=0 if res.meta.get("crisp") else self.s.min_distinct_colors,
                )
                ground_id = self.store.put_asset(
                    pix.png,
                    {
                        "kind": "ground",
                        "run_id": self.run.id,
                        "q": t.q,
                        "r": t.r,
                        "attempt": attempt_no,
                        "backend": res.backend,
                        "seed": seed,
                        "prompt": req.prompt,
                        **res.meta,
                    },
                )
                self._arrays[ground_id] = pix.rgba
                height_id = self._height_asset(res.height_png, t, design.biome, design.edges, materials, P)

                # 5) layers: prop sprites + ambient scatter on top of the ground
                async with self.tracer.span("tile.layers", sp) as lsp:
                    layers, flat = await self._compose_layers(
                        design, t, pix, ground_id, height_id, variant, lsp
                    )
                    lsp.set(sprites=[layer.label for layer in layers if layer.kind == "sprite"])
                flat_png = to_png(Image.fromarray(flat, "RGBA"))
                asset_id = self.store.put_asset(
                    flat_png, {"kind": "tile_preview", "run_id": self.run.id, "q": t.q, "r": t.r}
                )
                self._arrays[asset_id] = flat
                attempt.asset_id = asset_id
                attempt.validation = {
                    "ground_asset_id": ground_id,
                    "ok": checks.ok,
                    "failures": checks.failures,
                    **checks.metrics,
                    "normalization": norm,
                    "side_color": pix.side_color,
                }
                sp.set(asset_id=asset_id, valid=checks.ok, failures=checks.failures)
                self.tracer.emit(
                    "validation.result",
                    span_id=sp.id,
                    q=t.q,
                    r=t.r,
                    data={"attempt": attempt_no, **attempt.validation},
                )
                if not checks.ok:
                    attempt.outcome = "invalid"
                    self.run.stats.rejections_validation += 1
                    self.store.put_attempt(attempt)
                    return Candidate(
                        job,
                        attempt,
                        design,
                        pix,
                        asset_id,
                        checks,
                        norm,
                        ground_id,
                        flat,
                        flat_png,
                        layers,
                        used_versions,
                    )
                t.status = TileStatus.reviewing
                t.preview_asset_id = asset_id
                self._save_tile(t)
                self.store.put_attempt(attempt)
                return Candidate(
                    job,
                    attempt,
                    design,
                    pix,
                    asset_id,
                    checks,
                    norm,
                    ground_id,
                    flat,
                    flat_png,
                    layers,
                    used_versions,
                )
        except BudgetExceeded as e:
            self._budget_error = e
            attempt.outcome, attempt.error = "error", str(e)
            self.store.put_attempt(attempt)
            return None
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - one tile's failure never sinks the wave
            attempt.outcome, attempt.error = "error", f"{type(e).__name__}: {e}"[:500]
            self.store.put_attempt(attempt)
            return None

    # ================================================================== review

    async def _review(self, cands: list[Candidate], parent: Span) -> dict[Hex, Verdict]:
        out: dict[Hex, Verdict] = {}
        batch = self.run.options.review_batch
        chunks = [cands[i : i + batch] for i in range(0, len(cands), batch)]
        results = await asyncio.gather(*[self._review_chunk(c, parent) for c in chunks])
        for r in results:
            out.update(r)
        return out

    async def _review_chunk(self, cands: list[Candidate], parent: Span) -> dict[Hex, Verdict]:
        style = self.world.style
        assert style is not None
        P = style.tile_px
        labels = {c.job.tile.hex: i + 1 for i, c in enumerate(cands)}
        composite = self._contact_sheet(cands, labels, P)
        comp_id = self.store.put_asset(composite, {"kind": "review_composite", "run_id": self.run.id})
        payload = [
            {
                "label": labels[c.job.tile.hex],
                "coord": {"q": c.job.tile.q, "r": c.job.tile.r},
                "attempt": c.attempt.attempt,
                "directive": {
                    "biome": c.job.directive.biome,
                    "intent": c.job.directive.intent,
                    "features": c.job.directive.features,
                },
                "design": {
                    "summary": c.design.summary,
                    "landmark": next((layer.label for layer in c.layers if layer.kind == "sprite"), None),
                    "art_prompt": c.design.art_prompt,
                    "edges": [e.model_dump() for e in c.design.edges],
                },
                "metrics": {
                    "seam_delta": c.checks.metrics.get("seam_delta", {}),
                    "distinct_colors": c.checks.metrics.get("distinct_colors"),
                },
            }
            for c in cands
        ]
        async with self.tracer.span(
            "super.review",
            parent,
            candidates=len(cands),
            composite_asset_id=comp_id,
            labels={str(v): k.key for k, v in labels.items()},
        ) as sp:
            try:
                zooms = {labels[c.job.tile.hex]: _zoom_png(c) for c in cands}
                review = await super_agent.review_wave(
                    self.kit,
                    world=self.world,
                    anchor_png=self._anchor_png(),
                    composite_png=composite,
                    candidates=payload,
                    zooms=zooms,
                    history=self._review_history,
                    parent=sp,
                )
            except BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001 - degrade: deterministic checks already passed
                sp.set(review_error=str(e)[:300], degraded="accepted on deterministic checks only")
                return {}
            by_label = {v.label: v for v in review.verdicts}
            out: dict[Hex, Verdict] = {}
            for c in cands:
                h = c.job.tile.hex
                v = by_label.get(labels[h])
                if v is None:
                    continue
                out[h] = v
                self._review_history.append(
                    f"{h.key} {c.design.biome}: "
                    + ("accepted" if v.accept else f"rejected ({v.feedback[:90]})")
                )
                if v.sprite_feedback:
                    kinds = [layer.label for layer in c.layers if layer.kind == "sprite" and layer.label]
                    name, _, note = v.sprite_feedback.partition(":")
                    key = kind_key(name) if note else ""
                    target = key if key in kinds else (kinds[0] if kinds else None)
                    if target:
                        await self._revise_sprite(
                            target, (note if key == target else v.sprite_feedback).strip(), sp
                        )
                if v.material_feedback:
                    name, _, note = v.material_feedback.partition(":")
                    name = name.strip() if note and name.strip() in self.world.materials else c.design.biome
                    await self._revise_material(name, (note or v.material_feedback).strip(), sp)
                self.tracer.emit(
                    "review.verdict",
                    span_id=sp.id,
                    q=h.q,
                    r=h.r,
                    data={
                        "attempt": c.attempt.attempt,
                        "accept": v.accept,
                        "scores": v.scores.model_dump(),
                        "feedback": v.feedback,
                        "asset_id": c.asset_id,
                    },
                )
            sp.set(
                accepted=sum(1 for v in out.values() if v.accept),
                rejected=sum(1 for v in out.values() if not v.accept),
            )
            return out

    # ================================================================== helpers

    def _accept(self, c: Candidate, verdict: Verdict | None) -> None:
        t = c.job.tile
        t.status = TileStatus.accepted
        t.biome = c.design.biome
        t.summary = c.design.summary
        t.attributes = c.design.attributes
        t.edges = c.design.edges
        t.asset_id = c.asset_id
        t.ground_asset_id = c.ground_id or c.asset_id
        t.layers = c.layers
        t.relief = c.design.relief
        t.preview_asset_id = None
        t.side_color = c.pix.side_color
        t.art_prompt = c.design.art_prompt
        t.copy_of = None
        t.copy_mode = None
        self._save_tile(t)
        for linked in sync_shallow_copies(t, self.tiles):
            self._save_tile(linked)
            self.tracer.emit("tile.copy_synced", q=linked.q, r=linked.r, data={"source": t.key})
        c.attempt.outcome = "accepted"
        c.attempt.verdict = verdict
        self.store.put_attempt(c.attempt)
        self.run.stats.tiles_accepted += 1
        if not self.world.anchor_asset_ids:
            self.world.anchor_asset_ids = [c.asset_id]
            self.store.put_world(self.world)
            self.tracer.emit("anchor.selected", q=t.q, r=t.r, data={"asset_id": c.asset_id})
        self.tracer.emit(
            "tile.accepted",
            q=t.q,
            r=t.r,
            data={"attempt": c.attempt.attempt, "asset_id": c.asset_id, "reviewed": verdict is not None},
        )

    def _neighbor_context(
        self, h: Hex
    ) -> tuple[list[dict[str, Any]], dict[int, np.ndarray], dict[int, EdgeSpec]]:
        info: list[dict[str, Any]] = []
        arrays: dict[int, np.ndarray] = {}
        facing: dict[int, EdgeSpec] = {}
        for i in range(6):
            n = h.neighbor(i)
            nt = self.tiles.get(n)
            entry: dict[str, Any] = {
                "edge": i,
                "direction": DIRECTION_NAMES[i],
                "q": n.q,
                "r": n.r,
                "status": (nt.status.value if nt else "empty"),
            }
            if n.distance(ORIGIN) > self.world.radius:
                entry["status"] = "out_of_world"
            prov = self._provisional.get(n)
            if prov is not None:  # provisionally settled: build against its (frozen) edges
                fe = prov.design.edges[opposite(i)]
                entry.update(
                    status="accepted",
                    biome=prov.design.biome,
                    summary=prov.design.summary,
                    art_prompt=prov.design.art_prompt,
                    facing_edge=fe.model_dump(),
                )
                facing[i] = fe
                arrays[i] = prov.pix.rgba
            elif nt and nt.status == TileStatus.accepted and nt.edges and nt.asset_id:
                fe = nt.edges[opposite(i)]
                entry.update(
                    biome=nt.biome, summary=nt.summary, art_prompt=nt.art_prompt, facing_edge=fe.model_dump()
                )
                facing[i] = fe
                arrays[i] = self._array(nt.ground_asset_id or nt.asset_id)
            elif nt and nt.directive is not None and nt.status in ACTIVE_STATUSES:
                entry.update(biome=nt.directive.biome, intent=nt.directive.intent)
            info.append(entry)
        return info, arrays, facing

    def _tile(self, h: Hex) -> Tile:
        t = self.tiles.get(h)
        if t is None:
            t = Tile(q=h.q, r=h.r)
            self.tiles[h] = t
        return t

    def _save_tile(self, t: Tile) -> None:
        self.store.put_tile(self.world.id, t)
        self.tracer.emit("tile.updated", q=t.q, r=t.r, data={"tile": t.model_dump(mode="json")})

    def _array(self, asset_id: str) -> np.ndarray:
        a = self._arrays.get(asset_id)
        if a is None:
            a = load_tile(self.store.get_asset(asset_id))
            self._arrays[asset_id] = a
        return a

    def _ground_array(self, asset_id: str) -> np.ndarray:
        return self._array(asset_id)

    def _anchor_png(self) -> bytes | None:
        ids = self.world.anchor_asset_ids
        return self.store.get_asset(ids[0]) if ids else None

    def _emit_stats(self) -> None:
        self.tracer.emit("run.stats", data=self.run.stats.model_dump())

    def _raise_budget(self) -> None:
        if self._budget_error is not None:
            raise self._budget_error


def _seed(*parts: Any) -> int:
    return int(hashlib.sha256(repr(parts).encode()).hexdigest()[:8], 16)


def _image_prompt(design: TileDesign, world: World) -> str:
    style = world.style
    assert style is not None
    edge_desc = ", ".join(
        f"{DIRECTION_NAMES[i]} side {e.terrain.replace('_', ' ')}"
        + (f" with {'/'.join(e.connectors)}" if e.connectors else "")
        for i, e in enumerate(design.edges)
    )
    return (
        f"Top-down ground texture only, no buildings, trees or props. {design.art_prompt} "
        f"Ground: {design.biome.replace('_', ' ')}; {edge_desc}. Light {style.light_direction}. "
        f"{style.style_keywords}, pixel art game map tile"
    )


def _zoom_png(c: Candidate) -> bytes:
    flat = c.flat if c.flat is not None else c.pix.rgba
    img = Image.fromarray(flat, "RGBA")
    return to_png(img.resize((img.width * 8, img.height * 8), Image.Resampling.NEAREST))


def _merge_palette(palette: list[str], extra: list[str], cap: int = 128) -> list[str]:
    out = [c.lower() for c in palette]
    for c in extra:
        c = c.lower()
        if c not in out and len(out) < cap:
            out.append(c)
    return out


def _negative(design: TileDesign) -> str:
    base = "text, watermark, signature, border, frame, hexagon outline, perspective, blurry, photo, 3d render"
    return f"{design.negative_prompt}, {base}" if design.negative_prompt else base
