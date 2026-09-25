# HexWorld

Click an empty hex, describe a world or a board game, and watch a team of agents build it.

A **super agent** (the board creator) plans the region and sets the rules: the world spec, a shared
pixel-art style guide, the tile attribute schema, and which slots to fill, leave empty, or
**duplicate**. **Tile agents** design each hex against their surroundings. **Material and sprite
artists** create the world's assets on demand. The super reviews every candidate with vision and
routes feedback to whichever agent owns the problem.

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

Open http://localhost:5173 and click a hex. Every role runs on a real model configured per role in
`.env` (default `gpt-6-luna`). Sprites are painted by an image model (`HEXWORLD_SPRITE_IMAGE_MODEL`,
default `gpt-image-2.5-flare`); set it empty to have the sprite artist draw with the sprite DSL
instead. `hexworld models` lists what your key can use.

## Agents (Google ADK)

Every run is a collaboration between ADK agents with tools, each in its own persistent session:

| agent | tools | job |
|---|---|---|
| **super planner** | `submit_plan` | world spec, style, game-specific tile attributes, the map plan (regions, features, copies) |
| **super reviewer** | `zoom_candidate`, `submit_verdicts` | reviews candidates with vision; routes feedback to the tile agent, the material artist or the sprite artist |
| **super director** | `view_map`, `list_pending`, `update_tiles`, `commission_sprite`, `redo_tile`, `finish` | checks in during the build and steers what hasn't been built yet |
| **tile agent** (one per tile) | `view_surroundings`, `list_library`, `request_prop`, `submit_design` | designs its tile (biome, edges, connectors, up to 4 props) against its neighbours; revises in the same session when rejected |
| **material artist** | `render_material`, `submit_material` | designs a terrain's ground pattern and relief, *looks at its render*, revises, submits |
| **sprite artist** | `paint_sprite`, `submit_sprite` | art-directs a prop: an image model paints it, the engine pixelizes it to game scale, the artist *looks* and repaints until it reads |

Budgets (calls, $, wall clock), per-agent call caps, validation and scheduling live in the
orchestrator. Every agent turn, LLM call and tool call is traced into the event stream, and the
inspector's **Agents** tab shows each session as a transcript.

## Nothing is prebaked

The engine contains interpreters, not content. The world's **session library** starts empty and
grows only when a tile or agent first needs an asset (single-flighted: concurrent requests share one
generation). Each asset is designed once and reused, and a material revision repaints every tile
that uses it.

- **Materials** are written in a small DSL (`art/procedural.py`): colour ramp, pattern ops
  (patches, stripes, voronoi cells and cobbles, cellfill, speckle, pixel decals), block style,
  boundary treatment, relief (base height + height ops) and ambient scatter.
- **Sprites** are painted by an image model from the sprite artist's art direction, then reduced
  to game-scale pixel art with a bold outline (`art/paint.py`). Without an image model, they are
  drawn with the sprite DSL (`art/sprites.py`).

## The art engine

- **One world pixel grid** (`art/grid.py`). Every tile is a window onto a single world canvas:
  tile canvases start at integer world pixels, so neighbours paint identical pixels where they
  meet. Tile borders are straight geometric cuts through one continuous texture.
- **Terraria-style ground.** Materials are assigned per 2px art cell, with noise-warped organic
  contours (no square staircases). Surfaces of the same material merge, and framing is drawn only
  on exposed faces. Solids get grain, liquids get glints.
- **Pixel relief.** Each cell has a relief level, exported as the tile's heightmap layer
  (`art/relief.py`). The 3D board extrudes it into terraces with real walls, clipped exactly to
  the hex. 2D previews (review sheets, thumbnails) shade the same relief as 3/4-view cliffs.
- **Layers.** Each tile has a ground layer, a height layer and sprite layers. Up to 4 agent-chosen
  props (at most one landmark) plus ambient scatter are fitted by a layout engine
  (`art/layout.py`), so they stay inside the hex and don't overlap.

## How a run works

```
prompt ─▶ super.plan ─▶ streaming growth from the origin ─────────────────────────▶ done
           world spec     a tile starts when it touches a settled tile and no
           style guide    neighbour is mid-attempt:
           tile schema      tile agent designs ─▶ materials/sprites on demand ─▶ render
           slots/copies     ─▶ deterministic checks ─▶ PROVISIONALLY SETTLED (neighbours may start)
                            ─▶ super reviews (batched, off the critical path)
                            ─▶ accept | reject → revise in-session (edges neighbours used stay locked)
                          director check-ins steer the remaining plan
```

- **Streaming growth.** There are no rings or waves. The scheduler starts any planned tile that
  touches the settled world, prioritising tiles with many settled neighbours. Neighbouring
  *attempts* never overlap, so every design is made against fixed neighbour edges.
- **Provisional settle.** Once a candidate passes the deterministic checks, its edges are frozen and
  neighbours may build against it while the super reviews it. A rejected tile revises its content,
  but keeps any edges a neighbour has already used. A last attempt that passes every check is
  accepted rather than leaving a hole in the world.
- **Surroundings.** Each tile agent gets a lean brief: world vocabulary, its directive and its
  neighbours' edge contracts. Images and the library sit behind tools. Edge contracts are enforced
  deterministically, and a seam metric (colour sets per edge segment) rejects visible seams before
  the super ever looks.
- **Feedback routing.** The reviewer says who should fix a problem. Tile problems go back to the
  tile agent's session. Ground-pattern problems go to the material artist, whose fix repaints every
  tile using that material. Sprite problems go to that sprite's artist.
- **Copies.** The super can mark filler slots (open sea, plain desert) as copies of a prototype
  tile. A **shallow** copy is a linked instance that follows its prototype. A **deep** copy is an
  independent snapshot. Copies cost no LLM calls and are re-rendered in place, so they stay
  seamless with their own neighbours.
- **Robustness.** Structured tool submissions are validated, and errors go back to the agent.
  Transient errors are retried, and each run has budgets (calls, $, wall clock) and can be
  cancelled. One tile's failure never sinks the run, and a crashed run resumes from SQLite on
  restart.
- **Observability.** Every step is a typed event with hierarchical spans (run → tile job → attempt
  → design / image / layers / review → llm call). Events are persisted to SQLite + JSONL and
  streamed over WebSocket. The UI inspector has a trace timeline, per-tile attempt history,
  agent transcripts and token/cost counters.

## UI

The board fills the screen. Info appears only when you ask for it: click a tile, or press **I**, for
the inspector drawer. Hover the run capsule for live stats. **F** toggles the camera following the
build (rate-limited and smoothed, and it pauses whenever you grab the camera). **M** toggles sound.

## Layout

```
backend/hexworld/
  hex/            axial math, edge geometry
  domain/         pydantic models (plan, directive, design, tile, run, library…)
  agents/         ADK kit, super / director / tile / artist agents, prompts, fake test brain
  art/            grid.py (world pixel grid), procedural.py (material DSL), relief.py,
                  paint.py (painted sprites), sprites.py (sprite DSL, flatten), layout.py,
                  pixelize.py, composite.py, backend.py (image backends)
  orchestrator/   run.py (scheduler, library, review), copies.py, validators.py, runtime.py
  telemetry/      events + spans, event bus
  store.py        SQLite + content-addressed PNG assets
  api/            FastAPI REST + WebSocket stream
frontend/src/
  board/          three.js board (react-three-fiber): relief meshes, sprites, camera rig/director
  ui/             minimal chrome, inspector drawer, prompt card
  api/            typed client (types generated from backend schema: `pnpm gen:types`)
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
