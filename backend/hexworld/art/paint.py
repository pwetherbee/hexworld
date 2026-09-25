"""Painted sprites: an image model paints a prop; we turn it into game-scale pixel art.

The sprite artist agent art-directs (writes the subject description); the painter adds a fixed
style frame, and `pixelize_sprite` reduces the result to the world's pixel density: crop to the
subject, box-downsample to a target height, reduce to a small colour set, hard alpha, 1px outline.
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Any

import numpy as np
from PIL import Image

from hexworld.agents.themes import hex_to_rgb
from hexworld.art.sprites import OUTLINE, SpriteArt, _outlined

# Target heights in world pixels (tiles are 64px wide; one hex radius = 32px).
SIZES = {"small": 12, "medium": 24, "large": 36}  # large stays inside its own tile
MAX_WIDTH = 30


def pixelize_sprite(png: bytes, size: str = "medium", colors: int = 14) -> SpriteArt:
    """Painting -> game-scale pixel sprite: crop to the subject, punch up contrast (detail is lost
    at ~30px, so values must separate), box-downsample, reduce to a small palette, harden alpha,
    drop orphan pixels, add the bold outline."""
    from PIL import ImageEnhance

    img = Image.open(io.BytesIO(png)).convert("RGBA")
    a = np.asarray(img)
    solid = a[..., 3] >= 128
    if not solid.any():
        raise ValueError("the painting is empty (fully transparent)")
    ys, xs = np.nonzero(solid)
    crop = img.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    rgb = crop.convert("RGB")
    rgb = ImageEnhance.Contrast(rgb).enhance(1.25)
    rgb = ImageEnhance.Color(rgb).enhance(1.2)
    crop = Image.merge("RGBA", (*rgb.split(), crop.getchannel("A")))
    target_h = SIZES.get(size, SIZES["medium"])
    scale = target_h / crop.height
    if crop.width * scale > MAX_WIDTH:
        scale = MAX_WIDTH / crop.width
    w, h = max(3, round(crop.width * scale)), max(3, round(crop.height * scale))
    small = np.asarray(crop.resize((w, h), Image.Resampling.BOX)).copy()
    alpha = small[..., 3] >= 110
    alpha = _drop_orphans(alpha)
    q = Image.fromarray(small[..., :3], "RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    rgbq = np.asarray(q.convert("RGB"))
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[alpha, :3] = rgbq[alpha]
    out[alpha, 3] = 255
    return SpriteArt(frames=[_outlined(out, hex_to_rgb(OUTLINE))], motion="none")


def _drop_orphans(mask: np.ndarray) -> np.ndarray:
    """Remove opaque pixels with at most one opaque 4-neighbour (antialiasing crumbs, spikes)."""
    p = np.pad(mask, 1)
    n = p[:-2, 1:-1].astype(int) + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]
    return mask & (n >= 2)


def style_frame(style: Any, subject: str) -> str:
    keywords = getattr(style, "style_keywords", "") if style else ""
    return (
        "Terraria-style 16-bit pixel art game sprite, side view, designed to read at 32x32 pixels: "
        "a bold, simple, chunky silhouette made of a few large shapes, thick dark outline, flat "
        "vibrant colours with 3-tone shading lit from the top-left, strong value contrast, big "
        "visible pixels, no thin spikes or fine detail, no anti-aliasing. "
        f"{keywords}. Subject: {subject}. A single isolated object, centered, fully visible, "
        "transparent background, no ground, no drop shadow, no glow halo, no text."
    )


class OpenAISpritePainter:
    def __init__(
        self, *, api_key: str | None, base_url: str | None, model: str, quality: str, concurrency: int = 6
    ):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=2, timeout=120)
        self.model = model
        self.quality = quality
        self._sem = asyncio.Semaphore(max(1, concurrency))

    async def paint(self, prompt: str) -> tuple[bytes, dict[str, int]]:
        """-> (png, usage) where usage has text/image input and output token counts."""
        async with self._sem:
            r = await self._generate(prompt)
        return self._result(r)

    async def _generate(self, prompt: str) -> Any:
        return await self._client.images.generate(
            model=self.model,
            prompt=prompt,
            size="1024x1024",
            quality=self.quality,
            background="transparent",
            n=1,
        )

    def _result(self, r: Any) -> tuple[bytes, dict[str, int]]:
        b64 = r.data[0].b64_json
        if not b64:
            raise RuntimeError("image model returned no image")
        usage: dict[str, int] = {}
        u = getattr(r, "usage", None)
        if u is not None:
            details = getattr(u, "input_tokens_details", None)
            usage = {
                "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
                "text_input_tokens": int(getattr(details, "text_tokens", 0) or 0) if details else 0,
                "image_input_tokens": int(getattr(details, "image_tokens", 0) or 0) if details else 0,
            }
            if not details:
                usage["text_input_tokens"] = usage["input_tokens"]
        return base64.b64decode(b64), usage
