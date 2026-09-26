# Making HexWorld feel alive: research notes

Scope: placement and composition, abundance budgets, motion and life, emergent traces, and three.js/r3f
performance. Where a claim comes from a source it is cited. Numbers marked **(heuristic)** are my own
recommended starting values for HexWorld, to be tuned by eye.

Current state, checked in the repo: `backend/hexworld/art/layout.py` fits up to about 4 props and 1 landmark
per tile with width caps (landmark 0.95, prop 0.6, scatter 0.4 radii) and a nearest-free ring search.
`frontend/src/board/TileMesh.tsx` renders each sprite as its own mesh with its own `useFrame`
(cylindrical billboard plus `sway`, `bob`, `flicker` and `pulse` motions, all at a fixed frequency with a
per-sprite phase). Both limits, few sprites and one draw call and one JS callback per sprite, are the
main things to change.

---

## 1. Placement and composition

### 1.1 Separate *candidate generation* from *filtering*
Every production system I found uses the same two-stage pattern:
1. **Candidates:** blue-noise points from Poisson-disk sampling (a minimum distance `r` between points).
   Bridson's algorithm is O(n): a background grid with cell size `r/√2` holds at most one sample per cell,
   and each active sample tries `k≈30` candidates in the annulus `[r, 2r]`
   ([Bridson 2007](https://www.cs.ubc.ca/~rbridson/docs/bridson-siggraph07-poissondisk.pdf)).
2. **Filters/weights:** each candidate is kept with probability `density(x)`, which comes from world data.
   CropCraft modulates Poisson placement with a noise density map
   ([arXiv 2511.02417](https://arxiv.org/pdf/2511.02417)). A common vegetation pipeline takes Poisson
   candidates and then filters them against noise, slope and waterline
   ([Medium, GPU-instanced vegetation](https://medium.com/@willdavis84/gpu-instanced-vegetation-over-voxel-terrain-1754281c5ceb)).
   Horizon Zero Dawn's GPU placement builds per-asset density maps from height, slope, water distance and
   roads. Artists author the rules in a graph editor, and the same system places sounds, effects and
   wildlife as well as rocks and trees
   ([Guerrilla](https://www.guerrilla-games.com/read/gpu-based-procedural-placement-in-horizon-zero-dawn),
   [80.lv](https://80.lv/articles/the-procedural-nature-of-the-horizon-zero-dawn),
   [GDC Vault](https://gdcvault.com/play/1024700/GPU-Based-Run-Time-Procedural)).
   Minecraft's "placed features" work the same way: an ordered chain of placement modifiers
   (`count`, `rarity_filter` = 1/chance, `biome`, height and surface filters) turns one attempt into zero
   or more positions ([Minecraft Wiki: Placed feature](https://minecraft.wiki/w/Placed_feature)).

**For HexWorld:** give each sprite kind a *placement recipe* rather than a hand-picked slot. For example:
`{radius: 0.12, density: 0.6, near: {water: +0.5, landmark: +0.3}, avoid: {path: -1, slope>2: -0.7}, cluster: 3-5}`.
The tile agent (LLM) chooses *which* sprites and the *recipe parameters*, and a deterministic engine
samples the positions. This matches how Horizon's artists author rules without placing instances by hand.

### 1.2 Affinity and avoidance rules (ecological logic)
- Moisture falls with distance from fresh water and drives biome choice
  ([Red Blob, polygon map generation](http://www-cs-students.stanford.edu/~amitp/game-programming/polygon-map-generation/)).
  Horizon even tells the player that ridge-wood grows more densely near water. Use distance-to-water as a
  density input for reeds, trees and frogs.
- Suggested rule table **(heuristic)**, evaluated on the hex's ground and height layers plus its neighbours:
  | kind | likes | avoids |
  |---|---|---|
  | trees/bushes | water distance ≤ 1 tile, other trees (clumping) | paths, steep relief, building doors |
  | rocks/boulders | slopes, relief edges, cliff feet | path centre |
  | flowers/mushrooms | tree edges (ecotone), shade side | paths |
  | reeds/lilies | shoreline band (ground colour = water/wet) | dry ground |
  | people | doors, paths, market props, benches, fields | water, cliffs |
  | animals | grass, near other animals (herds), fences | buildings, crowds |
  | vehicles | roads, docks, barns | grass interior |
- Implement each rule as an additive field sampled at a candidate. Keep a candidate when
  `rand < clamp(base + Σ w·field)`. Neighbour tiles' edge content feeds fields near the rim, so forests
  continue across seams.

### 1.3 Clustering (the biggest visual win)
Uniform blue noise alone looks like "oatmeal" (see 2.3). Nature and set dressing both clump:
- The Level Design Book tells you to compose set dressing in **clusters of related details** (Gestalt
  proximity and similarity) and to build **asymmetric fractal groups**: place one rock, then duplicate,
  shrink, rotate and offset it, and repeat
  ([Level Design Book: Environment Art](https://book.leveldesignbook.com/process/env-art)).
- Algorithm: sample **cluster centres** with a large Poisson radius, then **children** around each centre
  (Thomas/Matérn cluster process). Each child sits at a Gaussian offset σ ≈ 0.3–0.5 of the cluster radius,
  is scaled to 0.6–0.85 of the parent, and has a small Poisson radius so children don't overlap.
- **Odd groups (1, 3, 5)**, one dominant element, varied scale and a mirrored flip. Never place 2 or 4
  equal copies side by side. (A standard art-composition rule of thumb; the fractal-cluster advice above
  is its level-design form.)
- **Negative space:** leave 30–50% of a tile's area **(heuristic)** open ground so the ground material
  reads and clusters have silhouettes. Clearings are also where characters go.

### 1.4 Storytelling vignettes
- Environmental storytelling means staging "player space with environmental properties that can be
  interpreted as a meaningful whole" (Smith & Worch, GDC 2010:
  [GDC Vault](https://gdcvault.com/play/1012647/What-Happened-Here-Environmental),
  [Worch lectures](https://www.worch.com/lectures/)). Smith adds that it "has to be possible to miss some
  things to make finding them meaningful"
  ([Nieman Storyboard](https://niemanstoryboard.org/2011/01/14/harvey-smith-on-environmental-storytelling-and-embedding-narrative/)).
- Practical form: a **vignette** is a small, fixed-composition group that implies an action or cause, e.g.
  campfire + log seat + bedroll; cart with a broken wheel + spilled crates + a person kneeling; fishing
  pole + bucket on a dock; woodpile + axe + stump. Let the tile agent ask for **at most one vignette per
  tile (heuristic)**, and have the layout engine place it as a unit with a local "stage" (a small bare
  ground patch).
- Townscaper shows the rule-based version: gardens spawn only in enclosed flat areas next to walls, and
  benches, bushes and chimneys appear from local conditions (corners, colour changes)
  ([Game Developer: How Townscaper Works](https://www.gamedeveloper.com/game-platforms/how-townscaper-works-a-story-four-games-in-the-making)).
  HexWorld equivalent: context-triggered "decorators", such as a mooring post where a path meets water,
  a signpost where 3+ tile edges carry paths, or a well in the most central clearing of a village.

### 1.5 Composition at three scales and leading lines
- BotW deploys three scales of "triangle" everywhere: large ones are landmarks, medium ones block the
  view, small ones set rhythm. Keeping clear contrast between scales is what keeps the hierarchy from
  going muddy ([Radiator Blog](https://www.blog.radiator.debacle.us/2017/10/open-world-level-design-spatial.html),
  [Kotaku](https://kotaku.com/breath-of-the-wilds-biggest-design-secret-lots-of-tria-1819113140)).
  For HexWorld this means one landmark per tile (already enforced), mid props in 1–3 clusters, and a
  sea of small scatter.
- **Leading lines:** align scatter along paths, rivers and field furrows (orient them and bias density to
  the edges of a path, not its centre). Paths should curve rather than run straight
  (Radiator, same source).

### 1.6 How other games decorate and populate (quick reference)
- **Minecraft:** a per-biome ordered feature list, count + rarity + surface filters per feature, and a
  dedicated vegetal decoration step ([Minecraft Wiki: World generation](https://minecraft.wiki/w/World_generation)).
- **Terraria:** *critters* (5 HP, harmless) spawn by biome and conditions. Butterflies appear only by day
  when it is not raining and wind is below 20 mph; fireflies appear near grass at night, with a random
  nightly rate; worms appear in rain ([Critters](https://terraria.wiki.gg/wiki/Critters),
  [Butterflies](https://terraria.wiki.gg/wiki/Butterflies), [Firefly](https://terraria.wiki.gg/wiki/Firefly)).
  **Lesson: ambient life is conditioned on time, weather and biome, so it changes.**
- **Stardew Valley:** debris (weeds, stones, twigs) and forage respawn daily into free tiles, and rain
  changes the amounts ([Foraging](https://stardewvalleywiki.com/Foraging),
  [Weeds](https://stardewvalleywiki.com/Weeds)). NPCs follow data-driven schedules of
  `time location x y facing animation dialogue`
  ([Modding: Schedule data](https://stardewvalleywiki.com/Modding:Schedule_data)).
- **RimWorld:** each biome defines `plantDensity`, `animalDensity` and wild-plant regrow days. The game
  keeps wild animal counts near a target by letting animals wander in and out
  ([RimWorld Wiki: Biomes](https://www.rimworldwiki.com/wiki/Modding_Tutorials/Biomes)). Colonist
  traffic wears grass into packed-dirt paths that revert when unused
  ([fluffy-mods/DesirePaths](https://github.com/fluffy-mods/DesirePaths)).
- **Dwarf Fortress:** simulates centuries of history before play. Its designer describes this as a
  "zero-player strategy game" whose record is the history, and it yields ruins, sites and legends you can
  visit ([DF Wiki: World generation](https://www.dwarffortresswiki.org/index.php/World_generation)).
- **Caves of Qud:** generates history (sultans, villages) and *rationalises it after the fact* instead of
  running a full simulation ([GDC 2018](https://gdcvault.com/play/1024990/Procedurally-Generating-History-in-Caves),
  [End-to-end PCG slides](https://media.gdcvault.com/gdc2019/presentations/Grinblat_Jason_End-to-End_Procedural_Generation.pdf)).
  This is a cheap, LLM-friendly model for HexWorld's narrative traces.
- **No Man's Sky:** noise fields and parametric/L-system rules combine human-authored parts into flora
  and fauna ([Wikipedia: Development of NMS](https://en.wikipedia.org/wiki/Development_of_No_Man%27s_Sky)).
  It is also the cautionary tale for "oatmeal" ([Vice](https://www.vice.com/en/article/nz7d8q/no-mans-sky-review)).
- **Townscaper / WFC:** local-rule decorators plus small "AI" birds and butterflies that anchor to a
  nearby object, occasionally fly around it and react to local geometry. Details fill in *staggered*
  after placement so the player watches them appear (Game Developer, above).

---

## 2. Abundance budgets and layering

### 2.1 Five layers, each with its own budget
The Level Design Book says to start with major shapes and then iterate smaller details, keeping value and
contrast hierarchy so gameplay stays readable (source above). Proposed per-tile budget for HexWorld,
at the current ~P px tile **(heuristic)**:

| layer | examples | count per tile | size (radii) | notes |
|---|---|---|---|---|
| L0 ground detail | pebbles, grass tufts, cracks | painted into ground PNG | – | material DSL; free |
| L1 micro-scatter | flowers, tufts, small stones | **8–20** | 0.05–0.12 | instanced, tiny, low contrast, no shadow |
| L2 mid props | bushes, rocks, crates, fences, small trees | **3–7** in 1–3 clusters | 0.15–0.4 | contact shadow, sway |
| L3 actors | people, animals, vehicles | **1–4** (settlement), **0–2** (wild) | 0.12–0.25 | the only layer that moves around |
| L4 landmark | big tree, tower, house, statue | **0–1** | ≤0.95 | tallest silhouette |
| L5 ambient FX | birds, butterflies, smoke, sparkles | 0–3 systems | – | client-only, not in tile data |

That comes to about 15–30 visible things per tile, against the current ≤5. The key is that about 70% of
them are L1: small, low-contrast and cheap. Don't raise L2 or L3 very far or the tile turns to soup.

### 2.2 Readability rules
- **Value contrast is reserved for what matters**: L3 actors and L4 landmarks get the highest contrast and
  the only outlines. L1 scatter is kept within ±15% value of the ground **(heuristic)**.
- **Silhouette separation:** keep a gap of at least 0.5 × sprite width between L2/L3 sprites along the
  camera's screen x-axis (billboards overlap in screen space even when their footprints don't).
- **Density varies by biome and settlement tier**, as RimWorld's per-biome `plantDensity`/`animalDensity`
  do: desert 0.3×, plains 1×, forest 1.6×, town streets 0.5× flora + 2× actors **(heuristic)**.

### 2.3 Avoiding "10,000 bowls of oatmeal"
Kate Compton's point is that *perceptual differentiation*, not mathematical difference, is the real
metric ([Compton, "So you want to build a generator"](https://galaxykate0.tumblr.com/post/139774965871/so-you-want-to-build-a-generator),
[Emily Short](https://emshort.blog/2016/09/21/bowls-of-oatmeal-and-text-generation/)).
For HexWorld:
- Vary **per-instance** scale ±15%, horizontal flip, tint ±5% hue/value and animation phase/speed ±20%.
  All of this is free, and it makes 16 painted sprites read like 60+.
- Vary **per-tile** composition: which cluster is dominant, where the clearing is, whether there is a
  vignette.
- A 16-sprite pack should cover all three scales (e.g. 6 micro, 6 mid, 3 actors, 1 landmark), not 16
  mid props.

---

## 3. Motion and life

### 3.1 Tiers from "faked" to "simulated"
Use the cheapest tier that sells the effect:
1. **Shader-only (no state):** wind sway, bob, breathing, water shimmer, fire flicker, leaf rustle.
2. **Local wander (tiny state, client-only):** critters, chickens and idle villagers take random walks
   within a radius of an anchor. Townscaper's birds and butterflies are exactly this.
3. **Scheduled routines (data-driven):** Stardew-style `time → (place, pose)` tables walked on the hex
   graph.
4. **Utility / "smart object" AI:** objects advertise what they satisfy and agents pick the best score
   weighted by needs. The Sims ("the objects are advertising") grew out of SimAnt pheromones
   ([GMTK: The Genius AI Behind The Sims](https://gmtk.substack.com/p/the-genius-ai-behind-the-sims)).
   Skyrim's Radiant AI is a prioritised package stack re-evaluated periodically: the topmost package whose
   conditions hold (time, location, "Sandbox") runs
   ([Nexus: How AI Overhaul works](https://www.nexusmods.com/skyrimspecialedition/articles/2467),
   [UESP/Fandom: Radiant AI](https://elderscrolls.fandom.com/wiki/Radiant_A.I.)).

For a viewer-driven world builder, **tiers 1–3 give about 90% of the feel**. Tier 4 is a later
"world ticks without you" feature.

### 3.2 Idle animation rules
- **Desynchronise everything**: characters that idle in lockstep look robotic
  ([Godot forum](https://forum.godotengine.org/t/npc-idle-animations-desynced/141321)). Use a random phase
  *and* a random ±20% speed per instance. Today TileMesh uses a fixed 1.4 Hz sway and 2.2 Hz bob for all
  sprites, which is worth changing.
- **Breathing** (a 1–3% vertical squash at about 15–20 cycles per minute, i.e. ~0.3 Hz) for people and
  animals, and **weight shifts** every 4–8 s ([MoCap Online idle guide](https://mocaponline.com/blogs/mocap-news/idle-animation-game-dev-guide)).
- **Random "fidget" events** (a 2-frame blink, a turn to face another direction, a peck, a tail flick)
  fire as a Poisson process with a mean of 3–8 s per actor **(heuristic)**. Animal Crossing villagers
  cycle through personality-coloured activities (jocks exercise, lazy villagers fish or sit by rivers,
  music-hobby villagers sing anywhere)
  ([Nookipedia: Villager](https://nookipedia.com/wiki/Villager), [Hobby](https://nookipedia.com/wiki/Hobby)).
  Map sprite kind to a small verb set (person: idle/walk/talk/work, animal: graze/walk/sit).
- **Wind as a world field, not a per-sprite sine**: `sway = A·sin(t·ω + k·(x+z)) + noise(x, z, t)`. A
  gust front travelling across the board makes trees on neighbouring tiles move *together but offset*,
  which reads as wind rather than jitter
  ([Codrops fluffy grass](https://tympanus.net/codrops/2025/02/04/how-to-make-the-fluffiest-grass-with-three-js/),
  [al-ro grass](https://al-ro.github.io/projects/grass/)).

### 3.3 Ambient creatures
- **Birds:** a boids flock (separation, alignment, cohesion; [Reynolds](https://www.red3d.com/cwr/boids/))
  of 5–15 birds that crosses the board every 20–60 s **(heuristic)**, plus perching birds anchored to
  trees and roofs that take off when the camera zooms close (Townscaper anchoring).
- **Butterflies/bees:** 2–4 around flower clusters by day. **Fireflies** around grass or water at night.
  **Fish** as ripples or jumping sprites on water tiles. All are gated by time of day and weather, as
  Terraria's critters are.
- **Smoke** from chimneys, campfires and forges: 6–12 particles per source **(heuristic)**, rising and
  drifting with the wind field.
- These are **client-only and derived** from tile data (e.g. "has flowers" → butterflies), so they need
  no LLM calls and stay in line with "nothing prebaked": they are interpreters over agent-made content.
  Their sprites can come from the same on-demand painted packs.

### 3.4 Routines on the hex graph
- Give each settlement tile **points of interest** (doors, well, market stall, field, dock). Actors hold a
  tiny schedule (Stardew format: `hour → poi`, [Schedule data](https://stardewvalleywiki.com/Modding:Schedule_data))
  and path between POIs with A* over hex centres and edge midpoints
  ([Red Blob: Hexagonal Grids](https://www.redblobgames.com/grids/hexagons/)). Within a tile they steer
  along the layout engine's free space.
- Use cheap "sandbox" fallbacks when no schedule applies: wander within 0.3 radii of the anchor, stop at a
  prop for 3–10 s, face it, then play a verb.
- **Budget:** at most about 30–60 actively walking actors in view **(heuristic)**, with the rest idle in
  place. Nobody can tell whether off-screen actors are simulated.

### 3.5 Day/night, weather, sound
- **Day/night:** a global light colour and ambient ramp, window and lantern emissive sprites that turn on
  at dusk (the existing `pulse`/`flicker` motion fits), and critter sets swapped by time (butterflies to
  fireflies).
- **Weather:** rain streak particles, puddle shimmer, fewer people outside, worms (Terraria) and wind
  gusts. Tie Stardew-style "rain changes spawns" to the actor and critter budgets.
- **Sound:** a looping **bed** per biome with few distinct details, plus **randomised one-shots** (bird
  call, hammer, dog bark) from nearby emitters with a strict voice budget. Distinct sounds must not live
  in the loop or players notice the repetition
  ([Game Audio Learning Portal](https://www.gameaudiolearning.com/knowledgebase/how-to-make-ambiences-for-games),
  [Bugnet: ambient layers](https://bugnet.io/blog/how-to-design-ambient-sound-layers)).
  Mix the bed by camera-weighted biome proportions of the tiles in view.

---

## 4. Emergence and narrative traces
- **Marks that systems leave:** RimWorld, Animal Crossing (City Folk/New Leaf) and Death Stranding wear
  paths where agents walk, and the paths revert when unused
  ([DesirePaths](https://github.com/fluffy-mods/DesirePaths),
  [Wikipedia: Desire path](https://en.wikipedia.org/wiki/Desire_path)). HexWorld can compute *planned*
  desire paths at build time: connect settlements, docks and landmarks with A* on the hex graph weighted
  by relief, and write those edges into the ground layer as worn tracks. Scatter density then drops along
  them automatically, since paths are an avoidance field.
- **History as rationalised backstory (Qud-style):** the super planner can emit 3–6 short "events" for
  the world (a flood, an abandoned mine, a fair). Tiles near an event get vignettes: flood → debris line
  and a stranded boat; abandoned mine → ruined cart, overgrown rails, bats at dusk. This is cheap and
  LLM-native, and it makes the placement engine carry story. Dwarf Fortress shows the payoff (ruins and
  sites you can visit) and Qud shows you don't need the full simulation.
- **"The world moves without you":** a lightweight tick (per in-game day) can move herds between grass
  tiles, grow crops (seedling to ripe sprite swap), let smoke appear or disappear, and run a
  RimWorld-style population target that lets animals drift in and out. These are client or orchestrator
  state changes that fit the existing event stream (`tracer` events).
- **Missable detail:** follow Smith's rule and put about 1 in 5 tiles **(heuristic)** in charge of
  something small and rare: a fox in a hedge, a lost hat, a single blue flower. Rare, conditioned
  surprises (Terraria's butterfly spawn rules) reward zooming in.

---

## 5. three.js / react-three-fiber implementation notes
- **Kill per-sprite `useFrame` and per-sprite meshes.** Render each *sprite pack* (a texture atlas of 16)
  as one `InstancedMesh` of quads: 1 draw call per pack, or per world if all packs share an atlas array.
  Put per-instance data in `InstancedBufferAttribute`s: `aOffset` (world xyz), `aScale`, `aAtlasRect`
  (uv offset and size, or a layer index into a `DataArrayTexture`), `aPhase`, `aSpeed`, `aMotion`
  (enum), `aTint`, `aFlip`. Chunked InstancedMeshes scale to around a million grass blades
  ([Codrops](https://tympanus.net/codrops/2025/02/04/how-to-make-the-fluffiest-grass-with-three-js/),
  [threejsdemos grass](https://threejsdemos.com/demos/procedural/grass)).
- **Billboard in the vertex shader:** build the quad from the camera right vector (cylindrical: keep world
  up) and apply the current "lean back toward camera" pitch there
  ([three.js forum: billboard for InstancedMesh](https://discourse.threejs.org/t/lookat-billboard-vertex-shader-for-instancedmesh-instances/86227)).
  One uniform (`uCamPos`) replaces N `useFrame` calls.
- **All idle motion in the shader** from `uTime + aPhase`: sway is a shear of top vertices by
  `uv.y² · windField(worldXZ, t)`, bob is a y-offset, breathing is a y-scale about the feet, and flicker
  is a sprite-frame index. Sample wind as a scrolling noise texture plus two sines
  ([al-ro](https://al-ro.github.io/projects/grass/)).
- **Frame animation:** add `aFrameCount` and `aFps` and pick an atlas cell by `floor((t+phase)·fps) % n`.
  Painted packs can include 2–4 frame idles cheaply.
- **Walking actors:** keep them in a separate small InstancedMesh (≤ a few hundred). Update `aOffset`
  on the CPU from a flat `Float32Array` each frame and set `needsUpdate` on just that attribute. No React
  state per actor.
- **Pixel-art correctness:** `NearestFilter`, no mipmaps (or mipmaps with nearest-mip at far zoom), alpha
  test (`discard` when `a < 0.5`) instead of blending, so sorting is not needed and the depth buffer
  handles overlap. Snap instance positions to the world pixel grid in screen space to avoid shimmer.
- **Contact shadows:** a second instanced quad set (flat ellipse, multiply blend) sharing `aOffset`.
- **LOD:** below a zoom threshold, drop L1 scatter (fade by `smoothstep` on camera distance in the shader,
  never pop) and freeze L2 animation. Frustum-cull per chunk (per tile ring), not per instance.
  Particles (smoke, fireflies, rain) are `Points` or instanced quads with GPU-computed positions from
  `uTime`, so no CPU work is needed.
- **Stagger reveals:** keep the existing pop-in, driven by an `aBirth` attribute (`scale = ease(t − aBirth)`),
  staggered by cluster. Townscaper's delayed detail fill makes generation itself feel alive.
- **Determinism:** seed all per-instance randomness (phase, flip, tint) from `hash(tileId, spriteIndex)` so
  reloads look identical and the backend and frontend agree.

---

## 6. Suggested priority for HexWorld
1. **Instanced billboard renderer plus shader motion** with per-instance phase and speed and a global wind
   field. This unlocks 10× sprite counts at lower cost.
2. **Placement recipes plus a cluster-process sampler** in `art/layout.py`, with affinity/avoidance fields
   from ground, height, water and path data and neighbour tiles. The LLM picks sprites and recipes; the
   engine places them.
3. **Layer budgets** (L1 micro-scatter 8–20, L2 3–7 clustered, L3 1–4, L4 ≤1) and pack composition across
   scales.
4. **Client-side ambient life:** birds (boids plus perchers), butterflies/fireflies, chimney smoke, water
   shimmer, gated by a day/night clock.
5. **Actors with POIs and tiny schedules** on the hex graph. Later: planner-level "events" feeding
   vignettes and desire paths.
