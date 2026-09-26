# Template: Sandbox (colony and city management)

Status: **later** (after Adventure). This spec fixes the shape so Adventure's architecture leaves
room for it; details will be expanded before we build it.

Inspirations: Dwarf Fortress and RimWorld (a colony of individuals with needs and stories),
SimCity and Cities: Skylines (zoning, services, flows), Banished and Timberborn (survival
economies), Against the Storm (a roguelite settlement loop with clear goals).

---

## 1. The fantasy

You found and grow a settlement in *this* world, and it grows around the land that is already
there: the mountain your miners tunnel into, the river your mill sits on, the city blocks the world
generator built. The people are individuals with names, trades, moods and memories; the land has
its own seasons, weather, wildlife and neighbours.

## 2. Core loop

```
observe (needs, stocks, alerts) → designate (zones, jobs, builds, priorities)
  → the simulation runs (agents walk, work, eat, sleep, fight, gossip)
  → events and stories surface → adapt
```

- Real-time with pause (speed 1/2/3), ticks deterministic.
- The player never controls individuals directly (Dwarf Fortress/RimWorld) except through
  priorities and drafted squads.

## 3. How the world maps onto the game

| world | sandbox |
|---|---|
| a tile | a plot: its biome decides yields (fertility, stone, wood, fish, ore), build cost and hazards |
| the heightmap | mining depth, flooding, line of sight for defence |
| buildings (built terrain) | existing structures you can claim, repair or demolish |
| connectors (roads, rivers) | movement speed, trade routes, water for industry |
| drilling | build interiors (a workshop's floor plan, a mine's levels) |
| sprites | people, animals, items on the ground: the same pack pipeline paints them |

## 4. Designed systems (code)

- **Needs** per person: food, rest, safety, social, purpose (5 bars, each with clear effects).
- **Jobs**: a small set of labours (haul, farm, build, craft, mine, cook, heal, guard, trade), each
  with a skill that grows by use.
- **Stocks and recipes**: 12–20 goods with production chains of depth ≤ 3 (grain → flour → bread).
- **Zones and buildings**: stockpile, farm, housing, workshop types, defence; placement on tiles.
- **Events**: raids, weather, disease, migrants, traders, festivals, each a template event with
  generated specifics.
- **Storyteller** (RimWorld's): a pacing director choosing events from a tension curve.

## 5. Generated content

- The **founding party**: 6–8 individuals with backstories tied to the world's factions and history
  (via the bible), traits, relationships and a personal want.
- **Goods and recipes** named in the world's idiom (NYC: "hot dog carts, bodega stock"; medieval:
  "salt pork, tallow"), mapped to the designed goods table.
- **Neighbours**: factions from the bible, with wants, trade goods and grudges.
- **Events** with specifics grounded in the place and the colony's history.
- **Chronicle**: a running history written from events (Dwarf Fortress legends style), in the
  world's voice, short.

## 6. Dynamic over time

- New migrants carry new stories that interact with existing ones (rivals, lovers, debts).
- The world reacts: over-logging turns a forest tile into a scrub material; a mine drains a lake.
- Neighbouring factions evolve (they grow, move, ally) on the director's slow clock.

## 7. Win and lose

- Open-ended, with **charters** (goals chosen at start: "a town of 50", "the first steamship",
  "survive five winters") and a gentle failure (the colony disbands; its ruins stay on the map for the
  next game).

## 8. Open questions

- Real-time vs turn-based ticks? (Proposal: real-time with pause.)
- How deep is the simulation of individuals (RimWorld-light or Dwarf Fortress-deep)?
- Does the sandbox run on the world layer (tiles as plots) or on a drilled layer (tiles as rooms)?
  Proposal: plots at the region layer, interiors by drilling.
