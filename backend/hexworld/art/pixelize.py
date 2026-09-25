"""Turn generator output into true pixel art on the world's master palette, plus hex geometry
helpers (masks, edge strips, seam metric) that the validators and compositor rely on.

Canonical tile format: RGBA PNG, tile_px x tile_px, pointy-top hex inscribed so that its
circumradius is tile_px / 2 (top and bottom corners touch the image edge).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image

from hexworld.agents.themes import hex_to_rgb, rgb_to_hex
from hexworld.art.grid import TileCanvas
from hexworld.hex import SQRT3


@dataclass
class PixelTile:
    rgba: np.ndarray  # (P, P, 4) uint8
    indices: np.ndarray  # (P, P) int16, -1 outside the hex
    png: bytes  # hex pixels (alpha 255) + a BLEED ring past the rim (alpha 254), see `_masked`
    distinct_colors: int
    coverage: float
    side_color: str
    method: str


@lru_cache(maxsize=16)
def hex_mask(px: int) -> np.ndarray:
    """Boolean (px, px) mask of the canonical pointy-top hex (pixel centers)."""
    s = px / 2.0
    c = (np.arange(px) + 0.5) - s
    x, y = np.meshgrid(c, c)
    ax, ay = np.abs(x), np.abs(y)
    return (ax <= SQRT3 / 2 * s + 1e-6) & (ay <= s - ax / SQRT3 + 1e-6)


def palette_array(palette: list[str]) -> np.ndarray:
    return np.array([hex_to_rgb(c) for c in palette], dtype=np.float32)


def nearest_indices(rgb: np.ndarray, pal: np.ndarray) -> np.ndarray:
    """Map (..., 3) RGB to nearest palette index using a 'redmean' perceptual distance."""
    flat = rgb.reshape(-1, 3).astype(np.float32)
    rmean = (flat[:, None, 0] + pal[None, :, 0]) / 2.0
    d = flat[:, None, :] - pal[None, :, :]
    dist = (
        (2 + rmean / 256) * d[..., 0] ** 2 + 4 * d[..., 1] ** 2 + (2 + (255 - rmean) / 256) * d[..., 2] ** 2
    )
    return dist.argmin(axis=1).reshape(rgb.shape[:-1]).astype(np.int16)


def crisp_tile(src_png: bytes, canvas: TileCanvas) -> PixelTile:
    """Already-exact pixel art rendered on the tile's world-grid canvas (integer-upscaled): sample
    pixel centres and apply the canvas hex mask. No palette re-quantization, so the output does
    not depend on the (growing) world palette."""
    C = canvas.C
    img = Image.open(io.BytesIO(src_png)).convert("RGBA")
    k = max(1, img.width // C)
    arr = np.asarray(img, dtype=np.uint8)[k // 2 :: k, k // 2 :: k][:C, :C].copy()
    return _masked(arr, canvas.mask(), "crisp")


def to_canvas(square: np.ndarray, canvas: TileCanvas) -> np.ndarray:
    """Place a P x P hex-square image (e.g. pixelized diffusion output) onto the tile's C x C
    world-grid canvas (sub-pixel offset rounded)."""
    P, C = canvas.P, canvas.C
    cx, cy = canvas.center
    ox, oy = canvas.origin
    x0, y0 = int(round(cx - canvas.s)) - ox, int(round(cy - canvas.s)) - oy
    out = np.zeros((C, C, 4), dtype=np.uint8)
    out[y0 : y0 + P, x0 : x0 + P] = square[: C - y0, : C - x0]
    # fill the 1-2px margins (outside the square) from the nearest square pixel so the hex is covered
    for _ in range(3):
        empty = out[..., 3] == 0
        if not empty.any():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src = np.roll(np.roll(out, dy, axis=0), dx, axis=1)
            fill = empty & (src[..., 3] > 0)
            out[fill] = src[fill]
    return out


BLEED_ALPHA = 254
BLEED_PX = 2


def _dilate(mask: np.ndarray, n: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(n):
        p = np.pad(out, 1)
        out = out | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    return out


def _masked(arr: np.ndarray, mask: np.ndarray, method: str) -> PixelTile:
    """Hex-masked tile. The stored PNG also keeps the world pixels just past the rim (alpha 254):
    the 3D face cuts the texture with the exact hex geometry, and pixels the rim only partly covers
    must be painted there, or the border shows a pixel staircase. `load_tile` drops them again."""
    src = arr
    arr = arr.copy()
    arr[~mask] = 0
    arr[mask, 3] = 255
    bleed = _dilate(mask, BLEED_PX) & ~mask & (src[..., 3] > 0 if src.shape[-1] == 4 else True)
    stored = arr.copy()
    stored[bleed, :3] = src[bleed, :3]
    stored[bleed, 3] = BLEED_ALPHA
    flat = arr[..., :3].reshape(-1, 3)
    _, idx = np.unique(flat, axis=0, return_inverse=True)
    indices = idx.reshape(arr.shape[:2]).astype(np.int16)
    indices[~mask] = -1
    return _finish(arr, indices, mask, method, stored)


def pixelize_to_canvas(src_png: bytes, palette: list[str], canvas: TileCanvas) -> PixelTile:
    """Diffusion output -> true pixel art on the master palette -> the tile's world-grid canvas."""
    sq = pixelize(src_png, palette, canvas.P, mask=False)
    return _masked(to_canvas(sq.rgba, canvas), canvas.mask(), sq.method)


def pixelize(
    src_png: bytes, palette: list[str], tile_px: int, *, oversample: int = 4, mask: bool = True
) -> PixelTile:
    """Generator image (any size, roughly square, hex filling the frame) -> canonical pixel tile.

    1. BOX-downsample to tile_px * oversample (averages away diffusion noise)
    2. map every pixel to the nearest master-palette color
    3. mode-pool each oversample x oversample block -> one palette index per output pixel
       (majority vote gives crisp pixels without the muddy in-between colors plain resizing makes)
    4. apply the hex mask
    Optional: if `proper-pixel-art` is installed it is tried first for grid recovery.
    """
    img = Image.open(io.BytesIO(src_png)).convert("RGBA")
    method = "palette-mode-pool"
    try:  # optional dependency, better on true "fake-pixel" diffusion output
        from proper_pixel_art import pixelate  # type: ignore[import-not-found]

        recovered = pixelate(img.convert("RGB"), num_colors=len(palette))
        if isinstance(recovered, Image.Image):
            img = recovered.convert("RGBA")
            method = "proper-pixel-art+palette-mode-pool"
    except Exception:
        pass
    work = tile_px * oversample
    img = img.resize((work, work), Image.Resampling.BOX if img.width >= work else Image.Resampling.NEAREST)
    arr = np.asarray(img, dtype=np.uint8)
    pal = palette_array(palette)
    idx = nearest_indices(arr[..., :3], pal)
    alpha = arr[..., 3] >= 128

    k = oversample
    blocks = idx.reshape(tile_px, k, tile_px, k).transpose(0, 2, 1, 3).reshape(tile_px, tile_px, k * k)
    ablocks = alpha.reshape(tile_px, k, tile_px, k).transpose(0, 2, 1, 3).reshape(tile_px, tile_px, k * k)
    counts = np.stack([((blocks == m) & ablocks).sum(-1) for m in range(len(palette))], axis=-1)
    out_idx = counts.argmax(-1).astype(np.int16)
    opaque = ablocks.sum(-1) * 2 >= k * k

    hexm = hex_mask(tile_px) if mask else np.ones((tile_px, tile_px), bool)
    out_idx[~(hexm & opaque)] = -1
    rgba = np.zeros((tile_px, tile_px, 4), dtype=np.uint8)
    valid = out_idx >= 0
    rgba[valid, :3] = pal[out_idx[valid]].astype(np.uint8)
    rgba[valid, 3] = 255

    return _finish(rgba, out_idx, hexm, method)


def _finish(
    rgba: np.ndarray, idx: np.ndarray, mask: np.ndarray, method: str, stored: np.ndarray | None = None
) -> PixelTile:
    valid = idx >= 0
    coverage = float(valid[mask].mean()) if mask.any() else 0.0
    distinct = int(len(np.unique(idx[valid]))) if valid.any() else 0
    buf = io.BytesIO()
    Image.fromarray(rgba if stored is None else stored, "RGBA").save(buf, format="PNG", optimize=True)
    return PixelTile(
        rgba=rgba,
        indices=idx,
        png=buf.getvalue(),
        distinct_colors=distinct,
        coverage=coverage,
        side_color=_side_color(rgba, mask),
        method=method,
    )


def load_tile(png: bytes) -> np.ndarray:
    """RGBA array of a stored tile/layer; the rim bleed ring (alpha 254) is dropped."""
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"), dtype=np.uint8).copy()
    a[a[..., 3] == BLEED_ALPHA] = 0
    return a


def _side_color(rgba: np.ndarray, mask: np.ndarray) -> str:
    """Darkened mean color of the hex border ring: used for the 3D prism's sides."""
    px = rgba.shape[0]
    inner = hex_mask(px) if px < 6 else _shrunk_mask(px, 0.8)
    ring = mask & ~inner & (rgba[..., 3] > 0)
    if not ring.any():
        return "#444444"
    mean = rgba[ring][:, :3].astype(np.float32).mean(0) * 0.6
    return rgb_to_hex(tuple(int(v) for v in mean))  # type: ignore[arg-type]


@lru_cache(maxsize=16)
def _shrunk_mask(px: int, f: float) -> np.ndarray:
    s = px / 2.0 * f
    c = (np.arange(px) + 0.5) - px / 2.0
    x, y = np.meshgrid(c, c)
    ax, ay = np.abs(x), np.abs(y)
    return (ax <= SQRT3 / 2 * s) & (ay <= s - ax / SQRT3)


# --------------------------------------------------------------------------- edges / seams
