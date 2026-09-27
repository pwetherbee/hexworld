"""Art DSLs written by agents: materials (ground patterns) and sprites (side-view props).

Nothing here is content. These are small, strict-mode friendly languages that the material and
sprite sub-agents write, and that `art/procedural.py` and `art/sprites.py` interpret into crisp
pixel art. Values are clamped rather than rejected, so an imperfect program still renders.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

Tone = Literal["outline", "dark", "base", "light", "hi"]
Motion = Literal["none", "sway", "bob", "flicker", "pulse"]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _color(v: str) -> str:
    v = v.strip().lower()
    if not v.startswith("#"):
        v = "#" + v
    return v if HEX_COLOR.match(v) else "#808080"


# ----------------------------------------------------------------------------- sprites


class ShapeOp(BaseModel):
    """One primitive on the sprite canvas (pixel units, origin top-left).

    rect: top-left (x, y), size (w, h) | ellipse: center (x, y), radii (w, h)
    tri: apex (x, y), base at y+h, half-width w | line: (x, y) -> (x+w, y+h) | pixel: (x, y)
    """

    op: Literal["rect", "ellipse", "tri", "line", "pixel"]
    x: float
    y: float
    w: float
    h: float
    color: int = Field(description="Index into the program's colors.")
    tone: Tone = Field(description="Ramp step of that color.")
    shade: bool = Field(description="Auto-shade: lighter upper-left, darker lower-right.")
    frames: list[int] = Field(description="Frames this shape appears in; [] = every frame.")


class SpriteProgram(BaseModel):
    width: int = Field(description="Canvas width in pixels (4-18). Match the ground's pixel scale.")
    height: int = Field(description="Canvas height in pixels (4-22).")
    colors: list[str] = Field(description="1-6 base colors '#rrggbb'; each gets a ramp (dark/base/light/hi).")
    shapes: list[ShapeOp] = Field(description="Painted in order (later shapes on top). <= 80.")
    frames: int = Field(description="Animation frames (1-4).")
    fps: float = Field(description="Frame rate if frames > 1.")
    motion: Motion = Field(description="Procedural motion applied by the renderer.")

    @model_validator(mode="after")
    def _clamp_all(self) -> SpriteProgram:
        self.width = int(_clamp(self.width, 4, 18))
        self.height = int(_clamp(self.height, 4, 22))
        self.colors = [_color(c) for c in self.colors[:6]] or ["#808080"]
        self.frames = int(_clamp(self.frames, 1, 4))
        self.fps = _clamp(self.fps, 0, 12)
        self.shapes = self.shapes[:80]
        for s in self.shapes:
            s.color = int(_clamp(s.color, 0, len(self.colors) - 1))
            s.frames = [f for f in s.frames if 0 <= f < self.frames]
        return self


# ----------------------------------------------------------------------------- materials


class DecalPixel(BaseModel):
    dx: int
    dy: int
    tone: Literal["outline", "dark", "base", "light", "hi", "accent"]


class PatternOp(BaseModel):
    """One layer of a material, evaluated in world pixel coordinates (seamless across tiles).

    patches:  smooth noise blobs, coverage = amount       stripes: waves at `angle`, period = scale
    speckle:  random single pixels, density = amount      cells:   voronoi cracks/mortar, width ~ amount
    cellfill: fill a fraction (amount) of voronoi cells    bevel:   per-cell light/dark bevel (stones)
    decals:   stamp `pixels` on a jittered grid (cell = scale, density = amount)
    built environments (cities, interiors):
    lots:     rectangular building lots on a staggered grid with 2px alleys, lot size = scale,
              share of lots filled = amount (each lot varies its shade: rooftops, market stalls)
    rooms:    wall lines of a room grid (room size = scale) with doorways (door chance = amount)
    checker:  checkerboard floor tiles (tile size = scale)
    planks:   wooden floorboards (board length = scale), dark seams
    bricks:   brick/stone courses (brick length = scale), mortar lines
    """

    op: Literal[
        "patches",
        "speckle",
        "stripes",
        "cells",
        "cellfill",
        "bevel",
        "decals",
        "lots",
        "rooms",
        "checker",
        "planks",
        "bricks",
    ]
    tone: Literal["outline", "dark", "base", "light", "hi", "accent"]
    scale: float = Field(description="Feature size in pixels (2-16; lots/rooms 10-40).")
    amount: float = Field(description="0-1 coverage/density/width, per op.")
    angle: float = Field(description="Degrees, for stripes.")
    pixels: list[DecalPixel] = Field(description="Decal pattern (for 'decals'); [] otherwise.")

    @model_validator(mode="after")
    def _c(self) -> PatternOp:
        self.scale = _clamp(self.scale, 2, 48)
        self.amount = _clamp(self.amount, 0, 1)
        self.pixels = [p for p in self.pixels if abs(p.dx) <= 3 and abs(p.dy) <= 3][:12]
        return self


class HeightOp(BaseModel):
    """Relief pattern, evaluated per BLOCK in world space: selected blocks are raised/lowered by
    `delta` levels (one level = one pixel-cube high). 'lots' raises building lots (city blocks, with
    varied heights); 'rooms' raises the walls of a room grid (interiors), leaving doorways."""

    op: Literal["patches", "cellfill", "stripes", "speckle", "lots", "rooms"]
    scale: float = Field(description="Feature size in pixels (8-48 for block-scale relief).")
    amount: float = Field(description="0-1 coverage/density.")
    delta: int = Field(description="-2..+4 levels added to selected blocks.")

    @model_validator(mode="after")
    def _c(self) -> HeightOp:
        self.scale = _clamp(self.scale, 4, 64)
        self.amount = _clamp(self.amount, 0, 1)
        self.delta = int(_clamp(self.delta, -2, 4))
        return self


class ScatterSpec(BaseModel):
    kind: str = Field(description="Sprite kind placed around this material, e.g. 'oak tree', 'boulder'.")
    count: int = Field(description="Sprites per tile of this material (0-8).")
    chance: float = Field(default=1.0, description="Share of this material's tiles that get it (0-1).")

    @model_validator(mode="after")
    def _c(self) -> ScatterSpec:
        self.count = int(_clamp(self.count, 0, 8))
        self.chance = _clamp(self.chance, 0, 1)
        return self


class BuildingsSpec(BaseModel):
    """Buildings as terrain: the engine lays out footprints on the world pixel grid, raises each
    building FLOOR_LEVELS relief levels per floor (in 3D they are real blocks with pixel-art facades),
    paints roofs into the ground and leaves the gaps (streets, alleys, yards) in the material's own
    pattern. Use it for any built terrain: city blocks, row houses, villages, towers, castles, ports."""

    layout: Literal["blocks", "rows", "detached", "towers", "compound"] = Field(
        description="blocks: staggered city blocks with alleys. rows: terraced/row houses side by side "
        "(Victorian streets, old towns). detached: houses with yards (suburbs, villages). towers: few "
        "large towers with plazas between (downtowns). compound: one big walled building per lot "
        "with a courtyard (castles, cloisters, warehouses)."
    )
    lot_px: int = Field(default=14, description="Typical footprint size in pixels (6-40; a tile is ~55px).")
    gap_px: int = Field(default=2, description="Alley/yard width between buildings in pixels (1-8).")
    street_grid: int = Field(
        default=1,
        description="City streets on the world's shared street lattice, so they join up across tiles "
        "and districts: 0 = no street grid (villages, castles, estates), 1 = a street on every lattice "
        "line (dense blocks about half a tile wide), 2 = every other line (big blocks, a tile wide).",
    )
    street_material: str = Field(
        default="",
        description="The world's street connector name (e.g. 'street') that the grid streets are "
        "paved with, so they look exactly like the connector streets; '' = plain asphalt.",
    )
    coverage: float = Field(default=0.85, description="Share of lots that hold a building (0.2-1).")
    floors_min: int = Field(default=2, description="Floors of the lowest buildings (1-40).")
    floors_max: int = Field(default=5, description="Floors of the tallest buildings (1-60).")
    tall_share: float = Field(
        default=0.1, description="Share of buildings near floors_max (the skyline); the rest skew low."
    )
    wall_colors: list[str] = Field(description="1-6 '#rrggbb' facade colours, varied per building.")
    roof_colors: list[str] = Field(description="1-4 '#rrggbb' roof colours.")
    facade: Literal["punched", "glass", "bands", "victorian", "industrial", "stone"] = Field(
        description="Window pattern drawn on the walls: punched (brick/plaster, a grid of windows), "
        "glass (curtain-wall towers), bands (office ribbon windows), victorian (tall narrow bays), "
        "industrial (sparse high windows), stone (castles, few slits)."
    )
    lit: float = Field(default=0.35, description="Share of lit (warm) windows, 0-1 (night cities high).")
    roof: Literal["flat", "parapet", "gabled", "terrace"] = Field(
        default="flat", description="flat, parapet (raised rim), gabled (a ridge), terrace (stepped)."
    )
    clutter: float = Field(default=0.3, description="Rooftop details (vents, water tanks), 0-1.")

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, v: Any) -> Any:
        if isinstance(v, dict) and "block_lots" in v and "street_grid" not in v:
            n = int(v.get("block_lots") or 0)
            v = {**v, "street_grid": 0 if n <= 0 else 1 if n <= 3 else 2}
        return v

    @field_validator("wall_colors", "roof_colors")
    @classmethod
    def _cols(cls, v: list[str]) -> list[str]:
        cols = [_color(c) for c in v][:6]
        if not cols:
            raise ValueError("give at least one colour")
        return cols

    @model_validator(mode="after")
    def _c(self) -> BuildingsSpec:
        self.lot_px = int(_clamp(self.lot_px, 6, 40))
        self.gap_px = int(_clamp(self.gap_px, 1, 8))
        self.street_grid = int(_clamp(self.street_grid, 0, 2))
        self.coverage = _clamp(self.coverage, 0.2, 1)
        self.floors_min = int(_clamp(self.floors_min, 1, 40))
        self.floors_max = int(_clamp(self.floors_max, self.floors_min, 60))
        self.tall_share = _clamp(self.tall_share, 0, 1)
        self.lit = _clamp(self.lit, 0, 1)
        self.clutter = _clamp(self.clutter, 0, 1)
        self.roof_colors = self.roof_colors[:4]
        return self


class Lens(BaseModel):
    """A drilled layer is its parent tile seen up close. Every material there carries the same lens
    (engine-set): world pixel (wx, wy) of the layer lies at parent world pixel (x + wx / factor,
    y + wy / factor), the layer's region centred on the parent tile's centre (x, y). The renderer
    reads the parent's large-scale structure through it, so nothing restarts at the new scale:
    buildings are the parent's lots (the same few buildings, now spanning several tiles), landforms
    are the parent's ridges, and the parent's big patches (clearings, clumps, fields) tint the
    ground under the layer's own close-up texture."""

    x: float
    y: float
    factor: float  # layer pixels per parent pixel
    k: float  # the parent's tile_px / 64
    levels: float  # relief levels here per parent level (floors, landforms)
    source: str = ""  # the parent material under this one ("" when the parent had none)
    buildings: BuildingsSpec | None = None  # the parent's buildings (lots, floors, coverage)
    elevation: int | None = None  # the parent's landform target
    ops: list[PatternOp] = Field(default_factory=list)  # the parent's large-scale patterns


class MaterialSpec(BaseModel):
    base_color: str = Field(description="'#rrggbb'. A 5-step ramp (outline/dark/base/light/hi) is derived.")
    accent_color: str = Field(description="'#rrggbb' for accent decals (flowers, embers, sparkles).")
    base_tone: Literal["dark", "base", "light"]
    liquid: bool
    rank: int = Field(
        description="0-9 height rank; higher materials get a dark lip where they meet lower ones."
    )
    boundary: Literal["lip", "foam", "glow", "none"] = Field(
        description="How this material's own border pixels look: foam (water), glow (lava), lip, none."
    )
    block_style: Literal["bevel", "outline", "flat"] = Field(
        default="bevel",
        description="How each 8px block is drawn: 'bevel' (lit top-left, shaded bottom-right; stone, dirt, "
        "grass, obsidian), 'outline' (dark 1px frame: bricks, planks, tiles), 'flat' (liquids, snow, sand).",
    )
    edges: Literal["organic", "straight"] = Field(
        default="organic",
        description="'straight' for built things: streets, canals, corridors and walls run in straight "
        "lines between tile edges; 'organic' (rivers, trails, coasts) meanders.",
    )
    markings: Literal["none", "dashed", "rails"] = Field(
        default="none",
        description="Connectors only: 'dashed' paints a road's dashed centre line and kerbs (streets, "
        "highways), 'rails' two rails with sleepers (railways, tram and cable-car lines), 'none' otherwise.",
    )
    # engine-set in a drilled layer (never shown to agents): the parent tile this layer zooms into
    lens: SkipJsonSchema[Lens | None] = None
    width: float = Field(
        default=1.0,
        description="Connectors only: width relative to the usual (the engine sets it for close-up "
        "layers; leave 1).",
    )
    height: int = Field(
        default=1, description="Base relief level 0-4 (liquids 0, plains 1, hills 2, rock 3+)."
    )
    elevation: int = Field(
        default=0,
        description="Large-scale rise in relief levels (0-40), grown by the engine as a smooth, "
        "ridged landform that blends into neighbouring terrains: 0 flat land and water, 2-5 rolling "
        "hills, 6-14 foothills and rocky slopes, 15-40 mountains and snow peaks (a level is ~1/18 of "
        "a tile's width). Cities on hills can use it too.",
    )
    height_ops: list[HeightOp] = Field(
        default_factory=list, description="Relief patterns (<= 3), e.g. ridges."
    )
    ops: list[PatternOp] = Field(description="Pattern layers in paint order (<= 8).")
    scatter: list[ScatterSpec] = Field(description="Ambient sprites for tiles of this material (<= 2 kinds).")
    buildings: BuildingsSpec | None = Field(
        default=None,
        description="For BUILT terrain only: buildings raised out of this ground as 3D blocks. The "
        "material's own colours and ops then describe the streets/yards between them.",
    )

    @field_validator("base_color", "accent_color")
    @classmethod
    def _col(cls, v: str) -> str:
        return _color(v)

    @model_validator(mode="after")
    def _c(self) -> MaterialSpec:
        self.rank = int(_clamp(self.rank, 0, 9))
        self.height = int(_clamp(self.height, 0, 4))
        self.elevation = 0 if self.liquid else int(_clamp(self.elevation, 0, 40))
        self.width = float(_clamp(self.width, 0.5, 4.0))
        self.height_ops = self.height_ops[:3]
        if self.liquid:
            self.height, self.height_ops = 0, []
        self.ops = self.ops[:8]
        self.scatter = self.scatter[:2]
        return self


# ----------------------------------------------------------------------------- session library


class SpriteEntry(BaseModel):
    kind: str
    program: SpriteProgram | None = None  # drawn with the DSL
    prompt: str | None = None  # or painted by the image model from this art direction
    asset_id: str
    px_w: int
    px_h: int
    frames: int
    fps: float
    motion: Motion
    run_id: str | None = None


def kind_key(kind: str) -> str:
    """Canonical library key: 'The Dark  Castle!' -> 'dark castle'."""
    k = re.sub(r"[^a-z0-9 ]+", " ", kind.lower())
    k = re.sub(r"\b(a|an|the|of|some)\b", " ", k)
    return re.sub(r"\s+", " ", k).strip()[:40] or "marker"


# Buildings are part of the landscape (built terrain with a BuildingsSpec, rendered as 3D blocks
# with facades); sprites are the people, creatures, vehicles, plants and small details on it.
# Unique landmark structures the generator can't express (windmill, lighthouse, statue, fountain,
# monument) may still be sprites.
BUILDING_WORDS = {
    "house",
    "home",
    "cottage",
    "building",
    "apartment",
    "tenement",
    "skyscraper",
    "highrise",
    "office",
    "shop",
    "store",
    "storefront",
    "warehouse",
    "factory",
    "barn",
    "mansion",
    "villa",
    "hut",
    "cabin",
    "shack",
    "bungalow",
    "townhouse",
    "rowhouse",
    "church",
    "chapel",
    "temple",
    "cathedral",
    "castle",
    "fortress",
    "fort",
    "palace",
    "keep",
    "citadel",
    "hall",
    "inn",
    "tavern",
    "pub",
    "school",
    "hospital",
    "hotel",
    "station",
    "bank",
    "library",
    "museum",
    "tower",
    "manor",
    "estate",
    "block",
    "condo",
    "loft",
    "garage",
    "depot",
    "mall",
    "arena",
    "stadium",
    "prison",
    "barracks",
    "homestead",
}


def is_building_kind(kind: str) -> bool:
    words = set(kind_key(kind).split())
    words |= {w[:-1] for w in words if w.endswith("s") and len(w) > 3}
    return bool(words & BUILDING_WORDS) or any(p in kind_key(kind) for p in BUILDING_PHRASES)


BUILDING_PHRASES = ("painted lad", "row of", "skyline", "city block", "high rise")


class PackItem(BaseModel):
    """One sprite of a pack, as the sprite director describes it for the image model."""

    kind: str = Field(description="The sprite kind exactly as given (library key).")
    subject: str = Field(
        description="What to paint: the object only, its materials, 2-4 main colours from the world "
        "palette, silhouette and 1-3 distinctive details (one or two sentences)."
    )
    size: Literal["small", "medium", "large"] = Field(
        default="medium",
        description="small: people, animals, lamps, crates, signs (~12px tall); medium: vehicles, "
        "trees, statues, stalls (~24px); large: landmarks like a windmill or a fountain (~36px).",
    )
    motion: Literal["none", "sway", "bob", "flicker", "pulse"] = Field(
        default="none",
        description="Idle motion: sway (trees, banners, people), bob (boats and floating things: they are "
        "placed on water), flicker (fire, torches), pulse (magic, glowing), none (still objects).",
    )
    terrain: str = Field(
        default="",
        description="Extras only: the terrain (from `terrains`) whose tiles this ambient sprite is spread over.",
    )


class Repaint(BaseModel):
    kind: str
    subject: str = Field(description="A sharper description that fixes what was wrong.")
