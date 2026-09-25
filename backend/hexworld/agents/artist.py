"""Artist sub-agents: design materials (ground looks) and sprites (props) on demand.

Their output goes into the world's session library (World.materials / World.sprites), so each
terrain or prop kind is designed once per world and reused by every later tile.
"""

from __future__ import annotations

from typing import Any

from hexworld.agents import prompts
from hexworld.agents.llm import ImagePart, LLMGateway, LLMRequest, strict_schema
from hexworld.domain import World
from hexworld.domain.art import MaterialSpec, SpriteProgram
from hexworld.telemetry import Span

MATERIAL_SCHEMA = strict_schema(MaterialSpec)
SPRITE_SCHEMA = strict_schema(SpriteProgram)


def _style_payload(world: World) -> dict[str, Any]:
    assert world.spec is not None and world.style is not None
    return {
        "world": {"title": world.spec.title, "theme": world.spec.theme, "genre": world.spec.genre},
        "style": world.style.model_dump(),
    }


async def design_material(
    gw: LLMGateway, *, world: World, name: str, is_connector: bool, parent: Span | None
) -> MaterialSpec:
    payload = {
        **_style_payload(world),  # stable prefix
        "existing_materials": {
            k: {"base_color": v.base_color, "rank": v.rank} for k, v in world.materials.items()
        },
        "material": name,
        "is_connector": is_connector,
    }
    req = LLMRequest(
        role="artist",
        task="material_design",
        system=prompts.ARTIST_MATERIAL,
        payload=payload,
        schema=MATERIAL_SCHEMA,
    )
    spec, _ = await gw.call(req, MaterialSpec, parent=parent)
    return spec  # type: ignore[return-value]


async def design_sprite(
    gw: LLMGateway,
    *,
    world: World,
    kind: str,
    context: str,
    anchor_png: bytes | None,
    parent: Span | None,
) -> SpriteProgram:
    payload = {
        **_style_payload(world),
        "library": {k: [e.px_w, e.px_h] for k, e in world.sprites.items()},  # sizes for scale consistency
        "tile_px": world.style.tile_px if world.style else 32,
        "kind": kind,
        "context": context,
    }
    images = (
        [ImagePart(anchor_png, label="World anchor tile (match its look):", detail="low")]
        if anchor_png
        else []
    )
    req = LLMRequest(
        role="artist",
        task="sprite_design",
        system=prompts.ARTIST_SPRITE,
        payload=payload,
        schema=SPRITE_SCHEMA,
        images=images,
    )
    program, _ = await gw.call(req, SpriteProgram, parent=parent)
    return program  # type: ignore[return-value]
