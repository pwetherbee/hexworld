import asyncio
from collections import defaultdict

from hexworld.agents.fake import FakeClient
from hexworld.agents.llm import LLMOutputError, LLMRequest, LLMResult, RecordingClient, ReplayClient
from hexworld.art.backend import ImageResult, ProceduralStubBackend
from hexworld.art.pixelize import load_tile, seam_delta
from hexworld.domain import RunOptions, RunStatus, TileStatus
from hexworld.hex import Hex


async def _run(rt, prompt="A temperate kingdom", q=0, r=0, world=None, **opts):
    world = world or rt.create_world()
    run = await rt.start_run(world.id, q, r, prompt, RunOptions(**opts))
    return world, await rt.wait(run.id)


def _tiles(rt, world):
    return {t.hex: t for t in rt.store.list_tiles(world.id)}


async def test_full_run_fills_plan_with_valid_seams(make_runtime):
    rt = make_runtime(fake_reject_rate=0.0)
    world, run = await _run(rt, radius=2)
    assert run.status == RunStatus.completed, run.error
    tiles = _tiles(rt, world)
    planned = [t for t in tiles.values() if t.status != TileStatus.intentionally_empty]
    assert run.stats.tiles_planned == len(planned) >= 15
    assert all(t.status == TileStatus.accepted for t in planned)
    assert run.stats.tiles_accepted == len(planned)
    # continuity contract: every shared edge between accepted tiles matches, visually too
    for h, t in tiles.items():
        for i in range(6):
            n = tiles.get(h.neighbor(i))
            if n and t.status == TileStatus.accepted and n.status == TileStatus.accepted:
                assert t.edges[i].compatible_with(n.edges[(i + 3) % 6])
                a, b = load_tile(rt.store.get_asset(t.asset_id)), load_tile(rt.store.get_asset(n.asset_id))
                assert seam_delta(a, i, b) <= rt.settings.max_seam_delta
    w = rt.store.get_world(world.id)
    assert w.spec and w.style and w.anchor_asset_ids


async def test_waves_never_contain_adjacent_tiles_and_grow_outward(make_runtime):
    rt = make_runtime()
    world, run = await _run(rt, radius=3)
    events = rt.store.list_events(run_id=run.id)
    waves = next(e for e in events if e.type == "waves.scheduled").data["waves"]
    rings = []
    for wave in waves:
        hexes = [Hex.parse(k) for k in wave]
        for a in hexes:
            for b in hexes:
                assert a.distance(b) != 1
        rings.append(max(h.distance(Hex(0, 0)) for h in hexes))
    assert rings == sorted(rings)


async def test_rejections_retry_with_feedback(make_runtime):
    rt = make_runtime(fake_reject_rate=1.0)  # fake super rejects every first attempt
    world, run = await _run(rt, radius=1)
    assert run.status == RunStatus.completed
    assert run.stats.rejections_review > 0
    tiles = _tiles(rt, world)
    non_origin = [t for h, t in tiles.items() if h != Hex(0, 0) and t.status == TileStatus.accepted]
    assert non_origin and all(t.attempts == 2 for t in non_origin)
    detail = rt.store.list_attempts(run_ids=[run.id], q=non_origin[0].q, r=non_origin[0].r)
    assert [a.outcome for a in detail] == ["rejected", "accepted"]
    assert detail[0].verdict and not detail[0].verdict.accept and detail[0].verdict.feedback
    assert detail[1].directive.feedback  # feedback was passed to the tile agent


async def test_spans_are_paired_and_parented(make_runtime):
    rt = make_runtime()
    _, run = await _run(rt, radius=1)
    events = rt.store.list_events(run_id=run.id)
    started = {e.span_id: e for e in events if e.type.endswith(".started")}
    finished = {e.span_id: e for e in events if e.type.endswith(".finished")}
    assert started.keys() == finished.keys()
    ids = set(started)
    for e in started.values():
        assert e.parent_span_id is None or e.parent_span_id in ids
    llm = [e for e in finished.values() if e.type == "llm.call.finished"]
    assert llm and all("input_tokens" in e.data for e in llm)
    kinds = {e.type for e in events}
    assert {"plan.created", "anchor.selected", "tile.accepted", "run.completed", "review.verdict"} <= kinds


async def test_budget_stops_run_and_releases_tiles(make_runtime):
    rt = make_runtime()
    world, run = await _run(rt, radius=3, max_llm_calls=12)
    assert run.status == RunStatus.completed and run.error and "budget" in run.error
    statuses = {t.status for t in _tiles(rt, world).values()}
    assert not statuses & {TileStatus.planned, TileStatus.generating, TileStatus.reviewing}
    assert run.stats.llm_calls <= 12


class FlatImages(ProceduralStubBackend):
    """Always returns a single flat color: fails the distinct-colors check."""

    async def generate(self, req):
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (req.size, req.size), (90, 160, 80)).save(buf, format="PNG")
        return ImageResult(png=buf.getvalue(), backend="flat", meta={"framing": "tile"})


async def test_invalid_images_fail_after_attempts_plus_simplified(make_runtime):
    rt = make_runtime(image=FlatImages(latency_s=0))
    world, run = await _run(rt, radius=1, max_attempts=2, anchor_candidates=1)
    assert run.status == RunStatus.completed
    tiles = _tiles(rt, world)
    failed = [t for t in tiles.values() if t.status == TileStatus.failed]
    assert failed and run.stats.tiles_failed == len(failed)
    # 1 anchor attempt, then waves: 2 normal + 1 simplified
    assert all(t.attempts == 3 for t in failed if t.hex != Hex(0, 0))
    events = [e.type for e in rt.store.list_events(run_id=run.id)]
    assert "tile.simplified" in events and "tile.failed" in events


class BrokenReviewer(FakeClient):
    async def complete(self, req: LLMRequest) -> LLMResult:
        if req.task == "wave_review":
            raise LLMOutputError("reviewer down")
        return await super().complete(req)


async def test_review_failure_degrades_to_deterministic_accept(make_runtime):
    rt = make_runtime(llm=BrokenReviewer(latency_s=0))
    world, run = await _run(rt, radius=1)
    assert run.status == RunStatus.completed
    assert all(
        t.status in (TileStatus.accepted, TileStatus.intentionally_empty) for t in _tiles(rt, world).values()
    )


async def test_tile_agent_errors_are_isolated(make_runtime):
    calls = defaultdict(int)

    class Flaky(FakeClient):
        async def complete(self, req):
            if req.task == "tile_design" and req.payload["directive"]["coord"] == {"q": 1, "r": 0}:
                calls["n"] += 1
                if calls["n"] <= 2:  # first attempt: both the call and its repair fail
                    return LLMResult(data={"nope": 1}, model="flaky")
            return await super().complete(req)

    rt = make_runtime(llm=Flaky(latency_s=0, reject_rate=0))
    world, run = await _run(rt, radius=1)
    t = _tiles(rt, world)[Hex(1, 0)]
    assert t.status == TileStatus.accepted and t.attempts == 2
    atts = rt.store.list_attempts(run_ids=[run.id], q=1, r=0)
    assert atts[0].outcome == "error" and "invalid output" in atts[0].error


async def test_extension_run_reuses_style_and_continues_edges(make_runtime):
    rt = make_runtime(fake_reject_rate=0)
    world, run1 = await _run(rt, "a green valley", radius=1)
    style1 = rt.store.get_world(world.id).style
    _, run2 = await _run(rt, "desert to the east", q=3, r=0, world=world, radius=1)
    assert run2.status == RunStatus.completed, run2.error
    w = rt.store.get_world(world.id)
    assert w.style == style1
    tiles = _tiles(rt, world)
    boundary = 0
    for h, t in tiles.items():
        if t.run_id != run2.id or t.status != TileStatus.accepted:
            continue
        for i in range(6):
            n = tiles.get(h.neighbor(i))
            if n and n.run_id == run1.id and n.status == TileStatus.accepted:
                boundary += 1
                assert t.edges[i].compatible_with(n.edges[(i + 3) % 6])
    assert boundary > 0


async def test_record_then_replay_reproduces_board(make_runtime):
    rt = make_runtime(fake_reject_rate=0.3)
    rt.llm = RecordingClient(FakeClient(latency_s=0, reject_rate=0.3), rt.store)
    world1, run1 = await _run(rt, "a pirate island", radius=2)
    rt.llm = ReplayClient(rt.store)
    world2, run2 = await _run(rt, "a pirate island", radius=2)
    b1 = {h: (t.status, t.asset_id) for h, t in _tiles(rt, world1).items()}
    b2 = {h: (t.status, t.asset_id) for h, t in _tiles(rt, world2).items()}
    assert b1 == b2
    assert run2.stats.cost_usd == 0


async def test_cancel_marks_run_and_releases(make_runtime):
    rt = make_runtime(llm=FakeClient(latency_s=0.05))
    world = rt.create_world()
    run = await rt.start_run(world.id, 0, 0, "slow world", RunOptions(radius=3))
    await asyncio.sleep(0.3)
    assert await rt.cancel_run(run.id)
    run = rt.store.get_run(run.id)
    assert run.status == RunStatus.cancelled
    assert not any(
        t.status in (TileStatus.planned, TileStatus.generating) for t in _tiles(rt, world).values()
    )


async def test_resume_after_crash(make_runtime, settings):
    rt = make_runtime(llm=FakeClient(latency_s=0.05))
    world = rt.create_world()
    run = await rt.start_run(world.id, 0, 0, "resumable", RunOptions(radius=2))
    await asyncio.sleep(0.4)
    await rt.shutdown()  # simulates process exit: run stays 'running'
    assert rt.store.get_run(run.id).status == RunStatus.running
    rt2 = make_runtime(store=rt.store)
    assert run.id in await rt2.resume_incomplete()
    run = await rt2.wait(run.id)
    assert run.status == RunStatus.completed
    assert all(
        t.status in (TileStatus.accepted, TileStatus.intentionally_empty, TileStatus.failed)
        for t in _tiles(rt2, world).values()
    )
