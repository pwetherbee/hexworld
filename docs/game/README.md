# HexWorld games: design specs

> A generated world is a place. These documents describe how it becomes a **game**: one whose rules
> are designed and solid, and whose content (creatures, people, items, quests, places) is generated
> for *this* world, at the start and throughout play, without ever feeling generic.

Status: **draft for review**. Nothing here is implemented yet. Every document marks
**Decision** (what we propose; push back freely) and **Open** (needs your call). Edit anything.

## Reading order

| # | document | what it settles |
|---|---|---|
| 1 | [principles.md](principles.md) | The non-negotiables: what "not slop" and "not half-assed" mean in practice |
| 2 | [architecture.md](architecture.md) | How games attach to worlds: templates, the rules engine, content, state, the play-time agents |
| 3 | [content-and-anti-slop.md](content-and-anti-slop.md) | The content pipeline and the reusable "skills" that keep generated content specific and coherent |
| 4 | [play-mode-ux.md](play-mode-ux.md) | The game button, the setup flow, play mode, saves |
| 5 | [templates/adventure/](templates/adventure/README.md) | **The first template**: a Pokémon-like adventure, specified in full |
| 6 | [templates/sandbox.md](templates/sandbox.md) | Later: a colony/city management template (Dwarf Fortress, SimCity) |
| 7 | [templates/board-race.md](templates/board-race.md) | Later: a board-game race (The Game of Life and friends) |
| 8 | [templates/settlers.md](templates/settlers.md) | Later: a settle-trade-build template (Catan) |
| 9 | [world-life.md](world-life.md) | Making the world itself feel alive: sprite abundance, placement, motion, routines |
| 10 | [roadmap.md](roadmap.md) | Build order, milestones, what each one proves, and the open questions in one place |

Research behind these specs:
- [../research/game-design-research.md](../research/game-design-research.md): the earlier synthesis
  (game theory, board games, open worlds);
- [../research/world-aliveness.md](../research/world-aliveness.md): how games make worlds feel alive;
- [../research/anti-slop.md](../research/anti-slop.md): why AI game content feels sloppy and what works;
- [../research/monster-tamer-combat.md](../research/monster-tamer-combat.md): turn-based creature combat.

## The idea in one paragraph

A world is built exactly as today. When it's done, a **game button** appears at the top of the
screen. The player picks a **template** (Adventure first), tweaks a few details, and the game
agents write a **world bible** for this world: who lives here, what creatures roam which terrains,
who guards what, what the conflict is. A deterministic **rules engine** (code we write and test,
per template) runs the game; agents only ever fill **content** into typed slots the template
defines, and every piece is checked against the bible and against anti-slop rules. Content keeps
coming during play: the **director** generates what lies just beyond the player's frontier and
reacts to what the player does, so the game grows with them, and nothing in it could have come from
a different world.

## Glossary

| term | meaning |
|---|---|
| template | A game type we design and build in code: rules, content schemas, validators, UI screens, a playtest bot (Adventure, Sandbox, Board race, Settlers) |
| game spec | One world's instance of a template: chosen options plus generated content references |
| canon / world bible | The structured facts of a world that all content must agree with (factions, places, history, creature roster, conflicts) |
| content | Anything generated for play: creatures, moves, NPCs, items, shops, quests, bosses, dialogue, backgrounds |
| skill | A reusable generation module: a prompt, a schema, validators and a critic, with tests (see content-and-anti-slop.md) |
| rules engine | Deterministic code that resolves every action; LLMs never adjudicate rules or set numbers |
| director | The play-time agent that decides what content to commission and when (pacing, reactions) |
| frontier | The set of places the player can reach next; content there is generated ahead of time |
| play mode | The game UI on top of the world (as opposed to build mode, today's UI) |
