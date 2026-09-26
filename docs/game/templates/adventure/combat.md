# Adventure: combat

The battle engine: small, deep, readable and balanced for creatures that are generated per world.
The LLM names and themes everything; **the engine owns every number**. Research and sources:
[../../../research/monster-tamer-combat.md](../../../research/monster-tamer-combat.md).

Design goals, in priority order:
1. **Readable in one battle.** Each world has a new type chart the player has never seen, so
   everything must be taught by the UI as you play (effectiveness on every move button).
2. **Real decisions every turn.** A per-turn resource (energy), telegraphed enemy moves, and rewards for
   reading the matchup that change tempo, not just damage.
3. **Low hidden randomness.** One visible random source per action at most.
4. **Balanced by construction.** Budgets and formulas, validated by the balance simulator
   (balance-and-testing.md), never hand-tuned per world.

---

## 1. The battle at a glance

- **Singles, 1 v 1**, party of up to 4 (option 3/4/6), plus storage.
- Each round, both sides choose an action, then actions resolve in turn order.
- Actions: **move** (one of 4 equipped), **switch**, **item** (costs the action), **brace**, **bond**
  (wild only), **flee** (wild only).
- A battle ends when one side has no creatures able to fight, the player bonds with or flees from
  the wild creature, or the **round limit** (30) hits (sudden death: both sides take escalating damage
  from round 25, telegraphed).

> **Decision:** doubles are out of v1 (reading load); the engine keeps sides as lists so doubles can
> be added later with synergy rules.

## 2. Stats

Four stats: **HP, ATK, DEF, SPD** (no physical/special split; the move carries the flavour).

- **Base stat total** by evolution stage: stage 1 = **280**, stage 2 = **360**, stage 3 = **440**;
  wardens' signature creatures and apex (legendary-like) species = **480**.
- **Archetypes** fix how the total is split (percent of the total):

| archetype | HP | ATK | DEF | SPD | plays like |
|---|---|---|---|---|---|
| Balanced | 25 | 25 | 25 | 25 | flexible |
| Striker | 20 | 32 | 16 | 32 | hits first and hard, fragile |
| Bruiser | 28 | 32 | 24 | 16 | slow and heavy |
| Tank | 32 | 18 | 34 | 16 | outlasts, protects |
| Skirmisher | 22 | 24 | 20 | 34 | tempo, status, switching |
| Support | 30 | 18 | 28 | 24 | heals, buffs, debuffs |

- The creature designer picks an archetype and may **tilt two stats by up to ±3 points of share**; the
  engine renormalises. Every stat keeps ≥ 15% of the total; SPD ≤ 34%.
- **Stat formula** (no IVs, no EVs): `HP = ⌊2B·L/100⌋ + L + 10`, `other = ⌊2B·L/100⌋ + 5`.
- **Temperament** (visible on the creature card): one stat ×1.1 and one ×0.9, or neutral. Rolled on
  encounter, shown before bonding. The only per-individual variation.
- **Level cap** 50. Evolution at ⅓ and ⅔ of the game's final level by default (Standard: 15 and 30),
  or by a condition (an item, a place, time of day, a bond level) chosen from a designed list.

## 3. Affinities (types), generated per world

### 3.1 How many and what they are

- **N = 6–8 affinities** per world (Short 6, Standard 7, Long 8).
- An affinity is a **family of the world's terrains**, not one terrain: glass towers + steel bridges →
  "Glass"; kelp beds + tide pools → "Tide". Every world terrain maps to exactly one affinity (so every
  place has a native affinity), and every affinity covers at least one terrain that exists.
- Names come from the naming language or plain words in the world's voice; each gets an icon (a pack
  sprite) and a colour from the palette (colour-blind safe: always icon + colour).

### 3.2 The chart is solved, not written

- Every affinity is **strong against exactly k others and weak to exactly k** (k = 2; k = 3 when N = 8),
  with no mutual pairs: a regular oriented graph, built as a **circulant** (types on a ring; type *i*
  beats *i + d* for each offset *d* in a set D with no *d* and −*d* both in D).
- The AffinityDesigner agent proposes **thematic pairs** ("lava beats snow", "tide beats ember"). The
  engine searches all ring orders and valid offset sets (cheap: ≤ 9! × a few dozen) for the chart that
  **agrees with the most proposals**, and reports which proposals it couldn't honour.
- Derived relations: if A is super-effective on B, B's attacks on A are resisted (×0.5); every type
  resists itself. So each type hits k types for ×2, is resisted by k+1, and is neutral to the rest.
- Validators: every type lies on a 3-cycle; no type's strengths are a subset of another's; no
  immunities (v1).

### 3.3 Multipliers

| relation | multiplier |
|---|---|
| super-effective | ×2 |
| neutral | ×1 |
| resisted (target beats the attacker's type, or same type) | ×0.5 |

- One affinity per creature in v1 (no dual types: no ×4 one-shots, simple previews). Coverage comes
  from moves of other affinities.
- **Teaching the chart:** every move button shows ×2 / ×½ against the current target before you
  commit; a one-screen chart viewer; the Compendium shows each species' affinity chip; affinities look
  like their terrains (their colours come from those materials).

## 4. Energy and moves

### 4.1 Energy (replaces PP)

- Max **8**, start **4**, **+2 at the end of each round**, **+1 when you land a super-effective hit**.
- Moves cost **0–5**. Power comes from cost: **Power = 40 + 15·cost** (40/55/70/85/100; cost 5 = 120).
- Invariant: any spending pattern sustains ≈ 70 power per turn, so expensive moves are **burst**, not
  more damage overall. This one rule lets the engine price every generated move.
- **Brace** (always available, costs nothing): take 50% damage this round and gain +2 extra energy. The
  answer to telegraphed attacks and a tempo tool.

### 4.2 Effect pricing (how a move with effects gets its numbers)

| effect tag | price |
|---|---|
| 30% chance of a status | −15 power |
| guaranteed status (0-power move) | cost 2 |
| self +1 stage | cost 1 · self +2 stages: cost 3 |
| target −1 stage (0-power move) | cost 1 |
| priority +1 | −20 power |
| drain 50% of damage | −20 power |
| recoil 25% | +15 power |
| 85% accuracy | +15 power |
| charge turn (telegraphed) | +40 power |
| multi-hit (2–3 hits) | −10 power total |
| heal 40% (0-power) | cost 3; halves on each reuse in the same battle |
| cleanse own status | cost 1 |
| energy siphon (steal 1) | −15 power |
| field (boost an affinity by ×1.3 for 3 rounds) | cost 3 |

### 4.3 Move archetypes (the catalog the generator picks from)

About 30 archetypes: Strike (cost 0–5), Quick Strike (priority), Flurry (multi-hit), Leech (drain),
Reckless (recoil), Charge Blast (telegraphed), Strike + status chance (×4 statuses), Inflict (×4
statuses), Sharpen / Harden / Hasten (+1 or +2), Weaken / Soften / Slow (target −1), Mend (heal),
Purge (cleanse), Siphon, Field (per affinity).
- The generator (MoveSkin) chooses an archetype, its affinity, its cost and tags; the engine computes
  the numbers; the LLM writes the name and one line of flavour.

## 5. Damage

```
base = (⌊2L/5⌋ + 2) · Power · ATK_eff / DEF_eff / 50 + 2
dmg  = ⌊ base · STAB(1.5) · Affinity(2 | 1 | 0.5) · Crit(1.5) · rand(0.90–1.00) · mods ⌋,  min 1
```

- STAB: the move's affinity equals the user's. Crit: 1/24 chance, ignores the defender's positive
  stages. Random spread narrowed to 0.90–1.00 so previews are tight.
- Sanity (equal level-20 Balanced creatures): a 60-power STAB move takes ≈ 3.2 hits to KO, ≈ 1.6 if
  super-effective; hits-to-KO drift from ≈ 2.4 at L5 to ≈ 3.5 at L50.
- **Target battle lengths** (validated in the sim): wild 3–5 rounds, trainer 6–10, warden 12–20.

## 6. Turn order, stages, status

- **Order:** switches and items first; then priority bracket (−1, 0, +1); then SPD (with stages); ties
  random. The **timeline strip** shows the next 6 actors and previews how a chosen action changes it.
- **Stages** capped at **±3**: ×1.5/×2/×2.5 up, ×0.67/×0.5/×0.4 down. Reset on switch. No accuracy or
  evasion stages; no one-hit-KO moves; most moves are 100% accurate.
- **Four status archetypes**, one at a time, shown as pips with a turn count, each renamed and
  re-skinned per world (a salt-burn, a static shock, a chill fog…):

| status | effect | duration |
|---|---|---|
| Scorch (damage over time) | 1/12 max HP per round and ATK ×0.75 | 4 rounds |
| Venom (ramping) | 1/16, 2/16, 3/16… per round | until switched or cured |
| Stun | loses its next action, then immune to Stun for 3 rounds | 1 action |
| Chill | SPD ×0.5 and −1 energy per round | 3 rounds |

- Deliberately no random full-paralysis and no sleep-locks.

## 7. Traits (one passive per species)

A catalog of ~20 parameterised passives; the creature designer picks one per line (evolutions may
upgrade it). Examples:

| trait | effect |
|---|---|
| Last Stand | +20% power below ⅓ HP |
| Steadfast | immune to Stun |
| Warm-up | +1 energy when switched in |
| Thick Hide | the first hit each battle deals 25% less |
| Home Ground | +10% power on its native terrain's tiles |
| Opportunist | +1 energy on a crit |
| Grudge | +1 ATK stage when an ally faints |
| Mender | heals 1/16 at round end |
| Swift Exit | switching out is priority +1 |
| Shield Breaker | super-effective hits remove 2 boss shield pips |
| Nocturnal | +10% SPD at night |
| Scavenger | +10% money after battles it took part in |
| … | ~8 more (defined in the engine with tests) |

## 8. Bonding (catching)

```
p = clamp( R · (1 − 0.66 · hp_fraction) · device · status, 0.02, 0.95 )
```

- R by rarity: common 0.9, uncommon 0.6, rare 0.35, apex 0.15. Device tiers ×1/×1.5/×2 (plus designed
  bonuses: at night, on a given terrain, against an affinity). Status ×1.5 (Stun ×2).
- Shown as three shakes, each passing with probability p^(1/3). **Pity:** +0.05 per failed attempt on
  the same creature. Wardens' creatures can't be bonded.
- Some species need a **condition** instead of (or before) a roll: a quest, an item, a time, a place.
  These are Compendium puzzles (creatures.md).
- A story-critical creature is never only obtainable by a roll.

## 9. Bosses: the mechanic library

Wardens and the confrontation combine the base rules with designed mechanics:

| mechanic | rule | answered by |
|---|---|---|
| **Shield & Break** | 3–5 shield pips; super-effective hits and crits remove one; at 0 the boss is Broken (skips its next action, takes ×1.5 for a round), then the shield refills | reading the chart, burst |
| **Telegraph** | big moves use a charge turn with an intent icon over the boss | Brace, switch to a resist, or Break first |
| **Phases** | at 66% and 33% HP: unlock a new move, then gain a stage or shift its shield's weakness | adapting the team |
| **Two bars** | HP ×2 shown as two bars | endurance, healing economy |
| **Field** | the arena starts with a field effect (e.g. Tide ×1.3); the boss renews it every 4 rounds | clearing or exploiting it |
| **Reinforcements** | at a threshold, a minion joins (doubles only for this fight; minions are weak and telegraphed) | focus choice |
| **Weather** | the arena's weather applies a status each round to a side not of its affinity | team choice before the fight |

- Each warden gets **one** mechanic (plus Shield & Break); the confrontation gets two, in phases.
- Warden level = region cap + 2; teams of 3–6 centred on the region's affinity with 1–2 counters.
- The warden validator simulates the fight with teams the player can plausibly have by then (from
  the region's obtainable species) and rejects unwinnable or trivial designs (balance-and-testing.md).

## 10. Enemy AI

Utility scoring over (move, target):

```
s = w_dmg · 100 · min(1, E[dmg] / target.hp)
  + (KO ? 60 : 0)
  + w_stat  · status_value      (0 if the target already has a status)
  + w_setup · setup_value       (high early and at high HP; 0 at max stages)
  + w_save  · value of banking energy toward a finisher
  − 1000 if the move would fail
  + noise ~ N(0, σ)
```

- **Personalities** (the designer picks one per trainer/species; never tunes weights): Brute (dmg 1.3,
  setup 0.5), Trickster (status 1.5), Guardian (brace/heal 1.5), Feral (high σ), Tactician (setup 1.3,
  save 1.3).
- **Difficulty:** σ (wild 25, trainer 10, warden 0), level offset (Relaxed −2, Hard +2), items carried
  (trainers 1–2 heals, wardens 2).
- **Switching** (trainers and wardens): if the best score < 30 and a bench creature resists the
  player's last move, switch (at most once per 3 rounds).
- **Lookahead** (wardens only): 1 ply, assuming the player's highest-damage move; prefer Brace or
  priority when about to be KO'd.
- **Fair information:** the AI never reads the player's current choice.

## 11. Growth

- **XP:** `total(L) = L³`. Yield = stage base (50/100/170) · Le/5 · ((2Le+10)/(Le+Lp+10))^2.5, ×1.5 vs
  trainers. Active creature 100%, bench 50%. At or above the region's cap, ×0.2 (soft cap: no
  grinding past strategy). ≈ 3 same-level wild battles per level.
- **Learnsets:** 4 equipped moves; new moves unlock at levels 1, 1, 5, 9, 14, 20, 26, 33, 40; learned
  moves stay swappable outside battle; teachers and teach items add coverage moves.
- **Bond level** (1–5, raised by battles together and gifts): small, visible perks (a trait upgrade at
  5), and some evolutions need it.

## 12. Levels across the game

- Final level by length: Short 30, Standard 45, Long 50.
- Warden *i* of W: level = 8 + ⌈(final − 8) · (i + 1) / (W + 1)⌉ (Standard: 16, 24, 32, 40, final 45).
- Wild levels = region level ± 2; region level grows with the wardens beaten (and with distance from
  the start before the first warden).

## 13. Money, blackout, flee

- Trainer prize = class base (regular 20, ace 40, warden 100) × the last creature's level; wild
  battles drop 2·L. Blackout: lose 10% and return to the last healer. Flee: guaranteed from wild
  battles unless the creature is faster and the player failed a flee this battle (then 50%).

## 14. The battle screen

- Layered background of the tile (battle-backgrounds.md); creatures idle-animate constantly.
- **Timeline strip** (next 6 actors, previews reordering). **Intent icons** above wardens and anything
  charging.
- **Move buttons:** name, affinity chip, cost pips, ×2/×½ badge vs the target, damage as a % range of
  the target's HP, a skull when the minimum roll KOs.
- **Hit feedback:** hit-stop 60–100 ms scaled by damage, screen shake by % HP lost, white flash and
  knockback, affinity-coloured particles, HP bar with a lagging ghost chunk, damage numbers sized by
  effectiveness ("WEAK!" in gold, resisted small and grey, crits orange).
- **Log line** for every event (the same event stream drives it). Battle speed and reduced-motion
  settings.

## 15. Guardrails (what the generator can and cannot do)

- Generators pick: archetype, affinity id, cost 0–5, effect tags, trait id, personality preset,
  rarity, evolution condition from the list. They never write a number. The `submit_*` tools reject any
  payload with free numeric fields.
- No new status effects, no new traits, no new mechanics per world: worlds **restyle** the catalog; the
  catalog grows only through engine releases with tests.

## 16. Open questions

- Energy vs classic PP: energy is the stronger design (every turn is a spend-or-save choice), but it
  diverges from Pokémon. Keep?
- Visible temperament ±10%: enough individuality, or add Coromon-style visible potential tiers later?
- Round limit 30: fine for wardens; too long for wilds (their target is 3–5 rounds anyway)?
