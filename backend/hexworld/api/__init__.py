"""HTTP + WebSocket API."""

from __future__ import annotations

import asyncio
import contextlib
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hexworld.config import REPO_ROOT, get_settings
from hexworld.domain import Attempt, Run, RunOptions, Scene, SkirtTile, Tile, World
from hexworld.domain.art import SpriteEntry
from hexworld.game.layers import SCENE_VERSION
from hexworld.orchestrator.runtime import RunConflict, Runtime
from hexworld.telemetry import Event

ASSET_ID = re.compile(r"^[0-9a-f]{8,64}$")


class CreateWorld(BaseModel):
    name: str | None = None
    radius: int | None = Field(default=None, ge=2, le=40)


class StartRun(BaseModel):
    q: int
    r: int
    prompt: str = Field(min_length=1, max_length=4000)
    options: RunOptions | None = None


class WorldDetail(BaseModel):
    world: World
    tiles: list[Tile]
    runs: list[Run]
    active_run_id: str | None
    last_event_id: int  # tiles reflect every event up to this id (clients skip older tile updates)
    drills: dict[str, str] = Field(default_factory=dict)  # "q,r" -> the world inside that tile


class EnterTile(BaseModel):
    radius: int | None = Field(default=None, ge=2, le=6)  # None: the world's region radius


class EnterResult(BaseModel):
    world: World
    run: Run | None


class TileDetail(BaseModel):
    tile: Tile
    attempts: list[Attempt]


class ApiSchemas(BaseModel):
    """Umbrella model: exported as JSON Schema and turned into frontend TypeScript types."""

    world: World
    world_detail: WorldDetail
    tile: Tile
    tile_detail: TileDetail
    run: Run
    event: Event
    start_run: StartRun
    enter_result: EnterResult
    scene: Scene
    skirt_tile: SkirtTile
    sprite_entry: SpriteEntry
    create_world: CreateWorld


def create_app(runtime: Runtime | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        rt = runtime or Runtime(get_settings())
        app.state.rt = rt
        await rt.resume_incomplete()
        yield
        await rt.shutdown()

    app = FastAPI(title="HexWorld", lifespan=lifespan)

    def rt() -> Runtime:
        return app.state.rt

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, **(await rt().backend_status())}

    @app.get("/api/worlds")
    async def list_worlds() -> list[World]:
        return [w for w in rt().store.list_worlds() if w.depth == 0]  # layers are reached by entering tiles

    @app.post("/api/worlds")
    async def create_world(body: CreateWorld) -> World:
        return rt().create_world(body.name, body.radius)

    @app.get("/api/worlds/{world_id}")
    async def get_world(world_id: str) -> WorldDetail:
        store = rt().store
        w = store.get_world(world_id)
        if w is None:
            raise HTTPException(404, "world not found")
        last = store.max_event_id(world_id)  # read before tiles: a tile can only be newer, never older
        return WorldDetail(
            last_event_id=last,
            world=w,
            tiles=store.list_tiles(world_id),
            runs=store.list_runs(world_id)[:30],
            active_run_id=rt().active_run(world_id),
            drills=store.list_drills(world_id),
        )

    @app.post("/api/worlds/{world_id}/tiles/{q}/{r}/enter")
    async def enter_tile(world_id: str, q: int, r: int, body: EnterTile) -> EnterResult:
        """The world inside a tile; the first entry creates it and starts building it."""
        try:
            world, run = await rt().layers.enter(world_id, q, r, body.radius)
        except KeyError as e:
            raise HTTPException(404, "world not found") from e
        except (ValueError, RunConflict) as e:
            raise HTTPException(409, str(e)) from e
        return EnterResult(world=world, run=run)

    @app.get("/api/worlds/{world_id}/skirt")
    async def skirt(world_id: str) -> list[SkirtTile]:
        """Ground rings just outside a region, continuing its rim (engine-rendered)."""
        try:
            return await rt().layers.skirt(world_id)
        except KeyError as e:
            raise HTTPException(404, "world not found") from e

    @app.get("/api/worlds/{world_id}/tiles/{q}/{r}/scene")
    async def get_scene(world_id: str, q: int, r: int) -> Scene:
        scene = rt().store.get_scene(world_id, q, r)
        if scene is None or scene.version < SCENE_VERSION:  # none yet, or painted by an older recipe
            raise HTTPException(404, "no scene yet")
        return scene

    @app.post("/api/worlds/{world_id}/tiles/{q}/{r}/scene")
    async def make_scene(world_id: str, q: int, r: int) -> Scene:
        """The tile seen up close, painted on first request (then stored)."""
        try:
            return await rt().layers.scene(world_id, q, r)
        except KeyError as e:
            raise HTTPException(404, "world not found") from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/api/worlds/{world_id}/avatar")
    async def avatar(world_id: str) -> SpriteEntry | None:
        try:
            return await rt().layers.avatar(world_id)
        except KeyError as e:
            raise HTTPException(404, "world not found") from e

    @app.delete("/api/worlds/{world_id}")
    async def delete_world(world_id: str) -> dict[str, bool]:
        if rt().active_run(world_id):
            raise HTTPException(409, "stop the world's active run before deleting it")
        if not rt().store.delete_world(world_id):
            raise HTTPException(404, "world not found")
        return {"deleted": True}

    @app.get("/api/worlds/{world_id}/tiles/{q}/{r}")
    async def get_tile(world_id: str, q: int, r: int) -> TileDetail:
        store = rt().store
        run_ids = [run.id for run in store.list_runs(world_id)]
        return TileDetail(
            tile=store.get_tile(world_id, q, r), attempts=store.list_attempts(run_ids=run_ids, q=q, r=r)
        )

    @app.post("/api/worlds/{world_id}/runs")
    async def start_run(world_id: str, body: StartRun) -> Run:
        try:
            return await rt().start_run(world_id, body.q, body.r, body.prompt, body.options)
        except KeyError as e:
            raise HTTPException(404, "world not found") from e
        except RunConflict as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> Run:
        run = rt().store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return run

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, bool]:
        return {"cancelled": await rt().cancel_run(run_id)}

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, after: int = 0, limit: int = Query(5000, le=20000)) -> list[Event]:
        return rt().store.list_events(run_id=run_id, after=after, limit=limit)

    @app.get("/api/worlds/{world_id}/events")
    async def world_events(world_id: str, after: int = 0, limit: int = Query(5000, le=20000)) -> list[Event]:
        return rt().store.list_events(world_id=world_id, after=after, limit=limit)

    @app.get("/api/assets/{asset_id}.png")
    async def asset(asset_id: str) -> FileResponse:
        if not ASSET_ID.match(asset_id):
            raise HTTPException(400, "bad asset id")
        path = rt().store.asset_path(asset_id)
        if not path.exists():
            raise HTTPException(404, "asset not found")
        return FileResponse(
            path, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )

    @app.get("/api/assets/{asset_id}/meta")
    async def asset_meta(asset_id: str) -> dict[str, Any]:
        meta = rt().store.get_asset_meta(asset_id)
        if meta is None:
            raise HTTPException(404, "asset not found")
        return meta

    @app.get("/api/schema")
    async def schema() -> dict[str, Any]:
        return ApiSchemas.model_json_schema()

    @app.websocket("/api/worlds/{world_id}/stream")
    async def stream(ws: WebSocket, world_id: str, after: int = 0) -> None:
        await ws.accept()
        runtime = rt()
        queue = runtime.bus.subscribe(world_id)
        try:
            last = after
            # Backlog first (subscribed already, so nothing emitted meanwhile is lost), then live.
            while True:
                backlog = runtime.store.list_events(world_id=world_id, after=last, limit=2000)
                for ev in backlog:
                    await ws.send_text(ev.model_dump_json())
                    last = ev.id
                if len(backlog) < 2000:
                    break
            while True:
                ev = await queue.get()
                if ev.id <= last:
                    continue
                await ws.send_text(ev.model_dump_json())
                last = ev.id
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            runtime.bus.unsubscribe(world_id, queue)
            with contextlib.suppress(Exception):
                await ws.close()

    dist = REPO_ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app
