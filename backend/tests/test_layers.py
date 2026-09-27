from hexworld.domain import RunOptions, RunStatus, TileStatus
from hexworld.game.layers import hex_count


async def test_entering_a_tile_builds_its_region_and_scenes_are_painted_once(make_runtime):
    rt = make_runtime(fake_reject_rate=0.0)
    world = rt.create_world()
    run = await rt.wait((await rt.start_run(world.id, 0, 0, "A temperate kingdom", RunOptions(radius=1))).id)
    assert run.status == RunStatus.completed, run.error

    child, crun = await rt.layers.enter(world.id, 0, 0, radius=2)
    assert child.parent and child.parent.world_id == world.id and child.depth == 1
    assert child.style == rt.store.get_world(world.id).style  # one art direction across layers
    assert crun is not None
    crun = await rt.wait(crun.id)
    assert crun.status == RunStatus.completed, crun.error
    tiles = [t for t in rt.store.list_tiles(child.id) if t.status == TileStatus.accepted]
    assert len(tiles) == hex_count(2)  # the whole hexagon, no gaps
    assert rt.store.list_drills(world.id) == {"0,0": child.id}

    again, none = await rt.layers.enter(world.id, 0, 0)
    assert again.id == child.id and none is None  # entering again reuses the layer

    skirt = await rt.layers.skirt(child.id)  # the region's terrain continues two rings past its rim
    assert len(skirt) == 6 * 3 + 6 * 4 and {s.ring for s in skirt} == {1, 2}
    assert all(rt.store.get_asset(s.asset_id) for s in skirt)
    assert await rt.layers.skirt(world.id) == []  # the overworld has no skirt

    scene = await rt.layers.scene(child.id, 1, 0)
    assert scene.layers and scene.layers[0].role == "backdrop"
    assert rt.store.get_asset(scene.layers[0].asset_id)
    assert (await rt.layers.scene(child.id, 1, 0)).created_at == scene.created_at  # painted once
    assert all(w.depth == 0 for w in [rt.store.get_world(world.id)])


def test_a_parents_streets_become_straight_chains_of_region_tiles():
    import numpy as np

    from hexworld.art.grid import TileCanvas
    from hexworld.art.procedural import street_half
    from hexworld.game.layers import street_chains
    from hexworld.hex import ORIGIN, SQRT3, Hex

    P, R = 64, 3
    canvas = TileCanvas(ORIGIN, P)
    (cx, cy), (ox, oy) = canvas.center, canvas.origin
    C = canvas.C
    ys, xs = np.mgrid[0:C, 0:C] + 0.5
    wx, wy = xs + ox, ys + oy
    half = street_half(P)
    mask = (np.abs(wy - cy) < half) | ((np.abs(wx - cx) < half) & (wy < cy))  # a T: E-W road, north leg
    k = (P / 2) * SQRT3 / 2 / (SQRT3 * (R + 0.5))
    chains = street_chains(mask, (ox, oy), (cx, cy), k, R, P)
    assert len(chains) == 2
    row = next(c for c in chains if all(h.r == 0 for h in c))
    assert row[0] == Hex(-R - 1, 0) and row[-1] == Hex(R + 1, 0)  # leads out of the region both ways
    leg = next(c for c in chains if c is not row)
    assert all(a.distance(b) == 1 for a, b in zip(leg, leg[1:], strict=False))
    assert Hex(0, 0) in leg and min(h.r for h in leg) == -R - 1 and max(h.r for h in leg) <= 0
