"""Run executor: one user prompt → plan → anchor bootstrap → wave expansion with review.

State machine per tile:
    planned → generating → reviewing → accepted
                  ↑            │
                  └── retry ───┘ (feedback)      → failed after max attempts (+1 simplified)

Waves: tiles are processed ring by ring outward from the origin; within a ring, by hex
3-coloring class. No two tiles in a wave are adjacent, so every tile in a wave sees only
already-accepted neighbors, and a wave can be generated fully in parallel and reviewed in
one batched vision call.
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

from hexworld.agents import artist
from hexworld.agents import super as super_agent
from hexworld.agents import tile as tile_agent
from hexworld.agents.llm import BudgetExceeded, LLMGateway, RunBudget
from hexworld.art.backend import ImageRequest
from hexworld.art.composite import context_canvas, crop_target, neighborhood_png, render_region, to_png
from hexworld.art.pixelize import PixelTile, crisp_tile, hex_mask, load_tile, pixelize
from hexworld.art.procedural import fallback_material, ramp_hexes
from hexworld.art.sprites import Placed, SpriteArt, flatten, rasterize, scatter_positions
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


@dataclass
class Job:
    tile: Tile
    directive: Directive
    attempts_this_run: int = 0


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
        self.gw = LLMGateway(
            rt.llm, concurrency=self.s.llm_concurrency, tracer=self.tracer, budget=self.budget
        )
        self.tiles: dict[Hex, Tile] = {t.hex: t for t in self.store.list_tiles(world.id)}
        self._arrays: dict[str, np.ndarray] = {}
        self._budget_error: BudgetExceeded | None = None
        self._deferred_copies: list[Tile] = []
        self._plan_notes: list[str] = []
        self._inflight: dict[str, asyncio.Future] = {}  # single-flight library generation
        self._sprite_arts: dict[str, SpriteArt] = {}
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
                llm=self.rt.llm.name,
                image_backend=self.rt.image.name,
            ) as root:
                if run.plan is None:
                    await self._plan(root)
                else:
                    self._reset_inflight()
                await self._stock_library(root)
                if not self.world.anchor_asset_ids:
                    await self._bootstrap_anchor(root)
                await self._expand(root)
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
        async with self.tracer.span("super.plan", root, candidates=len(candidates)) as sp:
            plan = await super_agent.plan_world(
                self.gw,
                world=w,
                prompt=self.run.prompt,
                origin=self.origin,
                candidates=candidates,
                nearby=nearby,
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

    async def _stock_library(self, root: Span) -> None:
        """Design everything the plan needs up front, in parallel: a material for every terrain and
        connector, then a sprite for every planned feature and every material's ambient scatter kind.
        Later tiles only generate what is genuinely new."""
        w = self.world
        assert w.spec is not None
        async with self.tracer.span("library.stock", root) as sp:
            names = [(n, False) for n in w.spec.terrain_vocabulary] + [
                (n, True) for n in w.spec.connector_vocabulary
            ]
            missing = [(n, c) for n, c in names if n not in w.materials]
            await asyncio.gather(*[self._ensure_material(n, c, sp) for n, c in missing])
            self._raise_budget()
            kinds: dict[str, str] = {}
            for t in self.tiles.values():
                if t.run_id == self.run.id and t.directive is not None:
                    for f in t.directive.features:
                        kinds.setdefault(kind_key(f), f"{t.directive.biome}: {t.directive.intent}")
            for name, spec in w.materials.items():
                for sc in spec.scatter:
                    kinds.setdefault(kind_key(sc.kind), f"ambient on {name}")
            todo = [(k, ctx) for k, ctx in kinds.items() if k not in w.sprites]
            await asyncio.gather(*[self._ensure_sprite(k, ctx, sp) for k, ctx in todo])
            self._raise_budget()
            sp.set(materials=len(missing), sprites=len(todo), library_size=len(w.materials) + len(w.sprites))

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
                    spec = await artist.design_material(
                        self.gw, world=w, name=name, is_connector=is_connector, parent=sp
                    )
                except BudgetExceeded as e:
                    self._budget_error = e
                    return fallback_material(name)
                except Exception as e:  # noqa: BLE001 - render with a plain fallback, retry next run
                    sp.set(error=str(e)[:200], fallback=True)
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

        return await self._single_flight(f"m:{name}", make)

    async def _ensure_sprite(self, kind: str, context: str, parent: Span | None) -> SpriteEntry | None:
        w = self.world
        key = kind_key(kind)
        if key in w.sprites:
            return w.sprites[key]

        async def make() -> SpriteEntry | None:
            async with self.tracer.span("library.sprite", parent, kind=key) as sp:
                try:
                    program = await artist.design_sprite(
                        self.gw, world=w, kind=key, context=context, anchor_png=self._anchor_png(), parent=sp
                    )
                except BudgetExceeded as e:
                    self._budget_error = e
                    return None
                except Exception as e:  # noqa: BLE001 - the tile simply goes without this prop
                    sp.set(error=str(e)[:200])
                    return None
                art = await asyncio.to_thread(rasterize, program)
                asset_id = self.store.put_asset(
                    art.strip_png(), {"kind": "sprite", "sprite": key, "run_id": self.run.id}
                )
                entry = SpriteEntry(
                    kind=key,
                    program=program,
                    asset_id=asset_id,
                    px_w=art.w,
                    px_h=art.h,
                    frames=len(art.frames),
                    fps=art.fps,
                    motion=program.motion,
                    run_id=self.run.id,
                )
                w.sprites[key] = entry
                self._sprite_arts[asset_id] = art
                self.store.put_world(w)
                sp.set(
                    asset_id=asset_id, size=[art.w, art.h], frames=len(art.frames), shapes=len(program.shapes)
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

        return await self._single_flight(f"s:{key}", make)

    async def _render_copy_in_place(self, t: Tile, src: Tile) -> None:
        """Copy the design, not the pixels: re-render the ground at this tile's own world position
        (seamless with its neighbours) and keep the prototype's props. No LLM calls."""
        style = self.world.style
        assert style is not None and t.edges is not None
        P = style.tile_px
        req = ImageRequest(
            prompt="",
            negative="",
            seed=0,
            size=self.s.gen_px,
            hints={
                "tile_px": P,
                "palette": style.palette,
                "biome": src.biome,
                "edges": [e.model_dump() for e in t.edges],
                "coord": (t.q, t.r),
                "materials": {n: m.model_dump() for n, m in self.world.materials.items()},
            },
        )
        async with self.rt.gpu_sem:
            res = await self.rt.image.generate(req)
        pix = await asyncio.to_thread(crisp_tile, res.png, P)
        ground_id = self.store.put_asset(
            pix.png, {"kind": "ground", "run_id": self.run.id, "copy_of": src.key}
        )
        self._arrays[ground_id] = pix.rgba
        sprites = [layer for layer in src.layers if layer.kind == "sprite"]
        placed = []
        for layer in sprites:
            art = self._sprite_arts.get(layer.asset_id) or SpriteArt.from_strip(
                self.store.get_asset(layer.asset_id), layer.frames, layer.motion, layer.fps
            )
            self._sprite_arts[layer.asset_id] = art
            placed.append(Placed(layer.label, art, layer.x, layer.y, layer.width / (art.w / (P / 2.0))))
        flat = flatten(pix.rgba, placed, P)
        flat[~hex_mask(P)] = 0
        flat_id = self.store.put_asset(to_png(Image.fromarray(flat, "RGBA")), {"kind": "tile_preview"})
        self._arrays[flat_id] = flat
        t.ground_asset_id = ground_id
        t.asset_id = flat_id
        t.layers = [
            TileLayer(kind="ground", asset_id=ground_id, px_w=P, px_h=P),
            *[s.model_copy() for s in sprites],
        ]
        t.side_color = pix.side_color

    def _sprite_art(self, entry: SpriteEntry) -> SpriteArt:
        art = self._sprite_arts.get(entry.asset_id)
        if art is None:
            art = SpriteArt.from_strip(
                self.store.get_asset(entry.asset_id), entry.frames, entry.motion, entry.fps
            )
            self._sprite_arts[entry.asset_id] = art
        return art

    async def _compose_layers(
        self, design: TileDesign, t: Tile, ground: PixelTile, ground_id: str, variant: int, parent: Span
    ) -> tuple[list[TileLayer], np.ndarray]:
        """Ground + prop sprites (designed on demand) + ambient scatter from the biome's material."""
        style = self.world.style
        assert style is not None
        P = style.tile_px
        # A landmark (at most one) stands in the middle; ambient scatter only when there is none.
        wanted: list[tuple[str, float, float, float, str]] = [
            (
                p.kind,
                max(-0.12, min(0.12, p.x)),
                max(-0.02, min(0.2, p.y)),
                p.scale,
                f"{design.biome}: {design.summary}",
            )
            for p in design.props[:1]
        ]
        mat = self.world.materials.get(design.biome)
        if mat is not None and not wanted:
            for kind, x, y, sc in scatter_positions(mat.scatter, (t.q, t.r), variant):
                wanted.append((kind, x, y, sc, f"ambient on {design.biome}"))
        entries = await asyncio.gather(*[self._ensure_sprite(k, ctx, parent) for k, _, _, _, ctx in wanted])
        layers = [TileLayer(kind="ground", asset_id=ground_id, px_w=P, px_h=P)]
        placed: list[Placed] = []
        for (_kind, x, y, sc, _), e in zip(wanted, entries, strict=True):
            if e is None:
                continue
            art = self._sprite_art(e)
            is_landmark = _kind == wanted[0][0] and len(design.props) > 0
            max_w = 1.0 if is_landmark else 0.5  # in hex radii: landmarks <= 1 radius, scatter half that
            sc = min(sc, max_w * (P / 2.0) / max(1, art.w))
            placed.append(Placed(kind=e.kind, art=art, x=x, y=y, scale=sc))
            layers.append(
                TileLayer(
                    kind="sprite",
                    asset_id=e.asset_id,
                    label=e.kind,
                    x=x,
                    y=y,
                    width=art.w / (P / 2.0) * sc,
                    px_w=art.w,
                    px_h=art.h,
                    frames=e.frames,
                    fps=e.fps,
                    motion=e.motion,
                )
            )
        flat = flatten(ground.rgba, placed, P)
        flat[~hex_mask(P)] = 0
        return layers, flat

    # ================================================================== anchor bootstrap

    async def _bootstrap_anchor(self, root: Span) -> None:
        """Generate N renderings of the origin tile; the super picks the style anchor with vision.
        Every later tile is conditioned on (and reviewed against) this anchor."""
        tile = self._tile(self.origin)
        if tile.status == TileStatus.accepted and tile.asset_id:
            self.world.anchor_asset_ids = [tile.asset_id]
            self.store.put_world(self.world)
            return
        if tile.directive is None:
            return
        job = Job(tile, tile.directive)
        k = self.run.options.anchor_candidates
        async with self.tracer.span("anchor.bootstrap", root, q=tile.q, r=tile.r, candidates=k) as sp:
            cands = await asyncio.gather(*[self._produce(job, sp, variant=i) for i in range(k)])
            self._raise_budget()
            good = [c for c in cands if c is not None and c.checks.ok]
            if not good:
                sp.set(outcome="no valid candidates; origin falls back to normal waves")
                tile.status = TileStatus.planned
                self._save_tile(tile)
                return
            if len(good) == 1:
                best = good[0]
            else:
                try:
                    pick = await super_agent.pick_anchor(
                        self.gw,
                        world=self.world,
                        intent=job.directive.intent,
                        candidates=[c.flat_png or c.pix.png for c in good],
                        parent=sp,
                    )
                    best = good[pick.best_label - 1]
                    sp.set(pick_reason=pick.reason, picked=pick.best_label)
                except BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001 - degrade: first valid candidate wins
                    sp.set(pick_error=str(e)[:200])
                    best = good[0]
            for c in good:
                if c is not best:
                    c.attempt.outcome = "rejected"
                    c.attempt.verdict = None
                    self.store.put_attempt(c.attempt)
            self._accept(best, None)
            self.world.anchor_asset_ids = [best.asset_id]
            self.store.put_world(self.world)
            self.tracer.emit("anchor.selected", q=tile.q, r=tile.r, data={"asset_id": best.asset_id})

    # ================================================================== waves

    def _waves(self) -> list[list[Tile]]:
        pending = [
            t
            for t in self.tiles.values()
            if t.run_id == self.run.id and t.status == TileStatus.planned and t.directive is not None
        ]
        groups: dict[tuple[int, int], list[Tile]] = defaultdict(list)
        for t in pending:
            groups[(t.hex.distance(self.origin), t.hex.color3())].append(t)
        return [groups[k] for k in sorted(groups)]

    async def _expand(self, root: Span) -> None:
        waves = self._waves()
        self.tracer.emit(
            "waves.scheduled",
            data={
                "waves": [[t.key for t in w] for w in waves],
            },
        )
        for i, wave in enumerate(waves):
            ring = wave[0].hex.distance(self.origin)
            async with self.tracer.span(
                "wave", root, index=i, ring=ring, color=wave[0].hex.color3(), tiles=[t.key for t in wave]
            ) as sp:
                await self._run_wave(wave, sp)
            self.store.put_run(self.run)
            self._emit_stats()
        # Copies whose prototype was not ready in their own wave (it sits further out, or it
        # failed) get one more pass. Anything still unresolved is generated normally.
        if self._deferred_copies:
            deferred, self._deferred_copies = self._deferred_copies, []
            groups: dict[tuple[int, int], list[Tile]] = defaultdict(list)
            for t in deferred:
                groups[(t.hex.distance(self.origin), t.hex.color3())].append(t)
            for key in sorted(groups):
                async with self.tracer.span(
                    "wave",
                    root,
                    index=f"deferred-{key[0]}.{key[1]}",
                    ring=key[0],
                    color=key[1],
                    tiles=[t.key for t in groups[key]],
                ) as sp:
                    await self._run_wave(groups[key], sp, final=True)
            self.store.put_run(self.run)
            self._emit_stats()

    async def _run_wave(self, wave: list[Tile], wave_span: Span, final: bool = False) -> None:
        jobs = [Job(t, t.directive) for t in wave if t.directive is not None]  # type: ignore[arg-type]
        copy_jobs = [j for j in jobs if j.directive.duplicate is not None]
        await self._generate([j for j in jobs if j.directive.duplicate is None], wave_span)
        # Copies resolve after the wave's generated tiles, so a prototype can be in the same wave.
        fallbacks = []
        for j in copy_jobs:
            outcome = await self._resolve_copy(j, wave_span, final)
            if outcome == "fallback":
                fallbacks.append(j)
            elif outcome == "deferred":
                self._deferred_copies.append(j.tile)
        await self._generate(fallbacks, wave_span)

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

    async def _generate(self, active: list[Job], wave_span: Span) -> None:
        opts = self.run.options
        while active:
            designs = await self._design_batch(active, wave_span)
            results = await asyncio.gather(
                *[self._produce(j, wave_span, design=designs.get(j.tile.hex)) for j in active]
            )
            self._raise_budget()
            candidates = [c for c in results if c is not None and c.checks.ok]
            verdicts = await self._review(candidates, wave_span) if candidates else {}

            next_active: list[Job] = []
            for job, cand in zip(active, results, strict=True):
                if cand is not None and cand.checks.ok:
                    v = verdicts.get(job.tile.hex)
                    if v is None or v.accept:
                        self._accept(cand, v)
                        continue
                    cand.attempt.verdict = v
                    cand.attempt.outcome = "rejected"
                    self.store.put_attempt(cand.attempt)
                    self.run.stats.rejections_review += 1
                    job.directive.feedback.append(v.feedback or "rejected by reviewer")
                elif cand is not None:
                    job.directive.feedback.append(cand.checks.feedback)
                if self._retry_or_fail(job, opts.max_attempts):
                    next_active.append(job)
            active = next_active

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

    async def _design_batch(self, jobs: list[Job], parent: Span, chunk: int = 10) -> dict[Hex, TileDesign]:
        """Tile agents for a whole wave in a few calls: tiles in a wave are never adjacent, so each
        design only depends on already-accepted neighbours. Anything missing is designed per tile."""
        if len(jobs) < 2:
            return {}
        world = self.world
        style = world.style
        assert style is not None
        out: dict[Hex, TileDesign] = {}
        chunks = [jobs[i : i + chunk] for i in range(0, len(jobs), chunk)]

        async def one(batch: list[Job]) -> None:
            items = []
            for j in batch:
                h = j.tile.hex
                neighbors, arrays, _ = self._neighbor_context(h)
                by_hex = {h.neighbor(i): a for i, a in arrays.items()}
                items.append(
                    {
                        "directive": j.directive,
                        "neighbors": neighbors,
                        "context_png": neighborhood_png(h, by_hex, style.tile_px) if by_hex else None,
                    }
                )
            async with self.tracer.span("tile.design_batch", parent, tiles=[j.tile.key for j in batch]) as sp:
                try:
                    got = await tile_agent.design_wave(
                        self.gw,
                        world=world,
                        tiles=items,
                        anchor_png=self._anchor_png(),
                        parent=sp,
                        sprite_library=sorted(world.sprites),
                    )
                except BudgetExceeded as e:
                    self._budget_error = e
                    return
                except Exception as e:  # noqa: BLE001 - fall back to per-tile design
                    sp.set(error=str(e)[:200])
                    return
                sp.set(designed=len(got), missing=len(batch) - len(got))
                for (q, r), d in got.items():
                    out[Hex(q, r)] = d

        await asyncio.gather(*[one(b) for b in chunks])
        return out

    async def _produce(
        self, job: Job, parent: Span, variant: int = 0, design: TileDesign | None = None
    ) -> Candidate | None:
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
                arrays_by_hex = {h.neighbor(i): a for i, a in accepted_arrays.items()}
                anchor = self._anchor_png()

                # 1) tile agent designs (LLM)
                async with self.tracer.span("tile.design", sp, batched=design is not None) as dsp:
                    if design is None:
                        design = await tile_agent.design_tile(
                            self.gw,
                            world=world,
                            directive=job.directive,
                            neighbors=neighbors,
                            schema=tile_agent.tile_design_schema(world),
                            anchor_png=anchor,
                            context_png=neighborhood_png(h, arrays_by_hex, P) if arrays_by_hex else None,
                            parent=dsp,
                            sprite_library=sorted(world.sprites),
                        )
                    design, norm = tile_agent.normalize_design(design, world, facing)
                    dsp.set(biome=design.biome, summary=design.summary, normalization=norm)
                attempt.design = design

                # 2) image generation (GPU-bounded)
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
                        "materials": {n: m.model_dump() for n, m in self.world.materials.items()},
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
                src = crop_target(res.png, P) if res.meta.get("framing") == "context" else res.png
                pix = (
                    await asyncio.to_thread(crisp_tile, src, P)
                    if res.meta.get("crisp")
                    else await asyncio.to_thread(pixelize, src, style.palette, P)
                )

                # 4) deterministic checks
                checks = check_candidate(
                    pix,
                    accepted_arrays,
                    max_seam_delta=self.s.max_seam_delta,
                    min_coverage=self.s.min_coverage,
                    min_distinct_colors=self.s.min_distinct_colors,
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

                # 5) layers: prop sprites + ambient scatter on top of the ground
                async with self.tracer.span("tile.layers", sp) as lsp:
                    layers, flat = await self._compose_layers(design, t, pix, ground_id, variant, lsp)
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
                        job, attempt, design, pix, asset_id, checks, norm, ground_id, flat, flat_png, layers
                    )
                t.status = TileStatus.reviewing
                t.preview_asset_id = asset_id
                self._save_tile(t)
                self.store.put_attempt(attempt)
                return Candidate(
                    job, attempt, design, pix, asset_id, checks, norm, ground_id, flat, flat_png, layers
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
        region: dict[Hex, np.ndarray] = {}
        slots: set[Hex] = set()
        for c in cands:
            h = c.job.tile.hex
            region[h] = c.flat if c.flat is not None else c.pix.rgba
            for n in h.neighbors():
                slots.add(n)
                nt = self.tiles.get(n)
                if nt and nt.status == TileStatus.accepted and nt.asset_id and n not in region:
                    region[n] = self._array(nt.asset_id)
        composite = to_png(render_region(region, tile_px=P, slots=slots, labels=labels, scale=4))
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
                review = await super_agent.review_wave(
                    self.gw,
                    world=self.world,
                    anchor_png=self._anchor_png(),
                    composite_png=composite,
                    candidates=payload,
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
            if nt and nt.status == TileStatus.accepted and nt.edges and nt.asset_id:
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
