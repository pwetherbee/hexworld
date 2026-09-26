# World life: abundance, placement and motion

Make every world feel inhabited before any game starts, and give games a living stage to play on.
Research: [../research/world-aliveness.md](../research/world-aliveness.md).

Status: **draft spec**. Independent of the game templates, but Adventure's roaming creatures and NPCs
reuse everything here, so it comes first in the roadmap.

---

## 1. Where we are

- A tile shows at most ~4 agent-chosen props, 1 landmark and a little material scatter (≤ 6 sprites),
  placed in hand-picked slots by `art/layout.py`.
- Each sprite is its own mesh with its own per-frame callback; all sway at the same frequency.
- Sprites are painted in packs of 16 with ambient extras spread by material scatter (`chance`).
- Nothing moves across tiles, time doesn't pass, and there is no weather or sound bed per place.

The result reads as a diorama. The target is a place where things live.

## 2. Targets

| measure | now | target |
|---|---|---|
| visible things per tile | ≤ 6 | 15–30 (≈70% tiny scatter) |
| sprites per world (distinct kinds) | 14–29 | 30–60, across all scales |
| things moving at any moment (in view) | sway only | 10–40 (walkers, critters, birds, smoke, water) |
| draw calls for sprites | one per sprite | one per pack atlas |
| a world at 03:00 vs 15:00 | identical | visibly different (light, who is out, fireflies) |

## 3. Layers of life (per tile budget)

| layer | what | count per tile | who decides | rendered as |
|---|---|---|---|---|
| L0 ground detail | pebbles, cracks, tufts | painted | material artist (DSL) | ground texture |
| L1 micro-scatter | flowers, grass tufts, litter, shells | 8–20 | material recipe + engine | instanced, tiny, low contrast, shader sway |
| L2 mid props | bushes, rocks, crates, fences, small trees | 3–7 in 1–3 clusters | tile agent picks kinds + recipes; engine places | instanced, contact shadow |
| L3 actors | people, animals, vehicles | settlement 1–4, wild 0–2 | tile agent + roster; engine places and animates | instanced, walking on routines |
| L4 landmark | big tree, fountain, lighthouse | 0–1 | tile agent | instanced, tallest |
| L5 ambient FX | birds, butterflies, fireflies, smoke, ripples | 0–3 systems | derived from tile data, client-only | particles / instanced |

> **Decision:** density varies by biome and settlement (desert ×0.3, plains ×1, forest ×1.6, town
> streets: flora ×0.5 and actors ×2), set per material by the artist within engine bounds.

## 4. Placement: recipes, not slots

The agent chooses **what** and **how it tends to be placed**; the engine samples **where**,
deterministically (seeded by tile and sprite index), seam-aware.

```jsonc
// a placement recipe (new, on props and scatter)
{ "kind": "reed clump", "layer": "L1",
  "density": 0.6,            // relative to the layer budget
  "spacing": 0.10,           // Poisson radius, in hex radii
  "cluster": [3, 5],         // children per cluster (odd groups), or null for even spread
  "likes":  { "water_edge": 0.8, "slope": -0.2 },
  "avoids": { "path": 1.0, "building": 1.0 } }
```

- **Candidates:** Poisson-disk (Bridson) over the hex, then **clusters** (Matérn process: centres, then
  children at a Gaussian offset, scaled 0.6–0.85).
- **Fields** evaluated per candidate from data we already have: ground material and its neighbours
  (water edge, forest edge), height and slope (relief), buildings (facade codes), paths and connectors,
  the landmark position, distance to the tile rim (for seam continuity, fields read neighbour edges).
- **Composition rules:** odd groups, one dominant element per cluster, mirrored flips, 30–50% of the
  tile left open, silhouettes separated along the camera's screen axis.
- **Vignettes:** at most one per tile, a fixed little scene placed as a unit on a small cleared
  stage (campfire + log + bedroll; broken cart + spilled crates + a kneeling person). The tile agent
  asks for one; the pack director paints its parts.
- **Context decorators** (Townscaper): the engine adds details where conditions meet (a mooring post
  where a path meets water, a signpost at a 3-way junction, a well in a village's central clearing),
  drawn from the world's cast.

## 5. Sprite packs across scales

- Packs (16 per image) are planned **across layers**: roughly 6 micro, 6 mid, 3 actors, 1 landmark,
  not 16 mid props. The planner's cast grows to 30–60 kinds per world.
- **Per-instance variety for free:** scale ±15%, horizontal flip, tint ±5%, animation phase and speed
  ±20%, seeded from tile and index (backend and frontend agree).
- **Idle frames:** actors and some props get 2–4 frame idles. The image model paints a 2–4 frame strip
  in one cell (the pack prompt already supports strips; to be validated).

## 6. Motion

Tiers, cheapest first:
1. **Shader-only**: wind sway from one world wind field (gusts roll across the board), bob, breathing
   (≈0.3 Hz, 1–3% squash) for creatures and people, flicker, water shimmer.
2. **Local wander**: critters and idle people drift within a radius of their anchor, pause, face things,
   fidget (a Poisson process, mean 3–8 s).
3. **Routines**: settlement actors walk between points of interest (doors, well, stalls, docks, fields)
   on a Stardew-style schedule (`hour → poi`), pathing over the hex graph and within tiles along free
   space.
4. **Simulation** (later, and game-driven): herds that move between tiles, populations that respond to
   the player (Adventure), colonists with needs (Sandbox).

Ambient systems (client-only, derived from tile data, no LLM):
- birds: a boids flock crossing the view every 20–60 s, perchers on trees and roofs that take off when
  the camera comes close;
- butterflies and bees by flower clusters by day; fireflies near grass and water at night;
- fish ripples and jumps on water tiles; chimney and campfire smoke drifting with the wind;
- rain and snow particles when a weather state is active.

## 7. Time, weather, sound

- A **world clock** (optional in build mode; always on in play mode): light colour ramp, windows and
  lanterns light at dusk (the facade shader already has lit windows), actors go home, fireflies come
  out.
- **Weather** states per region (clear, rain, fog, snow, wind) chosen by a slow clock and the world's
  climate; they change actor counts and critter types.
- **Sound**: a looping bed per biome mixed by what is in view, plus randomised one-shots from nearby
  emitters (a bird, a hammer, a bell), with a strict voice budget. (Licensed library via the existing
  sfx importer; generated audio is out of scope.)

## 8. Traces of history

- **Worn paths**: at build time, A* between settlements, docks and landmarks over the hex graph
  (weighted by relief) writes faint tracks into the ground layer; scatter avoids them automatically.
- **World events**: the planner writes 3–6 short past events (a flood, an abandoned mine, a fair); tiles
  near each get matching vignettes (a debris line and a stranded boat; a ruined cart and bats at dusk).
  This doubles as the Adventure bible's history evidence.
- **Missable details**: about 1 tile in 5 gets one small rare thing (a fox in a hedge, a lost hat).

## 9. Rendering (frontend)

- One `InstancedMesh` per pack atlas; per-instance attributes for position, scale, atlas cell, phase,
  speed, motion type, tint, flip, birth time. Billboarding and the lean-back in the vertex shader;
  all idle motion in the shader from `uTime`. No per-sprite React components or `useFrame`.
- Walkers in a separate small instanced mesh, positions updated from a flat array.
- Alpha test (no sorting), nearest filtering, pixel snapping; distance fade for L1; per-chunk culling.
- The staggered pop-in stays (driven by a birth attribute), so a world being built still blooms.

## 10. Build order

1. Instanced renderer + shader motion (unlocks 10× sprite counts; no visual change otherwise).
2. Placement recipes + cluster sampler + fields in `art/layout.py`; layer budgets.
3. Packs planned across scales; per-instance variety; bigger casts.
4. Ambient FX + world clock + weather.
5. Actors with points of interest and routines.
6. Worn paths, world events and vignettes, missable details.

Each step is measurable against §2 on the standard test worlds (NYC, market town, fishing village,
alpine valley, canyon town, volcanic island).

## 11. Open questions

- Should the world clock run in build mode by default, or only when toggled (a sun icon)?
- Walkers in build mode: always, or only when zoomed in (performance and calm)?
- Sound: do we want ambience in build mode, or only in play mode?
