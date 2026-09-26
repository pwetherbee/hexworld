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


# ----------------------------------------------------------------------------- sprite sheets

QUADRANTS = ["top-left", "top-right", "bottom-left", "bottom-right"]


def sheet_frame(style: Any, subjects: list[str]) -> str:
    keywords = getattr(style, "style_keywords", "") if style else ""
    cells = "; ".join(
        f"cell {i + 1} ({QUADRANTS[i]}): {s}" if s else f"cell {i + 1} ({QUADRANTS[i]}): leave empty"
        for i, s in enumerate(subjects + [""] * (4 - len(subjects)))
    )
    return (
        "A 2x2 sprite sheet of separate Terraria-style 16-bit pixel art game sprites, side view, each "
        "designed to read at 32x32 pixels: bold simple chunky silhouettes made of a few large shapes, "
        "thick dark outlines, flat vibrant colours with 3-tone shading lit from the top-left, strong "
        "value contrast, big visible pixels, no thin spikes or fine detail, no anti-aliasing. "
        f"{keywords}. Exactly one isolated object centred in each used quadrant, fully inside it with wide "
        f"empty margins, nothing crossing the centre lines. {cells}. Transparent background, no grid "
        "lines, no ground, no drop shadows, no glow halo, no text."
    )


def split_sheet(png: bytes, n: int) -> list[bytes | None]:
    """Quadrant PNGs for the first `n` cells; None for a cell that is empty or spills over a centre
    line (its object would be cut: that sprite is repainted on its own)."""
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    a = np.asarray(img)
    H, W = a.shape[:2]
    h2, w2 = H // 2, W // 2
    solid = a[..., 3] >= 128
    out: list[bytes | None] = []
    for i in range(n):
        y0, x0 = (i // 2) * h2, (i % 2) * w2
        cell = solid[y0 : y0 + h2, x0 : x0 + w2]
        inner_x = slice(w2 - 6, w2) if i % 2 == 0 else slice(0, 6)  # strip along the vertical centre line
        inner_y = slice(h2 - 6, h2) if i // 2 == 0 else slice(0, 6)  # strip along the horizontal one
        spill = int(cell[:, inner_x].sum()) + int(cell[inner_y, :].sum())
        if cell.mean() < 0.005 or spill > 40:
            out.append(None)
            continue
        buf = io.BytesIO()
        img.crop((x0, y0, x0 + w2, y0 + h2)).save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


class SheetPainter:
    """Batches concurrent paint requests into 2x2 sprite sheets: one image call paints up to four
    sprites, in the same time and for the same price as one. Requests with the same style that
    arrive within `window_s` share a sheet; a lone request is painted on its own; a sheet cell that
    comes back empty or spilling out of its quadrant is repainted individually."""

    def __init__(self, painter: OpenAISpritePainter, window_s: float = 1.0, per_sheet: int = 4):
        self.painter = painter
        self.model = painter.model
        self.window_s = window_s
        self.per_sheet = per_sheet
        self._queues: dict[str, list[tuple[str, Any, asyncio.Future]]] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._tasks: set[asyncio.Task] = set()

    async def paint(self, prompt: str) -> tuple[bytes, dict[str, int]]:
        return await self.painter.paint(prompt)

    async def paint_subject(self, subject: str, style: Any) -> tuple[bytes, dict[str, int]]:
        loop = asyncio.get_running_loop()
        key = getattr(style, "style_keywords", "") if style else ""
        fut: asyncio.Future = loop.create_future()
        q = self._queues.setdefault(key, [])
        q.append((subject, style, fut))
        if len(q) >= self.per_sheet:
            self._flush(key)
        elif key not in self._timers:
            self._timers[key] = loop.call_later(self.window_s, self._flush, key)
        return await fut

    def _flush(self, key: str) -> None:
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()
        q = self._queues.get(key, [])
        batch, self._queues[key] = q[: self.per_sheet], q[self.per_sheet :]
        if self._queues[key]:
            self._timers[key] = asyncio.get_running_loop().call_later(self.window_s, self._flush, key)
        if batch:
            task = asyncio.ensure_future(self._paint_batch(batch))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _paint_batch(self, batch: list[tuple[str, Any, asyncio.Future]]) -> None:
        try:
            if len(batch) == 1:
                subject, style, fut = batch[0]
                await self._single(subject, style, fut)
                return
            style = batch[0][1]
            png, usage = await self.painter.paint(sheet_frame(style, [b[0] for b in batch]))
            share = {k: v // len(batch) for k, v in usage.items()}
            cells = split_sheet(png, len(batch))
            for (subject, st, fut), cell in zip(batch, cells, strict=True):
                if cell is None:
                    await self._single(subject, st, fut, extra=share)
                elif not fut.done():
                    fut.set_result((cell, {**share, "sheet": len(batch)}))
        except Exception as e:  # noqa: BLE001 - every waiting artist gets the error
            for *_, fut in batch:
                if not fut.done():
                    fut.set_exception(e)

    async def _single(self, subject: str, style: Any, fut: asyncio.Future, extra: dict | None = None) -> None:
        try:
            png, usage = await self.painter.paint(style_frame(style, subject))
            if extra:
                usage = {k: usage.get(k, 0) + extra.get(k, 0) for k in set(usage) | set(extra)}
            if not fut.done():
                fut.set_result((png, usage))
        except Exception as e:  # noqa: BLE001
            if not fut.done():
                fut.set_exception(e)
