"""Image generation backends behind one protocol.

- ProceduralStubBackend: deterministic, offline, seam-consistent procedural pixel art (tests/dev)
- ComfyUIBackend: local open-source diffusion (Z-Image Turbo / FLUX.2 klein ...) via ComfyUI's API
- OpenAIImageBackend: hosted fallback (GPT Image), output goes through the same pixelizer
- FallbackImageBackend: circuit breaker that routes around a failing primary
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import io
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
from PIL import Image

from hexworld.agents.themes import base_color, hex_to_rgb, nearest_palette, shade
from hexworld.hex import DIRECTION_ANGLES, SQRT3, Hex


@dataclass
class ImageRequest:
    prompt: str
    negative: str
    seed: int
    size: int  # square output size in px
    mode: Literal["txt2img", "inpaint"] = "txt2img"
    context_png: bytes | None = None  # neighbor canvas; target area blank
    mask_png: bytes | None = None  # white = paint here
    style_refs: list[bytes] = field(default_factory=list)
    # Structured hints. Real backends ignore these; the stub renders from them.
    hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageResult:
    png: bytes
    backend: str
    meta: dict[str, Any] = field(default_factory=dict)


class ImageBackend(Protocol):
    name: str

    async def generate(self, req: ImageRequest) -> ImageResult: ...

    async def health(self) -> bool: ...


class ImageBackendError(Exception):
    pass


# --------------------------------------------------------------------------- procedural stub

BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float32) / 16.0


def _hash01(*vals: float) -> float:
    h = hashlib.blake2b(repr(vals).encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") / 2**64


def _value_noise(x: np.ndarray, y: np.ndarray, cell: float, seed: int) -> np.ndarray:
    """Cheap smooth value noise in *world* pixel coordinates (so it continues across tiles)."""
    gx, gy = x / cell, y / cell
    x0, y0 = np.floor(gx), np.floor(gy)
    fx, fy = gx - x0, gy - y0

    def rnd(ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
        v = np.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
        return v - np.floor(v)

    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = rnd(x0, y0), rnd(x0 + 1, y0)
    c, d = rnd(x0, y0 + 1), rnd(x0 + 1, y0 + 1)
    return (a + (b - a) * sx) * (1 - sy) + (c + (d - c) * sx) * sy


class ProceduralStubBackend:
    """Renders from structured hints: biome in the middle, each edge's terrain toward that edge,
    connectors as paths to edge midpoints, features/trees as tiny sprites. Texture noise is in world
    space and edge bands are pure edge terrain, so neighbors that agree on an EdgeSpec meet seamlessly.
    Output is upscaled + jittered to mimic diffusion "fake pixels" and exercise the pixelizer."""

    name = "stub"

    def __init__(self, latency_s: float = 0.25, upscale: int = 4):
        self.latency_s = latency_s
        self.upscale = upscale

    async def health(self) -> bool:
        return True

    async def generate(self, req: ImageRequest) -> ImageResult:
        if self.latency_s:
            await asyncio.sleep(self.latency_s * (0.6 + 0.8 * _hash01(req.seed)))
        png = await asyncio.to_thread(self._render, req)
        return ImageResult(png=png, backend=self.name, meta={"seed": req.seed, "framing": "tile"})

    def _render(self, req: ImageRequest) -> bytes:
        h = req.hints
        P: int = h["tile_px"]
        palette: list[str] = h["palette"]
        biome: str = h["biome"]
        edges: list[dict[str, Any]] = h["edges"]
        q, r = h["coord"]
        wx0, wy0 = Hex(q, r).to_pixel(P / 2.0)
        variant = req.seed % 997

        s = P / 2.0
        c = (np.arange(P) + 0.5) - s
        x, y = np.meshgrid(c, c)
        wx, wy = x + wx0, y + wy0
        apothem = s * SQRT3 / 2
        dots = np.stack(
            [
                (x * math.cos(math.radians(a)) + y * math.sin(math.radians(a))) / apothem
                for a in DIRECTION_ANGLES
            ],
            axis=-1,
        )
        nearest_edge = dots.argmax(-1)
        d = dots.max(-1)  # 0 center .. 1 edge

        def shades(terrain: str) -> list[np.ndarray]:
            b = base_color(terrain)
            return [
                np.array(hex_to_rgb(nearest_palette(shade(b, f), palette)), dtype=np.float32)
                for f in (0.75, 1.0, 1.2)
            ]

        biome_sh = shades(biome)
        edge_sh = [shades(e["terrain"]) for e in edges]

        n1 = _value_noise(wx, wy, 5.0, 1)
        n2 = _value_noise(wx, wy, 2.0, 2 + variant % 3)
        tex = 0.65 * n1 + 0.35 * n2
        bayer = BAYER4[(np.arange(P)[:, None] + int(wy0)) % 4, (np.arange(P)[None, :] + int(wx0)) % 4]

        img = np.zeros((P, P, 3), dtype=np.float32)
        t = np.clip((d - 0.42) / 0.40, 0, 1)
        t = t * t * (3 - 2 * t)
        use_edge = bayer < t
        level = np.where(tex < 0.38, 0, np.where(tex < 0.72, 1, 2))
        for li in range(3):
            m = level == li
            img[m] = biome_sh[li]
            for ei in range(6):
                me = m & use_edge & (nearest_edge == ei)
                img[me] = edge_sh[ei][li]

        # Connectors: straight paths from each connector edge's midpoint toward the center.
        conn_edges = [(i, cn) for i, e in enumerate(edges) for cn in e.get("connectors", [])]
        for i, cname in conn_edges:
            col = np.array(hex_to_rgb(nearest_palette(base_color(cname), palette)), dtype=np.float32)
            ang = math.radians(DIRECTION_ANGLES[i])
            mx, my = math.cos(ang) * apothem, math.sin(ang) * apothem
            # distance from segment center->midpoint
            L2 = mx * mx + my * my
            tt = np.clip((x * mx + y * my) / L2, 0, 1)
            dist = np.hypot(x - tt * mx, y - tt * my)
            width = max(1.2, P / 20)
            img[dist <= width] = col
            img[(dist <= width + 1) & (dist > width)] = col * 0.7
        if len(conn_edges) == 1:  # dead end: small pond/plaza at the center
            col = np.array(
                hex_to_rgb(nearest_palette(base_color(conn_edges[0][1]), palette)), dtype=np.float32
            )
            img[np.hypot(x, y) <= P / 9] = col

        # Props: trees for wooded biomes, generic landmarks for listed features.
        wooded = any(k in biome for k in ("forest", "jungle", "pine", "wood"))
        props: list[tuple[float, float, str]] = []
        if wooded:
            # Props stay inside the interior so the edge bands remain pure edge terrain.
            for k in range(9):
                ang = _hash01(q, r, k, 1) * 2 * math.pi
                rad = math.sqrt(_hash01(q, r, k, 2)) * 0.5 * apothem
                props.append((math.cos(ang) * rad, math.sin(ang) * rad, "tree"))
        for k, _feat in enumerate(h.get("features", [])[:2]):
            ang = _hash01(q, r, k, variant) * 2 * math.pi
            props.append((math.cos(ang) * s * 0.28, math.sin(ang) * s * 0.28, "landmark"))
        dark = np.array(hex_to_rgb(nearest_palette("#1b1b22", palette)), dtype=np.float32)
        for px_, py_, kind in props:
            if kind == "tree":
                leaf = np.array(
                    hex_to_rgb(nearest_palette(shade(base_color(biome), 0.6), palette)), dtype=np.float32
                )
                hi = np.array(
                    hex_to_rgb(nearest_palette(shade(base_color(biome), 1.25), palette)), dtype=np.float32
                )
                rr = max(1.5, P / 16)
                blob = np.hypot(x - px_, y - py_) <= rr
                img[np.hypot(x - px_ + 0.5, y - py_ + 0.5) <= rr + 0.7] = dark
                img[blob] = leaf
                img[np.hypot(x - px_ + rr / 3, y - py_ + rr / 3) <= rr / 2.2] = hi
            else:
                wall = np.array(hex_to_rgb(nearest_palette("#9a8f84", palette)), dtype=np.float32)
                roof = np.array(hex_to_rgb(nearest_palette("#8e3b46", palette)), dtype=np.float32)
                bw = max(2, P // 9)
                box = (np.abs(x - px_) <= bw) & (np.abs(y - py_) <= bw * 0.8)
                img[(np.abs(x - px_) <= bw + 1) & (np.abs(y - py_) <= bw * 0.8 + 1)] = dark
                img[box] = wall
                img[box & (y - py_ < 0)] = roof

        # Upscale + jitter: mimic generator output so the pixelizer is actually exercised.
        big = np.repeat(np.repeat(img, self.upscale, 0), self.upscale, 1)
        rng = np.random.default_rng(req.seed)
        big = np.clip(big + rng.normal(0, 5, big.shape), 0, 255).astype(np.uint8)
        out = Image.fromarray(big, "RGB")
        if out.width != req.size:
            out = out.resize((req.size, req.size), Image.Resampling.NEAREST)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()


# --------------------------------------------------------------------------- ComfyUI


class ComfyUIBackend:
    """Queues API-format workflow JSONs on a local ComfyUI server.

    Workflows live in services/comfyui/workflows/<name>.json and use string placeholders:
      "{{prompt}}", "{{negative}}", "{{seed}}", "{{width}}", "{{height}}",
      "{{context_image}}", "{{mask_image}}", "{{ref_image_1}}".. "{{ref_image_3}}"
    A value that is exactly a placeholder is replaced with a typed value (int for seed/size,
    uploaded filename for images); placeholders inside longer strings are substituted as text.
    """

    name = "comfyui"

    def __init__(self, base_url: str, workflow_dir: Path, timeout_s: float = 180.0):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.workflow_dir = Path(workflow_dir)
        self.timeout_s = timeout_s
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        self.client_id = uuid.uuid4().hex

    async def health(self) -> bool:
        try:
            r = await self._http.get("/system_stats", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def _workflow(self, name: str) -> dict[str, Any] | None:
        p = self.workflow_dir / f"{name}.json"
        if not p.exists():
            return None
        wf = json.loads(p.read_text(encoding="utf-8"))
        wf.pop("_comment", None)
        return wf

    async def _upload(self, png: bytes, stem: str) -> str:
        name = f"hexworld_{stem}_{hashlib.sha256(png).hexdigest()[:12]}.png"
        r = await self._http.post(
            "/upload/image", files={"image": (name, png, "image/png")}, data={"overwrite": "true"}
        )
        if r.status_code != 200:
            raise ImageBackendError(f"upload failed: {r.status_code} {r.text[:200]}")
        body = r.json()
        return f"{body['subfolder']}/{body['name']}" if body.get("subfolder") else body["name"]

    async def generate(self, req: ImageRequest) -> ImageResult:
        wf_name = "neighbor_inpaint" if req.mode == "inpaint" else "txt2img_tile"
        wf = self._workflow(wf_name)
        if wf is None and req.mode == "inpaint":
            wf_name, wf = "txt2img_tile", self._workflow("txt2img_tile")
        if wf is None:
            raise ImageBackendError(f"no workflow file for {wf_name} in {self.workflow_dir}")

        values: dict[str, Any] = {
            "prompt": req.prompt,
            "negative": req.negative,
            "seed": req.seed,
            "width": req.size,
            "height": req.size,
        }
        if req.context_png is not None:
            values["context_image"] = await self._upload(req.context_png, "ctx")
        if req.mask_png is not None:
            values["mask_image"] = await self._upload(req.mask_png, "mask")
        for i, ref in enumerate(req.style_refs[:3]):
            values[f"ref_image_{i + 1}"] = await self._upload(ref, f"ref{i + 1}")
        graph = _substitute(copy.deepcopy(wf), values)

        r = await self._http.post("/prompt", json={"prompt": graph, "client_id": self.client_id})
        if r.status_code != 200:
            raise ImageBackendError(f"/prompt rejected: {r.status_code} {r.text[:400]}")
        prompt_id = r.json()["prompt_id"]

        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            h = await self._http.get(f"/history/{prompt_id}")
            entry = h.json().get(prompt_id) if h.status_code == 200 else None
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ImageBackendError(f"workflow error: {json.dumps(status)[:400]}")
                for node_out in entry.get("outputs", {}).values():
                    for im in node_out.get("images", []):
                        v = await self._http.get(
                            "/view",
                            params={
                                "filename": im["filename"],
                                "subfolder": im.get("subfolder", ""),
                                "type": im.get("type", "output"),
                            },
                        )
                        return ImageResult(
                            png=v.content,
                            backend=self.name,
                            meta={
                                "workflow": wf_name,
                                "workflow_sha": _sha(wf),
                                "prompt_id": prompt_id,
                                "seed": req.seed,
                                "framing": "context" if wf_name == "neighbor_inpaint" else "tile",
                            },
                        )
                if status.get("completed"):
                    raise ImageBackendError("workflow completed without an image output")
            await asyncio.sleep(0.25)
        raise ImageBackendError(f"timed out after {self.timeout_s}s")


def _substitute(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {k: _substitute(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, values) for v in node]
    if isinstance(node, str) and "{{" in node:
        for k, v in values.items():
            ph = "{{" + k + "}}"
            if node == ph:
                return v
            node = node.replace(ph, str(v))
    return node


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- OpenAI images


class OpenAIImageBackend:
    name = "openai-image"

    def __init__(self, api_key: str | None, base_url: str | None, model: str):
        from openai import AsyncOpenAI

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set (required for the OpenAI image backend)")
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=1)
        self.model = model

    async def health(self) -> bool:
        return True

    async def generate(self, req: ImageRequest) -> ImageResult:
        prompt = f"{req.prompt}. Top-down game tile texture filling the whole frame. Avoid: {req.negative}"
        try:
            if req.mode == "inpaint" and req.context_png is not None:
                images = [("context.png", req.context_png, "image/png")]
                images += [(f"ref{i}.png", r, "image/png") for i, r in enumerate(req.style_refs[:2])]
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "image": images,
                    "prompt": prompt,
                    "size": "1024x1024",
                }
                if req.mask_png is not None:
                    kwargs["mask"] = ("mask.png", _mask_to_alpha(req.mask_png), "image/png")
                resp = await self._client.images.edit(**kwargs)
                framing = "context"
            else:
                resp = await self._client.images.generate(
                    model=self.model, prompt=prompt, size="1024x1024", n=1
                )
                framing = "tile"
        except Exception as e:
            raise ImageBackendError(f"openai image error: {e}") from e
        b64 = resp.data[0].b64_json
        if not b64:
            raise ImageBackendError("openai image response had no b64 data")
        return ImageResult(
            png=base64.b64decode(b64), backend=self.name, meta={"model": self.model, "framing": framing}
        )


def _mask_to_alpha(mask_png: bytes) -> bytes:
    """OpenAI edit masks are transparent where the image should be edited."""
    m = Image.open(io.BytesIO(mask_png)).convert("L")
    rgba = Image.new("RGBA", m.size, (0, 0, 0, 255))
    rgba.putalpha(Image.eval(m, lambda v: 255 - v))
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- circuit breaker


class FallbackImageBackend:
    """Primary with a circuit breaker: after `threshold` consecutive failures the primary is skipped
    for `cooldown_s`, and requests go straight to the fallback."""

    def __init__(
        self, primary: ImageBackend, fallback: ImageBackend | None, threshold: int = 3, cooldown_s: float = 60
    ):
        self.primary = primary
        self.fallback = fallback
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._open_until = 0.0
        self.name = primary.name if fallback is None else f"{primary.name}>{fallback.name}"

    @property
    def circuit_open(self) -> bool:
        return time.monotonic() < self._open_until

    async def health(self) -> bool:
        return await self.primary.health()

    async def generate(self, req: ImageRequest) -> ImageResult:
        if not self.circuit_open:
            try:
                res = await self.primary.generate(req)
                self._failures = 0
                return res
            except Exception as e:
                self._failures += 1
                if self._failures >= self.threshold:
                    self._open_until = time.monotonic() + self.cooldown_s
                if self.fallback is None:
                    raise
                res = await self.fallback.generate(req)
                res.meta["fallback_reason"] = str(e)[:200]
                return res
        if self.fallback is None:
            raise ImageBackendError("primary image backend circuit open and no fallback configured")
        res = await self.fallback.generate(req)
        res.meta["fallback_reason"] = "circuit open"
        return res
