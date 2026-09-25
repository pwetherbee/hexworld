# HexWorld: notes for Claude

- Monorepo: `backend/` (Python 3.13, uv, FastAPI) + `frontend/` (Vite, React 19, react-three-fiber, zustand).
- **Everything visual is generated on demand by agents. Nothing is prebaked.** The engine holds only
  interpreters: the material DSL (`art/procedural.py`), the sprite DSL (`art/sprites.py`) and the
  hex/tile renderers. Content comes from the super / tile / material-artist / sprite-artist agents
  (`agents/`) and lives in the world's session library (`World.materials`, `World.sprites`), which
  later tiles reuse. Don't add hand-authored terrain looks or sprite recipes.
- Real LLMs by default (`HEXWORLD_LLM=openai`, key in repo-root `.env`, never commit it). The
  `FakeClient` in `agents/fake.py` is a test double for the pytest suite only. Keep it minimal and
  schema-valid for every task.
- Tiles are layered: a seamless ground layer (seams checked on the ground only) plus sprite layers
  (upright billboards, at most one landmark per tile, contained to the centre). `asset_id` on a
  tile is the flattened preview; `ground_asset_id` is the ground.
- Hex conventions are shared across both sides: pointy-top axial, edge i ↔ neighbour edge (i+3)%6,
  direction order E, NE, NW, W, SW, SE. They live in `backend/hexworld/hex/__init__.py` and
  `frontend/src/board/hexMath.ts` (and the grid shader in `HexGrid.tsx`). Change them together.
- LLM-facing schemas must stay strict-mode compatible: every object closed, all properties required
  (see `agents/llm.py:strict_schema`). DSL values are clamped in validators, never rejected.
- Every state change goes through `RunExecutor._save_tile` / tracer events, since the UI is driven
  entirely by the event stream. New steps should be wrapped in `tracer.span(...)`.
- After changing API models run `pnpm --dir frontend gen:types`.
- Tests: `cd backend && uv run pytest` (fast, offline via the test double);
  `cd frontend && pnpm test && pnpm build`.
- `frontend/public/sfx/` holds licensed audio imported by `scripts/import-sfx.mjs`. Never commit it.
