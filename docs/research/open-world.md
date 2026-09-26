# Open worlds, exploration and collection: research for a playable HexWorld

> Research for the HexWorld game-design doc. Topic: open-world and exploration/collection games, with
> **Pokémon** as the central case study, plus what procedural generation has learned the hard way.
> Numbers in brackets like [12] refer to the **Sources** list at the end. Claims without a bracket
> are widely known series facts (release history, basic mechanics) or our own design opinions,
> labelled as such.

---

## 0. TL;DR: ten things to steal

1. **A world is a graph of places with a reason to visit each one.** Pokémon's region reads as
   *town → route → town → dungeon → town*, and every node has a job: heal, shop, story beat,
   new encounters, gate, reward. HexWorld tiles need the same: a **role** as well as a biome.
2. **The collection is a map of the world.** The Pokédex works because species are tied to
   terrain, time and place (grass, water, caves, night) [28]. "Where does X live?" becomes "go there".
   Give every tile or biome a **native encounter table** so the collection *requires* exploring.
3. **Landmarks pull; occlusion teases.** Breath of the Wild uses big, medium and small "triangles"
   to hide and reveal, and "gravity" of points of interest to scatter players off the critical path
   [5][6][7]. A hex map can do this with tall sprites (landmarks) and fog.
4. **The map is a reward.** Towers (BotW), map fragments (Elden Ring) and radial Lightroot reveals
   (Tears of the Kingdom) make *uncovering* the map a satisfying act [6][10][11]. HexWorld already
   generates tiles on demand: **the act of generation can be the act of discovery.**
5. **Gates should be keys, not walls.** HMs, badges, Scarlet/Violet's mount upgrades, Terraria's
   pickaxe tiers and Outer Wilds' pure-knowledge gates are all lock-and-key graphs [14][27][28].
   An agent can generate those graphs if the engine validates that they are solvable.
6. **Open order needs scaling or signposting.** Scarlet/Violet let you take gyms in any order but
   fixed their levels, so the "free" order was really a hidden fixed order [28b][28c]. If players
   can go anywhere, either scale the challenge or show difficulty on the map.
7. **Oatmeal is a perception problem, not a quantity problem.** Kate Compton: mathematically unique
   ≠ perceptually unique [1]. No Man's Sky shipped 18 quintillion planets and was still called
   repetitive, then was rescued by *things to do* (bases, missions, multiplayer), not more planets [17].
8. **Generate history, then scatter its evidence.** Caves of Qud generates sultan biographies and
   then places them in the world as shrines and texts the player finds in any order; the player's
   own pattern-seeking does the rest [20]. That is the right model for lore-consistent agents.
9. **LLM NPCs work best inside a structure.** Generative agents show that memory, reflection and
   planning give believable behaviour [29]; the shipped games that land (1001 Nights, Hidden Door,
   Whispers from the Star) wrap the model in a tight game frame [31][34]. Structure first, dialogue second.
10. **Juice is how "generated" becomes "alive".** Swink's game feel = real-time control +
    simulated space + polish [40]; "Juice it or lose it" and "The Art of Screenshake" show that
    feedback, not features, is what makes a thing feel great [38][39]. HexWorld's event stream is
    ideal for this: every state change can be animated.

---

## 1. Pokémon: the case study

### 1.1 The collection fantasy and its social engine

Pokémon's creator Satoshi Tajiri grew up collecting insects (his classmates called him "Dr. Bug")
and has said that seeing two Game Boys connected by a link cable was what made him imagine
creatures moving between players [28e][28f]. Two design facts follow directly:

- **Collection is the goal**: "obtain at least one member of each of the different species…,
  thus completing a fictional encyclopedia… known as a Pokédex" [28a].
- **Collection is social by construction**: version exclusives mean no one player can finish alone;
  trading "is considered an important aspect of Pokémon" [28a]. The social act is baked into the
  collection maths, not bolted on.

Why it works psychologically (design interpretation): a Pokédex is a **visible, finite, partially
filled set**. Empty slots are questions ("what's number 132? where does it live?"), and each answer
is found *somewhere in the world*. The collection turns the map into a treasure map.

### 1.2 Region anatomy: towns, routes, dungeons and the gym spine

A classic region (Kanto, Johto, Hoenn, Sinnoh) is a hand-authored graph with clear node types:

| Node type | Job in the loop | Typical content |
|---|---|---|
| **Town / city** | Safety, restock, story, a gym | Pokémon Center (heal), Mart (shop), houses with NPC hints and gifts, the gym |
| **Route** | Travel, encounters, trainer fights | Tall grass, water, ledges (one-way), trainers who battle on sight, items |
| **Dungeon** (cave, forest, tower, villain base) | Tension and attrition | No healing, darkness or puzzles, denser encounters, a boss or legendary |
| **Gate / barrier** | Pacing | A tree to Cut, water to Surf, a boulder for Strength, an NPC blocking the road |
| **Landmark event** | Memory | A legendary in a cave, the villain team's hideout, the rival fight on a bridge |

The **gym spine** is the progression backbone: eight gyms, each themed on one type, each giving a
badge, then the Elite Four and Champion [28a]. Later games varied it (Alola's island trials in
Sun/Moon; Sword/Shield's Champion Cup tournament [28a]), but the shape survives: *a readable
sequence of increasingly hard, themed set-piece fights, each unlocking the next stretch of map.*

The pattern to note is the **rhythm**: a town is a breath in, a route or dungeon is a breath out.
Tension (HP and PP draining, no heals) builds on the route and releases at the next Pokémon Center.
This alternation is the cheapest pacing tool in game design, and a hex map can express it directly:
"safe" tiles and "wild" tiles in a deliberate ratio along the path.

### 1.3 Gating: HMs, badges and the level curve

- **HM field moves** (Cut, Surf, Strength, Flash, Fly, later Rock Smash, Waterfall, and others)
  were both battle moves and overworld keys, and each generally required a specific badge to use
  outside battle. That turns the gym spine into a **lock-and-key graph over the map**: badge N
  unlocks Surf, Surf unlocks the sea routes, the sea routes lead to gym N+1.
- The cost was well known: HM moves took up party move slots, forcing "HM slave" Pokémon. From
  Sun/Moon onward, HMs were replaced by summonable ride Pokémon, and later games moved storage and
  traversal out of the party altogether (e.g. the PC box accessible anywhere from Let's Go on
  [28a]). **Lesson:** keys should not tax the core loop.
- **The level curve is the invisible gate.** Wild levels on each route and the gym leaders' levels
  rise along the intended path. The player *can* wander, but under-levelled wandering hurts. That
  is a soft gate that also creates the grind-or-be-clever choice (use type advantage instead of levels).

### 1.4 Encounter tables per terrain

Wild encounters are **attached to terrain types**: walking in tall grass, cave floors, surfing on
water, and fishing (with rods of increasing quality giving access to different tables) each roll
against the area's own list, and later generations added time-of-day and weather variation [28a].
Design consequences:

- **Terrain is legible.** The player learns "grass = danger and opportunity" instantly. The map
  *tells you* where encounters are.
- **Rarity creates return trips.** A 5% slot on Route 8 is a reason to come back.
- **Areas are distinguishable by their fauna.** Two green routes feel different because different
  things live there, which is exactly the "perceptual differentiation" Compton describes [1].
- **Visible encounters** arrived in the 3D era: Let's Go and Sword/Shield's Wild Area show wild
  Pokémon in the world, and Legends: Arceus lets you sneak up and catch them without battling [28g].
  Seeing the creature before committing turns a random roll into a decision (approach, avoid, stalk).

### 1.5 The type chart: rock-paper-scissors with depth

Eighteen types in the modern games; a Pokémon takes double damage from types it is weak to and half
from types it resists [28a]. Why it is so durable:

- **Readable at a glance** (fire beats grass) yet **deep in combination** (dual types, 4× weaknesses,
  immunities).
- **It links combat to exploration**: gym 3 is electric, so go catch a ground type, which lives in
  the cave on Route 9. The type chart is the reason team-building *requires* travel.
- **It makes the gym spine a series of puzzles** rather than a stat check, which is also what
  softens the level-curve gate.

For HexWorld the transferable idea is a **small, legible affinity chart** generated per world (the
super planner could invent "tide beats ember, ember beats bramble…" to fit the lore) that ties
*what you collect* to *where you must go next*.

### 1.6 Overworld ↔ interior transitions (the drill-down precedent)

Classic Pokémon maps are **separate screens stitched by doors**: step onto a door tile, fade to black,
load the interior map (often much larger inside than outside), step on the mat to return.
Caves and towers are multi-floor maps joined by ladders. Relevant properties:

- **Scale changes freely across a door.** Interiors are not bound to the exterior footprint; a
  small house can hold a big room. Players accept this without complaint.
- **The fade is a promise.** A short transition tells the player "new space, new rules" (no
  encounters indoors, healing here, a puzzle there).
- **Return is instant and exact.** You come back out where you went in. Spatial memory is preserved.

This is exactly HexWorld's drill-down. The lesson is that **the transition itself should be quick,
consistent and reversible**, and that the child space can have different rules (safe, dangerous,
puzzle) signalled on entry.

### 1.7 The 3D and open-world era

- **Legends: Arceus (2022)**: a hub (Jubilife Village) plus five large open areas split by biome,
  not a seamless open world; overworld catching without battles; stealth; oversized "alpha"
  Pokémon; **research tasks per species** (catch N, see it use move X, defeat N), with **Pokédex
  research as the main progression metric** [28g]. The Verge called it "the biggest overhaul to the
  Pokémon formula since the series debuted" [28g]. Key lesson: *make the collection verbs richer*
  (observe, sneak, catch, battle, feed) rather than just "fight, then throw a ball".
- **Scarlet/Violet (2022)**: a true open world with three parallel story lines (8 gyms, 5 Titan
  Pokémon, 5 Team Star bases) that can be done in any order; Titans upgrade the legendary mount's
  traversal (dash, swim, jump, glide, climb), a modern HM equivalent; "Let's Go" auto-battles let
  your lead Pokémon fight weak wilds in the overworld [28h]. The big design flaw: **no level
  scaling**, so the "any order" freedom hid a de facto fixed order, and the suggested levels were
  not shown on the map, making it easy to wander into walls or get over-levelled [28b][28c]. It
  received the lowest Metacritic scores of the mainline series, mostly for performance, while still
  selling over 10 million copies in three days [28h].
- **Legends: Z-A (Oct 2025)**: a single city (Lumiose) with "Wild Zones" cordoned off inside it,
  a nightly ranked battle tournament (the Z-A Royale) as the progression spine, and **real-time
  battles** replacing turn-based combat [28a][28i]. Critics praised the battles but found the city
  visually restrictive [28i]. Interesting for HexWorld: a whole game set in *one drilled-in town*.

### 1.8 What Pokémon teaches HexWorld

- **Node roles matter more than terrain.** Every tile needs a job in the loop.
- **Encounters belong to terrain + place.** Encounter tables are world content, not engine content.
- **A visible, finite collection** is the strongest long-term exploration motivator known.
- **Gates = keys the player earns**, spread across the map so earning one opens a new region.
- **If order is open, the world must say how dangerous each place is**, or scale to the player.

---

## 2. Other open-world and exploration games

### 2.1 Zelda: Breath of the Wild / Tears of the Kingdom

- **The problem they solved**: early heat maps showed player flow "clearly concentrated on a few
  discrete paths" [5]. Nintendo's fix was spatial composition, not quest markers.
- **Triangles in three sizes**: large ones are landmarks visible from far away; medium ones block
  the view so players must climb or go around; small ones "serve the tempo" [6][7][8]. Occlusion
  followed by reveal is the core rhythm of discovery ("what's behind that hill?").
- **Gravity**: smaller points of interest placed between towers pull players sideways, producing
  individual, dispersed routes [4][5]. Key sites sit in sunken bowls because going down is easier
  than going up, so terrain itself guides you [4].
- **Towers** reveal a region of the map and serve as vantage points; they were re-placed during
  development to encourage side-tracking rather than linear tower hopping [6].
- **Chemistry engine / multiplicative design**: simple rules for elements (fire, ice, wind,
  electricity) and objects that react to the player and to each other, so many solutions exist
  to one situation [9]. Director Hidemaro Fujibayashi framed it as moving from "additive" to
  "multiplicative" design [9].
- **Tears of the Kingdom** stacks **three map layers** (Sky, Surface, Depths) of similar size. Every
  surface Shrine has a Lightroot directly beneath it in the Depths, surface water corresponds to
  walls below, and Lightroots reveal the Depths map *radially* around themselves rather than by
  region [10a][10b]. This is the closest AAA precedent for **consistent parent/child layers**: the
  lower layer is a mirror or inversion of the upper, so knowledge of one helps navigate the other.

### 2.2 Elden Ring

- Miyazaki wanted variety in how exploration feels: exploring blind before you have a region's map
  fragment versus exploring with a rough idea after. Map fragments deliberately "do not have all
  the details", so they don't spoil discovery, and they are optional [11].
- Two content scales co-exist: the **open field** (sparse, fast on horseback, dotted with small
  caves, catacombs and ruins) and **legacy dungeons** (dense, hand-crafted castles). That mix of
  "wide and light" with "deep and dense" maps well onto HexWorld's world tiles vs drilled-in interiors.
- Story is fragmentary so players "piece them together or imagine what happened" [11]: the lore
  lives in item descriptions and places, not cutscenes.

### 2.3 Minecraft and Terraria: procedural worlds with material progression

- **Minecraft** biomes are chosen from noise fields for temperature, humidity, continentalness,
  erosion, weirdness and depth; each biome has ideal values and the closest match wins [26a][26b].
  Progression is **material tiers** (wood → stone → iron → diamond) that unlock deeper mining and
  then other dimensions. The world is fully procedural; the *progression* is fully authored.
- **Terraria** is the sharpest example of **depth as progression**: Surface → Underground → Cavern →
  Underworld [27a]. Biomes stack vertically (the underground jungle sits under the surface jungle
  [27a]). Bosses gate materials and NPCs (e.g. defeating Skeletron grants access to the Mechanic;
  evil-biome boss drops craft the pickaxe needed to mine Hellstone) [27b]. Killing the Wall of Flesh
  in the Underworld flips the world to **Hardmode**, carving new Hallow and evil biome stripes across
  every layer [27c]. **The world itself changes in response to progress.**
- Lesson: procedural terrain is fine as long as **authored progression rules** decide what is
  found where and what unlocks what. "Deeper = harder = richer" is instantly legible.

### 2.4 Outer Wilds: knowledge is the only key

- The entire solar system is open from the start; the only gate is what you know [13][14].
  The talk explicitly lists what Outer Wilds does *not* reward: no XP, abilities, items, upgrades,
  collectibles or unlocked areas; **knowledge is the only reward** [14].
- The loop: *inspire curiosity → player explores → reward with knowledge → more curiosity* [14].
- Big visible events hook curiosity better than text: cyclones, collapsing planets, the sun going
  supernova; "show, don't tell" [14].
- Every piece of found text points backwards and forwards: where the story thread started and
  where to go next [14]. The **ship log** records only what the player has certainly learned, so
  keeping track is never the hard part [14].
- A learned failure: an early meteor-crash hook fell flat because players were not yet familiar
  with the village, so "they have no reason to be more curious" [13]. **Curiosity needs a baseline
  of familiarity**: first make a place known, then disturb it.

### 2.5 Skyrim: radiant quests and their limits

Skyrim's Radiant system assembles quests from components (location, enemy type, reward), prefers
**locations the player has not visited yet**, and keeps roughly a dozen candidate locations per quest
type [16]. UESP's own summary is the verdict: it "cannot create large, complicated, or particularly
interesting quests" but can produce near-infinite ones cheaply [16]. The failure mode is "go to X,
kill/fetch Y, return", repeated.
**Lesson:** template quests are useful as *exploration pointers* (they send you somewhere new) but
not as *content*. HexWorld's advantage is that an agent can give each instance a specific *why*.

### 2.6 No Man's Sky: procedural universe, redeemed by verbs

At launch (2016) critics praised the technology but found the play repetitive; one line that stuck:
you can generate quintillions of unique planets but not quintillions of unique things to do [17].
Kate Compton's "procedural oatmeal" was applied to it directly [17][44]. The recovery came through
free updates that added **things to do and people to do them with**: Foundation (bases, freighters,
modes, 2016), Atlas Rises (story missions, co-op, 2017), NEXT (full multiplayer, third-person, 2018),
Beyond (2019), later Companions and Expeditions, culminating in The Game Awards' Best Ongoing Game in
2020 [17]. **Lesson:** variety in *space* is not variety in *play*. Give tiles verbs.

### 2.7 Stardew Valley: the cozy loop

A daily loop (tend the farm → forage/fish/mine → talk to villagers → sleep) wrapped in a seasonal
loop. The Community Center **bundles** are a collection checklist tied to place and season (spring
forage, winter-only beach finds, fish from specific waters), and completing them unlocks the
greenhouse, minecarts, the bus to the desert and more [19]. It is Pokémon's "collection as a map of
the world" in a non-combat form: bundles send you to every corner of the valley across the calendar.

### 2.8 Dwarf Fortress and Caves of Qud: procedural history

- **Dwarf Fortress** simulates world history (civilisations, wars, figures) before play begins, and
  its dwarves act autonomously, which is where its famous emergent stories come from [21a][21b].
- **Caves of Qud** deliberately does *not* simulate history. It generates five sultans' lives as
  events parameterised by existing entities, then **rationalises them after the fact**; each event
  becomes a short "gospel" text, and gospels appear on shrines, paintings and engravings generated
  as the player explores, or are traded with NPCs; the player's journal sorts them chronologically
  [20]. Each sultan gets a "domain" (glass, ice, stars, might…) to give a mythic personality, and the
  designers lean on **apophenia**, the player's own pattern-making, for coherence [20]. The world map
  is static and handcrafted while the areas are procedural: a **hybrid** [20].
- **Lesson for agents:** generate a compact *history* first (a few named figures, factions, events),
  then let tile agents embed **evidence** of it (ruins, statues, place names, NPC rumours). Each
  tile then carries a fragment of a larger story the player assembles.

### 2.9 Roguelikes: meaningful route choices

- **Spelunky**: a 4×4 grid of rooms, a guaranteed solution path is laid first from top to bottom,
  then each room is filled from hand-made templates matching its required exits, with random
  variation on top [22a][22b]. *Guarantee the critical path structurally, then decorate.*
- **Slay the Spire**: each act is 17 floors of up to 6 nodes; fixed floors (first floor easy fights,
  floor 9 all treasure, floor 15 all rest sites, then the boss) frame the randomness; other nodes
  roll from weighted odds (roughly 53% normal fights, 22% unknown, 12% rest, 8% elite, 5% shop), and
  unknown rooms use a pity system [23]. The map is **fully visible**, so the pleasure is *planning a
  route*: risk (elites for relics) versus recovery (rest sites). Choice needs **information**.
- **Hades**: narrative is delivered through a large pool of pre-written events chosen by run state
  (e.g. low health), with weighting, so "the game is paying attention" [24]. Reactivity makes
  repetition feel personal.

### 2.10 Civilization: fog of war and interesting decisions

- Fog of war hides unexplored land and darkens tiles without current vision [43]: the whole map is a
  promise. Early turns are pure exploration: every scout step can reveal a hut, a wonder, a rival.
- Sid Meier's "a game is a series of interesting decisions": good decisions involve trade-offs, are
  **situational**, let players express a style, need enough information, have lasting consequences,
  and must be **acknowledged** by the game ("the worst thing you can do is just move on") [25].
- "One more turn" (design interpretation) comes from **overlapping short timers**: a city finishes
  next turn, a scout is one step from the fog edge, research completes in two. There is always an
  imminent payoff. HexWorld's turn/board mode should stagger payoffs the same way.

---

## 3. Principles

### 3.1 Why players explore

- **Curiosity is a question the world makes you ask** [14]. Visible anomalies (a smoking mountain,
  a tower, a ruin half-hidden by a hill) ask questions; text rarely does.
- **Landmarks and occlusion** [5][6]. A landmark says "there is something there"; occlusion says "and
  you can't see it all yet".
- **Collection sets** (Pokédex, bundles) turn curiosity into a to-do list with gaps [19][28a].
- **Familiarity before surprise** [13]. Players must know the baseline before a change is interesting.
- **Reward at the end of the look.** Every "what's over there?" must resolve into *something*: an
  encounter, an item, a vista, a lore fragment, a shortcut. An empty answer trains players to stop asking.

### 3.2 Map legibility and discovery

- **Fog of war** frames the unknown [43]; **reveal mechanics** make revealing feel earned: towers
  (region reveal), map fragments (partial reveal, details left for discovery) [11], Lightroots
  (radial reveal) [10b].
- **The map as trophy.** A filled map is a record of your journey. Show explored vs unexplored
  clearly, and show *what you found* on it (icons for towns, dungeons, rare encounters).
- **Show danger on the map** when order is open. Scarlet/Violet's lack of visible level guidance is
  a cautionary tale [28c]. Slay the Spire shows everything and the fun is planning [23].
- **Rule of thumb** (design opinion): the player should always see at least *one* unexplored thing
  worth walking to from wherever they stand.

### 3.3 Pacing and progression gates

- **Hard gates** (need Surf, need the pickaxe, need knowledge) structure *where* you can go.
- **Soft gates** (level curve, danger, resource drain) structure *when* it is wise to go.
- **Tension/release rhythm**: dungeon → town, run → hub, night → morning.
- **Parallel spines** (Scarlet/Violet's three stories) add freedom but need scaling or signposting [28b].
- **Keys that change traversal** (Surf, glide, climb) are the most satisfying gates because the
  whole map re-reads after you get them: old places now have new paths.

### 3.4 Oatmeal: making generated content meaningful

Kate Compton's framing [1]: define the artifact, list what makes good examples good, and list the
deal-breakers. Mathematically unique outputs can be perceptually identical ("10,000 bowls of
oatmeal"). **Perceptual differentiation** (this feels different from the last) is an easier bar
than **perceptual uniqueness** (this is memorable). She notes that people respond to **evidence of
process and forces**, the sense of an alive world behind the content [1].

Practical anti-oatmeal levers:
- **Purpose over variety**: each tile gets a role (see 4.4). Variety without purpose is oatmeal.
- **Evidence of forces**: rivers flow downhill to the sea; towns sit at river crossings; ruins sit
  where the old empire's history says it fell. Coherence reads as meaning.
- **Contrast and rarity**: a world of 30 good tiles and 3 extraordinary ones beats 33 medium tiles.
  Rarity has to be designed in.
- **Verbs per place** (No Man's Sky's lesson [17]): a tile you can *do* something on beats a prettier one.
- **Hybrids**: authored structure + generated fill (Spelunky's path + templates [22a], Qud's static
  map + procedural areas [20], Minecraft's procedural terrain + authored progression [26a]).

### 3.5 Interior/overworld scale transitions

Precedents: Pokémon's door fades (§1.6); Elden Ring's field vs legacy dungeons (§2.2); Terraria's
depth layers (§2.3); Tears of the Kingdom's mirrored layers (§2.1). Principles:
- The child space **inherits identity** from the parent (a jungle's cave is a jungle cave; a Shrine
  above implies a Lightroot below [10a]).
- The child can have **its own rules** (safe, dangerous, puzzle) signalled on entry.
- **Transitions are fast and reversible**; returning puts you back exactly where you were.
- Depth is **a difficulty and reward axis**: deeper usually means denser, stranger and richer.

### 3.6 NPCs and quests, including LLMs (2023-2026)

- **Generative Agents** (Park et al., 2023): 25 LLM agents in a Sims-like town ("Smallville") with a
  memory stream, reflection and planning; from one seeded intention (host a Valentine's Day party)
  they spread invitations, arranged dates and turned up at the right time. Ablations showed that
  observation, planning and reflection each matter for believability [29].
- **AI Dungeon** (2019, GPT-2 then GPT-3) proved the appetite for open-ended AI adventures and also
  the core weakness: coherence drifts without structure [30].
- **Hidden Door** (early access Aug 2025): an AI narrator in the style of a tabletop game master,
  inside licensed story worlds, with collectible cards unlocked by finishing stories that carry over
  between stories [31a][31b]. A structured, collectible frame around generation.
- **Ubisoft NEO NPCs** (GDC 2024, with Inworld and Nvidia): writers authored each NPC's backstory,
  personality, agenda and emotions; demos covered relationship-building, reacting to game events and
  planning a heist together; Ubisoft stressed it was a prototype with no specific game attached [32].
- **Shipped LLM games**: 1001 Nights (story told to a king becomes items in the world: "language as
  reality") [34b], Whispers from the Star (Aug 2025, conversation with a stranded astronaut) [34a].
  Commentators note that the successful ones use the LLM as the core of a *constrained* game idea.
- **LLM content pipelines in research**: Word2World generates a story, extracts characters, tiles
  and goals, then generates a playable 2D tile world in steps [35]; a 2026 "World-Gen to
  Quest-Line" pipeline chains world → NPCs → player → campaign → quests as JSON with enforced
  schemas and reports coherent output without degradation as complexity rises [36]; a 2024 study
  generating side quests as code found models varied in code validity vs narrative quality, and
  that validation was still needed [37]. **This is essentially HexWorld's architecture**: staged
  agents, structured outputs, validation tools.

Takeaways for NPCs/quests:
- **Anchor every quest to map facts** (a named tile, an encounter, an item, a gate). Radiant's
  lesson is that "go to X" is fine as long as X is *interesting* and the *why* is specific [16].
- **Keep persistent state small and structured** (who, wants what, knows what, feels how) and let
  the LLM render it into dialogue. Generative Agents shows memory + reflection is what creates
  believability [29].
- **Reactivity beats length** [24]: an NPC who mentions the thing you just did is worth ten who
  ramble.

### 3.7 Juice and game feel

- **Swink**: game feel is "real-time control of virtual objects in a simulated space, with
  interactions emphasised by polish" [40].
- **Juice it or lose it** (Jonasson & Purho, GDC Europe 2012): a plain Breakout clone becomes
  delightful through tweening, squash and stretch, particles, sound, screen shake and small surprises;
  none of it changes the rules [38].
- **The Art of Screenshake** (Nijman, 2013): around 30 tricks in 25 minutes turning a flat shooter
  into one that feels violent and immediate: hit-pause, knockback, shake, muzzle flash, bigger bullets, lingering
  debris, camera lead [39].
- There is a known counter-argument that juice can mask weak design ("resist the urge") [41]:
  juice amplifies a good loop; it cannot replace one.

---

## 4. Concrete takeaways for HexWorld

### 4.1 What the player does moment to moment: three modes

HexWorld's super planner already designs "game-specific tile attributes". The mode determines which
attributes matter. Recommendation: build **Adventure** first (it exercises drill-down), keep
**Board** as the fast, shareable mode, and let **Sandbox** fall out of the tooling.

**A. Adventure mode (Pokémon / Zelda-like)**. *You are a character on the map.*
- Moment to moment: move tile to tile (a hop with a tiny arc and landing dust); each step may
  trigger the tile's **encounter table** (a creature, a traveller, a hazard, a find). Towns heal and
  trade; wild tiles drain and reward.
- Collection: a **world-specific Compendium** (the "dex") generated by the super planner: 20-40
  creatures/artifacts native to specific biomes, layers, times or weather. Empty slots show a
  silhouette and a *hint of where* ("glimmers in deep water at night").
- Progression: a **spine of 4-8 set pieces** (gyms, shrines, lairs) and a **key graph** (a raft
  for rivers, a lantern for caves, a charm to pass the watchers at the pass).
- Drill-down: entering a town, dungeon or building **is** drilling into its tile.

**B. Board-game mode (Civ / Catan / Slay-the-Spire-like)**. *You command pieces on the map.*
- Turn-based: move scouts into fog, claim tiles, harvest attributes (the resources the planner
  defined), resolve events. The map is fully legible and the fun is planning.
- "One more turn" through **staggered timers**: something always completes next turn.
- Drill-down for tactical resolution: a siege drills into the town tile and plays out on its child map.

**C. Builder/sandbox mode (Minecraft / Stardew-like)**. *You change the world.*
- Describe changes in natural language ("a lighthouse on that cape"); agents regenerate tiles
  consistently with neighbours. Cozy loop: seasons, commissions from NPCs, a bundles-style
  collection board [19].
- This is also the **authoring tool** for the other two modes.

### 4.2 How drill-down layers map onto game structure

| Layer | A tile is… | Play role (adventure) | Typical gates | Encounters / content |
|---|---|---|---|---|
| 0 World | a region | Overworld travel, choose the next destination | Traversal keys (water, mountains, cursed forest), region danger level | Rare roaming legendaries, weather, caravans |
| 1 Region | a town, forest, lake, dungeon entrance | Routes and exploration, the main encounter layer | Local obstacles (bridge out, sealed gate) | Biome encounter tables, trainers/rivals, items, lore evidence |
| 2 Town / dungeon | a district, a street, a cave section | Towns: safe hub (heal, shop, quests). Dungeons: tension, attrition, puzzle | Locked doors, darkness, puzzles | Towns: NPCs and quest givers. Dungeons: denser encounters, a boss |
| 3 Building / chamber | a room zone | Interiors: dialogue, shops, secrets, the boss room | Keys, knowledge (passwords, clues) | NPCs, containers, clues, the set-piece fight |
| 4+ Room detail | a corner, an object | Search and inspect (optional, cheap models) | None | Flavour, hidden collectibles, lore fragments |

Rules that make this feel right:
- **Depth is an axis of danger and reward** (Terraria [27a]): deeper = rarer encounters, better loot.
- **Children mirror parents** (Tears of the Kingdom [10a]): a parent tile's attributes (a "shrine"
  marker, a river connector, a "haunted" flag) *must* appear in the child map. HexWorld's seed
  layout already guarantees ground and connectors; extend it to **game attributes**: a parent's
  `has_dungeon` becomes a guaranteed entrance tile in the child.
- **Not every tile needs to be drillable in play.** Mark drillable tiles visually (a door glint, an
  entrance sprite) so drilling is a *choice with an expected payoff*, not a lottery. Elden Ring
  makes caves and catacombs visible as entrances; Pokémon makes doors obvious.
- **Door-fade grammar**: drilling is a fast zoom (see 4.6), and a small banner states the child's
  rules ("Safe haven", "Wild: encounters", "Dark: lantern needed").

### 4.3 How agents generate encounters, quests, NPCs and gates consistently

**World bible first (super planner).** Before tiles, generate a compact, structured bible:
factions, 3-5 historical figures with "domains" (Qud-style [20]), the affinity chart (§1.5), the
compendium roster with habitats, the progression spine (ordered set pieces), and the **key graph**.
Everything downstream is validated against it, as HexWorld's `submit_*` tools already do for art.

**Encounter tables (tile agents).** Each tile stores `encounters: [{id, weight, condition}]`, drawn
only from the roster entries whose habitat matches the tile's biome, layer and neighbours. The
engine validates:
- every compendium entry is obtainable in at least one reachable tile;
- rare entries are rare (weight caps) and located "somewhere interesting" (near a landmark);
- difficulty rises along the spine or with depth (a soft level curve).

**Progression gates (planner + engine validator).** Represent gates as a lock-and-key graph:
`lock(tile, requires=key)`, `key(item/ability/knowledge, found_at=tile)`. The engine runs a
reachability check (can the spine be completed from the start tile with keys found in order?),
exactly as Spelunky guarantees its path before decorating [22a]. Prefer **traversal keys** that make
the map re-read (raft, glider, lantern), and avoid keys that tax the core loop (HM slaves).
If the order is open, **show danger on the map** (a skull rating on tiles) or scale set pieces to
the player; don't repeat Scarlet/Violet [28b][28c].

**Quests (director agent).** Grammar skeleton + LLM flesh:
- Skeleton types: *fetch*, *escort*, *hunt*, *deliver*, *investigate*, *restore*. Each must bind to
  **real map facts**: a named tile, a compendium entry, an existing NPC, a gate.
- The "why" comes from the world bible (a faction's need, a historical grudge), which is what
  Radiant quests lack [16].
- Prefer quests that **point into the fog** (Radiant's one good idea: send the player somewhere
  unvisited [16]) and that **end with a map change** (a bridge rebuilt, a town grows a market).
- Staged, schema-validated generation is what the recent research converges on [36][37].

**NPCs (per-town agents, cheap models deeper down).**
- State: `{name, role, wants, knows[], opinion_of_player, schedule}`, small and structured.
  Knowledge is scoped: a fisherman knows the lake's rare fish and a rumour about the next region,
  which makes NPCs **hint-givers for the collection and the key graph** (Outer Wilds-style
  "where to go next" pointers [14]).
- Reactivity over verbosity: NPCs reference recent player events (Hades [24]).
- Generative Agents-style memory and reflection [29] for a few important NPCs only; background
  NPCs can be template-plus-flavour.

**Lore evidence (tile agents).** Each tile may carry a `lore_fragment` referencing the bible
(a statue of the Glass Sultan, a battlefield where faction A broke faction B). Fragments go into a
**journal** sorted by the bible's chronology, as in Qud [20]. The player assembles the history.

### 4.4 Anti-oatmeal checklist: every tile has a reason to exist

For each generated tile, the planner or reviewer should be able to answer *yes* to at least one:
- **Role**: is it a hub, route, dungeon, landmark, gate, resource or vista?
- **Verb**: can the player *do* something here (encounter, harvest, talk, solve, rest, drill in)?
- **Evidence**: does it show a force or history (erosion, a road worn by trade, a ruin from the bible)?
- **Pointer**: can you see something interesting *from* here that makes you want to move?
- **Uniqueness budget**: per region, 1-2 tiles are allowed to be extraordinary (the "legacy dungeon",
  the giant tree); the rest support them. Rarity is designed.

And world-level checks:
- The **landmark density** keeps an unexplored point of interest visible from anywhere (BotW
  gravity [4][5]).
- **Occlusion**: tall sprites (mountains, towers, forests) block sight lines so reveals happen.
- **Contrast** between neighbouring regions (cold/hot, safe/wild, busy/empty).
- **No dead ends without payoff**: a cul-de-sac tile holds a reward.

### 4.5 Collection and meta-progression

- A per-world **Compendium** (creatures, relics, recipes or people, whatever fits the prompt) with
  habitats, so completion requires visiting every biome and depth.
- **Research-task depth** (Legends: Arceus [28g]): per entry, several verbs (seen, caught, observed
  behaviour, found in a rare variant). Richer than a binary "caught".
- **Cross-world social layer**: HexWorld worlds are shareable, so entries or cards could carry over
  between worlds (Hidden Door's card collection is a precedent [31a]), and trading between players is
  Pokémon's original social engine [28e].

### 4.6 Making it slick

HexWorld's UI is already driven by an event stream, so every event can have a feel spec:
- **Movement**: hop tweens with ease-out, a small squash on landing, dust particles, a footstep sound
  that varies by the tile's material (grass, sand, stone, water splash).
- **Encounter**: a quick flash or screen swirl, a hit-pause, the creature sprite popping in with
  overshoot (the Pokémon transition is iconic for a reason).
- **Discovery**: fog peeling back with a soft radial reveal (Lightroot-style [10b]); a chime and a
  map icon stamping onto the tile; a "New!" count ticking up in the compendium.
- **Generation as spectacle**: tiles being built can "grow" in (ground first, then sprites rising),
  so waiting on agents feels like watching the world form rather than loading.
- **Drill-down zoom**: a continuous camera zoom into the tile, parent detail cross-fading into the
  child grid, under ~400 ms of perceived transition (our target, not a sourced number); zooming out
  reverses it exactly.
- **Acknowledge every decision** (Meier's "worst thing is to just move on" [25]): gates opening
  get a thunk and dust, quests completing change something visible on the map.
- Keep juice **proportional**: big effects for big moments; tiny, fast ones for frequent actions [38][39][41].

### 4.7 Risks to plan for

- **Latency vs discovery.** On-demand generation must stay ahead of the player: pre-generate the
  ring of tiles just beyond the fog edge and the child map of the tile under the cursor.
- **Coherence drift across layers.** Validate children against parents (the bible, seed layout,
  inherited attributes); this is HexWorld's core strength and should be enforced by tools, not prompts.
- **Open order without scaling** (Scarlet/Violet): decide early between scaling and signposting.
- **LLM verbosity.** Cap dialogue length; prefer one sharp line and a map-changing consequence.
- **Oatmeal at depth.** Deep layers are where cheaper models and less context live; use templates
  and strict roles there, and reserve open-ended generation for landmarks.

---

## Sources

**Procedural generation and oatmeal**
- [1] Kate Compton, "So you want to build a generator…": https://galaxykate0.tumblr.com/post/139774965871/so-you-want-to-build-a-generator
- [44] Vice, "'No Man's Sky' Is Like 18 Quintillion Bowls of Oatmeal": https://www.vice.com/en/article/nz7d8q/no-mans-sky-review

**Zelda**
- [4] Game Developer, "Breath of the Wild Open World Analysis: Gravity to go Forward": https://www.gamedeveloper.com/design/breath-of-the-wild-open-world-analysis-gravity-to-go-forward
- [5] Radiator Blog, "Open world level design: spatial composition and flow in Breath of the Wild" (CEDEC 2017 summary): https://www.blog.radiator.debacle.us/2017/10/open-world-level-design-spatial.html
- [6] Game Developer, "5 design lessons learned from The Legend of Zelda: Breath of the Wild": https://www.gamedeveloper.com/design/5-design-lessons-learned-from-i-the-legend-of-zelda-breath-of-the-wild-i-
- [7] Nintendo Life, "Zelda: Breath Of The Wild's Ingenious Design Is All About Triangles, Apparently": https://www.nintendolife.com/news/2017/10/zelda_breath_of_the_wilds_ingenious_design_is_all_about_triangles_apparently
- [8] Translation of Nintendo's CEDEC 2017 talks (Matt Walker, inline image version): https://gist.github.com/idbrii/e39fe96279aa1670319bfa521d907399
- [9] Engadget, "'Breath of the Wild' creators explain how they bucked tradition" (GDC 2017): https://www.engadget.com/2017-03-12-breath-of-the-wild-gdc-talk.html ; Zelda Universe, "Freedom in Breath of the Wild": https://zeldauniverse.net/features/ocarinas-image-freedom-in-breath-of-the-wild/ ; Game Developer video: https://www.gamedeveloper.com/design/video-designing-i-zelda-breath-of-the-wild-i-s-unconventional-mechanics
- [10a] Automaton, "Tears of the Kingdom's Surface and Depths share a deep connection": https://automaton-media.com/en/news/20230609-19405/
- [10b] Stamen, "Cartographers Play Video Games: A Review of the Map in Tears of the Kingdom": https://stamen.com/cartographers-play-video-games-a-review-of-the-map-in-the-legend-of-zelda-tears-of-the-kingdom/

**Elden Ring**
- [11] Frontline, "Elden Ring Release Interview with Director Miyazaki (Part 1/2)": https://www.frontlinejp.net/2022/03/05/elden-ring-release-interview-with-director-miyazaki-part-1/

**Outer Wilds**
- [13] Game Developer, "Live, die, repeat: How Outer Wilds piques curiosity…": https://www.gamedeveloper.com/design/live-die-repeat-how-i-outer-wilds-i-piques-curiosity-in-an-ambivalent-solar-system
- [14] Kelsey Beachum, "Sparking Curiosity-Driven Exploration Through Narrative in Outer Wilds", GDC 2021 slides: https://media.gdcvault.com/GDC+2021/beachum_gdc_2021(1).pdf ; see also Game Developer on the GDC 2020 talk by Alex Beachum and Loan Verneau: https://www.gamedeveloper.com/design/attend-gdc-and-learn-how-i-outer-wilds-i-nailed-curiosity-driven-game-design

**Skyrim, No Man's Sky, Stardew**
- [16] UESP, "Skyrim:Radiant": https://en.uesp.net/wiki/Skyrim:Radiant
- [17] Wikipedia, "No Man's Sky" (reception and updates): https://en.wikipedia.org/wiki/No_Man%27s_Sky ; GDC Vault, "Continuous World Generation in No Man's Sky": https://www.gdcvault.com/play/1024265/Continuous_World_Generation_in__No_Man_s_Sky_
- [19] Stardew Valley Wiki, "Bundles": https://stardewvalleywiki.com/Bundles

**Procedural history**
- [20] Grinblat & Bucklew, "Subverting Historical Cause & Effect: Generation of Mythic Biographies in Caves of Qud", FDG 2017: https://www.pcgworkshop.com/archive/grinblat2017subverting.pdf ; GDC Vault, "Procedurally Generating History in Caves of Qud": https://gdcvault.com/play/1024990/Procedurally-Generating-History-in-Caves
- [21a] Game Developer, "Interview: The Making Of Dwarf Fortress": https://www.gamedeveloper.com/design/interview-the-making-of-dwarf-fortress
- [21b] Tarn Adams, "Emergent Narrative in Dwarf Fortress", in *Procedural Storytelling in Game Design*: https://www.taylorfrancis.com/chapters/edit/10.1201/9780429488337-15/emergent-narrative-dwarf-fortress-tarn-adams

**Roguelikes and strategy**
- [22a] Spelunky Wiki, "Level Generation": https://spelunky.fandom.com/wiki/Level_Generation/2
- [22b] Wikipedia, "Spelunky": https://en.wikipedia.org/wiki/Spelunky
- [23] Slay the Spire Wiki, "Map Generation": https://slaythespire.wiki.gg/wiki/Map_Generation
- [24] Game Developer, "How Supergiant weaves narrative rewards into Hades' cycle of perpetual death": https://www.gamedeveloper.com/design/how-supergiant-weaves-narrative-rewards-into-i-hades-i-cycle-of-perpetual-death
- [25] Game Developer, "GDC 2012: Sid Meier on how to see games as sets of interesting decisions": https://www.gamedeveloper.com/design/gdc-2012-sid-meier-on-how-to-see-games-as-sets-of-interesting-decisions ; GDC Vault: https://gdcvault.com/play/1015756/Interesting
- [43] Wikipedia, "Civilization IV" (fog of war): https://en.wikipedia.org/wiki/Civilization_IV

**Minecraft and Terraria**
- [26a] Minecraft Wiki, "World generation": https://minecraft.wiki/w/World_generation
- [26b] Alan Zucconi, "The World Generation of Minecraft": https://www.alanzucconi.com/2022/06/05/minecraft-world-generation/
- [27a] Terraria Wiki, "Layers": https://terraria.wiki.gg/wiki/Layers
- [27b] Terraria Wiki, "Guide:Game progression": https://terraria.wiki.gg/wiki/Guide:Game_progression
- [27c] Terraria Wiki, "Hardmode": https://terraria.wiki.gg/wiki/Hardmode

**Pokémon**
- [28a] Wikipedia, "Gameplay of Pokémon": https://en.wikipedia.org/wiki/Gameplay_of_Pok%C3%A9mon
- [28b] GamesRadar+, "Pokemon Scarlet and Violet's open gym challenge won't include level-scaling": https://www.gamesradar.com/pokemon-scarlet-and-violets-open-gym-challenge-wont-include-level-scaling-and-that-sucks/
- [28c] Game Rant, "Pokemon Scarlet and Violet's Gyms Are Out of Options With No Level Scaling": https://gamerant.com/pokemon-scarlet-violet-gym-battles-level-scaling-difficulty-open-world/ ; Screen Rant, "Scarlet & Violet's Open World Has A Big Leveling…": https://screenrant.com/pokemon-scarlet-violet-leveling-open-world-difficulty/
- [28e] Wikipedia, "Satoshi Tajiri": https://en.wikipedia.org/wiki/Satoshi_Tajiri
- [28f] Kotaku, "The Origins Of Pokémon": https://kotaku.com/the-origins-of-pokemon-5806664
- [28g] Wikipedia, "Pokémon Legends: Arceus": https://en.wikipedia.org/wiki/Pok%C3%A9mon_Legends:_Arceus
- [28h] Wikipedia, "Pokémon Scarlet and Violet": https://en.wikipedia.org/wiki/Pok%C3%A9mon_Scarlet_and_Violet
- [28i] Wikipedia, "Pokémon Legends: Z-A": https://en.wikipedia.org/wiki/Pok%C3%A9mon_Legends:_Z-A ; Noisy Pixel review: https://noisypixel.net/pokemon-legends-za-review/

**LLMs, NPCs and generated quests**
- [29] Park et al., "Generative Agents: Interactive Simulacra of Human Behavior" (2023): https://arxiv.org/abs/2304.03442
- [30] Wikipedia, "AI Dungeon": https://en.wikipedia.org/wiki/AI_Dungeon
- [31a] Variety, "Hidden Door: AI Role-Playing Fan Fiction Game Platform Launches" (2025): https://variety.com/2025/gaming/news/hidden-door-ai-role-playing-fan-fiction-game-platform-1236488265/
- [31b] Hidden Door, "Introducing Early Access": https://www.hiddendoor.co/blog/early-access
- [32] GamesBeat, "Ubisoft debuts GenAI-powered Neo NPCs and gameplay prototype": https://gamesbeat.com/ubisoft-neo-npcs-nvidia-inworldai-gdc/ ; Nvidia ACE at GDC 2024: https://www.nvidia.com/en-us/geforce/news/nvidia-ace-gdc-gtc-2024-ai-character-game-and-app-demo-videos/
- [34a] Anuttacon, "Whispers from the Star": https://wfts.anuttacon.com/
- [34b] "Language as Reality: A Co-creative Storytelling Game Experience in 1001 Nights Using Generative AI": https://ar5iv.labs.arxiv.org/html/2308.12915
- [35] "Word2World: Generating Stories and Worlds through Large Language Models" (2024): https://arxiv.org/abs/2405.06686
- [36] Borawski et al., "From World-Gen to Quest-Line: A Dependency-Driven Prompt Pipeline for Coherent RPG Generation" (2026): https://arxiv.org/abs/2604.25482
- [37] "Large Language Models for dynamic game content: procedural side-quest generation" (2024): https://www.researchgate.net/publication/385292792_Large_Language_Models_for_dynamic_game_content_procedural_side-quest_generation

**Game feel and juice**
- [38] Martin Jonasson & Petri Purho, "Juice It or Lose It", GDC Europe 2012: https://www.gdcvault.com/play/1016487/juice-it-or-lose ; video: https://www.youtube.com/watch?v=Fy0aCDmgnxg
- [39] Jan Willem Nijman, "The Art of Screenshake", INDIGO Classes 2013: https://www.youtube.com/watch?v=AJdEqssNZ-U
- [40] Steve Swink, *Game Feel*, chapter 1 "Defining Game Feel": http://mycours.es/gamedesign2014/files/2014/10/Game-Feel-Steve-Swink-chapter-1.pdf ; Wikipedia, "Game feel": https://en.wikipedia.org/wiki/Game_feel
- [41] Game Developer, "Video: Indies, resist the urge to 'juice it or lose it'": https://www.gamedeveloper.com/design/video-indies-resist-the-urge-to-juice-it-or-lose-it-
