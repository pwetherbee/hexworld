from hexworld.domain import Layout, PlannedTile, ShapeSpec
from hexworld.hex import ORIGIN, Hex
from hexworld.orchestrator.layout import hex_line, rasterize, shape_cells


def _lay(**kw) -> Layout:
    base = {
        "regions": [
            {
                "name": "sea",
                "biome": "water",
                "intent": "open sea",
                "shapes": [{"kind": "blob", "center": {"q": 0, "r": 0}, "radius": 5, "roughness": 0.5}],
                "fill": "shallow_copy",
            },
            {
                "name": "ridge",
                "biome": "hills",
                "intent": "a long ridge",
                "shapes": [
                    {
                        "kind": "path",
                        "points": [{"q": -4, "r": 2}, {"q": 0, "r": 0}, {"q": 8, "r": -4}],
                        "width": 1,
                    }
                ],
            },
            {
                "name": "bay",
                "biome": "water",
                "intent": "gap",
                "mode": "void",
                "shapes": [{"kind": "hex", "center": {"q": 2, "r": 2}, "radius": 1}],
            },
        ],
        "landmarks": [{"q": 8, "r": -4, "intent": "watchtower on the cape", "features": ["watchtower"]}],
        "routes": [{"connector": "road", "points": [{"q": -4, "r": 2}, {"q": 0, "r": 0}]}],
    }
    base.update(kw)
    return Layout.model_validate(base)


def _run(layout, max_tiles=60, occupied=frozenset()):
    return rasterize(
        layout,
        origin=ORIGIN,
        origin_tile=None,
        max_tiles=max_tiles,
        world_radius=64,
        occupied=set(occupied),
        connectors={"road"},
    )


def test_shapes():
    assert len(shape_cells(ShapeSpec(kind="hex", center={"q": 0, "r": 0}, radius=2), 0)) == 19
    assert len(shape_cells(ShapeSpec(kind="rect", center={"q": 0, "r": 0}, w=4, h=3), 0)) == 12
    line = hex_line(Hex(0, 0), Hex(5, -2))
    assert len(line) == 6 and all(a.distance(b) == 1 for a, b in zip(line, line[1:], strict=False))


def test_layout_is_capped_keeps_landmarks_and_carves_voids():
    res = _run(_lay(), max_tiles=30)
    hexes = {Hex(t.q, t.r) for t in res.tiles}
    assert len(res.tiles) == 30 and res.dropped_over_cap > 0
    assert ORIGIN in hexes and Hex(8, -4) in hexes  # the far landmark survives the cap
    assert Hex(2, 2) not in hexes  # void
    tower = next(t for t in res.tiles if (t.q, t.r) == (8, -4))
    assert tower.features == ["watchtower"] and tower.priority == 5


def test_routes_become_matching_edge_hints_and_filler_copies():
    res = _run(_lay(), max_tiles=80)
    by = {Hex(t.q, t.r): t for t in res.tiles}
    hinted = 0
    for h, t in by.items():
        for eh in t.edge_hints:
            n = by[h.neighbor(eh.edge)]
            other = next(x for x in n.edge_hints if x.edge == (eh.edge + 3) % 6)
            assert other.connectors == eh.connectors == ["road"]
            hinted += 1
    assert hinted >= 8
    copies = [t for t in res.tiles if t.duplicate.mode == "shallow"]
    assert copies and all(by[t.duplicate.source].duplicate.mode == "none" for t in copies)


def test_occupied_tiles_are_skipped_and_origin_tile_kept():
    origin_tile = PlannedTile(q=0, r=0, biome="town", intent="the seed tile", features=["well"])
    res = rasterize(
        _lay(),
        origin=ORIGIN,
        origin_tile=origin_tile,
        max_tiles=80,
        world_radius=64,
        occupied={Hex(1, 0), Hex(0, 0)},
        connectors={"road"},
    )
    by = {Hex(t.q, t.r): t for t in res.tiles}
    assert Hex(1, 0) not in by and by[ORIGIN].biome == "town" and by[ORIGIN].features == ["well"]
