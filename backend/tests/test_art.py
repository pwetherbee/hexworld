import io

import numpy as np
from PIL import Image

from hexworld.art.backend import ComfyUIBackend, ImageRequest, ProceduralBackend, _substitute
from hexworld.art.composite import context_canvas, crop_target, render_region
from hexworld.art.grid import TileCanvas, seam_delta
from hexworld.art.paint import pixelize_sprite
from hexworld.art.pixelize import crisp_tile, load_tile
from hexworld.art.procedural import fallback_material, render_ground
from hexworld.art.relief import load_levels
from hexworld.domain.art import HeightOp
from hexworld.hex import Hex

P = 64


async def _tile(q, r, biome, edges, materials=None):
    req = ImageRequest(
        prompt="",
        negative="",
        seed=1,
        size=512,
        hints={
            "tile_px": P,
            "biome": biome,
            "coord": (q, r),
            "materials": materials or {},
            "edges": [{"terrain": t, "connectors": c} for t, c in edges],
        },
    )
    res = await ProceduralBackend(latency_s=0).generate(req)
    return crisp_tile(res.png, TileCanvas(Hex(q, r), P)), res


def test_canvases_share_one_world_grid():
    for h in (Hex(0, 0), Hex(1, 0), Hex(-3, 2), Hex(5, -7)):
        c = TileCanvas(h, P)
        ox, oy = c.origin
        cx, cy = c.center
        assert isinstance(ox, int) and isinstance(oy, int)
        assert ox <= cx - c.s - 1 and oy <= cy - c.s - 1
        assert ox + c.C >= cx + c.s + 1 and oy + c.C >= cy + c.s + 1
        assert abs(c.mask().sum() - 2.598 * c.s**2) < 0.03 * 2.598 * c.s**2


def test_neighbours_paint_identical_world_pixels_near_the_shared_edge():
    edges = [{"terrain": "grass", "connectors": []}] * 6
    a_rgb, _ = render_ground(tile_px=P, biome="grass", edges=edges, coord=(0, 0))
    b_rgb, _ = render_ground(tile_px=P, biome="grass", edges=edges, coord=(1, 0))
    ca, cb = TileCanvas(Hex(0, 0), P), TileCanvas(Hex(1, 0), P)
    (ax, ay), (bx, by) = ca.origin, cb.origin
    compared = same = 0
    for j in range(ca.C):
        for i in range(ca.C):
            bi, bj = ax + i - bx, ay + j - by
            if 0 <= bi < cb.C and 0 <= bj < cb.C and not ca.mask()[j, i] and cb.mask()[bj, bi]:
                compared += 1
                same += int((a_rgb[j, i] == b_rgb[bj, bi]).all())
    assert compared > 20 and same / compared > 0.95


async def test_crisp_tile_masks_hex_and_seams_are_continuous():
    a, _ = await _tile(0, 0, "grass", [("grass", [])] * 6)
    b, _ = await _tile(1, 0, "grass", [("grass", [])] * 6)
    w, _ = await _tile(1, 0, "water", [("water", [])] * 6)
    ca, cb = TileCanvas(Hex(0, 0), P), TileCanvas(Hex(1, 0), P)
    assert not a.rgba[..., 3][~ca.mask()].any() and a.coverage > 0.97
    assert seam_delta(a.rgba, ca, 0, b.rgba, cb) < 0.2  # same texture continuing (organic patches)
    assert seam_delta(a.rgba, ca, 0, w.rgba, cb) > 0.4
    assert abs(seam_delta(a.rgba, ca, 0, b.rgba, cb) - seam_delta(b.rgba, cb, 3, a.rgba, ca)) < 0.05


async def test_procedural_ground_exports_block_relief():
    spec = fallback_material("crags").model_copy(
        update={"height": 2, "height_ops": [HeightOp(op="patches", scale=16, amount=0.5, delta=2)]}
    )
    _, res = await _tile(0, 0, "crags", [("crags", [])] * 6, materials={"crags": spec.model_dump()})
    h = load_levels(res.height_png)
    assert h.min() >= 2 and h.max() == 4
    ox, oy = TileCanvas(Hex(0, 0), P).origin
    blocks: dict = {}
    for j in range(h.shape[0]):
        for i in range(h.shape[1]):
            blocks.setdefault(((ox + i) // 2, (oy + j) // 2), set()).add(int(h[j, i]))
    assert all(len(v) == 1 for v in blocks.values())  # relief is constant per 2px art cell


def test_pixelize_sprite_crops_scales_and_outlines():
    img = np.zeros((1024, 1024, 4), np.uint8)
    img[300:900, 400:600] = (200, 60, 40, 255)
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, format="PNG")
    art = pixelize_sprite(buf.getvalue(), "large")
    assert art.h == 36 + 2 and art.w <= 32  # target height + 1px outline each side
    fr = art.frames[0]
    assert fr[..., 3].any() and (fr[..., 3] == 0).any()


async def test_context_canvas_and_crop_roundtrip():
    a, _ = await _tile(1, 0, "grass", [("grass", [])] * 6)
    ctx, mask = context_canvas(Hex(0, 0), {Hex(1, 0): a.rgba}, P, 576)
    ctx_img, mask_img = Image.open(io.BytesIO(ctx)), Image.open(io.BytesIO(mask))
    assert ctx_img.size == mask_img.size == (576, 576)
    m = np.asarray(mask_img)
    assert m[288, 288] == 255 and m[0, 0] == 0
    assert Image.open(io.BytesIO(crop_target(ctx, P))).size == (192, 192)


def test_render_region_labels():
    img = render_region(
        {Hex(0, 0): np.zeros((P + 3, P + 3, 4), np.uint8)}, tile_px=P, labels={Hex(0, 0): 1}, scale=2
    )
    assert img.width > 0 and img.height > 0


def test_comfy_placeholder_substitution():
    wf = {"1": {"inputs": {"seed": "{{seed}}", "text": "a {{prompt}} b", "image": "{{context_image}}"}}}
    out = _substitute(wf, {"seed": 42, "prompt": "castle", "context_image": "x.png"})
    assert out["1"]["inputs"] == {"seed": 42, "text": "a castle b", "image": "x.png"}


def test_comfy_workflow_templates_parse():
    from hexworld.config import REPO_ROOT

    backend = ComfyUIBackend("http://127.0.0.1:1", REPO_ROOT / "services" / "comfyui" / "workflows")
    for name in ("txt2img_tile", "neighbor_inpaint"):
        wf = backend._workflow(name)
        assert wf is not None, name
        assert "{{prompt}}" in str(wf) and "{{seed}}" in str(wf)


def test_load_tile_roundtrip():
    arr = np.zeros((8, 8, 4), np.uint8)
    arr[2:4, 2:4] = (255, 0, 0, 255)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, format="PNG")
    assert (load_tile(buf.getvalue()) == arr).all()


async def test_heightmap_marks_liquid_surfaces():
    water = fallback_material("water").model_copy(update={"liquid": True, "height": 0, "height_ops": []})
    _, res = await _tile(0, 0, "grass", [("water", [])] * 6, materials={"water": water.model_dump()})
    rgb = np.asarray(Image.open(io.BytesIO(res.height_png)).convert("RGB"))
    liquid = rgb[..., 1] > 127
    c = TileCanvas(Hex(0, 0), P)
    assert liquid[c.mask()].any() and not liquid[c.C // 2, c.C // 2]  # water band, grass centre
    assert (load_levels(res.height_png)[liquid] == 0).all()
