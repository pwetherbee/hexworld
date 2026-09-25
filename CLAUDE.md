# HexWorld: notes for Claude

- Monorepo: `backend/` (Python 3.13, uv, FastAPI, **Google ADK** + LiteLLM) + `frontend/` (Vite, React 19,
  react-three-fiber, zustand).
- **Multi-agent, on Google ADK** (`agents/kit.py`). Every agent is an ADK `LlmAgent` with tools, running in
  a persistent session:
  super planner / reviewer / director (`agents/super.py`, `agents/director.py`),
  tile agents (`agents/tile.py`), material + sprite artists (`agents/artist.py`).
  Results come back only through `submit_*` tools that validate and return errors to the agent.
  Feedback is routed to the agent that owns the problem (tile / material / sprite) and continues that
  agent's own session. The orchestrator (`orchestrator/run.py`) owns scheduling, budgets and validation,
  and exposes the facade the tools call.
- **Nothing is prebaked or pre-stocked.** The engine holds only interpreters: the material DSL
  (`art/procedural.py`), painted-sprite pixelization (`art/paint.py`) and the sprite DSL fallback
  (`art/sprites.py`). Assets enter the per-world session
  library (`World.materials`, `World.sprites`) only when a tile or agent first needs them
  (single-flighted). Don't add hand-authored content or up-front generation.
- Real models by default (`HEXWORLD_LLM=openai`, key in repo-root `.env`, never commit it). The
  `FakeClient` brain + `FakeAdkLlm` in `agents/kit.py` are a scripted test double for pytest only.
- Tiles are layered: ground (flat surface colours, seams checked on it), height (relief levels,
  `art/relief.py`) and sprite layers (upright billboards: up to 4 props, max one landmark, fitted by
  `art/layout.py`). The frontend extrudes the height layer (`board/relief.ts`); 2D previews shade it.
- **One world pixel grid** (`art/grid.py`): a tile canvas starts at
  `(floor(cx - s) - 1, floor(cy - s) - 1)` with size `P + 3`. The backend renderers, validators,
  compositor, `board/geometry.ts` (face UVs) and `board/relief.ts` all rely on it; change together.
  Ground PNGs carry a 2px bleed ring past the rim with alpha 254; `load_tile` strips it.
- Scheduling (`RunExecutor._grow/_job`): neighbouring *attempts* never overlap; a tile that passes the
  deterministic checks is provisionally settled (neighbours may start) while it is reviewed, and a
  rejected tile keeps the edges its neighbours were built against (`Job.locked`).
- Hex conventions are shared: pointy-top axial, edge i ↔ neighbour edge (i+3)%6, direction order
  E, NE, NW, W, SW, SE. `backend/hexworld/hex/__init__.py`, `frontend/src/board/hexMath.ts` and the grid
  shader in `HexGrid.tsx` must change together.
- Tool functions in agent modules rely on real type hints (no `from __future__ import annotations`
  there); coerce inputs with `kit.coerce` because models sometimes send raw dicts.
- Every state change goes through `RunExecutor._save_tile` / tracer events. The UI is driven entirely
  by the event stream. New steps should be wrapped in `tracer.span(...)`.
- After changing API models run `pnpm --dir frontend gen:types`.
- Tests: `cd backend && uv run pytest` (offline); `cd frontend && pnpm test && pnpm build`.
- `frontend/public/sfx/` holds licensed audio imported by `scripts/import-sfx.mjs`. Never commit it.
