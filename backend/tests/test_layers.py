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
