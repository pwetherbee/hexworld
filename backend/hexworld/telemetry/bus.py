"""In-process pub/sub: store-persisted events fan out to live WebSocket subscribers."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict

from hexworld.telemetry.events import Event


class EventBus:
    def __init__(self, max_queue: int = 5000):
        self._subs: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)
        self._max_queue = max_queue

    def subscribe(self, world_id: str) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(self._max_queue)
        self._subs[world_id].add(q)
        return q

    def unsubscribe(self, world_id: str, q: asyncio.Queue[Event]) -> None:
        self._subs[world_id].discard(q)

    def publish(self, ev: Event) -> None:
        for q in list(self._subs.get(ev.world_id, ())):
            # A slow consumer drops its oldest events instead of stalling the orchestrator;
            # clients recover via the `after` event-id replay on reconnect.
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(ev)
