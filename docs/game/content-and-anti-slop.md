# Content pipeline and anti-slop skills

How every piece of generated game content is made, checked and stored, and the reusable "skills"
that keep it specific, coherent and short. Research: [../research/anti-slop.md](../research/anti-slop.md).

> The rule: **the LLM chooses and describes; the engine decides and remembers.** Every piece of text
> is rendered from canon state and feeds a mechanic. If it does neither, it is cut.

---

## 1. What slop looks like (so we can test for it)

| failure | example | the test that catches it |
|---|---|---|
| generic | "Fire Wolf", "the Whispering Woods", "a mysterious stranger" | grounding check: ≥ 2 canon references; blocklists; novelty gate |
| promptonyms | Elara, Kael, Thorne, Eldoria, Shadowfang | names are minted by the engine, never free-written |
| purple prose | "a testament to the tapestry of ancient power" | slop lexicon filter; length caps |
| sameness | every NPC is kind and helpful; five "mysterious" creatures | engine-rolled wants/fears/quirks; motif quotas; embedding novelty |
| amnesia | the NPC you saved greets you as a stranger | deeds ledger consulted by every generation |
| hollow text | a quest whose outcome changes nothing | every outcome must declare state mutations |
| broken numbers | a potion that heals 9999, a shop selling for more than it buys | numbers are engine-only |
| incoherence | a desert creature living in the harbour | canon validator: habitats must reference existing terrains |
| waiting | a 3 s pause before an NPC speaks | frontier prefetch; skeleton-first; fallbacks |

## 2. The pipeline for one piece of content

```
  request (slot + context)
     │
     ├─► FactPack: retrieve canon facts for this slot (place, region motif, faction, nearby
     │             people/creatures, recent deeds, the voice guide)
     ├─► Roll:     the engine rolls the structure (archetype, motif, want, quirk, complication)
     ├─► Generate: one skill call fills the typed schema (flavour only, no numbers)
     ├─► Validate: schema, lengths, blocklists, grounding (ids resolve), game rules (habitat exists…)
     │     └─ errors go back to the same call as tool errors (max 2 repairs)
     ├─► Critique: rubric judge (grounded, specific, in voice, concise, has a job, consistent)
     │     └─ quoted spans go back for one rewrite if below threshold
     ├─► Novelty:  embedding similarity vs. the world's content of the same type; reject near-dupes
     ├─► Compile:  the engine turns archetype + tier into numbers
     └─► Register: content-addressed entry with provenance (facts used, rolls, model, scores)
```

- Budget per piece: ≤ 1 generation + ≤ 2 repairs + ≤ 1 critique rewrite. Past that, the slot takes
  its fallback (§5) and the failure is logged.
- Cheap pieces (a dialogue line, an item's flavour) skip the judge and rely on deterministic
  validators; expensive pieces (the bible, wardens, the roster) always get the judge and, at
  creation, a second opinion from a different model family.

## 3. The canon (world bible)

The single source of truth all content is checked against. Every fact has an id, a type and
provenance (which agent, which tiles).

| section | contents | written by |
|---|---|---|
| voice guide | register, era, humour level, taboo words, 5–8 rules, 3–6 exemplar lines | bible writer |
| naming languages | 1–3 cultures: phoneme inventory, syllable shapes, morphology, a sample of minted names | NameMint (engine) with LLM-chosen parameters |
| places | named regions and tiles, their motif (a Qud-style domain: salt, glass, bells…) | bible writer + engine (tiles) |
| factions | 2–5: name, motif, want, grievance, relationship to others, seat (a tile) | bible writer |
| history | 4–8 events with causes and evidence on the map (a ruin, a shrine) | bible writer, placed by engine |
| conflict | what is wrong, who is behind it, what it wants, how it shows on the map | bible writer |
| template canon | Adventure: creature concept, affinities, roster, wardens, spine, keys | game designer |
| deeds | what the player did (append-only during play) | engine |

> **Decision:** the canon is structured data first, prose second. Prose fields are short and optional;
> generation reads the structured fields.

## 4. The skills

A **skill** = prompt module + typed schema + deterministic validators + (optional) judge rubric +
fallback + tests over a fixture set of worlds. Skills are shared across templates.

### Core skills (all templates)

| # | skill | does | key validator |
|---|---|---|---|
| 1 | **FactPack** | builds the compact context block for a slot | every id in the output resolves in canon or is declared new with required fields |
| 2 | **Roll** | engine rolls archetype, motif, want, fear, quirk, complication | quotas: no archetype/motif more than N times per region |
| 3 | **NameMint** | per-culture naming language; mints candidates; the LLM may choose one or add an epithet | promptonym blocklist; edit distance to every existing name; phonotactics |
| 4 | **VoiceGuide** | writes and enforces the world's voice | exemplars stay in the prompt; judge scores "in voice" |
| 5 | **SlopFilter** | banned words/phrases/regexes (tapestry, testament, whispering, "a sense of", "little did", "ancient evil", *smiles softly*, triads of adjectives) | reject with the matched span; list grows from reviews |
| 6 | **LengthGovernor** | hard caps per field (line ≤ 30 words, description ≤ 20, pitch ≤ 3 sentences) | reject overruns (never truncate silently) |
| 7 | **Specificity** | ≥ 1 concrete noun from the FactPack; ≤ N abstract nouns (destiny, power, darkness, balance) | reject with the missing requirement |
| 8 | **Grounding** | output references ≥ 2 canon facts by id | ids exist and are relevant to the slot's place |
| 9 | **NoveltyGate** | embedding similarity vs. same-type content in the world (and a cross-world corpus for names) | threshold (≈0.9) → "too similar to X" |
| 10 | **Critic** | decomposed rubric, 1–5 per criterion, quoting evidence; told that shorter is better; order-randomised | below threshold → one rewrite with the quotes |
| 11 | **Consequence** | quests and events declare state mutations; generation consults deeds | every outcome maps to ≥ 1 mutation; cited deeds exist |
| 12 | **GrammarFallback** | a Tracery-style grammar per content type fed by canon (Qud-style) | always valid; used on timeout or failure |
| 13 | **Prefetcher** | keeps the frontier generated; single-flights by canonical key | latency budget met in the bot's runs |
| 14 | **StatForge** | engine-only numbers from archetype, tier, region, difficulty | unit-tested invariants (no dominant item, prices monotonic, …) |
| 15 | **Eval harness** | offline runs over seeded worlds: slop hits per 1k words, distinct-n, self-similarity, name collisions, groundedness, fallback rate | CI fails on regressions |

### Adventure skills (built on the core)

| skill | fills | notes |
|---|---|---|
| AffinityDesigner | the world's affinities and chart | engine validates the chart's graph properties (combat.md) |
| CreatureConcept | a species: concept, habitat, role, look, temperament, evolution idea | ≥ 1 habitat terrain from the world; silhouette distinct from roster (novelty on descriptions) |
| MoveSkin | a move's name and one-line flavour for a chosen archetype | name in the naming language or a plain descriptive phrase |
| NPCSeed | an NPC: role, want, fear, quirk (rolled), a local detail, voice card | must reference their tile and faction |
| DialogueLine | 1–3 lines for an NPC in a situation | voice card + deeds; cheap model; cached per (npc, situation, state) |
| ShopStock | a shop's identity and stock picks from the item catalog | stock reflects place, tier and recent events |
| ItemSkin | an item's name and flavour for a designed effect | local materials and idiom |
| QuestWeaver | a quest from a designed shape bound to map facts | outcomes mutate state; points into the fog |
| WardenDesigner | a warden: faction tie, affinity, team, mechanic from the boss library, arena | combat validator: beatable with the region's obtainable creatures |
| BackdropDirector | the battle background brief for a tile (battle-backgrounds.md) | uses the tile's materials, palette and sprites |

## 5. Fallbacks

Every slot has a chain: `generated → reuse a similar registered piece → grammar fallback → template
stock`. Examples:
- a dialogue line times out → the grammar renders "The keeper glances at the lamp. 'Tide's turning.'"
  from the NPC's quirk and the place motif;
- a creature's art fails → the pack retries once; then the silhouette placeholder (a dark cut-out of
  the role's body plan) keeps the battle playable, and the art arrives later.

Fallback use is a quality metric (target < 3% of shown content).

## 6. Evaluation

| metric | target (Standard Adventure) |
|---|---|
| slop-lexicon hits per 1,000 words | < 0.5 |
| grounded content (≥ 2 canon refs) | > 95% |
| name collisions with the promptonym list or across the last 50 worlds | 0 |
| mean pairwise similarity of creature descriptions in a world | below a calibrated threshold |
| NPC line swap test (could this line belong to another NPC?) judge fail rate | < 10% |
| fallback rate | < 3% |
| human blind review (30 samples per type per week) rated generic | < 5% |

- The **Compton test** for rosters and casts: a reviewer sees 5 creatures or NPCs from one world as
  one-liners and must tell them apart. Run per release.
- Every human "slop" flag becomes a blocklist entry or a regression fixture.

## 7. Where the skills live

`backend/hexworld/game/skills/` (shared) and `game/templates/<t>/skills/`. Each skill has a fixture set
of 6+ worlds (the standard test worlds) and golden tests for its validators. Skills are ADK agents
with `submit_*` tools like every other HexWorld agent; the validators are the tools' error returns.
