"""The super agent (board creator), on Google ADK.

- planner: `submit_world` (header + origin tile, which starts building at once), then
  `submit_tiles`; validation errors go back to it.
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
from hexworld.domain import PlannedTile, Verdict, WaveReview, World, WorldHeader, WorldPlan
from hexworld.hex import Hex
from hexworld.telemetry import Span


class AgentFailed(Exception):
    pass


def existing_world_payload(world: World) -> dict[str, Any] | None:
    if world.spec is None or world.style is None:
        return None
    return {
        "world": world.spec.model_dump(),
        "style": world.style.model_dump(),
        "tile_attributes": [a.model_dump() for a in world.tile_attributes],
    }


async def plan_world(
    kit: AgentKit,
    *,
    world: World,
    prompt: str,
    origin: Hex,
    candidates: list[Hex],
    nearby: list[dict[str, Any]],
    nearby_png: bytes | None,
    parent: Span | None,
    on_header: Callable[[WorldPlan], None] | None = None,
) -> WorldPlan:
    """Two submissions: `submit_world` (world, style, attributes, origin tile) lets the build start
    at the origin while the planner writes the rest; `submit_tiles` completes the plan."""
    allowed = {h.key for h in candidates}
    holder: dict[str, Any] = {}
    state: dict[str, Any] = {}

    def submit_world(header: WorldHeader) -> dict:
        """Submit the world spec, style, tile attributes and the ORIGIN tile's plan. The origin
        starts building immediately; then submit every other tile with submit_tiles."""
        try:
            header = coerce(WorldHeader, header)
        except (ValidationError, ValueError) as e:
            return {"error": str(e)[:900]}
        o = header.origin_tile
        if (o.q, o.r) != (origin.q, origin.r) or o.leave_empty:
            return {"error": f"origin_tile must be the origin {origin.key} and not left empty"}
        if "header" in state:
            return {"error": "the world is already submitted; now call submit_tiles"}
        state["header"] = header
        if on_header is not None:
            on_header(
                WorldPlan(
                    world=header.world,
                    style=header.style,
                    tile_attributes=header.tile_attributes,
                    tiles=[header.origin_tile],
                )
            )
        return {"ok": "the origin is being built; now call submit_tiles with every other tile"}

    def submit_tiles(tiles: list[PlannedTile], tool_context: ToolContext) -> dict:
        """Submit the plan for every other tile (the origin may be omitted). Returns an error
        describing what to fix if it is invalid."""
        header: WorldHeader | None = state.get("header")
        if header is None:
            return {"error": "call submit_world first"}
        try:
            tiles = [coerce(PlannedTile, t) for t in tiles]
        except (ValidationError, ValueError) as e:
            return {"error": str(e)[:900]}
        tiles = [t for t in tiles if (t.q, t.r) != (origin.q, origin.r)]
        keys = [f"{t.q},{t.r}" for t in tiles]
        bad = [k for k in keys if k not in allowed]
        if bad:
            return {"error": f"tiles outside candidate_coords: {bad[:8]}"}
        if len(set(keys)) != len(keys):
            return {"error": "duplicate tile coordinates"}
        plan = WorldPlan(
            world=header.world,
            style=header.style,
            tile_attributes=header.tile_attributes,
            tiles=[header.origin_tile, *tiles],
        )
        return submitted(tool_context, holder, plan=plan)

    h = kit.agent(
        name="super_planner",
        role="super",
        instruction=prompts.SUPER_PLAN,
        tools=[submit_world, submit_tiles],
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
        "candidate_coords": [{"q": c.q, "r": c.r, "ring": c.distance(origin)} for c in candidates],
        "existing_tiles_nearby": nearby,
    }
    parts = [text_part(payload)]
    if nearby_png:
        parts += [text_part("The existing map next to the new area:"), image_part(nearby_png)]
    res = await h.run(parts, parent, max_calls=8)
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
