# Adventure: people, items, shops, quests, wardens

Everything the player meets that isn't a wild creature. Rules and numbers are designed; identities,
words and reasons are generated from the canon.

---

## 1. NPCs

### 1.1 Roles (designed)

| role | mechanic | per region (Standard) |
|---|---|---|
| healer | restores the party (free or cheap); respawn point | 1 per town |
| shopkeeper | sells/buys from a stock | 1–2 per town |
| trainer | a battle on a route (optional or blocking); rewards money, sometimes an item | 3–6 |
| quest giver | offers a quest (§5) | 1–3 |
| teacher | teaches a move (for a price or a favour) | 0–1 |
| rival | recurs across the game, battles at set points, has an arc | 1 per game |
| warden | the region's boss (§6) | 1 |
| lore keeper | tells history fragments; points to landmarks | 0–1 |
| wanderer | moves between tiles; rumours, trades, a surprise | 1–2 |

Every NPC has a job from this table. An NPC without a mechanic is not generated.

### 1.2 What an NPC is made of

```yaml
npc:
  id, name            # name minted from the culture's naming language
  role                # from the table
  tile, faction       # where they are, who they belong to (canon ids)
  rolled:             # rolled by the engine (content-and-anti-slop.md §4 Roll)
    want: "to see the lighthouse lit again"
    fear: "the deep water"
    quirk: "counts things out loud"
    temperament: gruff | warm | nervous | proud | sly | weary | cheerful
  local_detail        # one concrete thing tied to their tile ("mends nets by the slipway")
  voice_card          # register, 1 speech habit, 1 phrase they may use once per conversation
  schedule            # hour → point of interest on their tile (world-life.md routines)
  sprite              # from a pack: body type, clothes, one prop, the world's palette
  memory              # structured: met_player, deeds_seen[], opinion (-3..+3), promises[]
```

- `want`, `fear`, `quirk` and `temperament` are rolled by the engine from designed lists (with
  quotas per region), then the LLM writes the specific version grounded in the place. This is what
  keeps a town of NPCs from sharing one personality.
- **Opinion** changes by deeds (helped, beat their creatures, bought, stole, completed or failed their
  quest). It changes prices, what they say and what they offer.

### 1.3 Dialogue

- Generated on demand from the NPC's structured state + the situation + deeds, 1–3 lines, by a cheap
  model with the voice card and the world's voice guide. Cached by (npc, situation, relevant state).
- **Situations** are designed: greet, first meet, idle, before/after battle, quest offer/progress/
  complete/fail, shop open, react to a deed, rumour, farewell.
- Choices are buttons with designed effects (accept, decline, ask about X, trade, battle). The LLM
  writes their labels; the engine owns their effects.
- **Rules:** lines never promise rewards or facts the engine didn't create; they reference at least
  one local fact or deed when relevant; no exposition dumps (lore arrives as a pointer: "the old bell
  is in the drowned chapel, north of here").

> **Open:** free-text chat with NPCs (type anything)? It's fun but slop-prone and slow. Proposal:
> not in v1; buttons only. Maybe later for a few key characters, with the same validators.

## 2. Items (designed effect catalog)

The engine defines effects; the LLM names and describes items in the world's idiom.

| class | effects (designed) | examples by world |
|---|---|---|
| restore | heal HP (tiers: 20/50/full), cure status, revive (half/full) | "bodega sports drink", "kelp poultice" |
| bond | the bonding device (tiers: basic/good/great/master; bonuses by affinity, time, place) | "tin whistle", "salted biscuit", "sigil card" |
| battle | one-battle stat boost, escape, guard | "espresso shot", "smoke pot" |
| held | passive effect on a creature (a stat +10%, an affinity boost, a small heal per turn) | "lucky button", "whalebone charm" |
| teach | teaches one move (TM-like, reusable) | "a busker's songbook", "an old tide chart" |
| key | traversal keys (exploration.md) and quest items | "ferryman's token" |
| lore | readable fragments of the history (evidence) | "a page of the keeper's log" |
| trade goods | sell for money (with local price differences) | "salt cod", "vintage records" |

- ≈ 25 items per Standard game, chosen from the catalog to fit the world (a world without water gets
  no swimming key).
- Prices come from the effect's tier (StatForge), modified by shop and opinion.

## 3. Shops

- A shop has an identity (who runs it, what it smells like, what they stock and why) and a stock
  picked from the catalog by the engine: region tier bounds what can be stocked; the place biases
  which (a harbour stocks water keys and fish; a glass district stocks tech items).
- **Stock changes** with story and deeds: help the fishers → better nets; a storm → prices up for a
  day; defeat a warden → the region's tier rises.
- Buying and selling with a spread; one "special" per shop per in-game day (a rotating rare item).

## 4. Economy (designed)

- Currency named per world ("shells", "tokens", "crowns").
- Income: trainer battles, quests, selling finds; wild battles give little money (so fights have a
  reason beyond XP but grinding isn't a money printer).
- Sinks: restores, bonding devices, teaching, keys (some), services (fast travel with a ferryman).
- Target: the player can afford the essentials of each region without grinding, and is choosing
  between nice-to-haves (balance-and-testing.md measures this).

## 5. Quests

### 5.1 Shapes (designed grammar)

| shape | structure | example |
|---|---|---|
| fetch | go to a place, find X, return | "bring back the keeper's log from the drowned chapel" |
| deliver | carry X from A to B (maybe with a condition) | "take the medicine to the cliff hut before nightfall" |
| hunt | defeat or bond with a specific creature (maybe a rare variant) | "the crab that took the harbour bell" |
| escort | an NPC follows you through dangerous tiles | "walk the net-mender to the far beach" |
| investigate | visit 2–3 places, collect clues, choose an answer | "who lit the false lantern?" |
| restore | bring items to fix a place; the map changes | "salvage three planks to mend the pier" |
| rival | a staged battle with story before and after | "the rival at the lighthouse" |
| bond | earn a creature's trust through a small task chain | "feed the stray gull three days running" |

### 5.2 Rules

- A quest is bound to **real map facts**: its places are existing tiles (often in the fog, so quests
  pull exploration), its items and creatures are in canon.
- Every outcome declares **state mutations**: a tile's material variant (the pier mended), a new NPC or
  shop item, opinion changes, a population change, a rumour. The engine applies them; the player
  sees the world change.
- Rewards are tiered by distance and difficulty (StatForge): money, an item from the catalog, a
  teachable move, a creature, access.
- Main quests (the spine) are designed at game creation; side quests are generated at the frontier and
  in reaction to events (dynamic-content.md). The quest log shows at most 5 active side quests.
- Failure is possible for some (a timed delivery), and has consequences too.

## 6. Wardens (bosses)

- One per region, tied to a faction or force in the bible, with a clear reason to stand in the
  player's way (or to test them).
- **A warden = a team + a mechanic + an arena**:
  - team: 3–6 creatures centred on the region's affinity with 1–2 counters to the obvious answers;
    levels at the region's cap;
  - mechanic: one from the **boss mechanic library** (combat.md §9): a field effect, a shield phase,
    reinforcements, an enrage at half health, a telegraphed big attack, a weather change;
  - arena: the warden's tile rendered as a special battle background, with the mechanic visible in it.
- Beating a warden grants the mark, the traversal key and a story beat (the faction reacts, the map
  changes).
- The confrontation (final boss) uses two mechanics in phases and the conflict's creature or person,
  with a short, earned epilogue written from the deeds ledger.

## 7. The rival

- One per game, generated with a personality contrasting the player's likely style (the director
  watches the player's team and the rival's team counters it without hard-countering).
- Appears 3–5 times (Standard), each time changed by what happened since (they lost a creature, they
  joined a faction, they help at the end).
