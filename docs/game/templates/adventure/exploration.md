# Adventure: exploration

The overworld: how the player moves, what a place is, how creatures and people appear on the map,
fog, gates, keys and time.

---

## 1. Places

- **One tile = one place** (a "screen" in the Zelda sense). The player stands on a tile and interacts
  with what is on it: roaming creatures, NPCs, objects, exits.
- Each tile gets a **role** at game creation (from its biome, buildings and the region plan):

| role | what it offers | example tiles |
|---|---|---|
| town | healing, shop, NPCs, quests, safe (no wild encounters) | built terrain with buildings |
| route | travel, light encounters, a few NPCs (trainers, travellers) | roads, meadows, streets |
| wild | the main encounter areas, items to find | forest, marsh, rocky coast |
| dungeon | an attrition sequence and a boss (later: a drilled interior) | caves, ruins, a flooded tunnel |
| landmark | a set piece: lore, a rare creature, a view that reveals fog | the lighthouse, a summit |
| gate | needs a key to enter or cross | deep water, a cliff, a locked district |

- Every tile must pass the no-oatmeal test: at least one of a role-appropriate verb, a piece of
  evidence (lore), a pointer (something visible from it), or a creature habitat.

## 2. Movement

- **Hop** to an adjacent tile by click or keys. Hopping takes a moment of in-game time (§6).
- **Passability** is computed by the engine from the world, never by an LLM:
  - water tiles (liquid biome) need a water key;
  - a climb where the relief rises more than *H* levels across the shared edge needs a climbing key;
  - tiles of a "hazard" material (lava, deep snow, toxic marsh, a dark tunnel) need their key;
  - connectors make movement cheap (roads) or are the only way across (bridges).
- **Reach overlay** on hover: which tiles can be entered now, which need which key (icon), and how
  dangerous each is (creature level band).

## 3. Encounters on the map (visible first)

- Wild creatures are **visible roaming sprites** on the map (symbol encounters). Each wanders within
  its habitat tiles on a simple routine (graze, rest, patrol, flee at night). Walking into one, or
  it into you, starts a battle.
- **Why visible:** agency (avoid or engage), readability (you can see what lives where), and the
  world looks alive (this reuses the sprite and placement systems from world-life.md).
- **Aggression** by species temperament: shy ones flee from the avatar, territorial ones approach,
  nocturnal ones appear only at night.
- **Density** per tile from its danger attribute and role: route 0–2, wild 2–4, dungeon 3–5.
- **Respawn** follows habitat capacity and time: a cleared tile refills over an in-game day, unless
  the population was over-hunted (dynamic-content.md).
- Option: **hidden encounters** (rustling tall grass, dark water) in wild tiles, off by default.

> **Decision:** encounter tables are derived, not written: for each tile, the engine lists the roster
> species whose habitats include the tile's biome or edge terrains, weights them by rarity and time
> of day, and bounds their levels by the region's band. Agents write habitats; the engine does the
> tables. Rare spawns are guaranteed at least one reachable tile (validated).

## 4. Fog of war

- Tiles start **hidden**; entering or seeing a tile reveals it (fog peels radially, a chime).
- **Sight**: from a tile you see its neighbours; from higher relief you see further (+1 ring per 8
  levels of elevation above the surroundings), so summits and towers are vistas.
- **Landmarks are visible through fog** as silhouettes (their big sprite, a light at night) to pull
  the player.
- Uses the `visibility` field reserved on tiles, per save.

## 5. Gates and keys

- Each warden's mark grants a **traversal key** that opens a class of tiles. Keys are generated from
  the world's own obstacles, drawn from a designed catalog:

| key class | opens | example (world-specific skin) |
|---|---|---|
| water | liquid tiles, ports | "the ferryman's token", "a harbour pass" |
| climb | steep relief edges | "rope and pitons", "fire-escape key" |
| dark | dark/cave materials | "a lantern of whale oil" |
| hazard | one hazardous material (lava, toxic, snow) | "salt boots", "a heat-ward charm" |
| social | a gated district (built terrain) | "a guild seal", "a VIP wristband" |
| mount | faster hops, cross a wide terrain | "a trained tide-horse" |

- The engine selects the key classes the world needs (only obstacles that exist in it), orders them
  along the spine, and validates the graph: every region reachable, each warden reachable with the
  keys obtainable before them, no softlocks.
- Keys **re-read the map** (Breath of the Wild's lesson): the water key opens the sea *and* every
  lake's islands, not one door.

## 6. Time

- An in-game clock advances per hop (and on rests): dawn, day, dusk, night.
- Time changes lighting (the world's day/night cycle, world-life.md), which creatures roam, shop hours
  and some NPC routines.
- Resting at an inn or camp heals and passes time.

## 7. Entering places (with drilling)

- When drilling exists, towns, dungeons and buildings are **entered** by drilling into their tile
  (the VISION doc's dive). The child layer is played at the same granularity (a tile = a room or a
  street). Until then, a town tile's services are menus and its NPCs stand on the tile.

## 8. What the player sees on a tile

- The tile's sprites (the world build's cast) plus **game sprites** (roaming creatures, NPCs, item
  sparkles, a shop sign) placed by the same layout engine with the game's own layer.
- A place card on arrival: name (from the naming language), role icon, one line of flavour,
  what's here (people, creatures seen here, shop).
