# HexWorld: notes for Claude

- Monorepo: `backend/` (Python 3.13, uv, FastAPI) + `frontend/` (Vite, React 19, react-three-fiber, zustand).
- Offline by default: `HEXWORLD_LLM=fake`, `HEXWORLD_IMAGE=stub`. Keep every feature working in that
  mode, and add fake/stub behaviour for any new LLM task or image mode (`agents/fake.py`, `art/backend.py`).
- Hex conventions are shared across both sides: pointy-top axial, edge i ↔ neighbour edge (i+3)%6,
  direction order E, NE, NW, W, SW, SE. They live in `backend/hexworld/hex/__init__.py` and
  `frontend/src/board/hexMath.ts`. Change both together.
- LLM-facing schemas must stay strict-mode compatible: every object closed, all properties required
  (see `agents/llm.py:strict_schema`). The super defines tile attributes via `AttributeDef` (a
  restricted meta-schema), never raw JSON Schema.
- Every state change goes through `RunExecutor._save_tile` / tracer events, since the UI is driven
  entirely by the event stream. New steps should be wrapped in `tracer.span(...)`.
- After changing API models run `pnpm --dir frontend gen:types`. It regenerates
  `frontend/src/api/types.gen.ts` from `hexworld export-schema`.
- Tests: `cd backend && uv run pytest` (fast, fully offline); `cd frontend && pnpm test && pnpm build`.
- `frontend/public/sfx/` holds licensed audio imported by `scripts/import-sfx.mjs`. Never commit it.
