"""Sprite interpreter: rasterizes agent-written SpritePrograms into side-view pixel art.

A program is a list of primitives on a small canvas. Each has a colour ramp step, optional
auto-shading (light from the upper-left) and a set of frames it appears in. The interpreter adds a
1px dark outline and returns an animation strip. Sprites stand on tiles as billboard layers.

No sprite content lives here; programs come from the sprite sub-agent via the world's library.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

from hexworld.agents.themes import hex_to_rgb, nearest_palette, shade
from hexworld.art.grid import TileCanvas
from hexworld.art.procedural import _hash
from hexworld.domain.art import ScatterSpec, ShapeOp, SpriteProgram

TONE_FACTORS = {"outline": 0.38, "dark": 0.68, "base": 1.0, "light": 1.28, "hi": 1.55}
OUTLINE = "#14141c"


@dataclass
class SpriteArt:
    frames: list[np.ndarray]  # RGBA (h, w, 4), same size
    motion: str = "none"
    fps: float = 0.0

    @property
    def w(self) -> int:
        return self.frames[0].shape[1]

    @property
    def h(self) -> int:
        return self.frames[0].shape[0]

    def strip_png(self) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(np.concatenate(self.frames, axis=1), "RGBA").save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @classmethod
    def from_strip(cls, png: bytes, frames: int, motion: str = "none", fps: float = 0.0) -> SpriteArt:
        a = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
        w = a.shape[1] // max(1, frames)
        return cls([a[:, i * w : (i + 1) * w].copy() for i in range(max(1, frames))], motion, fps)


def _shape_mask(op: ShapeOp, xx: np.ndarray, yy: np.ndarray) -> np.ndarray:
    if op.op == "rect":
        return (xx >= op.x) & (xx < op.x + max(1, op.w)) & (yy >= op.y) & (yy < op.y + max(1, op.h))
    if op.op == "ellipse":
        rx, ry = max(0.5, op.w), max(0.5, op.h)
        return ((xx + 0.5 - op.x) / rx) ** 2 + ((yy + 0.5 - op.y) / ry) ** 2 <= 1.0
    if op.op == "tri":
        t = (yy + 0.5 - op.y) / max(1e-6, op.h)
        return (t >= 0) & (t <= 1) & (np.abs(xx + 0.5 - op.x) <= op.w * t + 0.5)
    m = np.zeros(xx.shape, bool)
    if op.op == "pixel":
        c, r = int(math.floor(op.x)), int(math.floor(op.y))
        if 0 <= r < m.shape[0] and 0 <= c < m.shape[1]:
            m[r, c] = True
        return m
    # line
    n = int(max(abs(op.w), abs(op.h))) + 1
    for i in range(n + 1):
        t = i / n
        c, r = int(round(op.x + op.w * t)), int(round(op.y + op.h * t))
        if 0 <= r < m.shape[0] and 0 <= c < m.shape[1]:
            m[r, c] = True
    return m


def rasterize(program: SpriteProgram, palette: list[str] | None = None) -> SpriteArt:
    def col(hex_color: str) -> tuple[int, int, int]:
        return hex_to_rgb(nearest_palette(hex_color, palette) if palette else hex_color)

    ramps = [{t: col(shade(c, f)) for t, f in TONE_FACTORS.items()} for c in program.colors]
    outline = col(OUTLINE)
    W, H = program.width, program.height
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    frames = []
    for f in range(program.frames):
        a = np.zeros((H, W, 4), dtype=np.uint8)
        for op in program.shapes:
            if op.frames and f not in op.frames:
                continue
            m = _shape_mask(op, xx, yy)
            if not m.any():
                continue
            ramp = ramps[op.color]
            a[m] = (*ramp[op.tone], 255)
            if op.shade and op.op in ("rect", "ellipse", "tri"):
                cy, cx = (v.mean() for v in np.nonzero(m))
                span = max(1.0, math.sqrt(float(m.sum())) / 2)
                diag = (xx - cx) + (yy - cy)
                a[m & (diag > span * 0.7)] = (*ramp["dark"], 255)
                a[m & (diag < -span * 0.7)] = (*ramp["light"], 255)
                a[m & (diag < -span * 1.15)] = (*ramp["hi"], 255)
        frames.append(_outlined(a, outline))
    return SpriteArt(frames=frames, motion=program.motion, fps=program.fps if program.frames > 1 else 0.0)


def _outlined(a: np.ndarray, c: tuple[int, int, int]) -> np.ndarray:
    h, w = a.shape[:2]
    out = np.zeros((h + 2, w + 2, 4), dtype=np.uint8)
    out[1:-1, 1:-1] = a
    op = out[..., 3] > 0
    ring = np.zeros_like(op)
    ring[1:, :] |= op[:-1, :]
    ring[:-1, :] |= op[1:, :]
    ring[:, 1:] |= op[:, :-1]
    ring[:, :-1] |= op[:, 1:]
    out[ring & ~op] = (*c, 255)
    return out


# ----------------------------------------------------------------------------- placement


@dataclass
class Placed:
    kind: str
    art: SpriteArt
    x: float  # tile-local, circumradius units (east +)
    y: float  # (south +)
    scale: float = 1.0


def scatter_positions(scatter: list[ScatterSpec], coord: tuple[int, int], variant: int = 0):
    """Deterministic ambient placements for a tile: [(kind, x, y, scale)]."""
    q, r = coord
    out: list[tuple[str, float, float, float]] = []
    for si, sp in enumerate(scatter):
        placed = 0
        for k in range(sp.count * 3):
            if placed >= sp.count:
                break
            ang = float(_hash(q * 13 + k, r * 7 + si, 11.0 + variant)) * math.tau
            rad = math.sqrt(float(_hash(q + k, r - si, 13.0 + variant))) * 0.38  # inner area only
            x, y = math.cos(ang) * rad, math.sin(ang) * rad * 0.9
            if any(math.hypot(x - ox, y - oy) < 0.2 for _, ox, oy, _ in out):
                continue
            out.append((sp.kind, x, y, 0.85 + 0.3 * float(_hash(q, r + k, 17.0 + si))))
            placed += 1
    return out


def flatten(ground: np.ndarray, placed: list[Placed], canvas: TileCanvas) -> np.ndarray:
    """Top-down preview: paste each sprite's first frame bottom-centred at its position (back to
    front), clipped to the hex. Used for thumbnails, the review contact sheet and the style anchor."""
    out = ground.copy()
    s = canvas.s
    cx, cy = canvas.center
    ox, oy = canvas.origin
    C = canvas.C
    mask = canvas.mask()
    for p in sorted(placed, key=lambda p: p.y):
        fr = p.art.frames[0]
        if abs(p.scale - 1) > 0.15:
            h, w = fr.shape[:2]
            fr = np.asarray(
                Image.fromarray(fr, "RGBA").resize(
                    (max(1, round(w * p.scale)), max(1, round(h * p.scale))), Image.Resampling.NEAREST
                )
            )
        h, w = fr.shape[:2]
        x0 = int(round(cx + p.x * s - ox)) - w // 2
        y0 = int(round(cy + p.y * s - oy)) - h
        ys, xs = np.nonzero(fr[..., 3] > 0)
        X, Y = xs + x0, ys + y0
        ok = (X >= 0) & (X < C) & (Y >= 0) & (Y < C)
        X, Y, ys, xs = X[ok], Y[ok], ys[ok], xs[ok]
        keep = mask[Y, X]
        out[Y[keep], X[keep]] = fr[ys[keep], xs[keep]]
    return out


# ----------------------------------------------------------------------------- artist previews


def preview_png(art: SpriteArt, scale: int = 8) -> bytes:
    """What the sprite artist sees: every frame side by side, enlarged, on a neutral ground line."""
    pad = 2
    w = (art.w + pad) * len(art.frames) + pad
    h = art.h + pad * 2 + 2
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    canvas[..., :3] = (58, 62, 74)
    canvas[..., 3] = 255
    canvas[-3:, :, :3] = (92, 84, 70)  # ground strip
    for i, fr in enumerate(art.frames):
        x0 = pad + i * (art.w + pad)
        y0 = h - 3 - art.h
        region = canvas[y0 : y0 + art.h, x0 : x0 + art.w]
        m = fr[..., 3] > 0
        region[m] = fr[m]
    img = Image.fromarray(canvas, "RGBA").resize((w * scale, h * scale), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def lint(program: SpriteProgram, art: SpriteArt) -> list[str]:
    """Cheap objective feedback for the artist alongside the render."""
    out: list[str] = []
    fr = art.frames[0]
    opaque = fr[..., 3] > 0
    if opaque.sum() < 8:
        out.append("almost nothing visible: shapes may be outside the canvas or too small")
    else:
        lum = fr[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        dark = (lum < 55) & opaque
        if dark.sum() / opaque.sum() > 0.55:
            out.append(
                "mostly very dark: add lighter mid-tones and a few highlight pixels so it reads on the map"
            )
    outside = [
        i
        for i, s in enumerate(program.shapes)
        if s.op in ("rect", "pixel")
        and (s.x >= program.width or s.y >= program.height or s.x + max(1, s.w) <= 0)
    ]
    if outside:
        out.append(f"shapes {outside[:6]} are outside the {program.width}x{program.height} canvas")
    return out
