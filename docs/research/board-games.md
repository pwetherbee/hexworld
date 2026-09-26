# Board games, hex maps, and what makes them fun: research for HexWorld

> Scope: mechanics taxonomy, hex/map game case studies, design principles, digital adaptations, and
> concrete takeaways for letting HexWorld's agents turn a generated hex map into a playable game.
> Claims are sourced at the end; where something is my own synthesis/recommendation it is phrased as such.

## TL;DR

- **A map is not a game until it creates decisions.** The best map games make *where* you are matter
  through a small number of legible tile properties (Catan's number tokens, Terraforming Mars' placement
  bonuses, wargame terrain effects) and make *other players or a system* contest those places.
- **Prefer input randomness (known before you decide) over output randomness (after you decide).** A
  generated map is itself input randomness, which is the "good" kind for strategy. Output randomness
  (dice combat) should be bounded and legible.
- **Procedural maps buy replayability but create balance debt.** Every successful variable-setup game
  pairs randomness with constraints (Catan's "no adjacent red numbers", Twilight Imperium's tiered
  Milty-draft slices, Kingdom Builder's fixed-size sectors). HexWorld's planner should emit constraints
  and a balance report, not just a map.
- **Make the AI opponent predictable and telegraphed** (Spirit Island's explore/build/ravage deck,
  Into the Breach's shown attacks, Slay the Spire's intents, Gloomhaven's monster ability cards). That
  is what turns a generated scenario into a solvable, fair-feeling puzzle.
- **Recommended menu of game templates** (section 6): Settle & Produce (Catan-like), Expedition /
  Explore-and-Reveal (Mage Knight / Robinson Crusoe), Skirmish Tactics (Into the Breach / Gloomhaven on
  the drilled-down sub-board), Hold the Line co-op (Spirit Island / Pandemic), Area Majority, Route &
  Deliver, Race, and Tile-Laying Frontier. Each needs only 2-6 typed tile attributes.
- **Drill-down is a natural "zoom from strategy to tactics" layer.** Board games already do this:
  overworld exploration then tactical encounter (Mage Knight, Descent's Road to Legend app,
  Gloomhaven's town-to-scenario loop). The world layer should be simple and fast; the tactical sub-board
  should be small (Into the Breach uses 8x8) and fully telegraphed.

---

## 1. The mechanics taxonomy

Two references define the vocabulary. **BoardGameGeek** classifies every game by "mechanics" (worker
placement, area majority, deck building, hexagon grid, modular board, etc.). **Engelstein & Shalev's
_Building Blocks of Tabletop Game Design: An Encyclopedia of Mechanisms_** organises roughly 200
mechanisms into 13 chapters (including game structure, auctions, worker placement, area control and
set collection), each with a definition, diagram, examples and implementation considerations. The
**_Characteristics of Games_** book (Elias, Garfield, Gutschera) adds orthogonal axes that matter more
than mechanics for "feel": length, player count, luck vs skill, hidden information, downtime,
reward/effort ratio, snowball vs catch-up, complexity.

For each mechanic below: **feel** (what it is like to play), **why it works**, and **on a HexWorld map**
(how a generated map could host it).

### Action selection / action points
- **Feel:** "I can do 2-3 things this turn; which matter most?" Scythe lays out four actions on a
  player mat and forbids repeating the same one on consecutive turns; Civilization: A New Dawn uses a
  "focus bar" where each slot's power depends on its position, and each turn is a single action, which
  reviewers credit for its pace.
- **Why it works:** scarcity of actions creates opportunity cost; a constrained menu is fast to read.
- **Map:** actions are verbs on hexes (move, gather, build, explore, fight). Tile attributes
  (`move_cost`, `resource`, `build_slots`) set the price and payoff of each verb.

### Worker placement
- **Feel:** a race for the best spots; "if I don't take it now, you will." Wikipedia defines it as
  allocating a limited number of workers to stations that provide actions; placing blocks others
  (popularised by Caylus in 2005, then Stone Age and Agricola).
- **Why it works:** indirect interaction (blocking) without aggression; clear, visible state.
- **Map:** special hexes (mines, shrines, markets, the town you can drill into) become action spaces
  that one unit can occupy per round. Robinson Crusoe is a worker-placement game whose action spaces
  include exploring new island hexes.

### Area control / area majority
- **Feel:** tug-of-war over regions; tense scoring moments. Kingdom Builder awards gold for things like
  majority of settlements in a map sector.
- **Why it works:** simple win logic ("most pieces in a region"), strong player interaction,
  natural geography.
- **Map:** needs *regions* (clusters of hexes with a name and a value). The planner can group
  generated tiles into regions and assign each a score. Root is the modern exemplar: control of
  clearings drives building and scoring for most factions.

### Deck-building / bag- and pool-building
- **Feel:** start weak, improve your own engine; each shuffle surprises you in a way you caused.
  Dominion (2008) set the genre; Slay the Spire (2017) made it the backbone of roguelikes; Quacks of
  Quedlinburg combines bag-building with push-your-luck; Mage Knight and Heat use deck-building on a map
  or track.
- **Why it works:** randomness is *authored by the player* (you chose what went in the deck), so luck
  feels earned; growth is visible.
- **Map:** hexes are where cards come from (visiting a ruin adds a card; a cursed swamp adds a junk
  card). Mage Knight's 16-card starting deck doubles as movement, combat and influence.

### Engine building
- **Feel:** early investments compound; the late game is a satisfying payout. Terraforming Mars is the
  archetype: production and card synergies drive scoring.
- **Why it works:** clear arc (invest, then harvest); long-term planning.
- **Risk:** snowballing (see catch-up in section 4).
- **Map:** owned hexes are engine parts (a farm hex yields +1 grain each round; adjacency to a river
  doubles it).

### Tile placement / tile laying
- **Feel:** you are building the map; every tile is a small spatial puzzle. Carcassonne requires edges
  to match (roads to roads, cities to cities); Kingdomino scores region size x crowns; Tigris &
  Euphrates builds kingdoms from coloured tiles.
- **Why it works:** a shared, growing artefact; immediate spatial feedback; low rules overhead.
- **Map:** HexWorld *already is* a tile-laying engine with edge constraints. Letting players pick the
  next tile (or its seed/prompt) and score the result is almost free. Kingdomino's draft rule ("better
  tile now = worse pick order next round") is a cheap, elegant balancing trick to steal.

### Network / route building
- **Feel:** connect A to B before the path is blocked. Ticket to Ride pairs set-collection (colored
  train cards) with hidden destination tickets and scarce routes; Power Grid charges connection costs
  across a city map; Railroad Ink is a roll-and-write route builder.
- **Why it works:** clear goals, visible progress, natural blocking.
- **Map:** HexWorld tiles already have edge connectors (roads, rivers). A route game needs only
  `connectors` per edge and a build cost per hex.

### Pick-up and deliver
- **Feel:** logistics; planning efficient loops. Classic in train and trade games.
- **Why it works:** combines routing with economy; each delivery is a micro-goal.
- **Map:** `produces` and `demands` attributes on settlement tiles; `move_cost` shapes the routes.

### Set collection
- **Feel:** "I need one more blue." Ticket to Ride's train cards; Tigris & Euphrates scores only your
  *weakest* colour, forcing diversification.
- **Map:** resources scattered across biomes make every biome relevant. The T&E "weakest category wins"
  rule is a strong generic anti-specialisation rule for generated worlds.

### Auctions / bidding
- **Feel:** valuing things against people; bluffing. Power Grid auctions power plants.
- **Why it works:** self-balancing, since players price the imbalance. This is valuable for
  *procedural* content: if the generator makes one hex too good, an auction lets players price it.
- **Map:** auction starting positions, map slices, or newly revealed hexes.

### Trading / negotiation
- **Feel:** social, loud, emergent. Catan's resource trading; Cosmic Encounter's alliances and shared
  wins; Twilight Imperium's politics (agendas voted on once Mecatol Rex is held).
- **Why it works:** players fix each other's bad luck; interaction is high.
- **Map:** complementary resource distribution (no one region has everything) makes trade necessary.

### Push-your-luck
- **Feel:** "one more draw..." Quacks' pots can explode; Heat lets you go faster through corners at the
  cost of heat cards.
- **Map:** deeper exploration of a dungeon hex or a longer forced march across `danger` tiles.

### Hidden roles / social deduction
- **Feel:** paranoia, table talk. Werewolf, The Resistance/Avalon (one team knows the other),
  Blood on the Clocktower (dead players remain as ghost voters, avoiding player elimination).
- **Map:** a hidden traitor among explorers; secret objectives tied to hexes. Needs a social,
  synchronous group, so it is a niche template for HexWorld.

### Cooperative games
- **Feel:** a team against a system. Spirit Island, Gloomhaven, Robinson Crusoe, Pandemic.
- **Why it works:** needs an interesting *AI system*, usually a deck-driven, predictable opponent.
- **Map:** a threat that spreads across hexes following visible rules (section 2, Spirit Island).
  The strongest fit for single-player HexWorld.

### Legacy / campaign
- **Feel:** your choices permanently change the game. Risk Legacy (2011) invented the format; Pandemic
  Legacy: Season 1 (2015) made it acclaimed; Gloomhaven used sealed envelopes and stickers across 95
  scenarios.
- **Map:** HexWorld is *naturally* legacy: the world persists; a razed town stays razed, a cleared
  dungeon stays cleared, and new hexes are generated as consequences. No stickers needed.

### Roll-and-write
- **Feel:** everyone plays simultaneously on their own sheet from a shared roll/flip. Qwixx helped open
  the genre; Railroad Ink, Welcome To and Cartographers (you draw a map to fulfil the queen's edicts
  over four seasons) are map-flavoured examples.
- **Why it works:** near-zero downtime, any player count.
- **Map:** "everyone gets the same generated map and the same draws; best result wins." A great
  asynchronous or daily-challenge mode.

### Asymmetric factions / variable player powers
- **Feel:** "I play a different game than you." Cosmic Encounter pioneered aliens that each break one
  rule; Root gives four base factions entirely different economies (Marquise builds, Eyrie follows a
  decree and falls into turmoil, Woodland Alliance spreads sympathy and revolts, Vagabond is one piece
  doing quests); Twilight Imperium 4 has dozens of factions.
- **Why it works:** replayability and identity. Wehrle calls asymmetric games easy to design but hard
  to develop; he balances strong positions with "strategic liabilities" and relies on shared vocabulary
  so players can read each other.
- **Map:** factions keyed to biomes (the river folk move free on water; the mountain clan builds only
  on hills). Generate *one* rule-break per faction (the Cosmic Encounter approach), not a new game.

---

## 2. Hex and map games: case studies

### Catan (1995): hex production, trading, robber, variable setup
- 19 terrain hexes produce five resources; each hex carries a number token; two dice decide which hexes
  produce. Settlements sit on vertices, touching up to three hexes. 10 VP wins; bonuses for longest road
  and largest army. Over 32 million copies sold.
- **Why the hex board works:** vertex placement turns the map into a portfolio choice (diversify
  resources vs chase high-probability numbers). Pips (how many of 36 rolls produce) make the map's value
  *legible*.
- **The robber** is a player-directed, map-local disruption (block one hex, steal a card), which gives
  losing players a targeted lever.
- **Variable setup and its problems:** the official constraint is a single rule: 6s and 8s (5/36 each)
  may not be adjacent. Community generators add optional constraints (no adjacent 2/12, no identical
  adjacent numbers, no same-resource clusters) and brute-force shuffles until the constraints hold.
- **Lesson for HexWorld:** random + a few adjacency constraints + a legible value number per hex.

### Twilight Imperium (4th ed.): building the galaxy
- Hex system tiles are placed during setup in rings around Mecatol Rex. Strategy cards drive turn order;
  command tokens limit actions; agendas are voted on; public and secret objectives lead to 10 VP. Games
  typically run 6+ hours.
- **Balance problem and community fix:** the "Milty Draft" assigns blue-backed tiles one of three
  tiers, builds each slice from one tile per tier plus two red-backed (hazard) tiles, then players
  snake-draft a slice, a faction, and a seat. Many online players now prefer it.
- **Lesson:** tier the generated tiles, build *comparable slices*, and let players draft them. This
  maps directly to HexWorld's planner: it can generate tiers, not just tiles.

### Gloomhaven / Frosthaven / Jaws of the Lion: card-driven hex tactics
- Each round every player simultaneously picks two cards; the leading card sets initiative; you use the
  top half of one and the bottom half of the other. An attack modifier deck replaces dice. Maps are
  hex-gridded scenario layouts with obstacles, traps and chests; the campaign branches across 95
  scenarios with sealed content and permanent stickers. It was BGG's #1 game from 2017 to 2023.
- **Jaws of the Lion** teaches through its first five scenarios, with simplified starter cards that
  are swapped out as you progress; reviewers call it the best onboarding in the series.
- **Lessons:** simultaneous secret selection cuts downtime; a hand of cards that also works as a
  stamina timer creates tension without a clock; a deck (not dice) bounds output randomness; *teach
  the rules in the first scenarios instead of a rulebook*.

### Terraforming Mars: hex placement as a sub-game
- 61-hex Mars board; ocean, greenery and city tiles; placement bonuses printed on hexes; game ends when
  three global parameters (oxygen, temperature, oceans) are maxed. Scoring mixes engine building and
  placement.
- **Lesson:** a hex map can be a *secondary* scoring surface for a card/engine game. Global shared
  tracks that anyone can push forward create a natural, player-driven game clock.

### Root: asymmetry on a map
- Clearings connected by paths (a graph, not a grid). Each faction uses the same map for different
  purposes. Wehrle: shared vocabulary is how asymmetric players "witness and understand one another."
- **Lesson:** asymmetric rules still need a shared, simple map grammar (what a clearing/hex *is*, who
  rules it) so different factions interact meaningfully.

### Spirit Island: a readable, spreading threat
- Co-op; modular island boards divided into lands of different terrain. The invader deck drives an
  explore -> build -> ravage cycle: this turn's explored terrain is next turn's build and the turn after
  that's ravage, so players can see damage coming and plan. Fear lowers victory requirements as it
  accumulates ("terror levels"); blight accumulation is a loss condition. Fast powers resolve before
  invaders, slow powers after.
- **Lesson:** the best template for a HexWorld co-op AI opponent: threat keyed to *terrain type*
  (which the generator already assigns), advancing on a visible conveyor belt, and a victory condition
  that gets easier as players succeed (an escalating arc that rewards progress).

### Scythe: map as a stage for engines, not war
- Hex map, five asymmetric factions with mats, four actions (no repeats in consecutive turns), game
  ends immediately when someone places their sixth star. Combat is deliberately infrequent; reviewers
  note production matters more than war.
- **Lesson:** the *threat* of combat on a map shapes positioning even if fights are rare. A
  "first to N achievements" end trigger keeps games bounded.

### Civilization-style board games
- Civilization: A New Dawn builds its map from 16 double-sided 10-hex tiles placed by players, and its
  focus bar ties action strength to position. Win by completing three agendas; plays in about 90
  minutes.
- **Lesson:** the "4X in 90 minutes" is achievable by collapsing a turn to one action and using
  agendas (objective cards) as the win condition.

### Tigris & Euphrates: tile placement with conflict and "score your weakest"
- Four tile colours, matching leaders, internal and external conflicts when kingdoms merge,
  monuments. Final score is your *lowest* colour.
- **Lesson:** a single scoring rule can force players to engage with every part of the map.

### Hive: the board is the pieces
- No board: an infinite plane of hex tiles; pieces must stay connected ("one hive" rule); win by
  surrounding the enemy queen; each bug moves differently.
- **Lesson:** strong fit for HexWorld's infinite hex plane. A small abstract game can live on any
  hex neighbourhood with no terrain at all.

### Hex-and-counter wargames: ZOC, terrain, combat results tables
- **Zone of control**: the six hexes adjacent to a unit. Variants: rigid (must stop on entering),
  semi-rigid, elastic (costs extra movement), locking (cannot leave). ZOC exists so a mover can't slide
  past an opponent who can't react during the mover's turn.
- **Terrain effects chart**: move cost per terrain; defensive terrain shifts combat odds (e.g. forest,
  city or fortification drops 4:1 to 3:1).
- **Combat results table (CRT)**: compare attack:defence ratio, roll one die, read the result (retreat,
  eliminated, exchange).
- **Lesson:** ZOC plus a terrain effects chart is the most economical "movement matters" system ever
  devised, and it needs exactly the attributes HexWorld already has (`move_cost`, `defense`).

### Carcassonne and Kingdomino: tile laying
- Carcassonne: edges must match; place a meeple on a feature; completed features score. Kingdomino:
  5x5 kingdom, region size x crowns, draft order balances tile quality (15-20 minutes, Spiel des Jahres
  2017).
- **Lesson:** HexWorld's edge-matching generator is a Carcassonne rules engine waiting for scoring.

### Mage Knight: exploration by revealing tiles
- Players reveal map tiles as they explore; enemies are placed as tiles appear; a 16-card deck drives
  movement and combat; day/night rounds; scenario objectives such as conquering cities. Widely regarded
  as one of the best solo games.
- **Lesson:** reveal-on-explore is the single best fit for "infinite generated map". Generate the next
  tile when the player steps to the frontier, as HexWorld already does on demand.

### Heat: Pedal to the Metal: racing on a track
- Simultaneous card play for speed; corners have speed limits and exceeding them costs heat cards that
  clog your deck; slipstreaming; optional garage upgrades and weather. 1-6 players, 30-60 minutes.
- **Lesson:** a race is the simplest win condition on a map. Heat's "push past the limit, pay in deck
  quality" is a model for converting terrain danger into a resource cost rather than a die roll.

### Dungeon crawlers: HeroQuest and Descent
- One player (Zargon/Overlord) runs monsters and reveals the dungeon. Descent's Road to Legend app takes
  over the overlord role and reveals the map as doors open, enabling fully co-op play.
- **Lesson:** an app (or an LLM agent) replacing the game master is proven. HexWorld's agents can
  reveal the room map as players enter.

### Exploration games: Robinson Crusoe, Arkham/Eldritch Horror
- Robinson Crusoe: worker placement where Explore draws random island hex tiles showing terrain,
  beasts, food, wood, shelter; famously hard. Arkham Horror 3rd edition uses 12 double-sided
  neighbourhood tiles with scenario-specific layouts.
- **Lesson:** scenario-specific layouts make modular maps feel authored; exploration yields both
  resources and threats.

### What variable / modular / procedural setup does, and costs

| Benefit | Cost / balance risk | Proven mitigation |
|---|---|---|
| Replayability; no memorised openings | Start positions of unequal value | Catan adjacency rule; TI Milty slices; snake draft for placement |
| Exploration & surprise | Kingmaker tiles (one super-hex decides the game) | Tiering; auctions; "score your weakest" |
| Emergent stories | Unreachable goals or dead zones | Scenario objectives set *after* the map is known; connectivity checks |
| Scales to any player count | Asymmetric distances between players | Fixed-size sectors per player (Kingdom Builder uses 4 of 8 sectors) |
| Legibility suffers as maps grow | Analysis paralysis | Keep the value of each hex a single, visible number |

---

## 3. Design principles

### Meaningful decisions
- A decision is meaningful when options differ in outcome, the player can foresee some of the
  consequences, and none is obviously dominant. Characteristics of Games lists the reward/effort ratio
  as a core characteristic: complexity must pay for itself.
- For generated maps: every hex should present a trade-off (rich but dangerous; safe but slow).
  Uniformly good or bad regions yield no decisions.

### Tension, pacing and the arc of a game
- Games feel good when the decision space changes over time: an opening (expand, explore), a midgame
  (conflict, engine), and an endgame with a visible clock. Examples of built-in arcs: Spirit Island's
  fear levels; Terraforming Mars' global parameters; Scythe's six stars; Mage Knight's day/night rounds;
  Pandemic-style escalation.
- Rule of thumb (synthesis): every template needs (a) an escalation (threat grows, costs rise), (b) a
  visible end trigger, and (c) a final-turn scoring surprise small enough not to feel random.

### Player interaction: direct vs indirect
- Direct: attack, steal, the robber. Indirect: blocking a worker spot or a route, taking the tile
  someone wanted, racing the same objective. Cooperative: shared threat.
- Indirect interaction is friendlier for mixed audiences; direct interaction is dramatic but risks
  bullying and kingmaking.

### Downtime and simultaneous turns
- Downtime is time waiting for your turn. Proven fixes: simultaneous play (drafting in 7 Wonders,
  hidden selection in Colt Express, Gloomhaven's card choice, Heat's card play); reactive abilities on
  others' turns; fewer options per turn; non-blocking upkeep; clearer interfaces.
- Simultaneous action selection also removes first-player advantage but needs rule separation to
  resolve conflicts (Diplomacy writes orders secretly; Junta separates phases).
- Digital makes this easier: the app can resolve simultaneous orders instantly and support async play.

### Component clarity and state legibility (digital)
- In physical games clarity comes from iconography and reference cards. In digital, the best games
  *show consequences before commitment*: Into the Breach shows every enemy's attack direction and
  target; Slay the Spire shows each enemy's intended action and damage; Wildfrost shows each unit's
  attack countdown.
- For HexWorld: overlays for `move_cost`, reachable range, ZOC, threat next turn, and resource yield
  should be one keypress away. The pixel-art tile must not be the only carrier of rules information.

### Onboarding and rules teaching
- Jaws of the Lion's five tutorial scenarios with simplified starter cards is the benchmark. Ticket to
  Ride's turn ("draw cards, claim a route, or take tickets") shows how small a turn can be.
- For generated games: the agent should emit a **one-sentence goal**, a **three-verb turn**, and an
  opening scenario where only one mechanic is live, then unlock the rest.

### Game length
- Length should match weight. Kingdomino takes 15-20 minutes; Catan 1.5-2 hours; Twilight Imperium
  6+ hours. Characteristics of Games treats length as a first-class design axis.
- Generated games should default to short sessions (10-30 minutes) with persistence across sessions
  (legacy-style) instead of long single sessions.

### Snowballing and catch-up mechanics
- Runaway leaders come from positive feedback loops. The Thoughtful Gamer groups remedies as:
  ball-and-chain (Power Grid's reverse turn order for buying and building; Suburbia's speed bumps),
  point floors (Castles of Burgundy), subtle integration (Dominion's victory cards clog your deck),
  player balancing (Cosmic Encounter, TI; risks kingmaking), or none (Twilight Struggle).
- Quacks' "rat tails" give trailing players a head start proportional to the gap; players enjoy
  receiving them.
- Other levers: hidden scores (Ticket to Ride's destination tickets), separating resources from VP.

### Randomness: input vs output; luck vs skill
- **Input randomness** informs decisions (map generation, face-up cards); **output randomness** sits
  between decision and outcome (Risk/XCOM dice). Burgun argues input randomness is better for strategy
  because it preserves the link between decisions and results.
- Practical middle ground used by acclaimed games: decks instead of dice (Gloomhaven's modifier deck,
  whose content you control), small bounded variance, and visible odds.
- Luck is not the enemy: it lowers the skill gap for casual tables, creates stories, and hides who is
  winning. Tune it per audience.

### Fog of war and exploration
- Hidden map + reveal-on-explore (Mage Knight, Robinson Crusoe, Descent's app) produces discovery,
  which HexWorld does natively. The danger is unfairness: a player who reveals a bad tile loses by bad
  luck. Mitigate by generating the *distribution* of what is out there before revealing it, and by
  guaranteeing that frontier hexes within N steps include at least one resource and one escape route.

### Campaign / legacy progression
- Legacy games offer persistent change and narrative arcs; they trade away replayability of a single
  copy. HexWorld can have both: the world persists, but templates can be re-run on a fresh region.
- Gloomhaven's retirement and personal quests show how to cycle characters so power doesn't grow
  unbounded.

---

## 4. Digital adaptations and digital-native "board games"

- **Into the Breach (Subset Games):** 8x8 grid; three mechs; every enemy attack is telegraphed;
  protecting buildings that power the grid is the real objective. Designers wanted every loss to feel
  like your own fault; reviewers compared it to chess. Pushing enemies into each other is the core
  verb. The GDC 2019 design postmortem covers the four-year iteration.
  *HexWorld takeaway:* small boards, perfect information about the next enemy turn, and objectives
  beyond "kill everything" (protect a town hex).
- **Slay the Spire (Mega Crit):** branching node map, deck-building combat, enemy intents, relics;
  balanced with client metrics (GDC talk "Metrics Driven Design and Balance").
  *Takeaway:* the overworld can be a graph of choices; log metrics per generated template and tune.
- **Dicey Dungeons (Terry Cavanagh):** dice are resources placed into equipment slots; episodes change
  the rules per character. *Takeaway:* per-scenario rule mutators are a proven way to get variety.
- **Wildfrost:** lane-based card battler with visible attack counters and metaprogression.
- **Board Game Arena:** the largest online board-game platform, over a thousand titles, rules
  enforcement, real-time and asynchronous turn-based play. *Takeaway:* enforced rules + async turns
  are table stakes for a digital board game; HexWorld's validator-backed rules engine should be
  authoritative.
- **Descent: Road to Legend app:** an app plays the overlord and reveals the map as doors open.

---

## 5. What this means for an agent-authored game

The agents should not invent free-form rules. They should **instantiate a template with parameters**,
using the same "restricted meta-schema" pattern HexWorld already uses for tile attributes (typed,
bounded attributes the super planner defines). Generated rules should be:

1. **Composable from known mechanisms** (from the taxonomy above) so the engine can enforce them.
2. **Legible:** each rule maps to a visible overlay or UI element.
3. **Validated:** the orchestrator simulates or statically checks the setup (reachability, resource
   parity, start-position fairness), returning errors to the planner through `submit_*` tools like the
   existing tile pipeline.
4. **Themed:** the LLM's comparative advantage is flavour (names, factions, events), not arithmetic.

---

## 6. Concrete takeaways for HexWorld

### 6.1 Menu of game templates

Each entry: players, turn structure, actions, win condition, required tile attributes. Attributes are
suggestions for the super planner's `tile_attributes`.

**A. Settle & Produce (Catan-like economy)**
- *Players:* 2-4 (or 1 vs a bot). *Turn:* roll/draw production -> trade -> build.
- *Actions:* build settlement (vertex or hex), upgrade, build road, trade.
- *Win:* first to N VP (settlements, upgrades, longest road).
- *Attributes:* `resource` (enum), `yield_number` (2-12 or a weight), `buildable` (bool).
- *Balance:* no adjacent top-yield hexes; each resource present in at least k hexes; seat-order snake
  draft for starting spots.

**B. Expedition (Mage Knight / Robinson Crusoe explore-and-reveal)**
- *Players:* 1-4 co-op or competitive. *Turn:* play cards/spend stamina to move, explore frontier,
  resolve encounter.
- *Actions:* move, explore (generates a new tile), rest, fight/evade, gather.
- *Win:* reach/complete a scenario objective (find the relic, found a city) within T rounds.
- *Attributes:* `move_cost`, `danger` (0-3), `resource`, `site` (ruin/shrine/town/none).
- *Why it fits:* infinite map + on-demand generation is literally this mechanic.

**C. Skirmish Tactics (Into the Breach / Gloomhaven), primarily on the drilled-down sub-board**
- *Players:* 1-2. *Turn:* enemies telegraph -> player moves/acts -> enemies resolve.
- *Actions:* move, attack, push, use ability, interact with objects.
- *Win:* survive N turns / protect objective hexes / defeat the boss.
- *Attributes:* `move_cost`, `blocks_movement`, `blocks_sight`, `cover` (defence bonus), `hazard`
  (damage on end of turn), `elevation`.
- *Rules:* small board (roughly 7-radius or 8x8 equivalent), ZOC (elastic), no damage dice or a small
  modifier deck.

**D. Hold the Line (Spirit Island co-op)**
- *Players:* 1-4 co-op. *Turn:* invader card reveals a terrain type -> threat explores/builds/ravages on
  a three-step conveyor -> players act.
- *Actions:* place defenders, cleanse, fortify, use powers.
- *Win:* survive the deck or clear all threat; win condition relaxes as "fear" accrues. *Lose:* blight
  exceeds limit or a key hex falls.
- *Attributes:* `biome` (used by the threat deck), `population`, `defense`.

**E. Area Majority (Root-lite / El Grande-style)**
- *Players:* 2-5. *Turn:* place/move k units -> periodic regional scoring.
- *Win:* most points after R scorings.
- *Attributes:* `region` id, `region_value`, `move_cost`.
- *Balance:* equal total region value within reach of each start; scoring rounds announced in advance.

**F. Route & Deliver (Ticket to Ride / Power Grid)**
- *Players:* 2-5. *Turn:* draw cards, claim a route segment, or take a goal.
- *Win:* most points from claimed routes and completed secret destinations.
- *Attributes:* edge `connectors` (road/rail/river), `build_cost`, settlement `produces`/`demands`.

**G. Race (Heat-style)**
- *Players:* 1-6. *Turn:* simultaneous card choice -> move -> pay terrain penalties.
- *Win:* first to finish line / checkpoint sequence.
- *Attributes:* `move_cost`, `speed_limit` or `danger`; start and finish tiles.
- *Why it fits:* trivially generated, trivially balanced (everyone runs the same course).

**H. Frontier Tile-Laying (Carcassonne / Kingdomino)**
- *Players:* 1-4. *Turn:* draft one of k generated tiles -> place with matching edges -> optionally claim.
- *Win:* highest score from completed features or region size x crown count.
- *Attributes:* edge types (already present), `crowns`/`value`, `feature` ids.
- *Why it fits:* uses HexWorld's edge matching directly; generation *is* the game.

**I. Daily Cartographer (roll-and-write / solo challenge)**
- Everyone gets the same seed, map and draws; score on the same goals; leaderboard. Near-zero
  downtime, async, great for sharing.

**J. Hive-like abstract** on the bare hex plane for a quick two-player duel (optional, low cost).

### 6.2 Keeping generated maps balanced

1. **Tier, then place.** Have the planner assign each generated tile a value tier (Milty-style) and
   compose per-player slices from equal tier counts.
2. **Adjacency constraints** as validator rules: no two top-tier hexes adjacent; each resource type
   present at least k times; every start within d steps of every resource type; no start within d of
   the threat spawn.
3. **Symmetry when competitive, asymmetry when co-op or asymmetric-faction.** For competitive PvP,
   rotational symmetry around the start ring is the cheapest fairness. For asymmetric factions, balance
   with liabilities (Wehrle) and shared vocabulary.
4. **Let players price imbalance:** snake draft for seats/slices, auctions for starting hexes, or
   Kingdomino-style "better pick now, worse order later".
5. **Measure it.** Compute a per-start "value within radius r" (sum of yield weights discounted by
   `move_cost` distance), report the spread, and reject maps above a threshold. Record metrics from
   real plays per template (Slay the Spire approach).
6. **Catch-up by default, gently:** reverse turn order for purchases (Power Grid), rat-tail head starts
   (Quacks), or hidden scoring. Avoid heavy rubber-banding that punishes good play.
7. **Reachability and dead-zone checks:** every objective reachable, no enclosed pockets unless
   intended; frontier generation guarantees at least one useful neighbour.

### 6.3 Drill-down layers as gameplay

- **World -> region (strategic layer):** movement, economy, territory, exploration (templates A, B, D,
  E, F). Keep turns fast and abstract; a hex is a unit of territory.
- **Town (management layer):** a worker-placement board: each building hex is an action space (market,
  smithy, tavern for rumours/quests). This is how Robinson Crusoe and many euros make a place playable.
- **Street / dungeon / room (tactical layer):** template C. Entering a dungeon hex drills into an
  Into-the-Breach-sized board with telegraphed enemies; results propagate back up (loot, cleared
  status, reputation). Mage Knight, Descent and Gloomhaven all do strategic -> tactical transitions.
- **Consistency rules:** the parent tile's attributes seed the child board (a `danger: 3` swamp
  produces a sub-board with more hazards; a `resource: iron` hill contains a mine room). Results
  write back to the parent (persistent, legacy-style).
- **Keep only one layer "hot" at a time** to avoid cognitive overload; the parent layer pauses or
  advances on a clock (for example one world round per tactical encounter).

### 6.4 Agent guardrails for rule generation

- Output a **GameSpec**: template id, parameters, attribute schema, objectives, AI opponent deck,
  end trigger, onboarding scenario. Validate it like tile designs.
- Cap complexity: at most 3 actions per turn and 1 rule-break per faction.
- Always generate: one-line goal, turn summary, "what the enemy will do next" display, and overlays
  for every rules-relevant attribute.
- Test via headless self-play (bots) before showing the user; reject specs where the first player wins
  far more than chance or games exceed the target length.

---

## Sources

- BoardGameGeek, Browse Board Game Mechanics: https://boardgamegeek.com/browse/boardgamemechanic
- Engelstein & Shalev, _Building Blocks of Tabletop Game Design_ (Routledge): https://www.routledge.com/Building-Blocks-of-Tabletop-Game-Design-An-Encyclopedia-of-Mechanisms/Engelstein-Shalev/p/book/9781032015811
- Meeple Mountain review of _Building Blocks_: https://www.meeplemountain.com/reviews/building-blocks-of-tabletop-game-design/
- Elias, Garfield, Gutschera, _Characteristics of Games_ (MIT Press): https://www.penguinrandomhouse.com/books/655769/characteristics-of-games-by-george-skaff-elias-richard-garfield-and-k-robert-gutschera-foreword-by-eric-zimmerman-and-peter-whitley/
- Keith Burgun, "Randomness and Game Design": https://www.gamedeveloper.com/design/randomness-and-game-design
- Catan (Wikipedia): https://en.wikipedia.org/wiki/Catan
- Catan board balance constraints: https://settlersboard.com/rules
- Twilight Imperium (Wikipedia): https://en.wikipedia.org/wiki/Twilight_Imperium
- TI4 Milty Draft tool: https://milty.shenanigans.be/
- Gloomhaven (Wikipedia): https://en.wikipedia.org/wiki/Gloomhaven
- Gloomhaven: Jaws of the Lion review (Board Game Quest): https://www.boardgamequest.com/gloomhaven-jaws-of-the-lion-review/
- Jaws of the Lion review (Meeple Mountain): https://www.meeplemountain.com/reviews/gloomhaven-jaws-of-the-lion/
- Terraforming Mars (Wikipedia): https://en.wikipedia.org/wiki/Terraforming_Mars_(board_game)
- Root (Wikipedia): https://en.wikipedia.org/wiki/Root_(board_game)
- Interview with Cole Wehrle (Elevation Games): https://www.elevation.games/blog/interview-with-cole-wehrle-designer-of-root-john-company-and-pax-pamir
- Spirit Island (Wikipedia): https://en.wikipedia.org/wiki/Spirit_Island_(board_game)
- Scythe (Wikipedia): https://en.wikipedia.org/wiki/Scythe_(board_game)
- Civilization: A New Dawn review (Meeple Mountain): https://www.meeplemountain.com/reviews/sid-meiers-civilization-a-new-dawn/
- Civilization: A New Dawn review (Tabletop Gaming): https://www.tabletopgaming.co.uk/reviews/sid-meiers-civilization-a-new-dawn-review/
- Tigris and Euphrates (Wikipedia): https://en.wikipedia.org/wiki/Tigris_and_Euphrates
- Hive (Wikipedia): https://en.wikipedia.org/wiki/Hive_(game)
- Zone of control (Wikipedia): https://en.wikipedia.org/wiki/Zone_of_control
- The Battle for Moscow rules (CRT/terrain example): https://www.grognard.com/bfm/game.html
- Carcassonne (Wikipedia): https://en.wikipedia.org/wiki/Carcassonne_(board_game)
- Kingdomino (Wikipedia): https://en.wikipedia.org/wiki/Kingdomino
- Kingdom Builder (Wikipedia): https://en.wikipedia.org/wiki/Kingdom_Builder
- Kingdom Builder review (The Board Game Family): https://www.theboardgamefamily.com/2012/12/kingdom-builder-board-game-review/
- Mage Knight Board Game (Wikipedia): https://en.wikipedia.org/wiki/Mage_Knight_Board_Game
- Mage Knight review (The Opinionated Gamers): https://opinionatedgamers.com/2012/04/25/mage-knight-review/
- Heat: Pedal to the Metal (Wikipedia): https://en.wikipedia.org/wiki/Heat:_Pedal_to_the_Metal
- Descent: Journeys in the Dark (Wikipedia): https://en.wikipedia.org/wiki/Descent:_Journeys_in_the_Dark
- Descent: Road to Legend app review (There Will Be Games): https://therewillbe.games/articles-boardgame-reviews/5582-descent-the-road-to-legend-app-in-review
- Robinson Crusoe review (TechRaptor): https://techraptor.net/tabletop/reviews/robinson-crusoe-board-game-review
- Arkham Horror Third Edition (Fantasy Flight): https://www.fantasyflightgames.com/en/products/arkham-horror-third-edition/
- Power Grid (Wikipedia): https://en.wikipedia.org/wiki/Power_Grid
- Ticket to Ride (Wikipedia): https://en.wikipedia.org/wiki/Ticket_to_Ride_(board_game)
- Cosmic Encounter (Wikipedia): https://en.wikipedia.org/wiki/Cosmic_Encounter
- Worker placement (Wikipedia): https://en.wikipedia.org/wiki/Worker_placement
- Deck-building game (Wikipedia): https://en.wikipedia.org/wiki/Deck-building_game
- Legacy game (Wikipedia): https://en.wikipedia.org/wiki/Legacy_game
- Social deduction game (Wikipedia): https://en.wikipedia.org/wiki/Social_deduction_game
- Blood on the Clocktower (Wikipedia): https://en.wikipedia.org/wiki/Blood_on_the_Clocktower
- Cartographers (Wikipedia): https://en.wikipedia.org/wiki/Cartographers_(board_game)
- The curious rise of the roll-and-write game: https://donteatthemeeples.substack.com/p/rise-of-roll-and-write-games
- Quacks of Quedlinburg review (Tabletop Bellhop): https://tabletopbellhop.com/game-reviews/quacks-of-quedlinburg/
- Catch-up mechanisms (The Thoughtful Gamer): https://thethoughtfulgamer.com/2017/03/28/catch-up-mechanisms/
- BGG compendium of runaway-leader solutions: https://boardgamegeek.com/geeklist/204332/a-compendium-of-solutions-to-the-rich-gets-richer
- 7 Ways to Reduce Downtime (Entro Games): https://entrogames.substack.com/p/7-ways-to-reduce-downtime-in-your
- Simultaneous action selection (Wikipedia): https://en.wikipedia.org/wiki/Simultaneous_action_selection
- Board game pacing (Brandon the Game Dev): https://brandonthegamedev.com/board-game-pacing-keeping-your-game-interesting/
- Into the Breach (Wikipedia): https://en.wikipedia.org/wiki/Into_the_Breach
- Into the Breach Design Postmortem (GDC Vault): https://gdcvault.com/play/1026333/-Into-the-Breach-Design
- Slay the Spire (Wikipedia): https://en.wikipedia.org/wiki/Slay_the_Spire
- Slay the Spire: Metrics Driven Design and Balance (GDC Vault): https://www.gdcvault.com/play/1025731/-Slay-the-Spire-Metrics
- Dicey Dungeons (Wikipedia): https://en.wikipedia.org/wiki/Dicey_Dungeons
- Wildfrost (Wikipedia): https://en.wikipedia.org/wiki/Wildfrost
- Board Game Arena FAQ: https://en.boardgamearena.com/doc/faq
