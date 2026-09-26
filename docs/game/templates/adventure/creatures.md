# Adventure: creatures

How a world's creatures are conceived, designed, compiled into numbers, drawn and checked. The goal:
a roster where every species obviously belongs to this world, fills a job in the game, and looks and
plays different from its neighbours.

---

## 1. The creature concept (per world, in the bible)

Before any species, the bible writer answers, for this world (guided by the "Creatures" option):
- **What are they?** Native wildlife, spirits of places, machines, strays and street cryptids, familiars…
- **Why do they bond with people?** Food, music, a debt, a sigil, curiosity.
- **What is a battle?** A sparring match, a territorial display, a cleansing, a street contest. (Tone
  matters: in a cozy world battles are play-fights; creatures never die, they "faint" or "run off".)
- **The bonding device** and its idiom (a whistle, a biscuit, a sigil card, an app).
- **The keepers:** who studies them (the Compendium's voice: a naturalist's notebook, a street zine).

## 2. Roster design (the game designer agent, at creation)

The roster is designed as a whole, then each species is filled in. The engine gives the designer a
**brief** computed from the world:

| input | used for |
|---|---|
| affinities and their terrain families (combat.md §3) | every species has an affinity and a home terrain |
| regions in spine order, their terrains and tile counts | where each species lives and at what level band |
| roster size by length (Short 18, Standard 30, Long 48) | how many species |
| the region motifs and history from the bible | what each species is *about* |

### 2.1 Structure rules (validated)

- Species come in **lines** of 1–3 stages (Standard: ≈ 10 lines; ~40% three-stage, 40% two-stage,
  20% single). Apex species (1 per region at most) are single-stage with the 480 budget.
- **Every affinity** has ≥ 3 lines; **every region** has ≥ 1 line of each of its native affinities and
  ≥ 1 line from outside (a migrant, for variety).
- **Every archetype** appears across the roster; no region has two lines with the same (affinity,
  archetype).
- **Starters:** three lines forming an affinity triangle (A beats B beats C beats A), all Balanced or
  Skirmisher, obtainable only at the start.
- **Rarity budget:** commons ≈ 50%, uncommons 30%, rares 15%, apex 5%.
- **Habitats** must name terrains that exist; each species' habitat tiles must be reachable by the
  point in the spine where the player needs it (the obtainability validator).
- A **food web**: each line gets 0–2 prey and 0–2 predators among the roster (for ecology reactions in
  dynamic-content.md).

### 2.2 What a species is

```yaml
species:
  id, name                 # name: naming language, or a plain descriptive compound in the world's voice
  line, stage              # line id, 1..3
  affinity                 # affinity id
  archetype, tilt          # combat.md §2; tilt: two stats ±≤3 share points
  trait                    # trait id from the catalog
  rarity                   # common | uncommon | rare | apex
  habitat: [terrain ids], activity: day|night|dawn_dusk|always, weather: [optional]
  temperament_ai           # AI personality preset (combat.md §10)
  map_behaviour            # shy | curious | territorial | lazy | skittish (roaming on the map)
  evolution                # level | item | place | time | bond, with its parameter (from lists)
  learnset: [move ids at unlock levels]   # built by the engine from the designer's picks (§4)
  concept                  # one sentence: what it is, grounded in two canon facts
  look                     # the sprite brief: body plan, size, colours from the palette, one signature detail
  entry                    # the Compendium line (≤ 20 words, in the keepers' voice)
  prey, predators          # species ids
```

- Every text field is short, capped and passes the core skills (grounding, specificity, slop filter,
  novelty vs. the rest of the roster).
- **Stats are not in the spec**: the compiler derives them from stage, archetype and tilt.

## 3. Evolution that reads

- Each stage keeps a **silhouette anchor** from the previous one (the same signature detail, bigger or
  transformed) so lines are recognisable; the pack prompt includes the earlier stage's description.
- Stage 2 and 3 grow in size class (small → medium → large) and in the budget (280 → 360 → 440).
- The evolution condition is chosen from a list and should come from the world (a glass-district
  creature evolves after a night under neon; a tide creature at the spring tide).

## 4. Moves and learnsets

- For each line the designer picks **6–9 moves** from the move archetypes (combat.md §4.3) with
  affinity and cost, respecting the role:
  - own-affinity moves at low, mid and high cost (a damage curve across levels);
  - 1–2 coverage moves of other affinities (at least one hitting a type that resists it);
  - 1–2 utility moves fitting the archetype (Support: Mend/Weaken; Striker: Quick Strike; Tank:
    Harden/Leech).
- Moves are **shared across the roster** where it makes sense (a world has ≈ 70 moves, not 300);
  signature moves (1 per apex and per warden signature creature) are unique.
- The engine assigns unlock levels by cost (cheap early, costly late) and validates coverage (every
  line can hit at least one type super-effectively by mid-game).

## 5. Art

- Sprites are painted in **packs of 16** by the sprite director (the pack pipeline that already
  exists), with the creature's `look` as the subject and the world's style keywords.
- Each creature needs: a **battle sprite** (side view, larger: 48–64 px tall at 64 px tile density,
  2–4 idle frames), a **map sprite** (the same art reduced to map scale), a **Compendium silhouette**
  (derived by the engine: a solid fill of the sprite's alpha).
- The player's creatures face right, opponents left (mirrored), as in the classic layout.
- A line's stages are painted **in the same pack** where possible (consistent style and anchors).
- Variants (dynamic-content.md §5) are palette swaps plus one small painted detail, cheap.

> **Open:** 2–4 frame idle strips per creature from the image model are unproven at pack scale. Fallback:
> engine-made idle motion (breathing squash, bob, blink by recolouring an eye pixel cluster) on a single
> frame, which already looks alive in the shader.

## 6. The Compendium

- A grid by region and habitat; each slot shows the silhouette until seen, the sprite once seen, and a
  check once bonded; variants and "seen at night" marks.
- **Hints for empty slots** come from the species' habitat and activity ("seen around the slipway at
  dusk"), turning the Compendium into a treasure map.
- Entries are the keepers' voice, one line each, and grow a second line when bonded (a behaviour
  observed, drawn from the species' concept and the player's deeds with it).

## 7. Validators (creation time)

| validator | rule |
|---|---|
| structure | §2.1 counts and coverage |
| obtainability | every species can be seen and bonded in a tile reachable before it's needed; conditions are satisfiable |
| balance | the battle simulator's matrix across archetypes and affinities stays within bounds (balance-and-testing.md) |
| novelty | concept and look descriptions pairwise below the similarity threshold; names distinct by edit distance |
| grounding | each concept references ≥ 2 canon facts (a terrain, a place, a faction, an event, another species) |
| art | every pack cell present and readable (the director's review), silhouettes distinct (engine: IoU of alpha masks between species below a threshold) |

## 8. Worked examples (illustrative)

From test worlds generated this week, to show the target register (not final content):

- **Brinehook Cove** (fishing village, rocky coast). Affinities: Tide, Rock, Heath, Salt, Lamp, Gale.
  - *Creelcrab* (Rock, Tank, common): lives in the stacked creels on the quay; claws like net-mending
    hooks; evolves into *Slipwayward* after bonding at the slipway at low tide.
  - *Lampmoth* (Lamp, Skirmisher, uncommon): circles the lighthouse lens at night; Stun-on-hit; the
    keeper's log mentions it was "never here before the false light".
- **New York: Five Boroughs.** Affinities: Glass, Transit, Brownstone, Harbor, Park, Neon, Steam.
  - *Bodega Tabby* (Brownstone, Support, common): naps on warm stoop steps; its Mend is "Leftovers".
  - *Stackhorn* (Steam, Bruiser, rare): lives in the steam vents of the midtown blocks; comes out
    when the manholes hiss at dawn.

Each is grounded in the world's own terrains, places and cast, and has a job (a common Tank early, a
night-only Skirmisher that teaches the Stun mechanic, a Support starter candidate, a rare Bruiser as a
mid-game reward).
