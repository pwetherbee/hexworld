"""Turn generator output into true pixel art on the world's master palette, plus hex geometry
helpers (masks, edge strips, seam metric) that the validators and compositor rely on.

Canonical tile format: RGBA PNG, tile_px x tile_px, pointy-top hex inscribed so that its
circumradius is tile_px / 2 (top and bottom corners touch the image edge).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image

from hexworld.agents.themes import hex_to_rgb, rgb_to_hex
from hexworld.hex import DIRECTION_ANGLES, SQRT3, edge_endpoints


@dataclass
class PixelTile:
    rgba: np.ndarray  # (P, P, 4) uint8
    indices: np.ndarray  # (P, P) int16, -1 outside the hex
    png: bytes
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


def pixelize(src_png: bytes, palette: list[str], tile_px: int, *, oversample: int = 4) -> PixelTile:
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

    mask = hex_mask(tile_px)
    out_idx[~(mask & opaque)] = -1
    rgba = np.zeros((tile_px, tile_px, 4), dtype=np.uint8)
    valid = out_idx >= 0
    rgba[valid, :3] = pal[out_idx[valid]].astype(np.uint8)
    rgba[valid, 3] = 255

    return _finish(rgba, out_idx, mask, method)


def _finish(rgba: np.ndarray, idx: np.ndarray, mask: np.ndarray, method: str) -> PixelTile:
    valid = idx >= 0
    coverage = float(valid[mask].mean()) if mask.any() else 0.0
    distinct = int(len(np.unique(idx[valid]))) if valid.any() else 0
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
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
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"), dtype=np.uint8)


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


def edge_strip(
    rgba: np.ndarray, edge: int, n: int = 16, insets: tuple[float, ...] = (1.5, 2.5)
) -> np.ndarray:
    """(n, 3) float RGB samples along edge `edge`, from the corner at angle dir-30 to dir+30,
    each averaged over a few inset depths. NaN where transparent."""
    px = rgba.shape[0]
    s = px / 2.0
    (ax, ay), (bx, by) = edge_endpoints(s, edge)
    ang = math.radians(DIRECTION_ANGLES[edge])
    nx, ny = math.cos(ang), math.sin(ang)
    out = np.full((n, 3), np.nan, dtype=np.float32)
    # Middle 60% only: corners are 3-way junctions whose colors legitimately belong to the
    # adjacent edges, so they would register as false seams.
    for k, t in enumerate(np.linspace(0.2, 0.8, n)):
        px_x, px_y = ax + t * (bx - ax), ay + t * (by - ay)
        acc = []
        for inset in insets:
            ix = int(math.floor(s + px_x - nx * inset))
            iy = int(math.floor(s + px_y - ny * inset))
            if 0 <= ix < px and 0 <= iy < px and rgba[iy, ix, 3] > 0:
                acc.append(rgba[iy, ix, :3].astype(np.float32))
        if acc:
            out[k] = np.mean(acc, axis=0)
    return out


def seam_delta(tile: np.ndarray, edge: int, neighbor: np.ndarray) -> float:
    """0..1 color discontinuity across the edge shared with `neighbor` (which touches our `edge`
    with its edge (edge+3)%6, traversed in the opposite direction). Samples are smoothed along the
    strip so single dithering pixels don't count as seams."""
    a = edge_strip(tile, edge)
    b = edge_strip(neighbor, (edge + 3) % 6)[::-1]
    a, b = _smooth(a), _smooth(b)
    ok = ~(np.isnan(a).any(1) | np.isnan(b).any(1))
    if not ok.any():
        return 1.0
    # 150 RGB units ~ "clearly a different material" (e.g. grass vs rock); clipping keeps a few
    # wildly different pixels from dominating. Same-terrain dithered texture lands around 0.2.
    d = np.minimum(1.0, np.linalg.norm(a[ok] - b[ok], axis=1) / 150.0)
    return float(round(d.mean(), 4))


def _smooth(a: np.ndarray, w: int = 3) -> np.ndarray:
    out = a.copy()
    for i in range(len(a)):
        win = a[max(0, i - w // 2) : i + w // 2 + 1]
        good = win[~np.isnan(win).any(1)]
        out[i] = good.mean(0) if len(good) else np.nan
    return out
