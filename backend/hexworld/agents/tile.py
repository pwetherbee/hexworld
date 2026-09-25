"""Tile agent (Google ADK): designs one hex tile, with tools, in a session that persists across
attempts, so the super's feedback continues the same conversation."""

import inspect
from typing import Any, Literal

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field, ValidationError, create_model

from hexworld.agents import prompts
from hexworld.agents.kit import AgentHandle, AgentKit, image_part, submitted, text_part
from hexworld.domain import AttributeDef, Directive, EdgeSpec, PropSpec, TileDesign, World
from hexworld.telemetry import Span


def design_model(world: World) -> type[BaseModel]:
    """Per-world submission schema: terrains/connectors/attribute enums become real enums, so the
    model sees exactly what is allowed (the super defined these for this world)."""
    assert world.spec is not None
    terr = Literal[tuple(world.spec.terrain_vocabulary)]  # type: ignore[valid-type]
    conn = Literal[tuple(world.spec.connector_vocabulary)] if world.spec.connector_vocabulary else str  # type: ignore[valid-type]
    edge = create_model("Edge", terrain=(terr, ...), connectors=(list[conn], Field(default_factory=list)))
    fields: dict[str, Any] = {}
    for a in _described_bounds(world.tile_attributes):
        if a.type == "enum":
            t: Any = Literal[tuple(a.enum_values)]
        elif a.type == "enum_list":
            t = list[Literal[tuple(a.enum_values)]]
        else:
            t = {"integer": int, "number": float, "boolean": bool, "string": str}[a.type]
        fields[a.name] = (t, Field(description=a.description))
    attrs = create_model("Attributes", **fields)
    return create_model(
        "TileDesignSubmission",
        biome=(terr, Field(description="dominant terrain")),
        summary=(str, Field(description="one short sentence for the map inspector")),
        attributes=(attrs, ...),
        edges=(list[edge], Field(description="exactly 6, index = edge number (0 E,1 NE,2 NW,3 W,4 SW,5 SE)")),
        art_prompt=(str, Field(description="1-3 sentences, GROUND only, top-down")),
        negative_prompt=(str, ""),
        relief=(int, Field(description="0 liquid/flat .. 3 mountainous (render height)")),
        props=(
            list[PropSpec],
            Field(default_factory=list, description="0 or 1 landmark (the directive's feature)"),
        ),
    )


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


class TileAgent:
    """One agent per tile per run. Tools: view_surroundings, list_library, request_prop, submit_design."""

    def __init__(self, kit: AgentKit, *, world: World, directive: Directive, api: Any):
        self.world = world
        self.directive = directive
        self.api = api  # RunExecutor facade: surroundings(), library(), commission_sprite()
        self.holder: dict[str, Any] = {}
        c = directive.coord
        submission = design_model(world)

        def view_surroundings() -> dict:
            """See the map around your tile (your slot is the dark centre hex) plus neighbour details."""
            info, png = api.surroundings(c.q, c.r)
            out: dict[str, Any] = {"neighbors": info}
            if png:
                out["map"] = image_part(png)
            return out

        def list_library() -> dict:
            """Sprites and materials already designed for this world (reuse sprite kinds by exact name)."""
            return api.library()

        async def request_prop(kind: str, brief: str) -> dict:
            """Commission a landmark sprite from the sprite artist (or reuse it if the library has it).
            Returns the sprite's preview so you can decide whether to use it."""
            entry, png = await api.commission_sprite(kind, brief, c.q, c.r)
            if entry is None:
                return {
                    "error": "the sprite artist could not produce it; continue without, or try another kind"
                }
            out: dict[str, Any] = {"kind": entry.kind, "size_px": [entry.px_w, entry.px_h]}
            if png:
                out["preview"] = image_part(png)
            return out

        def submit_design(design: Any, tool_context: ToolContext) -> dict:
            """Submit your tile design."""
            try:
                d = TileDesign.model_validate(
                    design.model_dump() if hasattr(design, "model_dump") else design
                )
            except ValidationError as e:
                return {"error": str(e)[:700]}
            return submitted(tool_context, self.holder, design=d)

        submit_design.__signature__ = inspect.Signature(
            [  # type: ignore[attr-defined]
                inspect.Parameter("design", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=submission),
                inspect.Parameter(
                    "tool_context", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=ToolContext
                ),
            ]
        )
        submit_design.__annotations__ = {"design": submission, "tool_context": ToolContext, "return": dict}

        self.handle: AgentHandle = kit.agent(
            name="tile_agent",
            role="tile",
            instruction=prompts.TILE_DESIGN,
            tools=[view_surroundings, list_library, request_prop, submit_design],
            label=f"tile {c.q},{c.r}",
            q=c.q,
            r=c.r,
            holder=self.holder,
        )

    async def design(
        self,
        *,
        neighbors: list[dict[str, Any]],
        context_png: bytes | None,
        anchor_png: bytes | None,
        parent: Span | None,
    ) -> TileDesign | None:
        w = self.world
        assert w.spec is not None and w.style is not None
        payload = {
            "task": "tile_design",
            "world": w.spec.model_dump(),
            "style": w.style.model_dump(exclude={"palette"}),
            "attributes": [a.model_dump() for a in w.tile_attributes],
            "directive": self.directive.model_dump(mode="json"),
            "neighbors": neighbors,
            "sprite_library": sorted(w.sprites),
        }
        parts = [text_part(payload)]
        if anchor_png:
            parts += [text_part("World anchor tile (style reference):"), image_part(anchor_png)]
        if context_png:
            parts += [
                text_part("Map around your tile (your slot is the dark centre hex):"),
                image_part(context_png),
            ]
        res = await self.handle.run(parts, parent, max_calls=6)
        return res.get("design")

    async def revise(self, feedback: str, *, parent: Span | None) -> TileDesign | None:
        """Agent-to-agent feedback: the reviewer's note continues this tile agent's session."""
        msg = (
            f"The super agent rejected your tile: {feedback}\n"
            "Revise the design to address this and submit it again with submit_design."
        )
        res = await self.handle.run([text_part(msg)], parent, max_calls=5)
        return res.get("design")
