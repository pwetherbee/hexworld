# Making HexWorld playable: game-design research synthesis

This is the entry point to HexWorld's game-design research. It distils three detailed reports into
the conclusions that shape what we build. Read [`../VISION.md`](../VISION.md) first for the product
idea: a drillable, agent-built world that you can play.

| report | covers |
|---|---|
| [game-theory.md](game-theory.md) | Game theory for designers (dominant strategies, intransitivity, information, mechanism design, runaway leaders), frameworks of fun (MDA, player motivations, self-determination theory, flow, Koster, Meier, Schell), automated game design (Ludii, Yavalath, GAVEL, restricted play, MCTS playtesting, LLM critics), metrics |
| [board-games.md](board-games.md) | Mechanics taxonomy, hex and map games (Catan, Twilight Imperium, Gloomhaven, Spirit Island, Root, Mage Knight, wargames…), design principles (decisions, pacing, downtime, legibility, onboarding, randomness), digital adaptations (Into the Breach, Slay the Spire), ten game templates for generated maps, balancing procedural maps |
| [open-world.md](open-world.md) | Pokémon in depth (region anatomy, gates, encounter tables, type chart, door transitions, the 3D era), Zelda, Elden Ring, Minecraft/Terraria, Outer Wilds, Skyrim, No Man's Sky, Caves of Qud, roguelikes, Civilization; oatmeal, landmarks, fog, LLM NPCs and quests, juice |

Each report cites its sources inline and in a sources section. This synthesis cites the reports.

---

## 1. The big conclusions

The three reports came from different directions and agree on these.

### 1.1 A game is a stream of interesting decisions, and the map must create them
- Sid Meier's "series of interesting decisions" and Sirlin's "many viable options" define the target:
  no dominant option, consequences you can foresee without fully calculating them, and a situation
  that keeps changing.
- A generated map is scenery until its tiles *matter mechanically*. In the great map games a few
  **legible tile properties** carry the rules: Catan's number tokens, wargame terrain effects,
  Terraria's depth. HexWorld's game-specific tile attributes are exactly this lever, and they must
  become first-class rules inputs *and* visible overlays.
- Every tile should present a **trade-off** (rich but dangerous, safe but slow). Regions that are
  uniformly good or bad produce no decisions.

### 1.2 Rules are data an engine interprets, never code an LLM writes
- The strongest single finding across the automated-design literature: free-form LLM rule code is
  unreliable. In Boardwalk (2025), the best model produced only about 56% of games error-free.
  Systems that work (Ludii, Ludi → *Yavalath*, GAVEL, AutoBG) describe games in a **structured
  language of reusable pieces** and validate them.
- This is already HexWorld's architecture: the engine holds interpreters (material DSL, sprite DSL,
  layout DSL), and agents fill typed, bounded, validated specs through `submit_*` tools. Games get the
  same treatment: a **GameSpec** of turn structure, actions, resources, events, visibility, end
  conditions, scoring and balance clauses. It is interpreted by a deterministic rules engine and
  written by a rules agent that gets validation errors back.
- Agents should mostly **instantiate proven templates with parameters and one or two twists** rather
  than invent games from scratch. Small recombinations of known-good parts beat invention: Yavalath is
  "4 in a row wins, 3 in a row loses" on a hex board.

### 1.3 Never ship a game no agent has played
- Balance is measured by **search agents playing the rules**, not by asking an LLM. The playtest
  pipeline runs from cheap to expensive:
  1. static checks;
  2. random playouts;
  3. MCTS self-play;
  4. *restricted play* (Jaffe): an agent forbidden one action tells you if that action dominates or
     is useless;
  5. a skill ladder (stronger agents should reliably win);
  6. LLM persona critics for clarity and theme (advisory only).
- The metrics to compute:
  - seat and first-player advantage;
  - balance, decisiveness and completion;
  - **agency** (real decisions per turn);
  - game-length variance;
  - lead changes (drama);
  - skill ordering (depth);
  - dominant or useless actions;
  - **coverage**: how much of the map matters. For HexWorld this is critical: a beautiful map where
    play happens on five tiles is a failure.
- Failures route back to the rules agent as structured critiques ("seat 1 wins 68%: consider the pie
  rule"), just as review feedback routes to tile and material agents today.
- Caveat: AI play does not predict human fun. Agents measure *skill-sensitive* properties; humans (and
  telemetry from real plays) judge fun.

### 1.4 Procedural maps buy replayability but create balance debt, so emit constraints, not just maps
- Every successful variable-setup board game pairs randomness with **constraints**:
  - Catan: no two 6s or 8s adjacent.
  - Twilight Imperium: tiered "Milty" slices that players draft.
  - Kingdom Builder: fixed-size sectors.
- The planner should output a **balance report** alongside the map: per-start value within reach,
  resource parity, reachability of every objective, no dead zones.
- Where the generator can't be sure, **let players price the imbalance**: auctions for starts, snake
  drafts, the pie rule, or Kingdomino's "better tile now, worse pick order later".
- **Input randomness** (the map, known before you decide) is the good kind for strategy. Keep **output
  randomness** (combat dice) small, bounded and visible, or use decks instead of dice.

### 1.5 Every tile needs a reason to exist (no oatmeal)
- Kate Compton's "10,000 bowls of oatmeal": outputs that are mathematically unique can still feel
  identical. No Man's Sky shipped 18 quintillion planets and was still called repetitive. It was
  rescued by **things to do**, not more planets.
- Pokémon's regions work because every node has a **job** (town = heal/shop/story, route = travel +
  encounters, dungeon = attrition + boss, gate = pacing).
- Anti-oatmeal checklist per tile. Each tile needs at least one of:
  - a **role** (hub, route, dungeon, landmark, gate, resource, vista);
  - a **verb** (something to do there);
  - **evidence** of forces or history;
  - a **pointer** (something visible from it that makes you want to move).

  Rarity is designed: 1–2 extraordinary tiles per region, the rest supporting them.

### 1.6 Generate history first, then scatter its evidence
- Caves of Qud generates a compact mythic history, then places *fragments* of it across the world
  (shrines, engravings, rumours) for the player to assemble. Coherence comes from the player's own
  pattern-making.
- The agent pipeline should start from a **world bible**: factions, a few historical figures with
  "domains", the affinity chart, the creature/relic roster with habitats, the progression spine and
  the key graph. Every later agent works against it and is validated against it. Recent research
  pipelines (Word2World, "World-Gen to Quest-Line", 2026) converge on this staged, schema-validated
  shape, which is HexWorld's shape.

### 1.7 Exploration is the reward: landmarks pull, fog teases, the map is a trophy
- Breath of the Wild: large, medium and small "triangles" hide and reveal, and points of interest
  exert "gravity" that scatters players off the critical path.
- Towers, map fragments and radial Lightroot reveals make *uncovering* the map satisfying.
- Rule of thumb: from anywhere, the player should see at least one unexplored thing worth walking to.
- **Curiosity needs familiarity** (Outer Wilds): first make a place known, then disturb it.
- HexWorld's on-demand generation means **the act of generation can be the act of discovery**, and
  drilling is literally scouting: an information action.

### 1.8 Collections turn the map into a treasure map
- The Pokédex works because species are tied to terrain, place and time. An empty slot is a question
  whose answer is *somewhere on the map*. Stardew's bundles do the same for a cozy game.
- Give each world a **Compendium** (creatures, relics, recipes, people: whatever fits the prompt) with
  habitats and silhouette hints. Use richer verbs than "caught" (seen, observed, rare variant), as in
  Legends: Arceus. A small, legible **affinity chart** (the type chart) ties *what you collect* to
  *where you must go next*.

### 1.9 Gates are keys, and open order needs signposting or scaling
- HMs and badges, Terraria's pickaxe tiers, Scarlet/Violet's mount upgrades and Outer Wilds' pure
  knowledge are all **lock-and-key graphs**. The engine can validate that a generated key graph is
  solvable (Spelunky lays its critical path first, then decorates).
- Prefer **traversal keys** that make the whole map re-read (raft, glider, lantern). Avoid keys that
  tax the core loop (Pokémon's "HM slaves").
- Scarlet/Violet's lesson: if the player can go anywhere, either **scale difficulty** or **show danger
  on the map**. A hidden fixed order is the worst of both.

### 1.10 Predictable, telegraphed opponents feel fair
- Into the Breach shows every enemy attack, Slay the Spire shows each enemy's intent, and Spirit
  Island's invaders advance on a visible explore → build → ravage conveyor. Losses then feel like
  *your* mistake, and the game becomes a solvable puzzle.
- Generated threats should follow **visible rules keyed to terrain** (which the generator already
  assigns), not hidden dice.

### 1.11 Fun is motivated play, so pick the aesthetic first
- MDA: designers reach the player's experience only *indirectly*, through dynamics. The rules agent
  should first infer **target aesthetics** (e.g. Discovery + Fantasy + light Challenge) and **motivation
  weights** (Quantic Foundry's Action-Social / Mastery-Achievement / Immersion-Creativity) from the
  prompt, then choose mechanics whose dynamics produce them.
- Self-determination theory: **autonomy** (real choices, including *where* to engage, which drilling
  provides), **competence** (legible rules, fair skill ladder, clear feedback), **relatedness** (co-op,
  NPCs who react, shared worlds).
- Flow: let players **choose their own difficulty** through in-world choices (dive deeper, venture
  further), rather than silent rubber-banding.
- Ethics: keep variable rewards inside the *content* (what a drilled tile holds), never attached to
  money or streaks.

### 1.12 Slick is feedback, not features
- "Juice it or lose it" and "The Art of Screenshake": tweening, squash and stretch, particles, sound,
  hit-pause and small surprises turn a plain game into a delightful one without changing a rule. Juice
  amplifies a good loop; it can't replace one.
- Acknowledge every decision (Meier): gates open with a thunk, completed quests visibly change the map.
- Transitions (door fades, drill zooms) should be **fast, consistent and exactly reversible**, and
  announce the child space's rules ("Safe haven", "Wild: encounters", "Dark: lantern needed").

---

## 2. What this means for HexWorld's design

### 2.1 Modes, in build order
1. **Adventure** (Pokémon / Zelda / Terraria), first, because it exercises drilling:
   - an avatar travels the map; each tile rolls against its **encounter table**;
   - towns heal and trade, wild tiles drain and reward;
   - a Compendium drives exploration;
   - a spine of 4–8 set pieces plus a key graph provide progression;
   - entering a town, dungeon or building *is* drilling into its tile.
2. **Board** (Catan / Carcassonne / Spirit Island / Slay the Spire), fast and shareable:
   - turn-based and fully legible, where the fun is planning;
   - picked from the template menu (below) and balance-tested before play;
   - "one more turn" comes from staggered timers.
3. **Tactics** (Into the Breach / Gloomhaven), inside drilled sub-boards:
   - small boards with telegraphed enemies;
   - terrain and height as rules: cover, line of sight, high ground, hazards;
   - results write back to the parent tile.
4. **Sandbox / builder** (Minecraft / Stardew): change the world in natural language, with seasonal
   commissions. This is also the authoring tool for the other modes.

### 2.2 Template menu for board and tactics play
From the board-games report (section 6). Each needs only 2–6 typed tile attributes:

| template | loop | tile attributes |
|---|---|---|
| Settle & Produce (Catan) | produce → trade → build, first to N points | resource, yield, buildable |
| Expedition (Mage Knight / Robinson Crusoe) | move, explore the frontier (generates tiles), resolve encounters, reach the objective in T rounds | move_cost, danger, resource, site |
| Skirmish Tactics (Into the Breach / Gloomhaven) | enemies telegraph → you act → enemies resolve | move_cost, blocks_movement/sight, cover, hazard, elevation |
| Hold the Line co-op (Spirit Island) | a terrain-keyed threat advances on a visible conveyor; fear relaxes the win condition | biome, population, defense |
| Area Majority (Root-lite) | place/move units, periodic regional scoring | region, region_value, move_cost |
| Route & Deliver (Ticket to Ride) | claim edge routes, complete secret destinations | edge connectors, build_cost, produces/demands |
| Race (Heat) | simultaneous card play, terrain limits cost deck quality | move_cost, speed_limit/danger |
| Frontier Tile-Laying (Carcassonne / Kingdomino) | draft a generated tile, place with matching edges, score | edge types (already present), value |
| Daily Cartographer (roll-and-write) | same seed and draws for everyone, leaderboard | any |
| Hive-like duel | abstract on the bare hex plane | none |

### 2.3 Drill layers as game structure
| layer | a tile is… | adventure role | board/tactics role |
|---|---|---|---|
| 0 world | a region | overworld travel, choose the next destination; traversal-key gates | strategic map: territory, economy |
| 1 region | a town, forest, dungeon entrance | routes, the main encounter layer | expedition and area control |
| 2 town / dungeon | a district, a cave section | towns: safe hub, NPCs, quests. dungeons: attrition, boss | a town as a worker-placement board; a dungeon as a tactical board |
| 3 building / chamber | a room | dialogue, shops, secrets, the set-piece fight | small tactical board |
| 4+ | a corner, an object | search and inspect (cheap models) | none |

- **Depth is an axis of danger and reward** (Terraria): deeper is denser, stranger and richer.
- **Children mirror parents in game terms too** (Tears of the Kingdom's Shrine above and Lightroot
  below). The seed layout must carry **game attributes** down: a parent's `has_dungeon` guarantees an
  entrance tile in the child, and a `danger: 3` swamp yields more hazards.
- **Drillable tiles are marked** (a door glint, an entrance sprite), so drilling is a choice with an
  expected payoff rather than a lottery.
- **One layer is hot at a time.** The parent pauses, or advances one round per child encounter.

### 2.4 The agent pipeline for playable worlds
1. **Planner (super)**: infers target aesthetics and motivations from the prompt, then writes the
   **world bible**: factions, history with domains, the affinity chart, the Compendium roster with
   habitats, the spine and the key graph.
2. **Layout + tiles** (as today), with tiles also carrying **roles**, **encounter tables** drawn from
   the roster, and **lore fragments** from the bible.
3. **Rules agent**: fills a **GameSpec** from a template plus parameters plus 1–2 twists, with safeguards
   on by default:
   - pie rule or bidding for symmetric duels;
   - a catch-up lever for 3+ players;
   - turn limits;
   - no elimination in long games.
4. **Validators** (deterministic):
   - the key graph is solvable;
   - every Compendium entry is obtainable in a reachable tile;
   - a balance report for starts and resources;
   - no dead zones.
5. **Playtest agents**: the staged pipeline and metrics above. Critiques route back to the rules
   agent, and only verified improvements are accepted.
6. **At play time:**
   - a **director / game master** spawns encounters and quests. Quest templates come from a grammar
     skeleton (fetch, escort, hunt, deliver, investigate, restore), bound to real map facts, with the
     *why* taken from the bible, pointing into the fog, and ending with a visible map change.
   - **NPCs** with small structured state (`who, wants, knows, opinion, schedule`) that the LLM renders
     into short, reactive dialogue. Full generative-agents memory is reserved for a few key characters.

### 2.5 The feel spec (juice)
The UI is driven by the event stream, so every play event gets an animation spec, in the same
language as the build animations:
- **Hop:** an ease-out arc, squash on landing, dust, a footstep sound per material.
- **Encounter:** a swirl or flash, a hit-pause, the creature popping in with overshoot.
- **Discovery:** fog peeling back radially, a chime, an icon stamping onto the map, a Compendium
  counter ticking up.
- **Drill:** a continuous dive, with the parent cross-fading into the child grid in well under half a
  second (our target) and a banner announcing the child's rules. The exact reverse on exit.
- **Legibility overlays** one keypress away: movement cost and reachable range, zone of control and
  threat next turn, yields, danger ratings. Rules information never lives only in the pixel art.
- **Onboarding** (Jaws of the Lion): a one-sentence goal, a three-verb turn, and an opening scenario
  where only one mechanic is live.

### 2.6 Defaults and guardrails
- Sessions of 10–30 minutes, with the world persisting between sessions. HexWorld is naturally
  *legacy*: razed towns stay razed and cleared dungeons stay cleared.
- At most 3 actions per turn and 1 rule-break per faction; every rule maps to a visible UI element.
- Generate the *distribution* of what lies in the fog before revealing it, and guarantee each
  frontier offers something useful within N steps, so an unlucky reveal can't decide the game.
- Pre-generate just beyond the fog edge, and the child map under the cursor, so on-demand generation
  never makes the player wait during play.
- Keep dialogue short; prefer one sharp line plus a consequence on the map.

---

## 3. Suggested first playable milestone

**Adventure mode, v0**, on the next drillable build:
1. A world bible (roster of ~20 entries with habitats, an affinity chart, a 4-gym spine, a 3-key
   graph), validated for solvability and obtainability.
2. Tile roles and encounter tables filled in by tile agents from the bible. Fog of war over the
   `visibility` field.
3. An avatar with hop movement, encounters resolved by a tiny deterministic battle using the affinity
   chart, and a Compendium with silhouettes and habitat hints.
4. Drilling as entering places (towns safe, dungeons wild), with banners, and results written back.
5. A playtest bot that walks the spine to check it can be completed and reports pacing.

Then the Board templates (Expedition and Hold the Line first: they suit single player and reuse the
fog and threat machinery), then Tactics inside drilled dungeons.
