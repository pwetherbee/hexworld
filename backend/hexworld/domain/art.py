"""Art DSLs written by agents: materials (ground patterns) and sprites (side-view props).

Nothing here is content. These are small, strict-mode friendly languages that the material and
sprite sub-agents write, and that `art/procedural.py` and `art/sprites.py` interpret into crisp
pixel art. Values are clamped rather than rejected, so an imperfect program still renders.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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
    """

    op: Literal["patches", "speckle", "stripes", "cells", "cellfill", "bevel", "decals"]
    tone: Literal["outline", "dark", "base", "light", "hi", "accent"]
    scale: float = Field(description="Feature size in pixels (2-16).")
    amount: float = Field(description="0-1 coverage/density/width, per op.")
    angle: float = Field(description="Degrees, for stripes.")
    pixels: list[DecalPixel] = Field(description="Decal pattern (for 'decals'); [] otherwise.")

    @model_validator(mode="after")
    def _c(self) -> PatternOp:
        self.scale = _clamp(self.scale, 2, 16)
        self.amount = _clamp(self.amount, 0, 1)
        self.pixels = [p for p in self.pixels if abs(p.dx) <= 3 and abs(p.dy) <= 3][:12]
        return self


class ScatterSpec(BaseModel):
    kind: str = Field(description="Sprite kind placed around this material, e.g. 'oak tree', 'boulder'.")
    count: int = Field(description="Sprites per tile of this material (0-8).")

    @model_validator(mode="after")
    def _c(self) -> ScatterSpec:
        self.count = int(_clamp(self.count, 0, 8))
        return self


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
    ops: list[PatternOp] = Field(description="Pattern layers in paint order (<= 8).")
    scatter: list[ScatterSpec] = Field(description="Ambient sprites for tiles of this material (<= 2 kinds).")

    @field_validator("base_color", "accent_color")
    @classmethod
    def _col(cls, v: str) -> str:
        return _color(v)

    @model_validator(mode="after")
    def _c(self) -> MaterialSpec:
        self.rank = int(_clamp(self.rank, 0, 9))
        self.ops = self.ops[:8]
        self.scatter = self.scatter[:2]
        return self


# ----------------------------------------------------------------------------- session library


class SpriteEntry(BaseModel):
    kind: str
    program: SpriteProgram
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
