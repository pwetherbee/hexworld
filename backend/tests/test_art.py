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


def test_image_cost_uses_image_model_prices():
    from hexworld.agents.llm import estimate_image_cost

    usage = {"text_input_tokens": 200, "image_input_tokens": 0, "output_tokens": 1000}
    assert abs(estimate_image_cost("gpt-image-2.5-flare", usage) - (200 * 5 + 1000 * 30) / 1e6) < 1e-12


def _sheet(cells: list[tuple[int, int, int, int] | None], spill: bool = False) -> bytes:
    a = np.zeros((1024, 1024, 4), np.uint8)
    for i, box in enumerate(cells):
        if box is None:
            continue
        y0, x0 = (i // 2) * 512, (i % 2) * 512
        top, left, bottom, right = box
        a[y0 + top : y0 + bottom, x0 + left : x0 + right] = (200, 80, 40, 255)
    if spill:
        a[100:300, 480:540] = (10, 200, 10, 255)  # an object crossing the vertical centre line
    buf = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def test_sprite_sheet_splits_into_quadrants_and_flags_bad_cells():
    from hexworld.art.paint import split_sheet

    ok = split_sheet(_sheet([(100, 100, 400, 400)] * 4), 4)
    assert all(c is not None for c in ok)
    assert pixelize_sprite(ok[3], "medium").h == 24 + 2
    cells = split_sheet(_sheet([(100, 100, 400, 400), None, (100, 100, 400, 400)], spill=True), 3)
    assert cells[0] is None and cells[1] is None and cells[2] is not None  # spilled, empty, fine


async def test_sheet_painter_batches_concurrent_requests():
    import asyncio

    from hexworld.art.paint import SheetPainter

    class Fake:
        model = "gpt-image-2.5-flare"
        calls: list[str] = []

        async def paint(self, prompt: str):
            self.calls.append(prompt)
            await asyncio.sleep(0.01)
            if prompt.startswith("A 2x2 sprite sheet"):
                return _sheet([(100, 100, 400, 400)] * 3), {"output_tokens": 300}
            return _sheet([(100, 100, 400, 400)]), {"output_tokens": 200}

    fake = Fake()
    sp = SheetPainter(fake, window_s=0.05)  # type: ignore[arg-type]
    results = await asyncio.gather(*[sp.paint_subject(s, None) for s in ("barn", "pumpkin", "tree")])
    assert len(fake.calls) == 1 and all(png for png, _ in results)
    assert all(u["output_tokens"] == 100 and u["sheet"] == 3 for _, u in results)
    alone = await sp.paint_subject("windmill", None)
    assert len(fake.calls) == 2 and "Subject: windmill" in fake.calls[1] and alone[1]["output_tokens"] == 200


def _mat(ops, hops=(), height=1, **kw):
    from hexworld.domain.art import MaterialSpec

    return MaterialSpec(
        base_color="#8a6a50",
        accent_color="#ffcc66",
        base_tone="base",
        liquid=False,
        rank=5,
        boundary="lip",
        block_style="bevel",
        height=height,
        height_ops=list(hops),
        ops=list(ops),
        scatter=[],
        **kw,
    )


def _pop(kind, scale, amount=0.5, tone="dark"):
    from hexworld.domain.art import PatternOp

    return PatternOp(op=kind, tone=tone, scale=scale, amount=amount, angle=0, pixels=[])


def test_built_ops_raise_buildings_and_walls():
    from hexworld.art.relief import split_levels

    city = _mat([_pop("lots", 18, 0.9, "base")], [HeightOp(op="lots", scale=18, amount=0.9, delta=2)])
    _, h = render_ground(
        tile_px=P,
        biome="block",
        edges=[{"terrain": "block", "connectors": []}] * 6,
        coord=(0, 0),
        materials={"block": city},
    )
    lv = split_levels(h)[0][TileCanvas(Hex(0, 0), P).mask()]
    assert (lv == 1).mean() > 0.15 and (lv >= 3).mean() > 0.4  # alleys low, buildings up
    hall = _mat(
        [_pop("planks", 12), _pop("rooms", 24, 0.6, "outline")],
        [HeightOp(op="rooms", scale=24, amount=0.6, delta=3)],
    )
    _, h = render_ground(
        tile_px=P,
        biome="hall",
        edges=[{"terrain": "hall", "connectors": []}] * 6,
        coord=(0, 0),
        materials={"hall": hall},
    )
    lv = split_levels(h)[0][TileCanvas(Hex(0, 0), P).mask()]
    assert 0.08 < (lv == 4).mean() < 0.4  # thin walls, mostly floor


def test_straight_connectors_run_straight():
    ground = _mat([])
    street = _mat([], edges="straight").model_copy(update={"base_color": "#202020"})
    edges = [{"terrain": "g", "connectors": ["street"] if i in (0, 3) else []} for i in range(6)]
    rgb, _ = render_ground(
        tile_px=P, biome="g", edges=edges, coord=(2, -1), materials={"g": ground, "street": street}
    )
    c = TileCanvas(Hex(2, -1), P)
    dark = (rgb.max(-1) < 60) & c.mask()
    rows = np.nonzero(dark.any(1))[0]
    assert dark.any() and rows.max() - rows.min() <= 12  # a straight E-W band, not a meander


def test_buildings_rise_in_floors_with_facades_and_streets():
    from hexworld.art.procedural import render_ground_full
    from hexworld.art.relief import (
        FACADE_STYLES,
        facade_codes,
        levels_to_png,
        load_heightmap,
        relief_shade,
        split_levels,
    )
    from hexworld.domain.art import BuildingsSpec

    towers = _mat([]).model_copy(
        update={
            "buildings": BuildingsSpec(
                layout="towers",
                lot_px=16,
                street_grid=1,
                floors_min=12,
                floors_max=36,
                wall_colors=["#7fa7c9", "#c8ccd2"],
                roof_colors=["#6f747d"],
                facade="glass",
                roof="terrace",
            )
        }
    )
    rgb, packed, fac = render_ground_full(
        tile_px=P,
        biome="dt",
        edges=[{"terrain": "dt", "connectors": []}] * 6,
        coord=(1, -1),
        materials={"dt": towers},
    )
    m = TileCanvas(Hex(1, -1), P).mask()
    lv, liquid = split_levels(packed)
    codes = facade_codes(packed)
    built = codes > 0
    assert built[m].mean() > 0.3 and (~built[m]).mean() > 0.1  # buildings and streets both present
    assert lv[m].max() >= 12 and not liquid.any()  # tall towers, far above the old 0-4 range
    assert ((codes[built] >> 5) == FACADE_STYLES.index("glass")).all()
    assert fac[built].std() > 0  # wall colours painted
    # the PNG round-trip keeps levels, facade codes and the liquid flag
    assert (load_heightmap(levels_to_png(packed)) == packed).all()
    shaded = relief_shade(rgb, packed, facade=fac)
    assert shaded.shape == rgb.shape and not (shaded == rgb).all()


def test_building_kinds_are_not_sprites():
    from hexworld.domain.art import is_building_kind

    for k in (
        "house",
        "Victorian Houses",
        "brick_warehouse",
        "glass skyscraper",
        "old church",
        "painted ladies",
    ):
        assert is_building_kind(k), k
    for k in ("cable car", "street vendor", "apple tree", "windmill", "lighthouse", "fountain", "seagull"):
        assert not is_building_kind(k), k


def test_straight_connectors_form_a_square_grid_across_tiles():
    ground = _mat([])
    street = _mat([], edges="straight").model_copy(update={"base_color": "#202020", "markings": "dashed"})
    mats = {"g": ground, "street": street}
    a, b = Hex(0, 0), Hex(0, 0).neighbor(1)  # NE neighbour; the street crosses their shared edge
    ea = [{"terrain": "g", "connectors": ["street"] if i == 1 else []} for i in range(6)]
    eb = [{"terrain": "g", "connectors": ["street"] if i == 4 else []} for i in range(6)]
    ra, _ = render_ground(tile_px=P, biome="g", edges=ea, coord=(a.q, a.r), materials=mats)
    rb, _ = render_ground(tile_px=P, biome="g", edges=eb, coord=(b.q, b.r), materials=mats)
    ca, cb = TileCanvas(a, P), TileCanvas(b, P)
    # the edge midpoint in world pixels: both tiles pave the same horizontal run through it
    (ax, ay), (bx, by) = ca.center, cb.center
    mx, my = (ax + bx) / 2, (ay + by) / 2
    for dx in (-3, 3):
        i, j = ca.to_canvas(mx + dx, my)
        k, l_ = cb.to_canvas(mx + dx, my)
        on_a = ca.mask()[j, i] and ra[j, i].max() < 90
        on_b = cb.mask()[l_, k] and rb[l_, k].max() < 90
        assert on_a or on_b  # whichever tile owns the pixel paints road there
    # and the leg leaves the centre going north (axis-aligned), not diagonally
    i, j = ca.to_canvas(ax + 0.5, ay - P * 0.25)
    assert ra[j, i].max() < 90


def test_city_grids_share_one_street_lattice_across_districts():
    from hexworld.art.procedural import lattice
    from hexworld.domain.art import BuildingsSpec

    def district(layout: str, grid: int):
        b = BuildingsSpec(
            layout=layout,
            lot_px=12,
            street_grid=grid,
            street_material="street",
            wall_colors=["#c0a080"],
            roof_colors=["#a05040"],
            facade="punched",
        )
        return _mat([], edges="straight").model_copy(update={"buildings": b, "base_color": "#b0b0b0"})

    street = _mat([], edges="straight").model_copy(update={"base_color": "#101010"})
    mats = {"rows": district("rows", 1), "towers": district("towers", 2), "street": street}
    X, Y = lattice(P)
    for h, biome in ((Hex(0, 0), "rows"), (Hex(1, 0), "towers")):
        rgb, _ = render_ground(
            tile_px=P,
            biome=biome,
            edges=[{"terrain": biome, "connectors": []}] * 6,
            coord=(h.q, h.r),
            materials=mats,
        )
        c = TileCanvas(h, P)
        wx, wy = c.world_xy()
        # the lattice line through both tile centres (y = 0) is paved in the street material
        row = c.mask() & (np.abs(wy) < 1) & (np.abs(wx - h.to_pixel(P / 2)[0]) < P * 0.4)
        assert row.sum() > 10 and (rgb[row].max(-1) < 60).mean() > 0.9
        # and so is the vertical line through each centre (every district has streets on even lines)
        col = c.mask() & (np.abs(wx - h.to_pixel(P / 2)[0]) < 1) & (np.abs(wy) < P * 0.4)
        assert (rgb[col].max(-1) < 60).mean() > 0.9
    assert X > 20 and Y > 20


def test_elevation_rises_into_mountains_and_stays_continuous_across_edges():
    from hexworld.art.relief import split_levels
    from hexworld.hex import within

    mats = {
        "meadow": _mat([]).model_copy(update={"elevation": 1}),
        "slope": _mat([]).model_copy(update={"elevation": 12, "base_color": "#707070"}),
        "peak": _mat([]).model_copy(update={"elevation": 32, "base_color": "#f0f0f0"}),
    }
    rank = {"meadow": 0, "slope": 1, "peak": 2}

    def biome(h: Hex) -> str:
        return "peak" if h.r <= -1 else "slope" if h.r == 0 and h.q > 0 else "meadow"

    hexes = list(within(Hex(0, 0), 2))
    out, cv = {}, {}
    for h in hexes:
        b = biome(h)
        # the contract: an edge's terrain is agreed by both sides (here: the higher of the two)
        edges = [{"terrain": max(b, biome(h.neighbor(i)), key=rank.get), "connectors": []} for i in range(6)]
        out[h] = split_levels(
            render_ground(tile_px=P, biome=b, edges=edges, coord=(h.q, h.r), materials=mats)[1]
        )[0]
        cv[h] = TileCanvas(h, P)
    assert max(int(out[h].max()) for h in hexes if biome(h) == "peak") >= 20  # real mountains
    worst = 0.0
    for h in hexes:
        for e in range(3):
            n = h.neighbor(e)
            if n not in out:
                continue
            ca, cb = cv[h], cv[n]
            (ax, ay), (bx, by) = ca.origin, cb.origin
            x0, x1, y0, y1 = max(ax, bx), min(ax + ca.C, bx + cb.C), max(ay, by), min(ay + ca.C, by + cb.C)
            sa = (slice(y0 - ay, y1 - ay), slice(x0 - ax, x1 - ax))
            sb = (slice(y0 - by, y1 - by), slice(x0 - bx, x1 - bx))
            near = ca.mask()[sa] & cb.mask()[sb]  # the pixels both canvases treat as their own rim
            if near.any():
                d = np.abs(out[h][sa].astype(int) - out[n][sb].astype(int))[near]
                worst = max(worst, float(d.mean()))
    assert worst < 2.0


def test_a_lens_shows_the_parents_buildings_up_close():
    """Through a drilled layer's lens a tile shows a slice of a few big parent buildings, not a
    fresh block of small ones; the lens never reaches the agents' schema."""
    from hexworld.art.procedural import render_ground_full
    from hexworld.art.relief import facade_codes
    from hexworld.domain.art import BuildingsSpec, Lens, MaterialSpec
    from hexworld.game.layers import _components

    P = 64
    b = BuildingsSpec(
        layout="blocks",
        lot_px=18,
        street_grid=1,
        wall_colors=["#8a6a5a"],
        roof_colors=["#444444"],
        facade="punched",
    )
    city = _mat([]).model_copy(update={"buildings": b})
    lens = Lens(x=0, y=0, factor=7, k=1, levels=3.5, source="city", buildings=b)

    def buildings(spec: MaterialSpec) -> tuple[int, float]:
        _, packed, _ = render_ground_full(
            tile_px=P,
            biome="city",
            edges=[{"terrain": "city", "connectors": []}] * 6,
            coord=(0, 1),
            materials={"city": spec},
        )
        m = TileCanvas(Hex(0, 1), P).mask()
        built = (facade_codes(packed) > 0) & m
        comp = _components(built)
        return len({int(c) for c in comp[built]}), float(built.sum()) / max(
            1, len({int(c) for c in comp[built]})
        )

    n_own, size_own = buildings(city)
    n_zoom, size_zoom = buildings(city.model_copy(update={"lens": lens}))
    assert n_own >= 5 and n_zoom <= 3  # slices of a few big buildings, clipped by the tile
    assert "lens" not in str(MaterialSpec.model_json_schema())
