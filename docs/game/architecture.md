# Architecture: games on generated worlds

How a game attaches to a HexWorld world, who owns what, and how content flows at creation time and
during play. Template-specific rules live in `templates/`; this page is the shared machinery every
template uses.

---

## 1. The layers

```
┌──────────────────────────────── play UI (frontend) ────────────────────────────────┐
│ game button · setup panel · play HUD · battle/dialog/shop screens · saves          │
└──────────────▲───────────────────────────────────────────────▲─────────────────────┘
               │ commands (player intents)                     │ events (state changes)
┌──────────────┴──────────────── game service (backend) ───────┴─────────────────────┐
│  template plugin ──►  rules engine (pure reducer: state, command → events)          │
│                       validators · balance sim · playtest bot                       │
│  content registry  ◄── content pipeline (skills: generate → validate → critique)    │
│  canon (world bible)       ▲                                                        │
│  director (play-time agent) ┘  decides what to generate, when, and why              │
└──────────────▲──────────────────────────────────────────────────────────────────────┘
               │ reads (tiles, materials, sprites, heights) · commissions (sprites, drills)
┌──────────────┴──────────────── world (today's system) ─────────────────────────────┐
│ worlds · tiles · materials · sprites · layers/drilling · runs · event stream       │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

- The **world** stays what it is: the build system. Games read it and can commission more of it
  (a sprite pack, a drill into a building), but never rewrite it behind its back.
- The **game service** is new. It owns games, saves, the canon, the content registry and the
  play-time agents.
- The **play UI** is a new mode of the same frontend, driven by game events exactly as build mode is
  driven by build events.

---

## 2. Core objects

| object | owner | lifetime | contents |
|---|---|---|---|
| `Game` | game service | one per world per template instance | template id and version, options chosen by the user, status (drafting → generating → ready → archived) |
| `Canon` | game service | per game, grows during play | the world bible: voice guide, naming language, factions, places, history, conflicts, roster; every fact has an id and provenance |
| `ContentRegistry` | game service | per game, append-only | every generated piece (creature, move, NPC, item, quest, dialogue, background), content-addressed, with its generation record |
| `Save` | game service | many per game | event log + snapshot; points into the registry (never copies content) |
| `Template` | code | versioned | rules engine, content schemas, skills, validators, UI screens, playtest bot |

> **Decision:** a `Game` belongs to one world (or one layer of a drillable world). A world can host
> several games (an Adventure and later a Settlers match); each has its own canon, derived from the
> world's but extendable.

### 2.1 State is event-sourced

- The rules engine is a **pure reducer**: `step(state, command, rng) → (state', events[])`. The rng
  is seeded per save, so a save is exactly reproducible from its seed and command log.
- Events drive the UI (animations, sounds) and the director (reactions), and are the save format.
- Snapshots every N events make loading fast; the log makes replays, bug reports and spectating free.
- Content referenced by events is resolved from the registry by id; a save never regenerates
  anything.

### 2.2 Templates are plugins

A template provides, in code:

| part | description |
|---|---|
| `options` schema | what the user can set in the setup panel (difficulty, length, party size, tone…) |
| `canon` extensions | what this template needs in the bible (Adventure: roster, affinities, wardens; Settlers: resources) |
| `content` schemas | typed slots the agents fill (CreatureSpec, NPCSpec, ItemSpec…) with bounds |
| skills | generators for those schemas (see content-and-anti-slop.md) |
| rules engine | the reducer, with unit tests |
| compilers | turn generated content into engine data (roles/tiers → numbers) |
| validators | structural (schema), canon (grounding), game (solvable, obtainable, balanced) |
| director policy | which content to generate ahead of the player, and which reactions exist |
| UI kit | screens and HUD components, animations, sounds |
| playtest bot | plays a generated game end-to-end, reports metrics |

> **Decision:** templates are written by us, not by agents. Agents fill them. (The long-term idea of
> a rules DSL from the VISION doc remains the path for *board* templates; Adventure is too rich for a
> generic DSL and is better as a dedicated engine.)

---

## 3. Two clocks of generation

### 3.1 Game creation (before play, ~1–3 minutes, shown as a pipeline)

```
world (built) ──► canon: voice guide, naming, factions, history, conflicts
              ──► template canon: e.g. affinities + chart, roster, wardens, spine, key graph
              ──► validators: solvable, obtainable, balanced (retry loops per failing piece)
              ──► starting content: starter region fully (creatures, NPCs, shops, first quests)
              ──► art: sprite packs for the roster and NPCs, battle backgrounds for the start area
              ──► playtest bot: walks the spine in simulation, reports; blocking issues loop back
              ──► ready
```

- Only the **spine** and the **start** are generated fully. Everything else is generated at the
  frontier during play (3.2), so creation is fast and the world stays fresh.
- The user watches it happen (like the world build): "Writing the bible… 24 creatures… 4 wardens…
  test run: spine completable in ~3h".

### 3.2 During play (continuous, invisible)

- **Frontier generation.** When the player can reach a place within *k* moves (k≈2–3 tiles, or
  "adjacent region" for coarse content), the director commissions its content: encounters, NPC
  details, shop stock, a quest hook. It is ready before the player arrives. Nothing is generated
  for places the player never approaches.
- **Reactive generation.** Some events trigger new content: the player helped a faction (a new
  quest line), over-hunted a species (its predator migrates in), lost repeatedly to a warden (a
  mentor NPC appears with a hint), found a lore fragment (a rumour pointing into the fog).
- **Background world events.** On a slow clock (per in-game day), the director may run one
  world event (a storm, a migration, a festival, a rival's move), each defined as a template event
  type with generated specifics.
- **Budgets.** Each game has a play-time token/cost budget per hour; the director spends it where
  the player is. If the budget runs dry, fallbacks keep the game playable.

> **Decision:** the frontier radius and prefetch depth are template-owned and tuned by the playtest
> bot's latency measurements, with a target of **zero visible waits** at walking speed.

### 3.3 Fallbacks (never block, never break)

Every content slot has a chain: `generated (specific) → generated earlier for a similar slot (reuse)
→ template stock (generic but correct)`. A slow model means a slightly less specific piece of
content, never a spinner. Fallback use is logged and counted as a quality metric.

---

## 4. The play-time agents

| agent | when | does | never does |
|---|---|---|---|
| **Game designer** | creation | chooses options within the template, writes template canon (roster, wardens, spine) | writes rules or numbers |
| **Bible writer** | creation | voice guide, naming language, factions, history, conflicts | contradicts the world |
| **Content skills** | creation and play | fill one typed slot each (creature, NPC, item, quest, line of dialogue…) | publish without validation |
| **Critic** | on every content piece | scores against the rubric (specific? grounded? in voice? has a job?), sends back fixes | rewrite content itself |
| **Director** | play | watches events, decides what to commission, pacing, world events | touch game state directly (it issues content, the engine decides) |
| **NPC voice** | play, on dialogue | renders an NPC's structured state into 1–3 lines | invent facts outside canon, promise rewards the engine didn't grant |
| **Playtest bot** | creation, CI | plays the game | (it's code, not an LLM, except an optional LLM critic persona) |

- All of them are ADK agents in the existing kit, with `submit_*` tools that validate and return
  errors, exactly like the build agents today.
- Cheaper models for high-volume, low-stakes skills (dialogue lines, item flavour); the strongest
  model for the bible, the roster and bosses.

---

## 5. The world, from the game's point of view

What a game reads from the world, and what it may ask of it:

| world data | used for |
|---|---|
| tile biome, edge terrains, connectors | where things live and move; affinities; movement costs; routes |
| tile attributes (template-defined at world planning) | encounter tables, danger, role (town, route, dungeon…) |
| materials (colours, height, buildings) | battle backgrounds, habitat descriptions, ambience |
| sprites and cast | NPC and creature art reuse; placement of encounters on the map |
| heightmap | line of sight, climbing gates, vistas, battle background silhouettes |
| layers (drilling) | entering towns, dungeons and buildings |

What a game may commission: sprite packs (creatures, NPCs, items), a drill into a tile (a town
interior, a dungeon), a material variant (a scorched field after a battle). All through the existing
library machinery, with the same single-flight and budget rules.

> **Decision (owner):** games change the world permanently: tiles (a burned forest, a rebuilt bridge),
> sprites, connectors, and more (new tiles, new layers). Changes are engine "world edits" recorded as
> events, so the original build stays reproducible and every change has a cause in the game.

---

## 6. Where things live in the codebase (proposal)

```
backend/hexworld/game/
  __init__.py            Game, Save, events, the service API
  canon.py               the bible model + grounding queries
  registry.py            content registry (content-addressed, provenance)
  director.py            the play-time director agent
  skills/                reusable content skills (naming, voice, critic, dedupe, …)
  templates/
    adventure/           rules.py (reducer), content.py (schemas), compile.py, skills/, bot.py, tests/
frontend/src/game/
  GameButton.tsx, SetupPanel.tsx, PlayMode.tsx
  adventure/ (Overworld, Battle, Dialog, Shop, Party, Compendium)
```

API sketch: `POST /api/worlds/{id}/games` (create with options), `GET /api/games/{id}` (spec,
canon summary, status), `POST /api/games/{id}/saves`, `POST /api/saves/{id}/commands` (player
intent → events), `WS /api/saves/{id}/stream`.

---

## 7. Risks and how the design answers them

| risk | answer |
|---|---|
| Generated content is generic | grounding rule (2 world specifics), naming languages, critic, dedupe, eval set (content-and-anti-slop.md) |
| Mechanics feel shallow or broken | templates are hand-designed with tests and a balance sim; LLMs never set numbers |
| Waiting on the model during play | frontier prefetch, fallbacks, budgets; latency measured by the bot |
| Incoherence over a long game | canon is the single source of truth; every piece is checked against it; facts have ids |
| Cost | cheap models for volume, strong models for spine; content reuse; per-hour budgets |
| Scope creep across templates | one template done fully (Adventure) before the next starts |
