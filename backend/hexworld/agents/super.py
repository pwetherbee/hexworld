"""The super agent (board creator), on Google ADK.

- planner: produces the WorldPlan through `submit_plan`; validation errors go back to it.
- anchor picker: looks at candidate renders of the origin and picks the style anchor.
- reviewer: reviews each wave with vision, can zoom into candidates, and can address feedback to
  the tile agent (tile feedback) and to the sprite artist (sprite_feedback).
The director (mid-run management) lives in agents/director.py.
"""

from typing import Any

from google.adk.tools import ToolContext
from pydantic import ValidationError

from hexworld.agents import prompts
from hexworld.agents.kit import AgentKit, coerce, image_part, submitted, text_part
from hexworld.domain import AnchorPick, Verdict, WaveReview, World, WorldPlan
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
) -> WorldPlan:
    allowed = {h.key for h in candidates}
    holder: dict[str, Any] = {}

    def submit_plan(plan: WorldPlan, tool_context: ToolContext) -> dict:
        """Submit the complete WorldPlan. Returns an error describing what to fix if it is invalid."""
        try:
            plan = coerce(WorldPlan, plan)
        except (ValidationError, ValueError) as e:
            return {"error": str(e)[:900]}
        keys = [f"{t.q},{t.r}" for t in plan.tiles]
        bad = [k for k in keys if k not in allowed]
        if bad:
            return {"error": f"tiles outside candidate_coords: {bad[:8]}"}
        if len(set(keys)) != len(keys):
            return {"error": "duplicate tile coordinates"}
        o = next((t for t in plan.tiles if (t.q, t.r) == (origin.q, origin.r)), None)
        if o is None or o.leave_empty:
            return {"error": f"origin {origin.key} must be planned and not left empty"}
        return submitted(tool_context, holder, plan=plan)

    h = kit.agent(
        name="super_planner",
        role="super",
        instruction=prompts.SUPER_PLAN,
        tools=[submit_plan],
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
    res = await h.run(parts, parent, max_calls=6)
    if "plan" not in res:
        raise AgentFailed("planner did not submit a valid plan")
    return res["plan"]


async def pick_anchor(
    kit: AgentKit, *, world: World, intent: str, candidates: list[bytes], parent: Span | None
) -> AnchorPick:
    n = len(candidates)
    holder: dict[str, Any] = {}

    def submit_anchor(best_label: int, reason: str, tool_context: ToolContext) -> dict:
        """Choose the style anchor: the label (1..N) of the best candidate, and why."""
        if not 1 <= best_label <= n:
            return {"error": f"best_label must be in 1..{n}"}
        return submitted(tool_context, holder, pick=AnchorPick(best_label=best_label, reason=reason))

    h = kit.agent(
        name="super_anchor",
        role="super",
        instruction=prompts.SUPER_ANCHOR,
        tools=[submit_anchor],
        label="pick style anchor",
        holder=holder,
    )
    parts = [
        text_part(
            {
                "task": "anchor_pick",
                "world": world.spec.model_dump() if world.spec else None,
                "origin_intent": intent,
                "num_candidates": n,
            }
        )
    ]
    for i, png in enumerate(candidates):
        parts += [text_part(f"Candidate {i + 1}:"), image_part(png)]
    res = await h.run(parts, parent, max_calls=3)
    if "pick" not in res:
        raise AgentFailed("anchor pick not submitted")
    return res["pick"]


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
