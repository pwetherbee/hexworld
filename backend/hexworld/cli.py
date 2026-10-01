"""`hexworld` command line: serve, inspect runs, check models, export schema, run evals."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

from hexworld.config import get_settings


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="hexworld")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the API server")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--reload", action="store_true")

    r = sub.add_parser("runs", help="inspect runs")
    rs = r.add_subparsers(dest="runs_cmd", required=True)
    rs.add_parser("list")
    show = rs.add_parser("show")
    show.add_argument("run_id")

    sub.add_parser("models", help="list models visible to the configured OpenAI key")

    e = sub.add_parser("export-schema", help="write API JSON Schema (for frontend type generation)")
    e.add_argument("out", type=Path)

    ev = sub.add_parser("eval", help="run canned prompts headlessly and report quality/cost/latency")
    ev.add_argument("--radius", type=int, default=2)
    ev.add_argument("--prompts", type=Path, help="text file, one prompt per line")

    args = p.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn

        st = get_settings()
        uvicorn.run(
            "hexworld.api:create_app",
            factory=True,
            host=args.host or st.host,
            port=args.port or st.port,
            reload=args.reload,
            reload_dirs=[str(Path(__file__).parent)] if args.reload else None,
        )
    elif args.cmd == "runs":
        _runs(args)
    elif args.cmd == "models":
        asyncio.run(_models())
    elif args.cmd == "export-schema":
        from hexworld.api import ApiSchemas

        args.out.parent.mkdir(parents=True, exist_ok=True)
        schema = _strip_property_titles(ApiSchemas.model_json_schema())
        args.out.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    elif args.cmd == "eval":
        asyncio.run(_eval(args))


def _strip_property_titles(node):  # noqa: ANN001, ANN202
    """Shape the schema for json2ts: drop property titles (one alias per field otherwise), and
    mark every property required (responses always include them)."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "properties":
                out[k] = {
                    name: _strip_property_titles({kk: vv for kk, vv in sub.items() if kk != "title"})
                    for name, sub in v.items()
                }
            else:
                out[k] = _strip_property_titles(v)
        if "properties" in out:
            # The API always serializes every field (defaults included), so for the client
            # nothing is optional.
            out["required"] = list(out["properties"])
        return out
    if isinstance(node, list):
        return [_strip_property_titles(v) for v in node]
    return node


def _runs(args: argparse.Namespace) -> None:
    from hexworld.store import Store

    store = Store(get_settings().data_dir, get_settings().sqlite_journal)
    if args.runs_cmd == "list":
        for run in store.list_runs()[:50]:
            st = run.stats
            print(
                f"{run.id}  {run.status.value:9}  tiles {st.tiles_accepted}/{st.tiles_planned}  "
                f"${st.cost_usd:.4f}  {run.prompt[:60]!r}"
            )
        return
    run = store.get_run(args.run_id)
    if run is None:
        sys.exit(f"no run {args.run_id}")
    print(summarize(run, store.list_events(run_id=run.id, limit=100000)))


def summarize(run, events) -> str:  # noqa: ANN001
    st = run.stats
    lat: dict[str, list[float]] = {}
    for ev in events:
        if ev.type.endswith(".finished") and "duration_ms" in ev.data:
            key = ev.type.removesuffix(".finished")
            if key == "llm.call":
                key = f"llm.call[{ev.data.get('task')}]"
            lat.setdefault(key, []).append(ev.data["duration_ms"])
    wall = (run.finished_at or events[-1].ts if events else run.created_at) - run.created_at
    lines = [
        f"run {run.id}  [{run.status.value}]  {run.prompt[:80]!r}",
        f"  wall time        {wall:.1f}s" + (f"   error: {run.error}" if run.error else ""),
        f"  tiles            {st.tiles_accepted} accepted / {st.tiles_planned} planned / {st.tiles_failed} failed",
        f"  attempts         {st.attempts}  ({st.attempts / max(1, st.tiles_planned):.2f} per planned tile)",
        f"  rejections       {st.rejections_validation} validation, {st.rejections_review} review",
        f"  acceptance rate  {st.tiles_accepted / max(1, st.attempts):.0%} of attempts",
        f"  llm              {st.llm_calls} calls, {st.input_tokens} in ({st.cached_input_tokens} cached), "
        f"{st.output_tokens} out, ${st.cost_usd:.4f}",
        f"  images           {st.images}",
        "  latency (ms)     p50 / p95 / n",
    ]
    for k in sorted(lat):
        v = sorted(lat[k])
        p95 = v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]
        lines.append(f"    {k:28} {statistics.median(v):8.0f} / {p95:8.0f} / {len(v)}")
    return "\n".join(lines)


async def _models() -> None:
    from hexworld.agents.llm import list_openai_models

    st = get_settings()
    models = await list_openai_models(st.openai_api_key, st.openai_base_url)
    roles = {"super": st.super_model, "tile": st.tile_model, "artist": st.artist_model or st.tile_model}
    for m in models:
        tags = [r for r, name in roles.items() if name == m]
        print(m + (f"  <- {', '.join(tags)}" if tags else ""))
    for role, m in roles.items():
        if m not in models:
            print(f"WARNING: configured {role} model {m!r} not visible to this key", file=sys.stderr)


DEFAULT_EVAL_PROMPTS = [
    "A temperate kingdom with rolling hills, a river and a small castle",
    "A pirate archipelago with hidden coves and a volcano",
    "A frozen tundra board game where players race sled teams to the glacier",
]


async def _eval(args: argparse.Namespace) -> None:
    import numpy as np

    from hexworld.art.grid import TileCanvas, seam_delta
    from hexworld.art.pixelize import load_tile
    from hexworld.domain import RunOptions, TileStatus
    from hexworld.orchestrator.runtime import Runtime

    prompts = (
        [ln.strip() for ln in args.prompts.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if args.prompts
        else DEFAULT_EVAL_PROMPTS
    )
    rt = Runtime(get_settings())
    rows = []
    for prompt in prompts:
        world = rt.create_world(name=f"eval: {prompt[:30]}")
        run = await rt.start_run(world.id, 0, 0, prompt, RunOptions(radius=args.radius))
        run = await rt.wait(run.id)
        tiles = {
            t.hex: t for t in rt.store.list_tiles(world.id) if t.status == TileStatus.accepted and t.asset_id
        }
        arrays = {
            h: load_tile(rt.store.get_asset(t.ground_asset_id or t.asset_id))  # type: ignore[arg-type]
            for h, t in tiles.items()
        }
        P = arrays[next(iter(arrays))].shape[0] - 3 if arrays else 64
        seams = [
            seam_delta(arrays[h], TileCanvas(h, P), i, arrays[h.neighbor(i)], TileCanvas(h.neighbor(i), P))
            for h in arrays
            for i in range(3)
            if h.neighbor(i) in arrays
        ]
        print(summarize(run, rt.store.list_events(run_id=run.id, limit=100000)))
        print(
            f"  edge continuity  mean seam delta {np.mean(seams) if seams else 0:.3f} over {len(seams)} edges\n"
        )
        rows.append((run, float(np.mean(seams)) if seams else 0.0))
    await rt.shutdown()
    print("prompt                                     accepted  att/tile  cost      seam")
    for run, seam in rows:
        st = run.stats
        print(
            f"{run.prompt[:42]:42} {st.tiles_accepted:3}/{st.tiles_planned:<3}   "
            f"{st.attempts / max(1, st.tiles_planned):5.2f}    ${st.cost_usd:7.4f}  {seam:.3f}"
        )


if __name__ == "__main__":
    main()
