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
- **One street lattice** (`art/procedural.py: lattice`): vertical lines through every tile-centre
  column (x = i·√3/2·s), horizontal lines through every centre row and midway (y = j·0.75·s). Straight
  connectors run on it (`straight_segments`: diagonal legs turn at right angles) and built materials'
  street grids (`BuildingsSpec.street_grid`) are cut from it, paved with their `street_material`, so
  every road joins up. Built districts are zoned by whole lattice blocks, but only blocks wholly
  inside the hex: anything touching the rim follows the organic band rule, whose warp fades to zero
  at the rim so both tiles sharing an edge agree. Keep new ground features seam-consistent the same
  way (decide near the rim only from what both tiles know: the shared edge's terrain).
- Relief = material `height` (0-4) + height ops + `elevation` (0-40 landform, blended ~5px across
  terrains, ridged world-space noise, liquids flat) + buildings. `data/`-style checks: rendering
  neighbours must agree on levels along shared edges (see `test_elevation_...`).
- **Sprite packs** (with an image model): no per-sprite artists. Requests (plan cast, tile agents'
  `request_prop`, reviewer feedback) queue for ~1s, then ONE `SpriteDirector` call describes the batch
  and the painter paints up to 16 per image (`art/paint.py: pack_frame/split_grid`, blobs assigned to
  cells by centroid). Free cells are filled with the director's ambient `extras`, spread over their
  terrain as sparse material scatter (`ScatterSpec.chance`). The director reviews each pack once
  (≤4 repaints, swapped into tiles). The per-sprite `SpriteArtist` remains for the DSL fallback.
- Sprites stand on the right surface (`layout.GroundOk`): land props never on roofs or water,
  floating ones (`motion == "bob"`) on water; sizes scale with the world's `prop_scale`.
- **Layers and play** (`game/layers.py`, `frontend/src/play.ts`): the overworld is depth 0. Entering a
  tile creates a child `World` (`parent` link, `depth`, `scale_note`; same style, finer terrains) and
  builds it as a full hexagon (`RunOptions.fill_radius`); links live in the `drills` table, scenes in
  `scenes` (never on Tile/World records, which running executors overwrite). Scenes are painted
  backdrop + transparent foreground reduced to 384x256 and animated client-side (`ui/Play.tsx`).
- A region is its parent tile up close (`Layers._guide`): the parent's own pixel map fixes each region
  tile's terrain (`ParentLink.guide`, applied by `rasterize(guide=)` and `_apply_plan`), and its
  streets (all on the lattice) are traced into connector routes (`street_chains`), winding paths into
  tile links kept as a tree that leave through the parent's own edges (`path_links`), both ->
  `ParentLink.routes` -> `guided_hints`; `normalize_design` makes those the only streets/paths.
  Every material in a drilled layer carries an engine-only `Lens` (`MaterialSpec.lens`, hidden from
  agent schemas via SkipJsonSchema, set in `RunExecutor._through_lens`): the renderer reads the
  parent through it, so buildings are the parent's own lots at true size (`paint_buildings`),
  landforms the parent's ridges (`elevation_field`), big patches the parent's (`_paint_lens`).
  Agents get the zoom as metadata: `ParentLink.notes` (what each tile is within the parent: which
  building, street, open ground), `props`, and `context.scale`; the reviewer and tile agents see it
  as `up_close`. Connectors keep the parent's `edges` style, drawn wider (`width` 3.5/1.5).
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
