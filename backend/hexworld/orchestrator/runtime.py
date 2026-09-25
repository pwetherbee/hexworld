"""Process-wide runtime: store, event bus, LLM + image clients, active run tasks."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

from google.adk.models.base_llm import BaseLlm

from hexworld.agents.fake import FakeClient
from hexworld.agents.kit import fake_model_factory, openai_model_factory
from hexworld.agents.llm import Role
from hexworld.art.backend import (
    ComfyUIBackend,
    FallbackImageBackend,
    ImageBackend,
    OpenAIImageBackend,
    ProceduralBackend,
)
from hexworld.config import Settings
from hexworld.domain import Coord, Run, RunOptions, RunStatus, World
from hexworld.hex import ORIGIN, Hex
from hexworld.orchestrator.run import RunExecutor
from hexworld.store import Store
from hexworld.telemetry import EventBus, Tracer, new_id


class RunConflict(Exception):
    pass


def build_models(settings: Settings) -> Callable[[Role], BaseLlm]:
    if settings.llm == "fake":
        return fake_model_factory(FakeClient(reject_rate=settings.fake_reject_rate))
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set (put it in the repo-root .env)")
    return openai_model_factory(settings)


def build_image(settings: Settings) -> ImageBackend:
    def make(kind: str) -> ImageBackend:
        if kind in ("procedural", "stub"):
            return ProceduralBackend()
        if kind == "comfyui":
            return ComfyUIBackend(
                settings.comfyui_url, settings.comfyui_workflow_dir, settings.comfyui_timeout_s
            )
        if kind == "openai":
            return OpenAIImageBackend(
                settings.openai_api_key, settings.openai_base_url, settings.openai_image_model
            )
        raise ValueError(kind)

    primary = make(settings.image)

    def canon(k: str) -> str:
        return "procedural" if k == "stub" else k

    if settings.image_fallback == "none" or canon(settings.image_fallback) == canon(settings.image):
        return primary
    return FallbackImageBackend(primary, make(settings.image_fallback))


class Runtime:
    def __init__(
        self,
        settings: Settings,
        *,
        store: Store | None = None,
        model_factory: Callable[[Role], BaseLlm] | None = None,
        image: ImageBackend | None = None,
    ):
        self.settings = settings
        self.store = store or Store(settings.data_dir)
        self.bus = EventBus()
        self.store.add_listener(self.bus.publish)
        self.model_factory = model_factory or build_models(settings)
        self.llm_name = "fake" if settings.llm == "fake" or model_factory else f"adk+{settings.llm}"
        self.image = image or build_image(settings)
        self.gpu_sem = asyncio.Semaphore(settings.image_concurrency)
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.shutting_down = False

    # ------------------------------------------------------------------ worlds
    def create_world(self, name: str | None = None, radius: int | None = None) -> World:
        w = World(
            id=new_id("w"),
            name=name or "Untitled world",
            radius=radius or self.settings.world_radius,
            created_at=time.time(),
        )
        self.store.put_world(w)
        Tracer(w.id, None, self.store.append_event).emit(
            "world.created", data={"name": w.name, "radius": w.radius}
        )
        return w

    # ------------------------------------------------------------------ runs
    def active_run(self, world_id: str) -> str | None:
        for run_id, task in self.tasks.items():
            if not task.done():
                run = self.store.get_run(run_id)
                if run and run.world_id == world_id:
                    return run_id
        return None

    async def start_run(
        self, world_id: str, q: int, r: int, prompt: str, options: RunOptions | None = None
    ) -> Run:
        world = self.store.get_world(world_id)
        if world is None:
            raise KeyError(world_id)
        if Hex(q, r).distance(ORIGIN) > world.radius:
            raise ValueError(f"({q},{r}) is outside the world (radius {world.radius})")
        if (busy := self.active_run(world_id)) is not None:
            raise RunConflict(f"run {busy} is still active in this world")
        tile = self.store.get_tile(world_id, q, r)
        if tile.status.value in ("accepted", "planned", "generating", "reviewing"):
            raise ValueError(f"tile ({q},{r}) is not empty ({tile.status.value})")
        run = Run(
            id=new_id("run"),
            world_id=world_id,
            origin=Coord(q=q, r=r),
            prompt=prompt.strip()[:4000],
            options=options or RunOptions(),
            created_at=time.time(),
        )
        self.store.put_run(run)
        self._launch(run)
        return run

    def _launch(self, run: Run) -> None:
        executor = RunExecutor(self, run)
        task = asyncio.create_task(executor.execute(), name=f"run:{run.id}")
        self.tasks[run.id] = task
        task.add_done_callback(lambda t: self.tasks.pop(run.id, None))

    async def cancel_run(self, run_id: str) -> bool:
        task = self.tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return True

    async def wait(self, run_id: str) -> Run:
        task = self.tasks.get(run_id)
        if task is not None:
            await task
        run = self.store.get_run(run_id)
        assert run is not None
        return run

    async def resume_incomplete(self) -> list[str]:
        """Runs left 'running' by a crash/restart continue from their persisted plan + tiles."""
        resumed = []
        for run in self.store.list_runs():
            if run.status in (RunStatus.running, RunStatus.pending) and run.id not in self.tasks:
                self._launch(run)
                resumed.append(run.id)
        return resumed

    async def shutdown(self) -> None:
        self.shutting_down = True
        tasks = list(self.tasks.values())
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    async def backend_status(self) -> dict[str, Any]:
        return {
            "llm": self.llm_name,
            "super_model": self.model_factory("super").model,
            "tile_model": self.model_factory("tile").model,
            "image": self.image.name,
            "image_healthy": await self.image.health(),
        }
