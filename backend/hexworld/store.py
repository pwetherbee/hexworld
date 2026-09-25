"""SQLite persistence: worlds, tiles, runs, attempts, events, assets, LLM records.

Single-process, local-first. Writes are serialized with a lock; WAL keeps readers cheap.
Assets are content-addressed PNGs on disk. Events are also mirrored to one JSONL per run
so a run can be inspected (or diffed) with plain tools.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hexworld.domain import Attempt, Run, Tile, TileStatus, World
from hexworld.telemetry.events import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS worlds (id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tiles (
  world_id TEXT NOT NULL, q INTEGER NOT NULL, r INTEGER NOT NULL, json TEXT NOT NULL,
  PRIMARY KEY (world_id, q, r));
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, world_id TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (
  run_id TEXT NOT NULL, q INTEGER NOT NULL, r INTEGER NOT NULL, attempt INTEGER NOT NULL, json TEXT NOT NULL,
  PRIMARY KEY (run_id, q, r, attempt));
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, world_id TEXT NOT NULL, run_id TEXT, ts REAL NOT NULL,
  type TEXT NOT NULL, span_id TEXT, parent_span_id TEXT, q INTEGER, r INTEGER, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_world ON events (world_id, id);
CREATE INDEX IF NOT EXISTS events_run ON events (run_id, id);
CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, meta TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS llm_records (
  key TEXT NOT NULL, seq INTEGER NOT NULL, response TEXT NOT NULL, PRIMARY KEY (key, seq));
"""


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.assets_dir = self.data_dir / "assets"
        self.runs_dir = self.data_dir / "runs"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.data_dir / "hexworld.db", check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._listeners: list[Callable[[Event], None]] = []

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------------ worlds
    def put_world(self, w: World) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO worlds (id, json) VALUES (?, ?)", (w.id, w.model_dump_json())
            )

    def get_world(self, world_id: str) -> World | None:
        row = self._db.execute("SELECT json FROM worlds WHERE id = ?", (world_id,)).fetchone()
        return World.model_validate_json(row[0]) if row else None

    def list_worlds(self) -> list[World]:
        rows = self._db.execute("SELECT json FROM worlds").fetchall()
        return sorted((World.model_validate_json(r[0]) for r in rows), key=lambda w: -w.created_at)

    # ------------------------------------------------------------------ tiles
    def put_tile(self, world_id: str, t: Tile) -> None:
        with self._lock, self._db:
            if t.status == TileStatus.empty:
                self._db.execute("DELETE FROM tiles WHERE world_id=? AND q=? AND r=?", (world_id, t.q, t.r))
            else:
                self._db.execute(
                    "INSERT OR REPLACE INTO tiles (world_id, q, r, json) VALUES (?, ?, ?, ?)",
                    (world_id, t.q, t.r, t.model_dump_json()),
                )

    def get_tile(self, world_id: str, q: int, r: int) -> Tile:
        row = self._db.execute(
            "SELECT json FROM tiles WHERE world_id=? AND q=? AND r=?", (world_id, q, r)
        ).fetchone()
        return Tile.model_validate_json(row[0]) if row else Tile(q=q, r=r)

    def list_tiles(self, world_id: str) -> list[Tile]:
        rows = self._db.execute("SELECT json FROM tiles WHERE world_id=?", (world_id,)).fetchall()
        return [Tile.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------------ runs
    def put_run(self, run: Run) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO runs (id, world_id, json) VALUES (?, ?, ?)",
                (run.id, run.world_id, run.model_dump_json()),
            )

    def get_run(self, run_id: str) -> Run | None:
        row = self._db.execute("SELECT json FROM runs WHERE id=?", (run_id,)).fetchone()
        return Run.model_validate_json(row[0]) if row else None

    def list_runs(self, world_id: str | None = None) -> list[Run]:
        if world_id:
            rows = self._db.execute("SELECT json FROM runs WHERE world_id=?", (world_id,)).fetchall()
        else:
            rows = self._db.execute("SELECT json FROM runs").fetchall()
        return sorted((Run.model_validate_json(r[0]) for r in rows), key=lambda r: -r.created_at)

    # ------------------------------------------------------------------ attempts
    def put_attempt(self, a: Attempt) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO attempts (run_id, q, r, attempt, json) VALUES (?, ?, ?, ?, ?)",
                (a.run_id, a.q, a.r, a.attempt, a.model_dump_json()),
            )

    def list_attempts(self, *, run_ids: list[str], q: int, r: int) -> list[Attempt]:
        if not run_ids:
            return []
        marks = ",".join("?" * len(run_ids))
        rows = self._db.execute(
            f"SELECT json FROM attempts WHERE run_id IN ({marks}) AND q=? AND r=? ORDER BY attempt",
            (*run_ids, q, r),
        ).fetchall()
        return sorted((Attempt.model_validate_json(r[0]) for r in rows), key=lambda a: a.created_at)

    # ------------------------------------------------------------------ events
    def add_listener(self, fn: Callable[[Event], None]) -> None:
        self._listeners.append(fn)

    def append_event(self, ev: Event) -> Event:
        with self._lock:
            with self._db:
                cur = self._db.execute(
                    "INSERT INTO events (world_id, run_id, ts, type, span_id, parent_span_id, q, r, data)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ev.world_id,
                        ev.run_id,
                        ev.ts,
                        ev.type,
                        ev.span_id,
                        ev.parent_span_id,
                        ev.q,
                        ev.r,
                        json.dumps(ev.data, default=str),
                    ),
                )
            ev = ev.model_copy(update={"id": cur.lastrowid})
            if ev.run_id:
                with open(self.runs_dir / f"{ev.run_id}.jsonl", "a", encoding="utf-8") as f:
                    f.write(ev.model_dump_json() + "\n")
        for fn in self._listeners:
            fn(ev)
        return ev

    def list_events(
        self, *, world_id: str | None = None, run_id: str | None = None, after: int = 0, limit: int = 5000
    ) -> list[Event]:
        where, args = ["id > ?"], [after]
        if world_id:
            where.append("world_id = ?")
            args.append(world_id)
        if run_id:
            where.append("run_id = ?")
            args.append(run_id)
        rows = self._db.execute(
            "SELECT id, world_id, run_id, ts, type, span_id, parent_span_id, q, r, data FROM events"
            f" WHERE {' AND '.join(where)} ORDER BY id LIMIT ?",
            (*args, limit),
        ).fetchall()
        return [
            Event(
                id=row[0],
                world_id=row[1],
                run_id=row[2],
                ts=row[3],
                type=row[4],
                span_id=row[5],
                parent_span_id=row[6],
                q=row[7],
                r=row[8],
                data=json.loads(row[9]),
            )
            for row in rows
        ]

    def max_event_id(self, world_id: str) -> int:
        row = self._db.execute("SELECT MAX(id) FROM events WHERE world_id = ?", (world_id,)).fetchone()
        return row[0] or 0

    # ------------------------------------------------------------------ assets
    def put_asset(self, png: bytes, meta: dict[str, Any]) -> str:
        asset_id = hashlib.sha256(png).hexdigest()[:24]
        path = self.assets_dir / f"{asset_id}.png"
        if not path.exists():
            path.write_bytes(png)
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO assets (id, meta) VALUES (?, ?)",
                (asset_id, json.dumps(meta, default=str)),
            )
        return asset_id

    def asset_path(self, asset_id: str) -> Path:
        return self.assets_dir / f"{asset_id}.png"

    def get_asset(self, asset_id: str) -> bytes:
        return self.asset_path(asset_id).read_bytes()

    def get_asset_meta(self, asset_id: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT meta FROM assets WHERE id=?", (asset_id,)).fetchone()
        return json.loads(row[0]) if row else None

    # ------------------------------------------------------------------ llm record / replay
    def put_llm_record(self, key: str, seq: int, response: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO llm_records (key, seq, response) VALUES (?, ?, ?)",
                (key, seq, json.dumps(response)),
            )

    def get_llm_record(self, key: str, seq: int) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT response FROM llm_records WHERE key=? AND seq=?", (key, seq)
        ).fetchone()
        return json.loads(row[0]) if row else None
