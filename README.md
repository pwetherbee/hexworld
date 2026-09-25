# HexWorld

Click an empty hex, describe a world or a board game, and watch a team of agents build it.

A **super agent** (the board creator) plans the region and sets the rules: the world spec, a shared
pixel-art style guide, the tile attribute schema, and which slots to fill, leave empty, or
**duplicate**. **Tile agents** then design and paint each hex in parallel, using their
surroundings as context. The super reviews every wave with vision and accepts or rejects each tile,
with concrete feedback for the rejected ones.

The project is a testbed for multi-agent coordination that is **robust, observable and efficient**.

## Quick start (fully offline)

```bash
cd backend && uv sync && cd ../frontend && pnpm install
node scripts/import-sfx.mjs          # optional: local UI sounds (licensed, gitignored)
```

```bash
uv run --project backend hexworld serve      # API on :8000
```

```bash
pnpm --dir frontend dev                      # UI on :5173
```

Open http://localhost:5173 and click a hex. By default the fake LLM and the procedural stub renderer
are used, so the whole pipeline (planning, waves, validation, review, retries, copies, telemetry)
runs with no API keys or GPU. Copy `.env.example` to `.env` to switch to real backends:

| | offline | real |
|---|---|---|
| LLM | `HEXWORLD_LLM=fake` | `openai` (+ `OPENAI_API_KEY`), or `replay` to re-run recorded runs for free |
| Art | `HEXWORLD_IMAGE=stub` | `comfyui` (local open-source models, see `services/comfyui/`) or `openai` |

## How a run works

```
prompt ─▶ super.plan ──▶ anchor bootstrap ──▶ waves (ring by ring, 3-colour classes) ──▶ done
           world spec     N origin renders     ┌─ tile agents design (parallel, LLM)
           style guide    super picks one      ├─ image: inpaint INTO the accepted neighbours
           tile schema    with vision =        ├─ pixelize: palette-first + hex mask
           slots/copies   the style anchor     ├─ deterministic checks (edges, seams, coverage)
                                               ├─ super reviews the whole wave in 1 vision call
                                               └─ reject → retry with feedback → simplified → failed
```

- **Waves.** Within a ring, tiles are split by hex 3-colouring (`(q - r) mod 3`), so no two tiles
  in a wave are adjacent. Every tile then sees only accepted neighbours, the wave runs fully in
  parallel, and it gets reviewed in one batched vision call.
- **Surroundings.** Each tile agent gets its neighbours' edge contracts, summaries and art prompts,
  plus an image of the map around its slot. The image model inpaints the new tile into a canvas of
  the real neighbour pixels. An edge contract (terrain + connectors per edge) is enforced
  deterministically, and a pixel seam metric rejects visible seams before the super ever looks.
- **Copies.** The super can mark filler slots (open sea, plain desert) as copies of a prototype
  tile. A **shallow** copy is a linked instance that follows its prototype. A **deep** copy is an
  independent snapshot. Copies cost no LLM or image calls, but must pass the same edge and seam
  checks. If one doesn't fit its surroundings, that slot is generated instead.
- **Robustness.** Strict structured outputs validated by pydantic/jsonschema with one repair
  round-trip. Tenacity retries on transient errors, per-run budgets (calls, $, wall clock) and
  cancellation. An image circuit breaker falls back to another backend. One tile's failure never
  sinks its wave, and a crashed run resumes from SQLite on restart.
- **Observability.** Every step is a typed event with hierarchical spans (run → wave → tile
  attempt → llm call / image). Events are persisted to SQLite + JSONL and streamed over WebSocket.
  The UI inspector has a trace timeline, per-tile attempt history (images, seams, verdicts,
  feedback) and token/cost counters. `hexworld runs show <id>` prints p50/p95 latencies and
  acceptance rates.

## UI

The board fills the screen. Info appears only when you ask for it: click a tile, or press **I**, for
the inspector drawer. Hover the run capsule for live stats. **F** toggles the camera following the
build (rate-limited and smoothed, and it pauses whenever you grab the camera). **M** toggles sound.

## Layout

```
backend/hexworld/
  hex/            axial math, rings, 3-colouring, edge geometry
  domain/         pydantic models (plan, directive, design, tile, run, copy spec…)
  agents/         super.py, tile.py, prompts.py, llm.py (OpenAI/fake/record/replay + gateway), fake.py
  art/            backend.py (stub/ComfyUI/OpenAI/circuit breaker), pixelize.py, composite.py
  orchestrator/   run.py (state machine + waves), copies.py, validators.py, runtime.py
  telemetry/      events + spans, event bus
  store.py        SQLite + content-addressed PNG assets
  api/            FastAPI REST + WebSocket stream
frontend/src/
  board/          three.js board (react-three-fiber), tile animations, camera director
  ui/             minimal chrome, inspector drawer, prompt card
  api/            typed client (types generated from backend schema: `pnpm gen:types`)
services/comfyui/ workflow templates + setup notes
```

## Checks

```bash
cd backend && uv run pytest && uv run ruff check .
```

```bash
cd frontend && pnpm test && pnpm build
```

```bash
uv run --project backend hexworld eval --radius 2
```

`hexworld eval` runs canned prompts headlessly and reports acceptance rate, attempts per tile, cost
and seam continuity.
