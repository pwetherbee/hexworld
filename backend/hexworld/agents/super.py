"""The super agent (board creator), on Google ADK.

- planner: `submit_world` (header + origin tile, which starts building at once), then
  `submit_layout` (the map's shape); validation errors go back to it.
- reviewer: reviews each wave with vision, can zoom into candidates, and can address feedback to
  the tile agent (tile feedback) and to the sprite artist (sprite_feedback).
The director (mid-run management) lives in agents/director.py.
"""

from collections.abc import Callable
from typing import Any

from google.adk.tools import ToolContext
from pydantic import ValidationError

from hexworld.agents import prompts
from hexworld.agents.kit import AgentKit, coerce, image_part, submitted, text_part
from hexworld.domain import Layout, Verdict, WaveReview, World, WorldHeader, WorldPlan
from hexworld.hex import Hex
from hexworld.orchestrator.layout import COMPACT_ENOUGH
from hexworld.telemetry import Span


class AgentFailed(Exception):
    pass


def existing_world_payload(world: World) -> dict[str, Any] | None:
    if world.spec is None or world.style is None:
        return None
    out: dict[str, Any] = {
        "world": world.spec.model_dump(),
        "style": world.style.model_dump(),
        "tile_attributes": [a.model_dump() for a in world.tile_attributes],
    }
    if world.parent is not None:  # a drilled layer: the inside of one tile of the parent world
        out["drill"] = {
            "depth": world.depth,
            "scale": world.scale_note,
            "parent_tile": world.parent.context,
            "map": f"a full hexagon of radius {world.radius} ({3 * world.radius * (world.radius + 1) + 1} tiles)",
        }
    return out


async def plan_world(
    kit: AgentKit,
    *,
    world: World,
    prompt: str,
    origin: Hex,
    max_tiles: int,
    world_radius: int,
    occupied: list[Hex],
    nearby: list[dict[str, Any]],
    nearby_png: bytes | None,
    parent: Span | None,
    rasterize: Callable[[Layout, WorldHeader], Any],
    on_header: Callable[[WorldPlan], None] | None = None,
) -> WorldPlan:
    """Two submissions: `submit_world` (world, style, attributes, origin tile) lets the build start
    at the origin while the planner draws the map; `submit_layout` gives the map's SHAPE (regions of
    shape primitives, landmarks, routes), which the engine rasterizes into tiles."""
    holder: dict[str, Any] = {}
    state: dict[str, Any] = {}

    def submit_world(header: WorldHeader) -> dict:
        """Submit the world spec, style, tile attributes and the ORIGIN tile's plan. The origin
        starts building immediately; then draw the map with submit_layout."""
        try:
            header = coerce(WorldHeader, header)
        except (ValidationError, ValueError) as e:
            return {"error": str(e)[:900]}
        o = header.origin_tile
        if o is not None and o.leave_empty:
            return {"error": f"origin_tile must not be left empty: it is the clicked tile {origin.key}"}
        if o is not None and (o.q, o.r) != (origin.q, origin.r):
            header.origin_tile = o = o.model_copy(update={"q": origin.q, "r": origin.r})
        if "header" in state:
            return {"error": "the world is already submitted; now call submit_layout"}
        state["header"] = header
        if on_header is not None:
            on_header(
                WorldPlan(
                    world=header.world,
                    style=header.style,
                    tile_attributes=header.tile_attributes,
                    tiles=[o] if o is not None else [],
                )
            )
        return {"ok": "the origin is being built; now draw the map with submit_layout"}

    def submit_layout(layout: Layout, tool_context: ToolContext) -> dict:
        """Submit the map's layout: regions (shape primitives), landmarks and routes. The engine turns
        it into tiles. Returns an error describing what to fix if it is invalid."""
        header: WorldHeader | None = state.get("header")
        if header is None:
            return {"error": "call submit_world first"}
        try:
            layout = coerce(Layout, layout)
        except (ValidationError, ValueError) as e:
            return {"error": str(e)[:900]}
        vocab = set(header.world.terrain_vocabulary) | set(
            world.spec.terrain_vocabulary if world.spec else []
        )
        conns = set(header.world.connector_vocabulary) | set(
            world.spec.connector_vocabulary if world.spec else []
        )
        bad = sorted({r.biome for r in layout.regions if r.mode == "add" and r.biome not in vocab})
        bad += sorted({lm.biome for lm in layout.landmarks if lm.biome and lm.biome not in vocab})
        if bad:
            return {"error": f"biomes not in terrain_vocabulary: {bad}; use {sorted(vocab)}"}
        bad_c = sorted({rt.connector for rt in layout.routes if rt.connector not in conns})
        if bad_c:
            return {"error": f"route connectors not in connector_vocabulary: {bad_c}; use {sorted(conns)}"}
        if not any(r.mode == "add" for r in layout.regions):
            return {"error": "the layout needs at least one region with mode 'add'"}
        res = rasterize(layout, header)
        if res.compactness < COMPACT_ENOUGH and not state.get("warned_compact"):
            state["warned_compact"] = True  # a nudge, not a rule: the next submission is accepted
            return {
                "error": f"the map is very stretched (compactness {res.compactness:.2f}; a solid hexagon is 1.0, "
                f"aim for {COMPACT_ENOUGH + 0.15:.2f}+): keep an interesting outline but make the overall "
                "silhouette more compact: widen long bands to 3+ tiles, cluster the regions around the "
                "origin, keep length at most about twice the width (thin strands only as short spurs)"
            }
        if res.dropped_over_cap > max(6, max_tiles // 2):
            return {
                "error": f"your shapes cover {len(res.tiles) + res.dropped_over_cap} tiles but the budget is "
                f"{max_tiles}: shrink or remove shapes so the map fits (it would be cut off far from the origin)"
            }
        plan = WorldPlan(
            world=header.world,
            style=header.style,
            tile_attributes=header.tile_attributes,
            tiles=res.tiles,
        )
        return submitted(tool_context, holder, plan=plan, layout=layout, notes=res.notes)

    h = kit.agent(
        name="super_planner",
        role="super",
        instruction=prompts.SUPER_PLAN,
        tools=[submit_world, submit_layout],
        label="plan world",
        q=origin.q,
        r=origin.r,
        holder=holder,
    )
    payload = {
        "task": "world_plan",
        "existing_world": existing_world_payload(world),
        "user_prompt": prompt,
        "origin": {"q": origin.q, "r": origin.r},
        "max_tiles": max_tiles,
        "world_bounds": f"tiles within {world_radius} steps of 0,0",
        "occupied_nearby": [[o.q, o.r] for o in occupied][:400],
        "existing_tiles_nearby": nearby,
    }
    parts = [text_part(payload)]
    if nearby_png:
        parts += [text_part("The existing map next to the new area:"), image_part(nearby_png)]
    res = await h.run(parts, parent, max_calls=11)
    if "plan" not in res:
        raise AgentFailed("planner did not submit a valid plan")
    return res["plan"]


async def review_wave(
    kit: AgentKit,
    *,
    world: World,
    anchor_png: bytes | None,
    composite_png: bytes,
    candidates: list[dict[str, Any]],
    zooms: dict[int, bytes],
    history: list[str],
    parent: Span | None,
) -> WaveReview:
    labels = {c["label"] for c in candidates}
    holder: dict[str, Any] = {}

    zoomed: list[int] = []

    def zoom_candidate(label: int) -> dict:
        """Look at one candidate tile up close (ground + props, enlarged). Max 2 per review."""
        if len(zoomed) >= 2:
            return {"error": "zoom budget used (2 per review): decide from the composite"}
        zoomed.append(label)
        png = zooms.get(label)
        if png is None:
            return {"error": f"no candidate labelled {label}"}
        return {"label": label, "image": image_part(png)}

    def submit_verdicts(verdicts: list[Verdict], tool_context: ToolContext) -> dict:
        """Submit one verdict per candidate label."""
        try:
            verdicts = [coerce(Verdict, v) for v in verdicts]
        except (ValidationError, ValueError) as e:
            return {"error": str(e)[:700]}
        missing = labels - {v.label for v in verdicts}
        if missing:
            return {"error": f"missing verdicts for labels {sorted(missing)}"}
        kept, seen = [], set()
        for v in verdicts:
            if v.label in labels and v.label not in seen:
                seen.add(v.label)
                kept.append(v)
        return submitted(tool_context, holder, review=WaveReview(verdicts=kept))

    h = kit.agent(
        name="super_reviewer",
        role="super",
        instruction=prompts.SUPER_REVIEW,
        tools=[zoom_candidate, submit_verdicts],
        label=f"review {len(candidates)} tiles",
        holder=holder,
    )
    parts = [
        text_part(
            {
                "task": "wave_review",
                "world": world.spec.model_dump() if world.spec else None,
                **(
                    {
                        "up_close": {
                            "scale": world.scale_note,
                            "zoom": world.parent.context.get("scale"),
                            "tiles": {
                                c["label"]: world.parent.notes.get(f"{c['coord']['q']},{c['coord']['r']}", "")
                                for c in candidates
                                if "coord" in c
                            },
                            "rule": "this map is one tile of its parent seen up close: the parent's "
                            "buildings, streets and paths are laid out by the engine at their true size. "
                            "Never ask for more buildings, blocks, streets or a different land use.",
                        }
                    }
                    if world.parent is not None
                    else {}
                ),
                "your_recent_reviews": history[-12:],
                "candidates": candidates,
            }
        )
    ]
    if anchor_png:
        parts += [text_part("ANCHOR (style reference):"), image_part(anchor_png)]
    parts += [text_part("COMPOSITE (candidates outlined + numbered):"), image_part(composite_png)]
    res = await h.run(parts, parent, max_calls=5)
    if "review" not in res:
        raise AgentFailed("review not submitted")
    return res["review"]
