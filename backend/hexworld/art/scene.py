"""Scenes: a tile seen up close, as a layered pixel-art picture.

An image model paints the place from eye level (a backdrop) and, separately, what is right in front
of the viewer (a transparent foreground frame). Both are reduced to one crisp pixel grid so they read
as game art, and the viewer animates them (parallax, ambient effects named in `fx`). The description
comes entirely from the tile: its summary, terrain, neighbours, sprites, relief and the world's
palette and style, so every scene is of *this* place.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance

SCENE_W, SCENE_H = 384, 256  # logical pixels; painted at 1536x1024 and reduced 4x
PAINT_SIZE = "1536x1024"

# terrain words -> ambient effects the viewer can animate
FX_WORDS = {
    "water": (
        "water",
        "sea",
        "lake",
        "river",
        "pond",
        "harbor",
        "harbour",
        "bay",
        "tide",
        "canal",
        "shore",
        "surf",
    ),
    "leaves": ("forest", "wood", "grove", "orchard", "park", "garden", "tree", "jungle", "meadow"),
    "snow": ("snow", "ice", "glacier", "frost", "tundra", "alpine"),
    "embers": ("lava", "volcan", "forge", "ember", "ash", "fire", "magma"),
    "dust": ("desert", "sand", "canyon", "dune", "mesa", "dust", "quarry"),
    "fireflies": ("marsh", "swamp", "bog", "fen", "glade", "reed"),
    "gulls": ("coast", "cove", "harbor", "harbour", "pier", "quay", "cliff", "beach", "dock"),
    "steam": ("steam", "vent", "hot spring", "geyser", "factory"),
}


def scene_fx(words: list[str]) -> list[str]:
    text = " ".join(w.replace("_", " ").lower() for w in words)
    return [fx for fx, keys in FX_WORDS.items() if any(k in text for k in keys)][:3]


def _view_text(place: dict[str, Any]) -> str:
    """The place and what the viewer sees from it, looking north."""
    parts = [f"You stand on {place.get('here', 'this place')}."]
    if place.get("buildings"):
        parts.append(place["buildings"])
    view = place.get("view", {})
    for key, label in (("ahead", "Straight ahead"), ("left", "To the left"), ("right", "To the right")):
        if view.get(key):
            parts.append(f"{label}: {'; '.join(view[key][:3])}.")
    if view.get("beyond"):
        parts.append(f"Further ahead: {'; '.join(view['beyond'][:3])}.")
    if view.get("horizon"):
        parts.append(f"Far on the horizon: {'; '.join(view['horizon'][:3])}.")
    if place.get("region"):
        parts.append(f"All of this lies within {place['region']}.")
    return " ".join(parts)


def backdrop_prompt(style: Any, place: dict[str, Any], with_map: bool = False) -> str:
    keywords = getattr(style, "style_keywords", "") if style else ""
    palette = ", ".join((getattr(style, "palette", None) or [])[:16])
    ref = (
        "The image you are given is a top-down MAP of this spot and its surroundings (north is up; you "
        "stand in the hexagon marked YOU, looking north). Follow it for what lies where: coastlines, "
        "water, roads and paths, woods, buildings, landmarks, and the colours of the land. Do NOT paint "
        "a map: paint what you would see standing there. "
        if with_map
        else ""
    )
    return (
        "A wide, side-view 16-bit pixel art scene: the location screen of a top-down RPG, in the "
        "tradition of Octopath Traveler, Terraria and SNES backgrounds. " + ref + _view_text(place) + " "
        "Composition: the ground where you stand fills the lower third, what lies ahead rises in the middle "
        "distance, the far land on the horizon, and sky above "
        f"({place.get('sky', 'a clear day')}). Depth by colour: farther is paler and bluer. "
        f"World palette: {palette}. {keywords}. Chunky, clearly visible pixels, crisp edges, bold readable "
        "shapes, rich but calm detail, no people in the foreground, no text, no UI, no frame or border."
    )


def foreground_prompt(style: Any, place: dict[str, Any]) -> str:
    keywords = getattr(style, "style_keywords", "") if style else ""
    near = ", ".join(place.get("near", [])[:4]) or "grass tufts, stones and small plants"
    return (
        "The FOREGROUND LAYER ONLY of a side-view 16-bit pixel art RPG location scene of "
        f"{place.get('here', 'this place')}: {near}, very close to the viewer, framing "
        "the bottom edge and the two lower corners, no taller than a quarter of the image. Everything "
        "else is fully transparent: no sky, no background, no ground plane in the middle. "
        f"{keywords}. Chunky, clearly visible pixels, crisp edges, darker and more saturated than the "
        "scene behind, no text."
    )


def pixelize_scene(png: bytes, *, transparent: bool, colors: int = 64) -> bytes:
    """Painting -> one crisp pixel grid (SCENE_W x SCENE_H): box-downsample, a little contrast,
    a reduced colour set, hard alpha for the foreground."""
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    rgb = ImageEnhance.Contrast(img.convert("RGB")).enhance(1.08)
    rgb = ImageEnhance.Color(rgb).enhance(1.1)
    small = Image.merge("RGBA", (*rgb.split(), img.getchannel("A"))).resize(
        (SCENE_W, SCENE_H), Image.Resampling.BOX
    )
    a = np.asarray(small).copy()
    q = Image.fromarray(a[..., :3], "RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    out = np.zeros_like(a)
    out[..., :3] = np.asarray(q.convert("RGB"))
    out[..., 3] = np.where(a[..., 3] >= 128, 255, 0) if transparent else 255
    buf = io.BytesIO()
    Image.fromarray(out, "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def fallback_backdrop(sky: str, ground: str, horizon: str) -> bytes:
    """Engine-drawn scene when no image model is available (tests, offline): sky gradient, a
    horizon band and the ground in the tile's own colours."""

    def rgb(c: str) -> np.ndarray:
        c = c.lstrip("#")
        return np.array([int(c[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)

    a = np.zeros((SCENE_H, SCENE_W, 4), np.uint8)
    y = np.linspace(0, 1, SCENE_H)[:, None, None]
    top, low = rgb(sky) * 0.6, rgb(sky)
    a[..., :3] = (top * (1 - y) + low * y).astype(np.uint8)
    h0 = int(SCENE_H * 0.55)
    a[h0 : int(SCENE_H * 0.66), :, :3] = rgb(horizon).astype(np.uint8)
    a[int(SCENE_H * 0.66) :, :, :3] = rgb(ground).astype(np.uint8)
    a[..., 3] = 255
    buf = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buf, format="PNG")
    return buf.getvalue()
