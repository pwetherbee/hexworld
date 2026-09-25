# HexWorld

Click an empty hex, describe a world or a board game, and watch a team of agents build it.

A **super agent** (the board creator) plans the region and sets the rules: the world spec, a shared
pixel-art style guide, the tile attribute schema, and which slots to fill, leave empty, or
**duplicate**. **Tile agents** then design and paint each hex in parallel, using their
surroundings as context. The super reviews every wave with vision and accepts or rejects each tile,
with concrete feedback for the rejected ones.

The project is a testbed for multi-agent coordination that is **robust, observable and efficient**.

## Quick start

```bash
cd backend && uv sync && cd ../frontend && pnpm install
node scripts/import-sfx.mjs          # optional: local UI sounds (licensed, gitignored)
```

Put your OpenAI key in `.env` at the repo root (`OPENAI_API_KEY=...`; see `.env.example`), then:

```bash
uv run --project backend hexworld serve      # API on :8000
```

```bash
pnpm --dir frontend dev                      # UI on :5173
```

Open http://localhost:5173 and click a hex. Every role (super, tile agents, material artist, sprite
artist) runs on a real model configured per role in `.env`. `hexworld models` lists what your key
can use. Real responses are recorded, so `HEXWORLD_LLM=replay` can re-run a run for free.

## Agents (Google ADK)

Every run is a collaboration between ADK agents with tools, each in its own persistent session:

| agent | tools | job |
|---|---|---|
| **super planner** | `submit_plan` | world spec, style, game-specific tile attributes, the map plan (regions, landmarks, copies) |
| **super anchor** | `submit_anchor` | picks the style anchor from renders of the origin tile |
| **super reviewer** | `zoom_candidate`, `submit_verdicts` | reviews each wave with vision; routes feedback to the tile agent, the material artist or the sprite artist |
| **super director** | `view_map`, `list_pending`, `update_tiles`, `commission_sprite`, `redo_tile`, `finish` | checks in after every ring and steers the rest of the build |
| **tile agent** (one per tile) | `view_surroundings`, `list_library`, `request_prop`, `submit_design` | designs its tile against its neighbours; revises in the same session when rejected |
| **material artist** | `render_material`, `submit_material` | draws a terrain's ground pattern, *looks at its render*, revises, submits |
| **sprite artist** | `render_sprite`, `submit_sprite` | draws a prop from pixel primitives, *looks at its render*, revises, submits |

Budgets (calls, $, wall clock), per-agent call caps, validation and the wave scheduler live in the
orchestrator. Every agent turn, LLM call and tool call is traced into the event stream, and the
inspector's **Agents** tab shows each session as a transcript.

## Nothing is prebaked

The engine contains interpreters, not content. The **material DSL** (`art/procedural.py`: colour
ramp + patches, stripes, voronoi cells + bevel, cellfill, speckle, pixel decals, boundary style)
renders in world space, so tiles are seamless by construction. The **sprite DSL**
(`art/sprites.py`: rect/ellipse/tri/line/pixel with ramp tones, auto-shading, frames and motion)
rasterizes to outlined animation strips. The world's **session library** starts empty and grows
only when a tile or agent first needs an asset. Each one is designed once and reused, and a
material revision repaints every tile that uses it.

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
