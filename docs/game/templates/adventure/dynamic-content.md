# Adventure: dynamic content (the director)

The game keeps generating while you play, in two ways: **ahead of you** (so you never wait) and **in
answer to you** (so the world reacts). The director is the agent that decides what, where and when;
skills generate; the engine applies.

---

## 1. The director's loop

```
every event → update the player model → check triggers → commission content (async)
every in-game hour → pacing check → maybe a world event
every region entered → frontier plan for that region
```

- The director is an ADK agent with a small tool set: `commission(slot, context)`, `schedule_event`,
  `note(fact)`. It never changes game state directly: commissioned content arrives in the registry and
  is **offered** to the engine at designed insertion points (a tile's next spawn roll, a shop's next
  restock, an NPC's next line, a quest board).
- Much of its work is deterministic policy (code); the LLM part is choosing *which* reaction fits the
  story when several do, and writing the specifics.

## 2. Ahead of the player (frontier)

| content | generated when | radius |
|---|---|---|
| encounter tables + creature art for a region | the player is 1 region away | region |
| NPC seeds, shop stock, side-quest hooks for a tile | the player is within 2–3 hops | 3 hops |
| dialogue openers for NPCs on a tile | within 1 hop | 1 hop |
| battle background for a tile | within 2 hops | 2 hops |
| warden details and arena | region entered | region |

- Priorities follow the player's likely direction (the last few moves and the active quest's target).
- Latency is measured by the playtest bot; the target is zero visible waits at normal walking pace.

## 3. In answer to the player (reactions)

Designed trigger → reaction pairs, with generated specifics. The first set:

| trigger | reaction |
|---|---|
| over-hunting a species on a tile (N defeats in a day) | its population drops; its predator species migrates in (from the roster's food web); an NPC comments |
| bonding with a rare creature | a collector NPC appears with an offer; a rumour of its evolved form |
| helping a faction twice | a follow-up quest from its leader; shop discounts in its towns |
| angering a faction | its trainers challenge you; prices rise; a shortcut closes |
| losing to a warden twice | a mentor NPC appears near the arena with a hint about the mechanic |
| exploring every tile of a region | the region's landmark reveals a secret (a rare spawn, a lore item) |
| a long time without progress | a rumour points to the nearest unexplored interesting thing |
| finishing a quest that changes a place | the place's material or sprites change (a mended pier, a lit lighthouse) |
| a new in-game day | shops rotate specials; wanderers move; weather changes |

- Every reaction is small, visible and **explained in the world** (an NPC line, a sign, a rumour), so
  the player can connect cause and effect.

## 4. World events (slow clock)

- Designed event types: storm, migration, festival, blight, rival's move, faction clash, eclipse
  (rare creatures), market day.
- The director chooses at most one per in-game day, by a tension curve (RimWorld's storyteller idea):
  after a hard warden, a festival; after a quiet stretch, a storm.
- Each event has specifics generated from the canon (which festival, why, who's there) and designed
  effects (spawns, prices, closed tiles, a temporary quest).

## 5. The creature ecology (what makes spawns dynamic)

- Each species has a **habitat** (terrains), a **population** per tile (capacity from terrain and
  role), a **diet/predator link** (a small food web generated with the roster), and **activity** (day,
  night, dawn/dusk, weather).
- Populations regrow toward capacity each in-game day; predators move toward prey-rich tiles.
- New **variants** appear over time: a rare colour or a regional form (generated as a sprite tint or a
  small art variant plus a designed stat tweak), announced by rumours. This keeps the Compendium alive
  late in the game.

## 6. Budget and fallbacks

- A play-time budget per hour (tokens and images). The director spends it where the player is and on
  reactions first; frontier prefetch uses what's left.
- When the budget is low: reuse registered content, grammar fallbacks for lines, no new art (existing
  sprites with tints). The game never stops working.

## 7. Guardrails

- The director cannot: grant items, change numbers, remove the player's creatures, or block the spine.
- Every commissioned piece passes the same skills and validators as creation-time content.
- The spine (wardens, keys, the confrontation) is fixed at creation; the director only decorates and
  reacts around it, so the game always remains finishable (the playtest bot re-checks after large
  world changes).
