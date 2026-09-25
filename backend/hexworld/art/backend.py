"""Image generation backends behind one protocol.

- ProceduralBackend: deterministic, offline, seam-consistent procedural pixel-art ground (default)
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
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
from PIL import Image


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
    height_png: bytes | None = None  # relief levels on the tile canvas (procedural ground only)


class ImageBackend(Protocol):
    name: str

    async def generate(self, req: ImageRequest) -> ImageResult: ...

    async def health(self) -> bool: ...


class ImageBackendError(Exception):
    pass


# --------------------------------------------------------------------------- procedural


class ProceduralBackend:
    """Offline pixel-art ground renderer (see art/procedural.py). It is driven by structured
    hints (biome, edge contract, connectors) instead of the text prompt, so it is deterministic,
    free, and seamless by construction. It returns the ground layer only; props are sprite layers."""

    name = "procedural"
    deterministic_ground = True  # same hints -> same pixels: copies can be re-rendered in place

    def __init__(self, latency_s: float = 0.25):
        self.latency_s = latency_s

    async def health(self) -> bool:
        return True

    async def generate(self, req: ImageRequest) -> ImageResult:
        if self.latency_s:
            await asyncio.sleep(self.latency_s * (0.6 + 0.8 * ((req.seed % 997) / 997)))
        png, height_png = await asyncio.to_thread(self._render, req)
        return ImageResult(
            png=png,
            backend=self.name,
            meta={"seed": req.seed, "framing": "canvas", "crisp": True},
            height_png=height_png,
        )

    def _render(self, req: ImageRequest) -> tuple[bytes, bytes]:
        from hexworld.art.procedural import render_ground
        from hexworld.art.relief import levels_to_png

        h = req.hints
        rgb, heights = render_ground(
            tile_px=h["tile_px"],
            biome=h["biome"],
            edges=h["edges"],
            coord=tuple(h["coord"]),
            materials=h.get("materials"),
        )
        up = max(1, req.size // rgb.shape[0])
        big = np.repeat(np.repeat(rgb, up, 0), up, 1)
        buf = io.BytesIO()
        Image.fromarray(big, "RGB").save(buf, format="PNG")
        return buf.getvalue(), levels_to_png(heights)


ProceduralStubBackend = ProceduralBackend  # backwards-compatible name


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
    def deterministic_ground(self) -> bool:
        return getattr(self.primary, "deterministic_ground", False) and not self.circuit_open

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
