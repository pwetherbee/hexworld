# Adventure: balance and testing

How we know a generated Adventure is fair, finishable and fun enough to show a person, before a
person plays it. Nothing ships (to a player, or out of a release) without passing these.

---

## 1. Engine tests (per release)

- **Unit tests** for every formula and rule: damage, turn order, stages, statuses, energy, traits,
  bonding, XP, evolution, AI scoring, boss mechanics, economy.
- **Property tests:** no negative HP, no energy overflow, the round limit always ends battles, the
  reducer is deterministic for a seed, saves round-trip exactly.
- **Golden battles:** recorded battles replayed; their event logs must not change without an explicit
  update.

## 2. The battle simulator

A headless engine that runs thousands of battles between compiled creatures with the AI on both
sides (σ = 0 for measurement, then with noise).

| check | target |
|---|---|
| archetype matrix (same level, same budget, neutral affinities) | every archetype wins 35–65% against every other |
| affinity advantage (×2 vs ×0.5 matchup, equal otherwise) | favoured side wins 70–85% (a real edge, not a lock) |
| stage-1 vs stage-2 at equal level | stage 2 wins 65–80% |
| battle length | wild 3–5 rounds, trainer 6–10, warden 12–20 (median) |
| energy use | every cost bucket 0–5 is used in ≥ 5% of turns by the AI |
| move usage | no move archetype > 30% of all uses; none < 1% |
| trait impact | each trait shifts win rate by 2–8 points (visible, not dominant) |
| status | each status applied in 3–15% of battles; no status lock streaks > 2 turns |

Run on the engine catalog at release, and on **each generated roster** at game creation (a smaller
sample), which catches a generated move set that's degenerate for its line.

## 3. Warden checks (game creation)

- For each warden, build 20 plausible player teams from the species obtainable before it (weighted by
  rarity), at the region cap, with sensible movesets; simulate with the player AI at a "decent player"
  setting.
- **Target:** the decent team wins 55–80% on Balanced (Relaxed +15, Hard −15). Too high → strengthen
  (level +1, a better counter on the team, a stronger mechanic parameter from the allowed range); too
  low → weaken. Up to 3 automatic iterations, then flag for the designer agent with the numbers.
- The confrontation: 40–70% for a decent team at the final level.

## 4. The playtest bot (game creation and CI)

A scripted player that plays a generated game through the engine (no rendering):
- explores toward quest targets and unexplored tiles, avoids tiles above its level band;
- battles with the AI at "decent player" settings, bonds with new species when affordable, keeps a
  balanced team, heals and shops sensibly;
- follows the spine: wardens in any available order.

It reports:

| metric | target (Standard) |
|---|---|
| spine completable | yes, on every generated world (else the game is `needs_attention`) |
| estimated play time (from actions × typical seconds) | 2.5–4 h |
| wild battles per level | 2–4 |
| money: can afford essentials per region without grinding | yes; nice-to-haves need choices |
| blackouts on Balanced | 0–3 over the game |
| Compendium obtainable | 100% of species (with conditions) |
| tiles visited that had a job | ≥ 90% of tiles visited had something to do |
| softlocks (no legal progress) | none, including with any warden order |
| content latency at walking pace (with real generation) | zero visible waits in the timed run |

## 5. Content quality (game creation and weekly)

From content-and-anti-slop.md §6: slop lexicon rate, grounding, name collisions, similarity, swap test,
fallback rate, and the weekly human review with the Compton test for rosters and NPC casts.

## 6. Human playtests (per milestone)

- 3 people × 3 worlds × 1 Short game each, recorded (with consent) and surveyed: fun, clarity of the
  affinity chart by the second warden, moments of "this belongs to this world", moments of "this is
  generic" (each becomes a fixture or a blocklist entry).

## 7. Definition of done (Adventure v1)

- All engine tests and simulator targets pass.
- The playtest bot finishes Short games on 20 generated worlds and Standard on 10, with all metrics in
  range.
- Content metrics at target on the 6 standard test worlds.
- Three human playtests without a blocking issue and with "generic" flags below 5% of content seen.
- Every screen has animations, sounds, keyboard/controller support, empty and error states.
