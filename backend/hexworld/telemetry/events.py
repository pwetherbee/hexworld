"""Typed events and hierarchical spans.

Every meaningful step emits an Event. Spans (run → job → attempt → call) are expressed
as paired `<name>.started` / `<name>.finished` events sharing a span_id, so the whole
execution tree can be rebuilt from the flat, append-only log.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Event(BaseModel):
    id: int = 0  # assigned by the store
    ts: float = Field(default_factory=time.time)
    world_id: str
    run_id: str | None = None
    type: str
    span_id: str | None = None
    parent_span_id: str | None = None
    q: int | None = None
    r: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class Span:
    def __init__(self, tracer: Tracer, name: str, span_id: str, parent: str | None, base: dict[str, Any]):
        self.tracer = tracer
        self.name = name
        self.id = span_id
        self.parent = parent
        self.base = base
        self.result: dict[str, Any] = {}

    def set(self, **attrs: Any) -> None:
        self.result.update(attrs)

    def event(self, type_: str, **data: Any) -> Event:
        return self.tracer.emit(type_, span_id=self.id, parent_span_id=self.parent, **self.base, data=data)


class Tracer:
    """Emits events for one world/run into a sink (the store + bus)."""

    def __init__(self, world_id: str, run_id: str | None, sink: Callable[[Event], Event]):
        self.world_id = world_id
        self.run_id = run_id
        self._sink = sink

    def emit(
        self,
        type_: str,
        *,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        q: int | None = None,
        r: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> Event:
        ev = Event(
            world_id=self.world_id,
            run_id=self.run_id,
            type=type_,
            span_id=span_id,
            parent_span_id=parent_span_id,
            q=q,
            r=r,
            data=data or {},
        )
        return self._sink(ev)

    @asynccontextmanager
    async def span(
        self,
        name: str,
        parent: Span | str | None = None,
        *,
        q: int | None = None,
        r: int | None = None,
        **attrs: Any,
    ) -> AsyncIterator[Span]:
        parent_id = parent.id if isinstance(parent, Span) else parent
        if q is None and isinstance(parent, Span):
            q, r = parent.base.get("q"), parent.base.get("r")
        span = Span(self, name, new_id("sp"), parent_id, {"q": q, "r": r})
        t0 = time.perf_counter()
        span.event(f"{name}.started", **attrs)
        try:
            yield span
        except BaseException as e:
            span.event(
                f"{name}.finished",
                ok=False,
                error=f"{type(e).__name__}: {e}"[:500],
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                **attrs,
            )
            raise
        span.event(
            f"{name}.finished",
            ok=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            **attrs,
            **span.result,
        )
