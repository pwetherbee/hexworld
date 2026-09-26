# Roadmap: from living world to playable games

Build order, what each milestone proves, and every open question in one place. Estimates are rough
and assume one focused builder with agents.

---

## Milestones

### M0. The living world (foundation for everything)
World-life steps 1–3 ([world-life.md](world-life.md) §10): instanced sprite renderer with shader
motion; placement recipes and the cluster sampler; layer budgets; packs planned across scales.
- **Proves:** 15–30 things per tile at smooth frame rates; the world reads as inhabited.
- **Why first:** Adventure's roaming creatures, NPCs and battle backgrounds all reuse it.

### M1. Game scaffolding
The game service ([architecture.md](architecture.md)): `Game`, `Canon`, `ContentRegistry`, `Save`,
event-sourced reducer interface, the game button and setup panel ([play-mode-ux.md](play-mode-ux.md))
with a stub template, the core skills 1–8 and 12 ([content-and-anti-slop.md](content-and-anti-slop.md))
with their fixture worlds and the eval harness (skill 15).
- **Proves:** a world can get a canon (voice, names, factions, history) that passes the slop metrics on
  the 6 standard test worlds.

### M2. Adventure: the battle engine, alone
[combat.md](templates/adventure/combat.md) implemented as a pure engine with tests, the balance simulator,
and a battle screen playable with generated creatures on a fixed backdrop.
- **Proves:** combat is fun and balanced *before* any world is attached: the sim shows no dominant
  role or affinity, battles last the target number of turns, enemy AI is readable.

### M3. Adventure: creatures and the world
Affinity design, the roster and moves ([creatures.md](templates/adventure/creatures.md)), sprite packs
for creatures, encounter tables from habitats, roaming creatures on the map, bonding, the Compendium,
battle backgrounds ([battle-backgrounds.md](templates/adventure/battle-backgrounds.md)).
- **Proves:** walking around a generated world, meeting creatures that obviously belong to it, and
  fighting them in a scene of their tile.

### M4. Adventure: the spine
Places and roles, fog, gates and keys ([exploration.md](templates/adventure/exploration.md)), towns
(healers, shops, items, economy), wardens and the confrontation, the rival
([people-items-quests.md](templates/adventure/people-items-quests.md)), saves, the playtest bot
([balance-and-testing.md](templates/adventure/balance-and-testing.md)).
- **Proves:** a complete Short game (≈1 h) on any generated world of ≥ 30 tiles, finishable by the bot
  on 20 worlds and by a human on 3.

### M5. Adventure: alive
The director ([dynamic-content.md](templates/adventure/dynamic-content.md)): frontier generation,
reactions, ecology, world events, quests at the frontier, dialogue on demand, time and weather.
- **Proves:** two playthroughs of the same world diverge because of what the player did.

### M6. Adventure: Standard and Long
Bigger worlds or drilling (VISION layers), more wardens, the full roster sizes, polish, sound,
accessibility, onboarding.

### M7+. The other templates
Board race → Settlers → Sandbox (each with its own full spec first). Board race is the cheapest (reuses
the map, a track and the event system); Settlers needs trade AI; Sandbox needs a simulation core.

---

## Open questions (collected)

| # | question | where | proposal |
|---|---|---|---|
| 1 | ~~Default party size 4 or 6?~~ | adventure/README §3 | **decided: variable** |
| 2 | ~~World size for Standard?~~ | adventure/README §6 | **decided: variable worlds, layered play (overworld → region grid → scene), open-ended loop** |
| 3 | ~~Can a game change the world's tiles?~~ | architecture §5 | **decided: yes, permanently** |
| 4 | Free-text chat with NPCs? | people-items-quests §1.3 | not in v1 |
| 5 | Battle background view: side view or 3/4 using the real 3D tile? | battle-backgrounds §4 | side view first |
| 6 | Visible-only encounters, or hidden ones too? | exploration §3 | visible by default, hidden optional |
| 7 | Share links for worlds + games? | play-mode-ux §4 | design ids/permissions now, ship later |
| 8 | World clock / walkers / ambience in build mode? | world-life §11 | clock toggle; walkers when zoomed; ambience in play mode only |
| 9 | Settlers: exact Catan rules or a variant? | settlers §6 | mechanically standard, thematically the world's |
| 10 | Sandbox: real-time with pause vs turns? | sandbox §8 | real-time with pause |
| 11 | Multiplayer: hot-seat early, online later? | VISION §7 | hot-seat for Board race and Settlers; Adventure single-player |
| 12 | Model choices and budgets per play hour | architecture §4, dynamic-content §6 | strongest model for bible/roster/wardens; cheap model for lines; budget ≈ $0.10–0.30 per play hour, to be measured |
| 13 | Double battles (2v2) in Adventure? | combat | singles in v1; design the engine so doubles is an extension |
