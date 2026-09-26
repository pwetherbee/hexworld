# Template: Settlers (settle, trade, build)

Status: **later**. Catan's proven loop on a generated world, with generation used where it adds
something (the land, the resources' names and looks, events, opponents' personalities) and the rules
kept tight and balanced.

---

## 1. Rules core (designed, faithful to what works)

- Hex tiles produce **resources** when their **number** is rolled (2d6); settlements on tile corners
  collect from adjacent tiles; cities double.
- Build roads (edges), settlements (corners, distance rule), cities; buy development cards.
- Trade with players and ports; a robber blocks a tile and steals on 7.
- First to N victory points (default 10).

## 2. Mapping a generated world onto a Settlers board

- **Tiles → resources.** Each biome maps to one of five resources (a mapping chosen per world by the
  game designer with engine constraints). NYC: glass towers → "capital", brownstones → "housing",
  parks → "green", docks → "cargo", streets → "transit". Medieval: forest → wood, fields → grain…
- **Board extraction.** A contiguous 19–37 tile region is selected (or the whole world if small),
  with the classic balance constraints enforced by the engine:
  - resource counts within ±1 of the standard distribution;
  - number tokens: no 6 and 8 adjacent, each resource's total pip value within bounds;
  - no start spot worth more than X pips above the median (a balance report is shown).
  - Where the world's layout can't satisfy them, the engine **re-labels** tiles (keeping the art)
    rather than moving them.
- **Ports** at water edges from the world's coast; **desert** from the least productive biome.
- Corners and edges come from the hex grid we already have.

## 3. Generated content

- Resource names, icons and card art in the world's idiom (sprite packs).
- Development cards: the designed effects (knight, road building, monopoly, year of plenty, VP) get
  world-specific names and one-line flavour.
- AI opponents with personalities from the bible's factions (a greedy guild, a cautious council),
  implemented as parameters of one designed bot, not as LLM play.
- A short narrative framing and end-of-game chronicle.

## 4. Dynamic twists (optional, one at a time)

- A world event deck (the director draws from designed event types with generated specifics): a
  harvest festival doubles grain once, a flood blocks a coastal tile for two rounds.
- The robber becomes a world-specific antagonist with a face and voice.

## 5. Balance and testing

- The existing research's restricted-play and MCTS self-play apply directly (Settlers is well
  studied): measure seat advantage, game length, lead changes, dead tiles.

## 6. Open questions

- Keep exact Catan rules (known-good) or a light variant to avoid trade-dress issues? (Proposal:
  mechanically standard, visually and thematically entirely the world's own.)
- Player-to-player trading UI for AI opponents: offers and counter-offers need a designed trade AI.
