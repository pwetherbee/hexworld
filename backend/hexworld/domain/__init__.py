"""Domain models shared by agents, orchestrator, store and API.

Everything an LLM produces goes through one of these models (or a schema compiled
from them), so malformed output is caught at the boundary, never deep in the scheduler.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from hexworld.domain.art import MaterialSpec, SpriteEntry
from hexworld.hex import Hex

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class TileStatus(StrEnum):
    empty = "empty"
    planned = "planned"
    intentionally_empty = "intentionally_empty"
    generating = "generating"
    reviewing = "reviewing"
    accepted = "accepted"
    failed = "failed"


class RunStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Coord(BaseModel):
    q: int
    r: int

    @property
    def hex(self) -> Hex:
        return Hex(self.q, self.r)

    @property
    def key(self) -> str:
        return f"{self.q},{self.r}"

    @classmethod
    def of(cls, h: Hex) -> Coord:
        return cls(q=h.q, r=h.r)


# --------------------------------------------------------------------------- style / world


TILE_PX_CHOICES = (32, 48, 64, 96, 128)


class StyleGuide(BaseModel):
    """Shared visual contract for every tile in a world. Set once, then reused."""

    palette: list[str] = Field(
        description="Master palette, 12-32 '#rrggbb' colors. Every tile pixel maps to one."
    )
    tile_px: int = Field(
        description="Tile ground resolution in pixels (set by the engine from the run options)."
    )
    view: str = Field(description="Camera description, e.g. 'top-down orthographic'.")
    light_direction: str = Field(description="e.g. 'from the top-left'.")
    outline: str = Field(description="Outline rule, e.g. 'no outlines' or '1px dark outline on props'.")
    style_keywords: str = Field(description="Short art-direction keywords appended to every image prompt.")

    @field_validator("palette")
    @classmethod
    def _palette(cls, v: list[str]) -> list[str]:
        cleaned = []
        for c in v:
            if not HEX_COLOR.match(c):
                raise ValueError(f"bad palette color {c!r}")
            if c.lower() not in cleaned:
                cleaned.append(c.lower())
        if len(cleaned) < 4:
            raise ValueError("palette needs at least 4 distinct colors")
        cleaned = cleaned[:128]  # grows as the session library adds materials
        return cleaned

    @field_validator("tile_px")
    @classmethod
    def _tile_px(cls, v: int) -> int:
        # Snap to a supported size rather than failing a whole plan on it.
        return min(TILE_PX_CHOICES, key=lambda s: abs(s - v))


class WorldSpec(BaseModel):
    title: str
    genre: str = Field(description="e.g. 'adventure', 'board game with cards', 'turn-based tactics'.")
    theme: str
    lore: str = Field(description="2-4 sentences.")
    terrain_vocabulary: list[str] = Field(
        description="Allowed edge/biome terrain names (snake_case), e.g. grass, water, sand, rock, snow."
    )
    connector_vocabulary: list[str] = Field(
        description="Allowed linear features that cross tile edges (snake_case), e.g. road, river, wall."
    )
    directional_notes: str = Field(
        description="General layout direction, e.g. 'mountains north, coast east'."
    )
    prop_scale: float = Field(
        default=1.0,
        description="Size of every sprite relative to the tile, world-wide (0.3-1.5): 1 when a tile is a "
        "landscape chunk or a room, ~0.5 when a tile is a city block (people and cars next to real "
        "buildings), up to 1.3 for close-up interiors or board-game spaces.",
    )

    @field_validator("prop_scale")
    @classmethod
    def _prop_scale(cls, v: float) -> float:
        return min(1.5, max(0.3, float(v or 1.0)))

    @field_validator("terrain_vocabulary", "connector_vocabulary")
    @classmethod
    def _vocab(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for name in v:
            n = re.sub(r"[^a-z0-9_]", "_", name.strip().lower()).strip("_")[:32]
            if n and n not in out:
                out.append(n)
        return out

    @model_validator(mode="after")
    def _nonempty(self) -> WorldSpec:
        if not self.terrain_vocabulary:
            raise ValueError("terrain_vocabulary must not be empty")
        return self


# --------------------------------------------------------------------------- tile schema (meta-schema)


class AttributeDef(BaseModel):
    """One attribute tile agents may set. The super defines these; we compile them to JSON Schema.

    This *is* the restricted meta-schema: the super can't emit arbitrary JSON Schema, only
    typed, bounded attributes, so the compiled schema is always valid for strict structured
    output and for jsonschema validation.
    """

    name: str = Field(description="snake_case identifier")
    type: Literal["enum", "enum_list", "integer", "number", "boolean", "string"]
    description: str
    enum_values: list[str] = Field(description="Allowed values for enum / enum_list types; empty otherwise.")
    minimum: float | None = Field(description="Lower bound for integer/number; null otherwise.")
    maximum: float | None = Field(description="Upper bound for integer/number; null otherwise.")

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = re.sub(r"[^a-z0-9_]", "_", v.strip().lower())
        if not NAME.match(v):
            raise ValueError(f"bad attribute name {v!r}")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> AttributeDef:
        if self.type in ("enum", "enum_list") and not self.enum_values:
            raise ValueError(f"attribute {self.name}: enum types need enum_values")
        if self.type in ("integer", "number"):
            if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
                raise ValueError(f"attribute {self.name}: minimum > maximum")
        return self


RESERVED_ATTRIBUTES = {"biome", "summary"}


def compile_attribute_schema(attrs: list[AttributeDef]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for a in attrs:
        if a.name in RESERVED_ATTRIBUTES:
            continue
        p: dict[str, Any]
        if a.type == "enum":
            p = {"type": "string", "enum": a.enum_values}
        elif a.type == "enum_list":
            p = {"type": "array", "items": {"type": "string", "enum": a.enum_values}}
        elif a.type in ("integer", "number"):
            p = {"type": a.type}
            if a.minimum is not None:
                p["minimum"] = int(a.minimum) if a.type == "integer" else a.minimum
            if a.maximum is not None:
                p["maximum"] = int(a.maximum) if a.type == "integer" else a.maximum
        elif a.type == "boolean":
            p = {"type": "boolean"}
        else:
            p = {"type": "string"}
        p["description"] = a.description
        props[a.name] = p
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


# --------------------------------------------------------------------------- plan


class EdgeSpec(BaseModel):
    terrain: str = Field(description="Terrain along this edge; one of the world's terrain_vocabulary.")
    connectors: list[str] = Field(
        description="Connectors crossing this edge (subset of connector_vocabulary)."
    )

    def compatible_with(self, other: EdgeSpec) -> bool:
        return self.terrain == other.terrain and sorted(self.connectors) == sorted(other.connectors)


class EdgeHint(BaseModel):
    edge: int = Field(description="Edge index 0..5 (0 E, 1 NE, 2 NW, 3 W, 4 SW, 5 SE).")
    terrain: str
    connectors: list[str]


class CopySpec(BaseModel):
    """Lets the super reuse a tile instead of generating a new one (cheap filler: open sea, plain
    desert...). The source must be a non-copy tile in this plan or an accepted tile in the world.

    - shallow: a linked instance. The copy shares the prototype's art and data, and stays in sync if
      the prototype changes later.
    - deep: an independent snapshot. The copy gets its own record at copy time and never changes
      when the prototype does. `copy_of` is kept only as provenance.
    """

    mode: Literal["none", "shallow", "deep"] = Field(description="'none' = generate this tile normally.")
    source_q: int = Field(description="Prototype tile q (ignored when mode is 'none').")
    source_r: int = Field(description="Prototype tile r (ignored when mode is 'none').")

    @property
    def source(self) -> Hex:
        return Hex(self.source_q, self.source_r)


NO_COPY = CopySpec(mode="none", source_q=0, source_r=0)


class PlannedTile(BaseModel):
    q: int
    r: int
    # optional fields have defaults: a model that omits one must not cost a failed tool call
    leave_empty: bool = Field(default=False, description="True to deliberately leave this slot empty.")
    biome: str = Field(description="Dominant terrain, from terrain_vocabulary.")
    intent: str = Field(description="One sentence: what this tile is and its role in the world.")
    features: list[str] = Field(
        default_factory=list, description="Notable features/props, e.g. 'ruined tower', 'pine trees'."
    )
    edge_hints: list[EdgeHint] = Field(
        default_factory=list, description="Edge constraints the super wants (may be partial)."
    )
    priority: int = Field(default=3, description="1 (low) .. 5 (high); higher is generated earlier.")
    duplicate: CopySpec = Field(
        default_factory=lambda: CopySpec(mode="none", source_q=0, source_r=0),
        description="Copy another tile instead of generating (mode 'none' to generate).",
    )

    @property
    def hex(self) -> Hex:
        return Hex(self.q, self.r)


class WorldPlan(BaseModel):
    world: WorldSpec
    style: StyleGuide
    tile_attributes: list[AttributeDef]
    tiles: list[PlannedTile]


# --------------------------------------------------------------------------- layout DSL
# The planner describes the map's SHAPE with regions made of shape primitives, plus landmarks and
# connector routes; the engine rasterizes it into tiles (orchestrator/layout.py). This lets the super
# draw long coasts, archipelagos, patchwork districts or floor plans at any size, cheaply.


class ShapeSpec(BaseModel):
    kind: Literal["hex", "blob", "path", "rect"] = Field(
        description="hex: all tiles within `radius` of center. blob: an organic, irregular patch of about "
        "`radius` around center (`roughness` 0 = round .. 1 = ragged). path: a band through `points` "
        "(>= 2 waypoints), `width` tiles wide: ridges, coasts, corridors, streets, long valleys. rect: "
        "`w` columns x `h` rows around center: districts, city blocks, rooms and halls."
    )
    center: Coord | None = None
    radius: int = Field(default=2, ge=0, le=14)
    roughness: float = Field(default=0.4, ge=0, le=1)
    points: list[Coord] = Field(default_factory=list)
    width: int = Field(default=1, ge=1, le=5)
    w: int = Field(default=3, ge=1, le=24)
    h: int = Field(default=3, ge=1, le=24)


class Region(BaseModel):
    name: str
    biome: str = Field(description="From terrain_vocabulary.")
    intent: str = Field(description="What this region is (<= 12 words); becomes each tile's intent.")
    shapes: list[ShapeSpec] = Field(description="Union of shapes; later regions paint over earlier ones.")
    mode: Literal["add", "void"] = Field(
        default="add", description="'void' carves these tiles out (gaps, bays, courtyards, chasms)."
    )
    features: list[str] = Field(
        default_factory=list, description="Sprite kinds scattered over the region's tiles."
    )
    feature_density: float = Field(
        default=0.3, ge=0, le=1, description="Share of the region's tiles that get a feature (dense = 1-2)."
    )
    priority: int = Field(default=3, ge=1, le=5)
    fill: Literal["generate", "shallow_copy", "deep_copy"] = Field(
        default="generate",
        description="Filler regions (open sea, plain desert) may copy one prototype tile to save cost.",
    )


class Landmark(BaseModel):
    q: int
    r: int
    intent: str
    features: list[str] = Field(default_factory=list)
    biome: str | None = Field(default=None, description="Override the region's biome here.")


class Route(BaseModel):
    connector: str = Field(description="From connector_vocabulary (river, road, corridor...).")
    points: list[Coord] = Field(description=">= 2 waypoints; the route runs tile to tile between them.")


class Layout(BaseModel):
    regions: list[Region]
    landmarks: list[Landmark] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)


class WorldHeader(BaseModel):
    """First half of a plan: enough to start building the origin while the rest is planned."""

    world: WorldSpec
    style: StyleGuide
    tile_attributes: list[AttributeDef]
    origin_tile: PlannedTile | None = Field(
        default=None,
        description="The origin tile's plan (it starts building right away). If omitted, the origin "
        "waits for the layout and takes its region's terrain.",
    )


class Directive(BaseModel):
    """What the super asks of one tile agent (derived from a PlannedTile, plus retry feedback)."""

    coord: Coord
    biome: str
    intent: str
    features: list[str]
    edge_hints: list[EdgeHint]
    feedback: list[str] = Field(default_factory=list)
    simplified: bool = False
    duplicate: CopySpec | None = None


# --------------------------------------------------------------------------- tile agent output


class PropSpec(BaseModel):
    """A sprite standing on the tile (tree, castle, campfire...). Rendered as its own layer."""

    kind: str = Field(description="What it is, e.g. 'castle', 'pine tree', 'campfire', 'dark obelisk'.")
    x: float = Field(description="-0.6 (west) .. 0.6 (east), tile-local.")
    y: float = Field(description="-0.6 (north) .. 0.6 (south), tile-local.")
    scale: float = Field(description="0.6 .. 1.6 relative size.")


class TileDesign(BaseModel):
    biome: str
    summary: str
    attributes: dict[str, Any]
    edges: list[EdgeSpec]
    art_prompt: str
    negative_prompt: str
    relief: int = 1  # visual only: 0 flat/liquid .. 3 mountainous (prism height), not a game attribute
    props: list[PropSpec] = Field(default_factory=list)

    @field_validator("edges")
    @classmethod
    def _six(cls, v: list[EdgeSpec]) -> list[EdgeSpec]:
        if len(v) != 6:
            raise ValueError("exactly 6 edges required")
        return v


class Scores(BaseModel):
    style: int = Field(description="1-5 consistency with the style guide and anchor tile")
    fidelity: int = Field(description="1-5 visual quality / readability")
    edge_continuity: int = Field(description="1-5 how well edges continue into accepted neighbors")
    directive_fit: int = Field(description="1-5 how well it matches its directive")


class Verdict(BaseModel):
    label: int = Field(description="The number drawn on the candidate in the composite image.")
    accept: bool
    scores: Scores
    feedback: str = Field(description="If rejected: concrete, actionable fix for the tile agent. Else ''.")
    sprite_feedback: str = Field(
        default="",
        description="If the landmark sprite itself needs work: an instruction for the sprite artist. Else ''.",
    )
    material_feedback: str = Field(
        default="",
        description="If a terrain's shared ground pattern looks wrong: '<material name>: instruction' for "
        "the material artist (repaints every tile using it). Else ''.",
    )


class WaveReview(BaseModel):
    verdicts: list[Verdict]


class AnchorPick(BaseModel):
    best_label: int
    reason: str


# --------------------------------------------------------------------------- persisted entities


class TileLayer(BaseModel):
    """One visual layer of a tile. The ground layer is the seamless top-face texture. Sprite layers
    stand on it as upright billboards: side-view pixel art, optionally a horizontal strip of animation
    frames, plus a procedural motion the renderer applies."""

    kind: Literal["ground", "height", "facade", "sprite"]
    asset_id: str
    label: str = ""
    x: float = 0.0  # tile-local, in hex circumradius units (east +)
    y: float = 0.0  # (south +)
    width: float = 1.0  # world width in hex circumradius units
    px_w: int = 0  # one frame's pixel size
    px_h: int = 0
    frames: int = 1
    fps: float = 0.0
    motion: Literal["none", "sway", "bob", "flicker", "pulse"] = "none"
    # sprites: who put it there. landmark/prop = the tile agent's props; scatter = the biome
    # material's ambient scatter (owned by the material artist)
    role: Literal["landmark", "prop", "scatter"] | None = None


class Tile(BaseModel):
    q: int
    r: int
    status: TileStatus = TileStatus.empty
    run_id: str | None = None
    biome: str | None = None
    summary: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    edges: list[EdgeSpec] | None = None
    asset_id: str | None = None  # flattened preview (ground + sprites), used for thumbnails/review
    ground_asset_id: str | None = None  # seamless ground layer: seams, inpainting context
    layers: list[TileLayer] = Field(default_factory=list)
    relief: int = 1
    preview_asset_id: str | None = None  # candidate under review (shown ghosted in the UI)
    side_color: str | None = None
    art_prompt: str | None = None  # kept so neighbors' tile agents can continue this tile's visuals
    copy_of: Coord | None = None
    copy_mode: Literal["shallow", "deep"] | None = None
    attempts: int = 0
    directive: Directive | None = None
    visibility: Literal["visible", "fogged", "hidden"] = "visible"  # reserved for fog of war

    @property
    def hex(self) -> Hex:
        return Hex(self.q, self.r)

    @property
    def key(self) -> str:
        return f"{self.q},{self.r}"


class ParentLink(BaseModel):
    """A drilled layer: this world is the inside of one tile of its parent world."""

    world_id: str
    q: int
    r: int
    context: dict[str, Any] = Field(default_factory=dict)  # the parent tile as the planner sees it
    # "q,r" -> terrain: the parent tile's own map zoomed up to this layer (its streets, water, blocks
    # land where they are on the parent); the layout follows it, so the region IS the tile up close
    guide: dict[str, str] = Field(default_factory=dict)
    # the parent's streets traced tile by tile (straight connectors through the tiles they cross)
    routes: list[Route] = Field(default_factory=list)


class SceneLayer(BaseModel):
    role: Literal["backdrop", "foreground"]
    asset_id: str
    px_w: int
    px_h: int


class SkirtTile(BaseModel):
    """Ground just outside a region, continuing its rim terrain so the region blends into its
    surroundings (rendered by the engine alone, never planned or reviewed)."""

    q: int
    r: int
    ring: int  # 1 = right outside the rim
    biome: str
    asset_id: str


class Scene(BaseModel):
    """A tile seen up close: a layered, animated pixel-art picture of the spot."""

    world_id: str
    q: int
    r: int
    title: str
    caption: str
    layers: list[SceneLayer]
    fx: list[str] = Field(default_factory=list)  # ambient effects the viewer animates (water, leaves, ...)
    created_at: float
    version: int = 1  # scenes painted by an older recipe are repainted on request


class World(BaseModel):
    id: str
    name: str
    radius: int
    created_at: float
    parent: ParentLink | None = None  # set for drilled layers
    depth: int = 0  # 0 = the overworld
    scale_note: str = ""  # what one tile is at this depth (for planners and artists)
    region_radius: int = Field(
        default=3, ge=2, le=6, description="Radius of the region grid inside each tile (set at creation)."
    )
    spec: WorldSpec | None = None
    style: StyleGuide | None = None
    tile_attributes: list[AttributeDef] = Field(default_factory=list)
    anchor_asset_ids: list[str] = Field(default_factory=list)
    # Session library, filled on demand by the material/sprite sub-agents and reused by later tiles.
    materials: dict[str, MaterialSpec] = Field(default_factory=dict)
    sprites: dict[str, SpriteEntry] = Field(default_factory=dict)


class RunOptions(BaseModel):
    max_tiles: int = Field(
        default=40, ge=1, le=250, description="Upper bound on tiles the super may plan (it picks the shape)."
    )
    radius: int | None = Field(
        default=None, ge=0, le=9, description="Deprecated: a hexagon of this radius' worth of tiles."
    )
    tile_px: int | None = Field(
        default=None,
        description="Ground texture resolution per tile (32-128px). Only for a new world: all tiles of a "
        "world share one pixel grid, so extensions keep the world's resolution.",
    )
    region_radius: int | None = Field(
        default=None,
        ge=2,
        le=6,
        description="Only for a new world: radius of the region grid you find when entering a tile (then locked).",
    )
    fill_radius: bool = Field(
        default=False, description="Plan every tile within the world radius (drilled layers fill their hex)."
    )
    max_attempts: int = Field(default=3, ge=1, le=6)
    review_batch: int = Field(default=12, ge=1, le=16)
    max_llm_calls: int = Field(default=1500, ge=1)
    max_cost_usd: float = Field(default=2.0, gt=0)
    max_seconds: float = Field(default=2400, gt=0)

    @model_validator(mode="after")
    def _radius_to_tiles(self) -> RunOptions:
        if self.radius is not None and "max_tiles" not in self.model_fields_set:
            self.max_tiles = 3 * self.radius * (self.radius + 1) + 1
        return self


class RunStats(BaseModel):
    llm_calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    image_cost_usd: float = 0.0  # painted sprites (included in cost_usd)
    images: int = 0
    tiles_planned: int = 0
    tiles_accepted: int = 0
    tiles_failed: int = 0
    tiles_copied: int = 0
    copy_fallbacks: int = 0
    attempts: int = 0
    rejections_validation: int = 0
    rejections_review: int = 0


class Run(BaseModel):
    id: str
    world_id: str
    origin: Coord
    prompt: str
    options: RunOptions
    status: RunStatus = RunStatus.pending
    created_at: float
    finished_at: float | None = None
    error: str | None = None
    stats: RunStats = Field(default_factory=RunStats)
    plan: WorldPlan | None = None


class Attempt(BaseModel):
    run_id: str
    q: int
    r: int
    attempt: int
    directive: Directive
    design: TileDesign | None = None
    asset_id: str | None = None
    validation: dict[str, Any] = Field(default_factory=dict)
    verdict: Verdict | None = None
    outcome: Literal["pending", "invalid", "rejected", "accepted", "error"] = "pending"
    error: str | None = None
    created_at: float
