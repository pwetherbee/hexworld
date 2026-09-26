# Template: Adventure

The first HexWorld game. A creature-bonding, turn-based adventure in the tradition of Pokémon, played
on a generated world: explore it, meet the creatures that live in its terrains, bond with them,
battle, help and cross its people, and confront the wardens at the heart of its conflict.

Status: **draft spec for review**.

| document | covers |
|---|---|
| this page | fantasy, core loop, options, spine, length, what's generated when |
| [exploration.md](exploration.md) | the overworld: movement, places, roles, fog, encounters on the map, gates and keys, time |
| [combat.md](combat.md) | the battle rules: stats, affinities, moves, damage, status, turn order, enemy AI, bonding, growth |
| [creatures.md](creatures.md) | how creatures and their moves are generated, compiled to numbers and drawn |
| [people-items-quests.md](people-items-quests.md) | NPCs, dialogue, shops, items, economy, quests, wardens |
| [battle-backgrounds.md](battle-backgrounds.md) | the layered, animated pixel-art battle scenes generated per place |
| [dynamic-content.md](dynamic-content.md) | the director: what is generated ahead of the player and in reaction to them |
| [data-model.md](data-model.md) | schemas: canon, content, game state, events |
| [balance-and-testing.md](balance-and-testing.md) | the balance simulator, the playtest bot, metrics and the definition of done |

---

## 1. The fantasy

> You arrive in a place that has its own creatures, people and trouble. You learn its terrains by
> the creatures that live in them, earn the trust of a few, and grow strong enough to face what is
> wrong here.

What makes it *HexWorld's* adventure rather than a reskin:
- **The creatures are this world's.** Their kinds come from its terrains (a glass-tower district
  breeds different things than a salt marsh), their names from its languages, their habits from its
  history. The affinity system (types) is derived from the world's own materials.
- **The conflict is this world's.** Wardens, rivals and the final confrontation come from the world
  bible's factions and history, which come from the prompt the world was built from.
- **The world answers back.** What you hunt, help, beat and befriend changes what appears next
  (dynamic-content.md).

## 2. Core loop

```
            ┌────────────── explore (hop tile to tile, fog lifts) ◄────────────┐
            ▼                                                                   │
  meet (roaming creatures, people, places) ──► battle ──► bond / grow ──────────┤
            │                                                                   │
            └──► towns: heal · trade · quests · rumours ──► gates: wardens, keys ┘
```

- **Minute to minute:** choose where to go next (visible creatures, landmarks and rumours pull you),
  fight or avoid encounters, manage the party's health and items.
- **Hour to hour:** fill the Compendium, raise a team that covers the affinities you'll face, beat
  wardens, unlock new terrain with their keys, follow the world's story.

## 3. Options (setup panel)

| option | values (default in bold) | affects |
|---|---|---|
| Length | Short (≈1h, 2 wardens) · **Standard (≈3h, 4 wardens)** · Long (≈8h, 7 wardens) | spine size, roster size (18 · **30** · 48), final level (30 · **45** · 50) |
| Difficulty | Relaxed · **Balanced** · Hard · Hardcore | enemy levels vs player, AI depth, item prices, healing availability; Hardcore = fainted creatures leave the party (Nuzlocke-like) |
| Creatures | **Let the world decide** · Native wildlife · Spirits · Machines · Custom text | the creature concept in the bible (what they are, why they bond, what a battle means) |
| Tone | **Match the world** · Cozy · Adventurous · Eerie · Comic | the voice guide |
| Party size | any (**variable**; default 4) | active party cap; the engine handles any size (and sides of any size, for later doubles or raids) |
| Encounters | **Visible only** · Visible + hidden | whether wild tiles also have unseen rustle encounters |
| Notes | free text | a strong hint to the bible writer ("the lighthouse keeper is hiding something") |

> **Decision (owner):** party size is variable. The engine treats a party (and a battle side) as a list
> of any length; the option only sets the default cap.

## 4. The spine

Every Adventure has a designed structure, instantiated per world:

1. **Arrival** at a start town (chosen by the designer: a town tile near the map's centre of mass,
   or the world's origin tile). A guide NPC, a choice of **three starters** (covering an affinity
   triangle), the first quest.
2. **Regions**, one per warden, derived from the world's layout regions/biomes and ordered into a
   difficulty gradient radiating from the start. Each region has: a hub town (or camp), 3–8 wild
   places, a landmark, a warden's seat.
3. **Wardens** (the gym leaders / bosses): each tied to a faction or force in the bible and a
   dominant affinity of their region. Beating one grants a **mark** (badge) and a **traversal key**
   that opens more of the map (exploration.md, gates).
4. **The confrontation**: the conflict's source, reached once all marks are held; a multi-phase
   boss (combat.md) and a short epilogue written from what the player actually did.
5. **After, and beyond**: the game loop is **open-ended**. The spine gives the first arc; after it, the
   director keeps extending the game for as long as the player wants: new regions by drilling and by
   growing the world, new wardens and arcs from the evolving canon, rare hunts, rematches, quests.
   Length options size the *first arc*, not the game.

The spine is a **key graph** (which key opens which region) that the engine validates for
solvability and pacing before play (balance-and-testing.md).

## 5. What is generated when

| content | at game creation | during play |
|---|---|---|
| bible: voice, naming, factions, history, conflict, creature concept | ✔ | extended (new rumours, events) |
| affinities + chart | ✔ (validated) | fixed |
| roster (all species with habitats, roles, silhouettes) | ✔ (names, roles, habitats); art for the start region | art and full move sets per region as the frontier approaches |
| wardens + final boss (concepts, teams, mechanics) | ✔ (validated) | details refined when their region is reached |
| start region: NPCs, shops, quests, backgrounds | ✔ | reacts |
| other regions' NPCs, shops, quests, backgrounds | skeleton only | ✔ at the frontier |
| dialogue lines | a few openers | ✔ on demand (cheap model, cached) |
| world events, reactive quests, migrations | no | ✔ (director) |

## 6. Scale reference (Standard)

| thing | count |
|---|---|
| playable tiles (one layer) | 60–150 (a world of max tiles ≥ 60; larger worlds recommended, drilling later) |
| regions / wardens | 4 + the confrontation |
| species | 30 (≈ 10 lines of 1–3 stages) |
| moves | ≈ 70 (generated from ~30 designed archetypes) |
| affinities | 6–8 |
| named NPCs | 25–40 (4–8 per region) |
| items | ≈ 25 (from the designed effect catalog) |
| quests | 8–12 designed at creation, more generated during play |
| battles to finish | ≈ 60–90 |

> **Decision (owner):** worlds are variable in size, and play happens across layers: the world is the
> **overworld**; every overworld tile opens into its own region grid (a hex of radius 5–6); every
> region tile opens into a painted scene. Content scales with what exists and grows as the player goes.
