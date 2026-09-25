"""The super agent (board creator): plans the world, picks the anchor, reviews waves."""

from __future__ import annotations

from typing import Any

from hexworld.agents import prompts
from hexworld.agents.llm import ImagePart, LLMGateway, LLMRequest, strict_schema
from hexworld.domain import AnchorPick, WaveReview, World, WorldPlan
from hexworld.hex import Hex
from hexworld.telemetry import Span

PLAN_SCHEMA = strict_schema(WorldPlan)
REVIEW_SCHEMA = strict_schema(WaveReview)
ANCHOR_SCHEMA = strict_schema(AnchorPick)


def existing_world_payload(world: World) -> dict[str, Any] | None:
    if world.spec is None or world.style is None:
        return None
    return {
        "world": world.spec.model_dump(),
        "style": world.style.model_dump(),
        "tile_attributes": [a.model_dump() for a in world.tile_attributes],
    }


async def plan_world(
    gw: LLMGateway,
    *,
    world: World,
    prompt: str,
    origin: Hex,
    candidates: list[Hex],
    nearby: list[dict[str, Any]],
    parent: Span | None,
) -> WorldPlan:
    allowed = {h.key for h in candidates}

    def validate(plan: WorldPlan) -> None:
        keys = [f"{t.q},{t.r}" for t in plan.tiles]
        bad = [k for k in keys if k not in allowed]
        if bad:
            raise ValueError(f"tiles outside candidate_coords: {bad[:8]}")
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate tile coordinates")
        origin_tile = next((t for t in plan.tiles if (t.q, t.r) == (origin.q, origin.r)), None)
        if origin_tile is None or origin_tile.leave_empty:
            raise ValueError(f"origin {origin.key} must be planned and not left empty")

    payload = {
        # stable prefix first (improves provider prompt-cache hit rate across calls)
        "existing_world": existing_world_payload(world),
        "user_prompt": prompt,
        "origin": {"q": origin.q, "r": origin.r},
        "candidate_coords": [{"q": h.q, "r": h.r, "ring": h.distance(origin)} for h in candidates],
        "existing_tiles_nearby": nearby,
    }
    req = LLMRequest(
        role="super", task="world_plan", system=prompts.SUPER_PLAN, payload=payload, schema=PLAN_SCHEMA
    )
    plan, _ = await gw.call(req, WorldPlan, parent=parent, validate=validate)
    return plan  # type: ignore[return-value]


async def pick_anchor(
    gw: LLMGateway,
    *,
    world: World,
    intent: str,
    candidates: list[bytes],
    parent: Span | None,
) -> AnchorPick:
    n = len(candidates)

    def validate(p: AnchorPick) -> None:
        if not 1 <= p.best_label <= n:
            raise ValueError(f"best_label must be in 1..{n}")

    payload = {
        "world": world.spec.model_dump() if world.spec else None,
        "style": world.style.model_dump() if world.style else None,
        "origin_intent": intent,
        "num_candidates": n,
    }
    images = [ImagePart(png, label=f"Candidate {i + 1}", detail="low") for i, png in enumerate(candidates)]
    req = LLMRequest(
        role="super",
        task="anchor_pick",
        system=prompts.SUPER_ANCHOR,
        payload=payload,
        schema=ANCHOR_SCHEMA,
        images=images,
    )
    pick, _ = await gw.call(req, AnchorPick, parent=parent, validate=validate)
    return pick  # type: ignore[return-value]


async def review_wave(
    gw: LLMGateway,
    *,
    world: World,
    anchor_png: bytes | None,
    composite_png: bytes,
    candidates: list[dict[str, Any]],
    parent: Span | None,
) -> WaveReview:
    labels = {c["label"] for c in candidates}

    def validate(rv: WaveReview) -> None:
        got = [v.label for v in rv.verdicts]
        missing = labels - set(got)
        if missing:
            raise ValueError(f"missing verdicts for labels {sorted(missing)}")

    payload = {
        "world": world.spec.model_dump() if world.spec else None,
        "style": world.style.model_dump() if world.style else None,
        "candidates": candidates,
    }
    images = []
    if anchor_png:
        images.append(ImagePart(anchor_png, label="ANCHOR (style reference):", detail="low"))
    images.append(
        ImagePart(composite_png, label="COMPOSITE (candidates outlined + numbered):", detail="high")
    )
    req = LLMRequest(
        role="super",
        task="wave_review",
        system=prompts.SUPER_REVIEW,
        payload=payload,
        schema=REVIEW_SCHEMA,
        images=images,
    )
    review, _ = await gw.call(req, WaveReview, parent=parent, validate=validate)
    # Drop verdicts for unknown labels / duplicates (keep the first per label).
    kept, seen = [], set()
    for v in review.verdicts:  # type: ignore[union-attr]
        if v.label in labels and v.label not in seen:
            seen.add(v.label)
            kept.append(v)
    review.verdicts = kept  # type: ignore[union-attr]
    return review  # type: ignore[return-value]
