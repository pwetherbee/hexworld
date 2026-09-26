# HexWorld: vision

> Click an empty hex, describe a world, and a team of agents builds it. Zoom into any tile and it
> opens into a finer world of its own. Then **play it**.

This document is the north star for where HexWorld is going: an infinitely drillable, agent-built
world that is also a **game**: slick, legible, and genuinely fun. It covers the idea, the design
pillars, the architecture it implies, and the roadmap. The research behind the game-design choices
lives in [`research/game-design-research.md`](research/game-design-research.md).

---

## 1. The idea

HexWorld already turns one sentence into a living map:
- a **super agent** plans the world: its lore, its style, the shape of the map and the game-specific
  attributes of each tile;
- **tile agents** design each hex against their neighbours;
- **artist agents** create every material and sprite on demand;
- the super **reviews** everything and routes feedback to the agent that owns each problem.

The next step comes from one image: the Mandelbrot set, *an intricate, infinitely zoomable universe
born from simple rules*. (See Patrick Wetherbee, "How Language Models Will Revolutionize Virtual
Worlds".) The idea in that post:

- A **master agent** sets the broad strokes: kingdoms, boundaries, the story.
- It spawns **sub-agents** for regions. Those spawn agents for cities, rivers and forests, and those
  spawn agents for buildings and rooms. The cascade goes as deep as resources permit.
- Everything stays consistent from the top down, because every child works from its parent's context.
- **Children validate against their parents.** **Siblings coordinate horizontally**: a bustling
  market and a ghost town can't share the same street.
- Content is **generated on demand, chunk by chunk**, as the player approaches. Budgets cap how
  deep the recursion goes, and cheaper models handle the finer levels.
- *From the largest city to the smallest room, an intelligent agent has thought: what belongs here?*

That is the difference from classic procedural generation (Starfield's beautiful, empty planets).
**Variation comes from the diversity of the world that was conceived, not from a random number
generator.**

HexWorld is built to be that system, and hexes make it concrete: **a hex is made of hexes.**

---

## 2. Pillars

1. **Infinite depth.** Any tile can be drilled into, revealing a finer map at a smaller scale:
   world → region → town → street → building → room. Nothing exists until someone looks, and
   everything that exists fits its parent.
2. **Every tile has a reason to exist.** No oatmeal: no field of statistically varied but
   meaningless tiles. Each tile is designed by an agent that knows the lore, the neighbours and the
   parent, and each carries attributes the game actually uses.
3. **Playable.** A world is also a game. The super designs rules that fit the prompt, the map
   carries the game state, and drilling in is how you enter places.
4. **Agents all the way down.** Agents plan, build, review, direct, playtest and run the game.
   Deterministic engines handle what must be exact: geometry, rules adjudication, rendering. Agents
   handle what needs judgement and imagination.
5. **Slick.** Every state change is animated, legible and satisfying: the "juice" of great games,
   applied to a world being built and played live.

---

## 3. The drillable world

### 3.1 A hex made of hexes
Each deeper layer is **one continuous, finer hex grid**, scaled down by a factor *N* (about 6), so
each parent covers about N² ≈ 36 child tiles.
- Every fine hex belongs to exactly one parent hex, the one containing its centre. The layer is an
  exact partition of the parent layer.
- Drill into two neighbouring tiles and their child maps sit **side by side on the same grid**.
  They join through the ordinary edge-contract machinery. Sibling coordination comes free.
- Layers chain as deep as budget allows, and scale meaning shifts with depth:

```
layer 0  world      a tile is a region      "Harbour Town" (sprite: a town)
  └ layer 1  town   a tile is a district    market row, docks, the keep
      └ layer 2     a tile is a lot         stalls, a tavern, a fountain
          └ layer 3 a tile is a room corner tables, a hearth, a trapdoor…
```

### 3.2 Consistent with the parent, by construction
Before the child planner runs, the engine derives a **seed layout** from the parent tile. The child
planner (a "region agent") adds detail on top of it:
- **Ground → map.** The parent's centre biome fills the interior. Each parent edge terrain becomes a
  band along the matching side of the child map.
- **Connectors → routes.** A river entering the parent from the west and leaving north-east becomes
  a route across the child map. It crosses the rim at fine tiles chosen **deterministically from the
  parent edge's midpoint**, so the neighbouring parent's child map meets it at exactly the same place,
  whichever is drilled first.
- **Virtual contracts.** Rim tiles next to an undrilled neighbour get edge contracts derived from
  the parent edge. Real child tiles replace them once that neighbour is drilled.
- **Sprites → landmarks.** A castle standing on the parent tile becomes a castle-compound landmark
  at the corresponding place in the child map. Drill in again and you get its courtyards and halls.
- **Heights → heights.** The child layer starts from the parent's heightmap sampled at each fine
  position, so a mountain tile's children sit high on the mountain.
- **Context flows down.** The child planner gets the ancestor chain (world lore → region → this
  tile, compressed) and the summaries of already-drilled siblings.
- **Validation flows up.** The reviewer checks *parent fit*: does this map read as that tile, up close?

### 3.3 Data model
- Each layer is its own **World** record linked to its parent: `parent_world_id`, `depth`, `scale`.
- Parent tiles gain `child_world_id` and a drilled state.
- This reuses runs, the store, the event stream, per-layer libraries and the UI as they are.
- Style and palette are inherited. Materials are per layer, because grass at room scale is not
  grass at world scale. Ancestors' sprite kinds are offered for reuse.

### 3.4 On demand and bounded
- Nothing is generated until someone drills. A drill is one normal run (about 36 tiles, roughly
  1.5–2 minutes, about $0.10).
- A depth limit (default 4) and a per-world token/cost pool bound the recursion.
- Deeper layers can use cheaper models or lower reasoning effort (configurable per depth).

### 3.5 The drill experience
- Double-click (or Enter on) a tile: the camera dives into it, the hex fills the view and
  **dissolves into its child hexes**.
- If the layer doesn't exist yet, the seed beacon lights the footprint and the drill run starts. An
  optional note shapes it ("make it a smuggler's port").
- **Level of detail:** in a child layer, drilled areas are fine tiles, and the undrilled
  surroundings show their parent tiles enlarged as flat context.
- Breadcrumbs (World › Harbour Town › Market Row). Esc or zooming out climbs back up with the
  reverse transition.

---

## 4. Richer terrain: continuous heightmaps

Today each tile's relief is a local bump of 0–6 levels. The goal is terrain that reads as
**geography**:
- **Elevation per region.** Layout regions get an elevation and a relief style (flat, rolling,
  hilly, mountainous, cliffs, terraced, canyon, basin). The engine blends them into **one smooth
  elevation field** over the whole layer, so mountain ranges rise across many tiles, valleys sink
  and plateaus end in cliffs. Materials add local detail on top.
- **More levels:** about 0–40 instead of 0–6, stored at higher resolution, with the camera tuned for
  tall terrain.
- **Water tables:** liquids settle at their region's water level (mountain lakes, sea level), and
  flooded ground darkens with depth.
- **New relief ops:** slopes and ramps (stepped hillsides), canyons, mesas.
- **Inherited across layers:** a child layer's elevation starts from its parent's.

Height is also **gameplay**: line of sight, movement cost, high ground, flooding, a climb as a
progression gate.

---

## 5. Playable worlds

The world is the board. The prompt that describes the world can also describe the game. When it
doesn't, the super proposes one.

### 5.1 Game modes the super can choose from
Each mode is a *template*: a small rules skeleton that an agent instantiates for this world's lore,
map and attributes. The research doc details the families. The first ones:

| mode | the player… | inspired by |
|---|---|---|
| **Adventure** | walks an avatar through the world, discovers places, drills into towns and dungeons, meets NPCs, takes quests, collects creatures or artefacts, clears progression gates | Pokémon, Zelda, Terraria |
| **Board game** | takes turns with other players or AI opponents on the map: produce, trade, build, race, control areas | Catan, Carcassonne, Kingdomino, Root |
| **Tactics** | fights turn-based battles on a drilled-in sub-map, where terrain and height matter | Into the Breach, Gloomhaven, Fire Emblem |
| **Builder** | grows a settlement or civilisation across tiles, with an economy and events | Civilization, Settlers, Stardew |
| **Puzzle / race** | solves or races through a generated course | Heat, roguelike maps |

### 5.2 What makes a generated game good
- **Interesting decisions** (Sid Meier). Every turn offers several viable options with trade-offs,
  and no dominant strategy.
- **Legible state.** You can see what matters: movement costs, ownership, danger, fog of war.
  HexWorld's tile attributes become visible, first-class game state.
- **Pacing and tension.** Rising stakes, catch-up mechanics, no runaway leader, a satisfying end.
- **Exploration as reward.** The map *is* the reward: fog of war, landmarks visible from afar,
  "what's over there?", and a drill-in that reveals something surprising yet fitting.
- **Meaning over randomness.** Encounters, quests and loot come from the lore of the place, not
  from dice tables alone.

### 5.3 Agents at play time
- **World bible** (the super, first): factions, a compact history whose evidence is scattered across
  tiles, an affinity chart, a Compendium roster with habitats, a progression spine and a key graph.
  Everything downstream is validated against it.
- **Game designer** (the super, at plan time): infers the target aesthetics from the prompt, picks a
  template and writes the rules as **data** (a game spec: turn structure, actions, resources, win
  conditions, the tile attributes each rule reads). It never writes free-form code.
- **Rules engine** (deterministic): validates and resolves every action. LLMs never adjudicate
  rules, so the game stays fair, replayable and cheap.
- **Playtester agents**: simulated players (search- or LLM-driven) play the generated rules before a
  human does. They measure balance: first-player advantage, dominant strategies, game length, lead
  changes, decision density. The designer revises until the metrics are healthy.
- **Game master / director** (at play time): reacts to the player, spawns encounters and quests
  consistent with the lore, adjusts pacing, and generates content on demand (drilling).
- **NPC agents**: characters with memory and goals that live in the world, talk with the player and
  trade. They are grounded in their tile's and parent's context (in the spirit of the "generative
  agents" research).

### 5.4 The architecture this implies
- **Game spec** (pydantic) alongside the world spec, versioned and validated like everything else.
- **Game state**, event-sourced like the build, so replays, undo and spectating come free.
- **Visibility** per tile and player (the `visibility` field reserved from day one), used for fog of
  war.
- A **play UI layer** on the same board: avatar and pieces, turn HUD, action affordances, animated
  resolutions, with the same animation language as the build.
- **Save / share**: a world plus its game is a shareable artefact. Anyone can open it and play.

---

## 6. Roadmap

1. **Terrain:** continuous elevation fields, region relief styles, more levels, water tables and
   new relief ops. Improves every map now.
2. **Layers:** geometry and data model, drill runs (seed layout, ancestor and sibling context,
   parent-fit review), and the drill UI (dive transition, level of detail, breadcrumbs).
3. **Adventure v0:**
   - a world bible, validated for a solvable key graph and every Compendium entry being obtainable;
   - tile roles and encounter tables, and fog of war;
   - an avatar with hop movement, and tiny deterministic encounters using the affinity chart;
   - drilling as entering places, with results written back to the parent tile;
   - a bot that walks the spine to check it can be completed.

   (See the research doc's "first playable milestone".)
4. **Game spec + rules engine + playtesting agents** (staged: random playouts, MCTS self-play,
   restricted play, skill ladder, LLM critics), then the **Board** templates (Expedition and Hold the
   Line first) and **Tactics** inside drilled dungeons.
5. **Live agents:** game master and NPCs, quests and encounters generated from the lore.
6. **Polish and sharing:** onboarding, juice, sound, save and share, spectating.

## 7. Open questions
- How much of the rules the user describes versus the super proposes: a free-text game prompt, or
  a template picker plus tweaks?
- Single-player first, or local hot-seat / online multiplayer early?
- Where the budget goes at play time: should drilling during play be instant (pre-drill around the
  player) or a visible "the world is being made" moment (a feature, not a wait)?
- How persistent is the world: do NPCs and the game master keep changing it after the build
  (the post's "autonomous agents operating in real time")?
