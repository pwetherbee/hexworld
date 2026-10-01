# HexWorld

Click an empty hex, describe a world or a board game, and watch a team of agents build it.

A **super agent** (the board creator) plans the region and sets the rules: the world spec, a shared
pixel-art style guide, the tile attribute schema, and which slots to fill, leave empty, or
**duplicate**. **Tile agents** design each hex against their surroundings. **Material and sprite
artists** create the world's assets on demand. The super reviews every candidate with vision and
routes feedback to whichever agent owns the problem.

The project is a testbed for multi-agent coordination that is **robust, observable and efficient**.

## Run it

You need an **OpenAI API key**. That's the only secret. Pick one way to run:

| | what you need | command | open |
|---|---|---|---|
| **A. Docker** (easiest) | Docker | `docker compose up --build` | http://localhost:8080 |
| **B. Local dev** (hot reload) | Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22 + pnpm 10 | two terminals, below | http://localhost:5173 |
| **C. Google Cloud Run** | a GCP project + `gcloud` | `gcloud run deploy`, below | the service URL |

### A. Docker

```bash
git clone https://github.com/pwetherbee/hexworld.git
cd hexworld
cp .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY=sk-...`. Then:

```bash
docker compose up --build
```

Open http://localhost:8080. Worlds are saved in the `hexworld-data` Docker volume, so they survive
restarts. Stop with `Ctrl+C`. `docker compose down -v` also deletes the saved worlds.

Without compose:

```bash
docker build -t hexworld .
docker run --rm -p 8080:8080 -e OPENAI_API_KEY=sk-... -v hexworld-data:/data hexworld
```

### B. Local development

```bash
git clone https://github.com/pwetherbee/hexworld.git
cd hexworld
cp .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY=sk-...`. Install the dependencies once:

```bash
cd backend && uv sync && cd ../frontend && pnpm install && cd ..
```

Terminal 1 (API on :8000):

```bash
uv run --project backend hexworld serve
```

Terminal 2 (UI on :5173, proxies `/api` to :8000):

```bash
pnpm --dir frontend dev
```

Open http://localhost:5173. Optional: `node scripts/import-sfx.mjs` imports the UI sounds. They are
licensed, so they're kept out of git and Docker; without them the UI is silent.

### C. Google Cloud Run

The image is a single stateful service. Runs execute in the background inside the server process, and
the UI listens on a WebSocket, so deploy it as **one instance with CPU always on**. These steps use
`gcloud` from the repo root (Cloud Build builds the `Dockerfile` for you).

1. Pick a project and region, and enable the services:

   ```bash
   gcloud config set project YOUR_PROJECT_ID
   gcloud config set run/region us-central1
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
   ```

2. Store the OpenAI key as a secret:

   ```bash
   printf %s "sk-..." | gcloud secrets create openai-api-key --data-file=-
   ```

3. Create a bucket for the worlds (SQLite + generated images), so they survive redeploys:

   ```bash
   gcloud storage buckets create gs://YOUR_PROJECT_ID-hexworld-data --location=us-central1
   ```

4. Grant the service's identity access to both. Cloud Run uses the Compute Engine default service
   account unless you choose another:

   ```bash
   SA="$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
   gcloud secrets add-iam-policy-binding openai-api-key --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor
   gcloud storage buckets add-iam-policy-binding gs://YOUR_PROJECT_ID-hexworld-data --member="serviceAccount:$SA" --role=roles/storage.objectAdmin
   ```

5. Deploy:

   ```bash
   gcloud run deploy hexworld --source . \
     --allow-unauthenticated --execution-environment gen2 \
     --min-instances 1 --max-instances 1 --no-cpu-throttling \
     --cpu 2 --memory 2Gi --timeout 3600 --session-affinity \
     --set-secrets OPENAI_API_KEY=openai-api-key:latest \
     --set-env-vars HEXWORLD_DATA_DIR=/data,HEXWORLD_SQLITE_JOURNAL=DELETE \
     --add-volume name=data,type=cloud-storage,bucket=YOUR_PROJECT_ID-hexworld-data \
     --add-volume-mount volume=data,mount-path=/data
   ```

   `gcloud` prints the service URL when it's done. To deploy a new version, run step 5 again.

Why those flags:

- **`--max-instances 1`**: state lives in one process (SQLite + in-memory run schedulers).
- **`--no-cpu-throttling`** and **`--min-instances 1`**: builds keep running between requests and
  aren't cut off by scale-to-zero.
- **`--timeout 3600`** and **`--session-affinity`**: keep the live event WebSocket open.
- **`HEXWORLD_SQLITE_JOURNAL=DELETE`**: a bucket mount can't do SQLite's default WAL mode.

For heavier use, or if SQLite reports locking errors on the bucket, mount a Filestore (NFS)
volume at `/data` instead.

Want to try it without persistence? Drop the two `--add-volume*` flags and the env vars. Worlds then
live in the container and vanish on redeploy.

`--allow-unauthenticated` makes the URL public, and anyone with it can spend your OpenAI credits.
To keep it private, leave that flag out and put Cloud Run's IAM or IAP in front of it.

### Configuration

All settings are environment variables (or lines in `.env`). The full list, with defaults, is in
`backend/hexworld/config.py`.

| variable | default | what it does |
|---|---|---|
| `OPENAI_API_KEY` | (required) | key for every agent and the image model |
| `HEXWORLD_SUPER_MODEL` / `_TILE_MODEL` / `_ARTIST_MODEL` | `gpt-6-luna` | model per agent role |
| `HEXWORLD_SPRITE_IMAGE_MODEL` | `gpt-image-2.5-flare` | paints sprites and scenes; `""` = draw sprites with the built-in DSL |
| `HEXWORLD_DATA_DIR` | `./data` (`/data` in Docker) | SQLite database + generated PNGs |
| `HEXWORLD_SQLITE_JOURNAL` | `WAL` | `DELETE` on network filesystems (Cloud Run bucket, NFS) |
| `HEXWORLD_HOST` / `HEXWORLD_PORT` | `127.0.0.1` / `8000` | where the local server listens (the container listens on `0.0.0.0:$PORT`, default 8080) |

`uv run --project backend hexworld models` lists the models your key can use.

### For AI agents working on this repo

- Read `CLAUDE.md` first: architecture rules and conventions.
- The backend tests run offline (a scripted fake LLM), so no key is needed:
  `cd backend && uv run pytest`.
- Frontend: `cd frontend && pnpm test && pnpm build`.
- After changing API models (pydantic) run `pnpm --dir frontend gen:types`.
- Never commit `.env`, `data/` or `frontend/public/sfx/`.

## Using it

Click an empty hex and describe a world ("a misty fishing village on a cliff", "New York", "a
dwarven mine"). Agents plan it and build it tile by tile, live. The **game pill** at the top middle
switches to **play mode**:
- Walk the overworld as a traveller.
- **Enter** a tile to open its region: the tile seen up close, built from the parent tile's own map.
- **Look** at any tile for a painted pixel-art scene.

## Agents (Google ADK)

Every run is a collaboration between ADK agents with tools, each in its own persistent session:

| agent | tools | job |
|---|---|---|
| **super planner** | `submit_world`, `submit_layout` | world spec, style, game-specific tile attributes and the origin tile first (the origin starts building at once), then the map's layout: regions of shape primitives, landmarks and routes, within a max-tiles budget |
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

## Shapes and scale

The super draws the map's shape itself, within a **max tiles** budget. Its layout is a set of
regions built from shape primitives (organic blobs, winding paths/bands, rectangles, hexagons;
'void' regions carve out bays, courtyards and gaps), plus landmarks at specific tiles and connector
routes through waypoints (`orchestrator/layout.py` rasterizes it). That yields long valleys,
archipelagos, patchwork districts or floor plans, and planning cost grows with the number of
regions, not tiles. Islands of a plan grow in parallel.

A tile can be any scale: a stretch of countryside, a city block or a room. Built environments use
their own material ops (`lots` of buildings with alleys, `rooms` with doorways, `checker`, `planks`,
`bricks`) and straight-edged connectors for streets, canals and corridors; buildings and walls are
raised ground, so the 3D relief turns them into blocks.

## How a run works

```
prompt ─▶ super.plan (world + origin first, then the layout) ─▶ streaming growth ──▶ done
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
- **Feedback routing.** The reviewer sees each candidate's sprites with their owner (tile prop or
  a material's ambient scatter) and says who should fix a problem. Tile problems go back to the
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
