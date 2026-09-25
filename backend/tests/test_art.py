import io
import math

import numpy as np
import pytest
from PIL import Image

from hexworld.agents.themes import palette_for
from hexworld.art.backend import ComfyUIBackend, ImageRequest, ProceduralStubBackend, _substitute
from hexworld.art.composite import context_canvas, crop_target, render_region
from hexworld.art.pixelize import hex_mask, load_tile, pixelize, seam_delta
from hexworld.hex import Hex

PALETTE = palette_for(["water", "sand", "grass", "forest", "rock"], ["road", "river"])


def test_hex_mask_area():
    m = hex_mask(48)
    s = 24
    expected = (3 * math.sqrt(3) / 2 * s * s) / (48 * 48)
    assert abs(m.mean() - expected) < 0.02
    assert m[24, 24] and not m[0, 0] and not m[2, 47]


async def _stub_tile(q, r, biome, edges, px=48, seed=1):
    req = ImageRequest(
        prompt="",
        negative="",
        seed=seed,
        size=px * 4,
        hints={
            "tile_px": px,
            "palette": PALETTE,
            "biome": biome,
            "coord": (q, r),
            "features": [],
            "edges": [{"terrain": t, "connectors": c} for t, c in edges],
        },
    )
    res = await ProceduralStubBackend(latency_s=0).generate(req)
    return pixelize(res.png, PALETTE, px)


async def test_pixelize_uses_only_palette_colors_and_masks_hex():
    pix = await _stub_tile(0, 0, "grass", [("grass", [])] * 6)
    pal = {tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in PALETTE}
    opaque = pix.rgba[..., 3] == 255
    colors = {tuple(int(v) for v in px) for px in pix.rgba[opaque][:, :3]}
    assert colors <= pal
    assert not (pix.rgba[..., 3][~hex_mask(48)]).any()
    assert pix.coverage > 0.97
    assert pix.distinct_colors >= 3


async def test_seams_low_when_edges_agree_high_when_not():
    a = await _stub_tile(0, 0, "grass", [("grass", [])] * 6)
    b = await _stub_tile(1, 0, "grass", [("grass", [])] * 6, seed=2)  # east neighbor of a
    c = await _stub_tile(1, 0, "water", [("water", [])] * 6, seed=3)
    assert seam_delta(a.rgba, 0, b.rgba) < 0.3
    assert seam_delta(a.rgba, 0, c.rgba) > 0.6
    # symmetric
    assert seam_delta(a.rgba, 0, b.rgba) == pytest.approx(seam_delta(b.rgba, 3, a.rgba), abs=0.05)


async def test_connectors_meet_across_edges():
    road = [("grass", [])] * 6
    a_edges = list(road)
    a_edges[0] = ("grass", ["road"])
    b_edges = list(road)
    b_edges[3] = ("grass", ["road"])
    a = await _stub_tile(0, 0, "grass", a_edges)
    b = await _stub_tile(1, 0, "grass", b_edges)
    assert seam_delta(a.rgba, 0, b.rgba) < 0.3


async def test_context_canvas_and_crop_roundtrip():
    a = await _stub_tile(1, 0, "grass", [("grass", [])] * 6)
    ctx, mask = context_canvas(Hex(0, 0), {Hex(1, 0): a.rgba}, 48, 432)
    ctx_img, mask_img = Image.open(io.BytesIO(ctx)), Image.open(io.BytesIO(mask))
    assert ctx_img.size == mask_img.size == (432, 432)
    m = np.asarray(mask_img)
    assert m[216, 216] == 255 and m[0, 0] == 0
    crop = Image.open(io.BytesIO(crop_target(ctx, 48)))
    assert crop.size == (144, 144)


def test_render_region_labels():
    img = render_region(
        {Hex(0, 0): np.zeros((48, 48, 4), np.uint8)}, tile_px=48, labels={Hex(0, 0): 1}, scale=2
    )
    assert img.width > 0 and img.height > 0


def test_comfy_placeholder_substitution():
    wf = {"1": {"inputs": {"seed": "{{seed}}", "text": "a {{prompt}} b", "image": "{{context_image}}"}}}
    out = _substitute(wf, {"seed": 42, "prompt": "castle", "context_image": "x.png"})
    assert out["1"]["inputs"] == {"seed": 42, "text": "a castle b", "image": "x.png"}


def test_comfy_workflow_templates_parse(tmp_path):
    from hexworld.config import REPO_ROOT

    backend = ComfyUIBackend("http://127.0.0.1:1", REPO_ROOT / "services" / "comfyui" / "workflows")
    for name in ("txt2img_tile", "neighbor_inpaint"):
        wf = backend._workflow(name)
        assert wf is not None, name
        flat = str(wf)
        assert "{{prompt}}" in flat and "{{seed}}" in flat


def test_load_tile_roundtrip():
    arr = np.zeros((8, 8, 4), np.uint8)
    arr[2:4, 2:4] = (255, 0, 0, 255)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, format="PNG")
    assert (load_tile(buf.getvalue()) == arr).all()
