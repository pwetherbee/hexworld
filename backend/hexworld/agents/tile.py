"""Tile agent: designs one hex (attributes, edges, art prompt) from a directive + neighbor context."""

from __future__ import annotations

from typing import Any

from hexworld.agents import prompts
from hexworld.agents.llm import ImagePart, LLMGateway, LLMRequest
from hexworld.domain import AttributeDef, Directive, EdgeSpec, TileDesign, World, compile_attribute_schema
from hexworld.telemetry import Span


def tile_design_schema(world: World) -> dict[str, Any]:
    """Per-world structured-output schema, compiled from the super's vocabularies + attributes.

    Numeric bounds are communicated via descriptions and enforced by `normalize_design`
    (clamping) rather than schema keywords, which keeps the schema portable across providers.
    """
    assert world.spec is not None
    terrains = world.spec.terrain_vocabulary
    connectors = world.spec.connector_vocabulary
    attrs = compile_attribute_schema(_described_bounds(world.tile_attributes))
    for p in attrs["properties"].values():
        p.pop("minimum", None)
        p.pop("maximum", None)
    connector_item: dict[str, Any] = (
        {"type": "string", "enum": connectors} if connectors else {"type": "string"}
    )
    edge = {
        "type": "object",
        "properties": {
            "terrain": {"type": "string", "enum": terrains},
            "connectors": {"type": "array", "items": connector_item},
        },
        "required": ["terrain", "connectors"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "biome": {"type": "string", "enum": terrains},
            "summary": {"type": "string"},
            "attributes": attrs,
            "edges": {
                "type": "array",
                "items": edge,
                "description": "Exactly 6 items; index = edge number 0..5.",
            },
            "art_prompt": {"type": "string"},
            "negative_prompt": {"type": "string"},
            "relief": {
                "type": "integer",
                "description": "Visual height of the tile (render only): 0 water/lava/flat, 1 plains, 2 hills/forest, 3 mountains.",
            },
            "props": {
                "type": "array",
                "description": "0-3 sprites standing on the tile (buildings, landmarks, creatures, special trees). "
                "Ambient vegetation/rocks are added automatically from the biome; do not list them.",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "description": "e.g. 'dark castle', 'campfire', 'crystal spire'",
                        },
                        "x": {"type": "number", "description": "-0.6 west .. 0.6 east"},
                        "y": {"type": "number", "description": "-0.6 north .. 0.6 south"},
                        "scale": {"type": "number", "description": "0.6 .. 1.6"},
                    },
                    "required": ["kind", "x", "y", "scale"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "biome",
            "summary",
            "attributes",
            "edges",
            "art_prompt",
            "negative_prompt",
            "relief",
            "props",
        ],
        "additionalProperties": False,
    }


def _described_bounds(attrs: list[AttributeDef]) -> list[AttributeDef]:
    out = []
    for a in attrs:
        if a.type in ("integer", "number") and (a.minimum is not None or a.maximum is not None):
            a = a.model_copy(update={"description": f"{a.description} (range {a.minimum}..{a.maximum})"})
        out.append(a)
    return out


def normalize_design(
    design: TileDesign, world: World, accepted_facing: dict[int, EdgeSpec]
) -> tuple[TileDesign, dict[str, Any]]:
    """Deterministically repair what can be repaired, and report every change (observability).

    - edges facing accepted neighbors are forced to match them exactly (continuity contract)
    - unknown terrains/connectors are coerced to the biome / dropped
    - numeric attributes are clamped; missing attributes get safe defaults
    """
    assert world.spec is not None
    terrains = set(world.spec.terrain_vocabulary)
    connectors = set(world.spec.connector_vocabulary)
    report: dict[str, Any] = {"repaired_edges": [], "coerced": [], "clamped": [], "defaulted": []}

    biome = design.biome if design.biome in terrains else world.spec.terrain_vocabulary[0]
    if biome != design.biome:
        report["coerced"].append(f"biome {design.biome}->{biome}")

    edges: list[EdgeSpec] = []
    for i, e in enumerate(design.edges):
        if i in accepted_facing:
            want = accepted_facing[i]
            if not e.compatible_with(want):
                report["repaired_edges"].append(i)
            edges.append(want.model_copy())
            continue
        terrain = e.terrain if e.terrain in terrains else biome
        if terrain != e.terrain:
            report["coerced"].append(f"edge{i} {e.terrain}->{terrain}")
        conns = sorted({c for c in e.connectors if c in connectors})
        edges.append(EdgeSpec(terrain=terrain, connectors=conns))

    attrs: dict[str, Any] = {}
    for a in world.tile_attributes:
        v = design.attributes.get(a.name)
        if v is None:
            v = _default(a)
            report["defaulted"].append(a.name)
        if a.type in ("integer", "number") and isinstance(v, int | float) and not isinstance(v, bool):
            lo = a.minimum if a.minimum is not None else v
            hi = a.maximum if a.maximum is not None else v
            c = min(max(v, lo), hi)
            c = int(round(c)) if a.type == "integer" else float(c)
            if c != v:
                report["clamped"].append(a.name)
            v = c
        elif a.type == "enum" and v not in a.enum_values:
            report["coerced"].append(f"{a.name} {v}->{a.enum_values[0]}")
            v = a.enum_values[0]
        elif a.type == "enum_list":
            v = [x for x in (v or []) if x in a.enum_values]
        attrs[a.name] = v

    props = [
        p.model_copy(
            update={
                "x": min(0.6, max(-0.6, p.x)),
                "y": min(0.6, max(-0.6, p.y)),
                "scale": min(1.6, max(0.6, p.scale)),
            }
        )
        for p in design.props[:3]
        if p.kind.strip()
    ]
    relief = min(3, max(0, design.relief))
    fixed = design.model_copy(
        update={"biome": biome, "edges": edges, "attributes": attrs, "props": props, "relief": relief}
    )
    return fixed, report


def _default(a: AttributeDef) -> Any:
    if a.type == "enum":
        return a.enum_values[0]
    if a.type == "enum_list":
        return []
    if a.type == "boolean":
        return True
    if a.type in ("integer", "number"):
        return a.minimum if a.minimum is not None else 0
    return ""


async def design_tile(
    gw: LLMGateway,
    *,
    world: World,
    directive: Directive,
    neighbors: list[dict[str, Any]],
    schema: dict[str, Any],
    context_png: bytes | None,
    anchor_png: bytes | None,
    parent: Span | None,
    sprite_library: list[str] | None = None,
) -> TileDesign:
    assert world.spec is not None and world.style is not None
    payload = {
        # stable, world-level prefix (identical across all tile calls in a world)
        "world": world.spec.model_dump(),
        "style": world.style.model_dump(exclude={"palette"}),
        "attributes": [a.model_dump() for a in world.tile_attributes],
        # per-tile
        "directive": directive.model_dump(mode="json"),
        "neighbors": neighbors,
        "sprite_library": sprite_library or [],
    }
    images: list[ImagePart] = []
    if anchor_png:
        images.append(ImagePart(anchor_png, label="World anchor tile (style reference):", detail="low"))
    if context_png:
        images.append(
            ImagePart(
                context_png,
                label="Map around your tile (your slot is the dark hex in the center):",
                detail="low",
            )
        )
    req = LLMRequest(
        role="tile",
        task="tile_design",
        system=prompts.TILE_DESIGN,
        payload=payload,
        schema=schema,
        images=images,
    )
    design, _ = await gw.call(req, TileDesign, parent=parent)
    return design  # type: ignore[return-value]
