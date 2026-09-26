from hexworld.agents.fake import FakeClient
from hexworld.domain import Coord, EdgeSpec, RunOptions, RunStatus, Tile, TileStatus
from hexworld.hex import Hex
from hexworld.orchestrator.copies import apply_copy, resolve_root, sync_shallow_copies


async def _run(rt, prompt="A temperate kingdom", radius=3):
    world = rt.create_world()
    run = await rt.start_run(world.id, 0, 0, prompt, RunOptions(radius=radius))
    return world, await rt.wait(run.id)


async def test_super_duplicates_filler_tiles_shallow_and_deep(make_runtime):
    rt = make_runtime(llm=FakeClient(latency_s=0, reject_rate=0, duplicate_rate=1.0))
    world, run = await _run(rt, "an endless desert of dunes", radius=3)
    assert run.status == RunStatus.completed, run.error
    tiles = {t.hex: t for t in rt.store.list_tiles(world.id)}
    copies = [t for t in tiles.values() if t.copy_of is not None]
    assert copies and run.stats.tiles_copied == len(copies)
    assert {t.copy_mode for t in copies} == {"shallow", "deep"}
    for c in copies:
        src = tiles[c.copy_of.hex]
        assert src.status == TileStatus.accepted and src.copy_of is None  # always a root prototype
        assert c.biome == src.biome
        # procedural ground: the copy is re-rendered in place (same design, own pixels), same props
        sprites = lambda t: [x.asset_id for x in t.layers if x.kind == "sprite"]  # noqa: E731
        assert c.ground_asset_id and sprites(c) == sprites(src)
        assert c.attempts == 0  # no LLM or image work was spent on it
        for i in range(6):  # a copy still honors the continuity contract
            n = tiles.get(c.hex.neighbor(i))
            if n and n.status == TileStatus.accepted:
                assert c.edges[i].compatible_with(n.edges[(i + 3) % 6])
    events = rt.store.list_events(run_id=run.id)
    fallbacks = [e for e in events if e.type == "copy.fallback"]
    assert run.stats.copy_fallbacks == len(fallbacks)
    for e in fallbacks:  # a slot that didn't fit was generated instead
        t = tiles[Hex(e.q, e.r)]
        assert t.copy_of is None and t.attempts >= 1
    # fewer attempts than tiles: copies are free
    assert run.stats.attempts < run.stats.tiles_planned + 3


def test_duplicate_specs_are_sanitized(make_runtime):
    """The layout DSL only produces valid copies, but plans also arrive by other paths (director
    updates, resumed runs): the orchestrator must still sanitize arbitrary duplicate specs."""
    import time

    from hexworld.domain import CopySpec, PlannedTile, Run, StyleGuide, WorldPlan, WorldSpec
    from hexworld.hex import within
    from hexworld.orchestrator.run import RunExecutor

    rt = make_runtime(llm=FakeClient(latency_s=0, reject_rate=0))
    world = rt.create_world()
    run = Run(
        id="run_t",
        world_id=world.id,
        origin=Coord(q=0, r=0),
        prompt="p",
        options=RunOptions(),
        created_at=time.time(),
    )
    rt.store.put_run(run)
    ex = RunExecutor(rt, run)

    def copy(mode, q, r):
        return CopySpec(mode=mode, source_q=q, source_r=r)

    dups = {
        (0, 0): copy("shallow", 1, 0),  # origin: invalid
        (0, 1): copy("deep", 1, 0),  # valid
        (-1, 1): copy("shallow", 0, 1),  # copy of a copy -> collapses to its root
        (1, -1): copy("deep", 9, 9),  # unknown source
    }
    tiles = [
        PlannedTile(
            q=h.q, r=h.r, biome="sand", intent="dunes", duplicate=dups.get((h.q, h.r), copy("none", 0, 0))
        )
        for h in within(Hex(0, 0), 1)
    ]
    spec = WorldSpec(
        title="t",
        genre="g",
        theme="t",
        lore="l",
        terrain_vocabulary=["sand"],
        connector_vocabulary=[],
        directional_notes="",
    )
    style = StyleGuide(
        palette=["#000000", "#ffffff", "#ff0000", "#00ff00"],
        tile_px=64,
        view="v",
        light_direction="l",
        outline="o",
        style_keywords="k",
    )
    plan = ex._apply_plan(WorldPlan(world=spec, style=style, tile_attributes=[], tiles=tiles))
    notes = ex._plan_notes
    assert any(n.startswith("0,0:") for n in notes) and any(n.startswith("1,-1:") for n in notes)
    planned = {(t.q, t.r): t.duplicate for t in plan.tiles}
    assert planned[(-1, 1)] == copy("shallow", 1, 0)  # collapsed to root
    assert planned[(0, 0)].mode == "none" and planned[(1, -1)].mode == "none"


def _tile(q, r, asset, **kw):
    return Tile(
        q=q,
        r=r,
        status=TileStatus.accepted,
        asset_id=asset,
        biome="sand",
        summary="s",
        edges=[EdgeSpec(terrain="sand", connectors=[]) for _ in range(6)],
        **kw,
    )


def test_shallow_copies_follow_prototype_deep_copies_do_not():
    src = _tile(0, 0, "a1", attributes={"elevation": 1})
    shallow, deep = Tile(q=1, r=0), Tile(q=2, r=0)
    apply_copy(shallow, src, "shallow")
    apply_copy(deep, src, "deep")
    tiles = {t.hex: t for t in (src, shallow, deep)}
    assert shallow.asset_id == deep.asset_id == "a1"
    deep.attributes["elevation"] = 3  # deep copies own their data
    assert src.attributes["elevation"] == 1

    src.asset_id, src.summary, src.attributes = "a2", "regenerated", {"elevation": 2}
    changed = sync_shallow_copies(src, tiles)
    assert changed == [shallow]
    assert (
        shallow.asset_id == "a2"
        and shallow.summary == "regenerated"
        and shallow.attributes == {"elevation": 2}
    )
    assert deep.asset_id == "a1" and deep.attributes == {"elevation": 3}


def test_resolve_root_follows_copy_chain():
    a = _tile(0, 0, "a")
    b = _tile(1, 0, "a", copy_of=Coord(q=0, r=0), copy_mode="deep")
    c = _tile(2, 0, "a", copy_of=Coord(q=1, r=0), copy_mode="shallow")
    tiles = {t.hex: t for t in (a, b, c)}
    assert resolve_root(tiles, Hex(2, 0)) == Hex(0, 0)
