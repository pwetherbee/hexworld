# Turn-based monster-tamer combat: research and a v1 rule set

Goal: a small, deep, balanced battle engine for per-world generated creatures. The LLM names and themes
things. The engine owns every number. Sources are listed at the end; bracketed numbers [n] refer to them.

---

## 1. What Pokémon actually does (the reference engine)

**Damage (Gen V+ core)** [1][2]:

```
base = floor( floor( floor(2*L/5 + 2) * Power * A/D ) / 50 ) + 2
dmg  = base * Targets * Weather * Crit * rand(0.85..1.00) * STAB * Type * Burn * Other
```

Crit is x1.5 from Gen VI (x2 in Gen II-V) and ignores the defender's positive stages. STAB is x1.5. Type is
the product over the defender's types (0, 0.25, 0.5, 1, 2, 4). Burn halves physical damage.

**Stats** [3]: `HP = floor((2B + IV + EV/4) * L/100) + L + 10`, `Other = (floor((2B + IV + EV/4) * L/100) + 5) * Nature`
with IV 0-31, EV up to 252 per stat and 510 total, and Nature x1.1 / x0.9. Six stats: HP/Atk/Def/SpA/SpD/Spe.
Stat stages run -6..+6 and multiply by (2+n)/2 or 2/(2-n), so +6 is x4. Accuracy and evasion use thirds (x3 max).

**Why simplified games drop IV/EV.** They are hidden, grindy, and only matter in min-max PvP. Legends: Arceus
removed both and replaced them with visible 0-10 "Effort Levels" raised by items, so that two of the same
species with the same nature and training have identical stats [4]. Coromon kept one "Potential" roll but
shows it as a visible tier (Standard/Potent/Perfect) and lets you spend bonus points [5]. Lesson: any
per-individual variance must be **visible and small**.

**Levels and XP.** Six growth curves. Medium Fast is `XP_total(L) = L^3`. Gen V's *scaled* yield [6]:
`XP = (b * Le / 5) * ((2Le + 10) / (Le + Lp + 10))^2.5 + 1`, x1.5 for trainer battles. The scaled term
rubber-bands, so over-levelled creatures learn slowly and under-levelled ones catch up.

**Type chart** [7]: 18 types, 324 cells. 51 (15.7%) are super-effective, 61 are x0.5, 8 are immune, and
204 (63%) are neutral. The best offensive types hit 5 types super-effectively. Normal hits none. Dual types
produce x4 and x0.25.

**Status** [8]: one major status at a time. Burn: 1/16 max HP per turn and physical damage halved. Poison: 1/8
per turn. Toxic: 1/16, 2/16, ... escalating. Paralysis: speed x0.5 (Gen VII+) and a 25% chance to lose the
turn. Sleep: 1-3 turns. Freeze: 20% thaw per turn. Crit rate (Gen VII) by stage: 1/24, 1/8, 1/2, 1 [9].

**Priority**: integer brackets (-7..+5) that act before speed. Speed only orders moves inside a bracket.
Ties are random.

**Catching (Gen V)** [10]: `X = ((3M - 2H) * rate * ball / (3M)) * status`, and the catch chance is
approximately `(X/255)^0.75`, rolled as three "shake" checks. Status is x2.5 for sleep/freeze and x1.5 for
the others. So a full-HP target is about 1/3 as catchable as a 1-HP one.

**Money** [11]: `prize = class_base * level_of_last_creature`. Blacking out costs money by the same formula
(Gen IV+).

**Enemy AI** (Gen III/IV) [12][13]: every move starts at score 100. Flags add or subtract small integers:
-10 for moves that would fail or hit an immunity, +4 for a KO, +6 for priority, -1 if the move is not the
highest-damage one, a chance of +2 for setup moves on turn 1, and so on. The AI takes the highest score and
breaks ties randomly. Difficulty comes from which flags a trainer has.

---

## 2. What modern tamers changed, and why it reads better

| Game | Change | Takeaway for us |
|---|---|---|
| **Cassette Beasts** [14][15][16] | 14 single elements. Type matchups mostly apply *status reactions* (Air on Fire gives "Extinguished", which lowers attack; Fire on Air grants an Air Wall) instead of big damage multipliers. **AP**: each fighter gains 2 AP per round and gets +1 AP for a type-advantaged hit. Moves cost 0-5ish. Max AP is 5-10. Moves are "stickers" that can be swapped freely. | A resource that regenerates each turn makes every turn a spend-or-save choice. Rewarding type reading with resource, not only damage, is gentle and deep. |
| **Temtem** [17][18] | Doubles by default. One stamina pool; overexerting costs HP and a turn. **Hold** = cooldown turns (0-4). **Synergy** = bonus when the partner has type X. Priority *multiplies speed* (x0.5 to x1.75). Damage `(7 + L/200 * Power * A/D) * mods`. 12 types, x2/x0.5, dual types give x4. | A stamina cost plus a rest action creates tempo. Doubles are deep but double the reading load. |
| **Coromon** [5] | SP pool plus a rest action (restore half). Visible potential tier. Free move swapping. | Visible, player-directed stat bonuses. |
| **Nexomon / Digimon** [19][20] | 9 types, or a 3-attribute triangle (Vaccine > Virus > Data > Vaccine, x2). Small charts. | Small charts are learnable in one session. |
| **Monster Crown** [21][22] | Breeding forced types to be *temperaments*: a 5-cycle (Will > Brute > Malicious > Unstable > Relentless > Will). Offspring take stats from both parents by rule. | A procedural or hybrid roster needs an abstract, regular type graph. |
| **Monster Sanctuary / Siralim** [23][24] | Skill trees and Light/Dark shifts (defensive vs offensive). Siralim: roughly 1200 creatures, each with one signature trait, and synergies by race. Strength comes from synergy rather than grinding. | Give each creature *one* rules-defined passive trait from a catalogue. That makes it distinct without the LLM inventing mechanics. |
| **SMT Press Turn** [25] | Hitting a weakness or landing a crit costs half a turn icon (extra action). Missing or hitting a resist costs extra. Symmetric for enemies. | Very readable reward for type knowledge, but swingy in 1v1. The Cassette +1 AP version is the safer v1 choice. |
| **Octopath Break/Boost** [26] | Shield pips drop on weakness hits. At 0 the enemy is stunned 1 turn and takes x2. +1 BP per turn, bank up to 5. | An ideal **boss** mechanic that reuses the type chart. |
| **Slay the Spire intents** [27][28] | An icon shows what each enemy will do next (attack number, buff, debuff, defend). | Telegraphing turns guessing into planning. |
| **Into the Breach** [29][30] | Every enemy attack is telegraphed, so each loss is the player's own fault. Perfect information. | Show consequences before commitment. |
| **Darkest Dungeon** [31] | Initiative = SPD + d8 each round, with no turn-order display on purpose (tension). | A counter-example. We want the FFX CTB-style visible timeline [32] that previews how an action changes the order. |

**What makes turn-based combat deep but readable** (common thread):

1. A few stats and statuses, each with a visible icon and a duration.
2. A resource with a per-turn tempo (AP, stamina, BP).
3. Knowing the enemy's next move (intents, charge turns).
4. Rewards for exploiting the matchup that change tempo, not only damage.
5. Previews: damage range, KO markers, turn-order changes.
6. Low invisible randomness.

---

## 3. Generated type systems: the constraints that keep them balanced

**Graph model.** Types are nodes. "A is super-effective on B" is a directed edge. A classical result for
rock-paper-scissors generalisations: a perfectly fair "each beats exactly half the others" tournament needs
an odd N, with each node beating (N-1)/2 [33][34]. We do not need a full tournament (most pairs should stay
neutral, as in Pokémon's 63%). We need a **k-regular oriented graph**: every type has out-degree k
(hits k types super-effectively) and in-degree k (is weak to k types), with no mutual pairs.

**Construction that always works (circulant).** Place the N types on a ring and pick an offset set D with
|D| = k and no d where -d is also in D (mod N). Type i beats i+d for every d in D. I checked valid D counts by
script:

| N | k | valid D sets |
|---|---|---|
| 5 | 2 | 4 |
| 6 | 2 | 4 |
| 7 | 2 | 12 |
| 7 | 3 | 8 |
| 8 | 2 | 12 |
| 8 | 3 | 8 |
| 9 | 2 | 24 |
| 9 | 3 | 32 |

k=3 only exists for N ≥ 7. Then **choose the labelling (permutation) and D that maximise thematic agreement**
with the LLM's proposed pairs (e.g. "lava_flow beats snow_peak"). N! is 5040 for N=7 and about 363k for
N=9, so brute force or hill-climbing is cheap. The LLM gives preferences; the solver guarantees regularity.

**Derived relations (Pokémon-like reciprocity).** If A is super-effective on B, then B's attacks on A are
x0.5 ("the thing that beats you shrugs you off"). Every type also resists itself. Per type, offence is then
k super-effective, k+1 resisted, and the rest neutral. Defence is weak to k and resists k+1. For N=7, k=2
that gives 2 weaknesses, 3 resists and 2 neutral; memory load is about 2N facts.

**Validation checks:**

- Every type lies on at least one 3-cycle.
- No type's super-effective set is a subset of another's (no strictly dominated type).
- No immunities in v1.
- Every terrain family maps to exactly one type (many terrains to one type). Types are *not* terrains 1:1.

**Balance levers beyond the chart**, where procedural rosters get their balance:

- **Stat budgets** (Pokémon base-stat totals). **Archetype templates** fix the split.
- **Move budgets**: power is computed from cost and effects.
- **Move pools by role**: every species gets its own-type moves at each tier, one coverage type, and one
  utility move.
- Siralim and Monster Crown both show that rule-based inheritance of stats and traits scales to hundreds of
  creatures without hand balancing [21][24].

---

## 4. Recommended v1 rule set

### 4.1 Creatures

- **Stats: HP, ATK, DEF, SPD.** Physical and special are merged. This halves the reading load, and the move
  itself carries the flavour.
- **One type per creature** in v1. This removes x4 one-shots and keeps previews simple. Coverage comes from
  moves of other types.
- **Stat budget (base stat total over 4 stats)** by evolution stage: stage 1 = 280, stage 2 = 360,
  stage 3 = 440. Bosses and legendaries: 480.
- **Archetypes** (shares of the budget as HP/ATK/DEF/SPD). The LLM picks one archetype and may tilt any two
  stats by up to ±3 points of share. The engine normalises. Every stat must keep at least a 15% share, and
  SPD may not exceed 34%:

  | Archetype | HP | ATK | DEF | SPD |
  |---|---|---|---|---|
  | Balanced | 25 | 25 | 25 | 25 |
  | Striker | 20 | 32 | 16 | 32 |
  | Bruiser | 28 | 32 | 24 | 16 |
  | Tank | 32 | 18 | 34 | 16 |
  | Skirmisher | 22 | 24 | 20 | 34 |
  | Support | 30 | 18 | 28 | 24 |

- **Stat formula** (no IV/EV): `HP = floor(2B*L/100) + L + 10`, `Other = floor(2B*L/100) + 5`.
- **Temperament**: one visible stat x1.1 and one x0.9, or neutral.
- **Level cap 50.** Evolutions happen at L16 and L32 by default.
- **Passive trait**: one per species, picked from an engine catalogue of about 20 parameterised traits.
  Examples: "+20% power below 1/3 HP", "immune to Stun", "+1 energy when switched in",
  "first hit each battle takes 25% less".
- **Learnset**: 4 equipped moves. New moves unlock at L1, 1, 5, 9, 14, 20, 26, 33, 40. Learned moves stay
  swappable outside battle (Cassette Beasts and Coromon do this).

### 4.2 Damage

```
base = (floor(2L/5) + 2) * Power * ATK_eff / DEF_eff / 50 + 2
dmg  = floor(base * STAB(1.5) * Type(2 | 1 | 0.5) * Crit(1.5) * rand(0.90..1.00) * mods), minimum 1
```

- The random spread is narrowed to 0.90-1.00 (from 0.85) so previews are tighter.
- Crit chance is 1/24 and ignores the defender's positive stages.
- **Sanity check** (my script, equal level-20 Balanced creatures with base 80): a 60-power STAB move takes
  about 3.2 hits to KO, and 1.6 hits if super-effective. An 80-power move takes about 2.5 hits.
  Hits-to-KO drift from about 2.4 at L5 to about 3.5 at L50 (same shape as Pokémon), so fights lengthen
  slightly as you progress, which is fine.

### 4.3 Energy (replaces PP)

- Max 8, start at 4, **+2 at the end of each round**, and **+1 on a super-effective hit** (as in Cassette
  Beasts).
- **Power from cost**: `Power = 40 + 15*cost` for cost 0..4 (40/55/70/85/100). Cost 5 gives 120.
- **Invariant**: any spending pattern sustains about 70 power per turn. For example, 0/4 alternating gives
  70, and 2 every turn gives 70. Expensive moves are burst, not better DPS. This one rule lets the engine
  price any generated move.
- **Effect pricing** (subtract from power, or add to cost for 0-power moves):

  | Effect | Price |
  |---|---|
  | 30% chance of status | -15 power |
  | Guaranteed status (0 power) | cost 2 |
  | Self +1 stage | cost 1 |
  | Self +2 stages | cost 3 |
  | Priority +1 | -20 power |
  | Drain 50% | -20 power |
  | Recoil 25% | +15 power |
  | Accuracy 85% | +15 power |
  | Charge turn (telegraphed) | +40 power |
  | Heal 40% | cost 3; each reuse in the same battle heals half as much |

- The LLM only chooses cost, effect tags and the type. The engine computes the numbers.
- **Brace** (always available): take 50% damage this round and gain +2 extra energy. This counters
  telegraphs and fits Temtem/Coromon's "rest".

### 4.4 Turn order, stages, status, accuracy

- **Order**: priority bracket (-1, 0, +1), then SPD (with stages), then a random tie-break. Switching and
  items go first.
- **Stages** capped at **±3**: multipliers x1.5 / x2 / x2.5 up, and x0.67 / x0.5 / x0.4 down. Stages reset
  when the creature switches out.
- **No accuracy or evasion stages. No OHKO moves.** Most moves are 100% accurate.
- **Four status archetypes.** The engine owns the rules; each world renames and re-skins them. One major
  status at a time, shown as pips with a turn count:

  | Status | Effect | Duration |
  |---|---|---|
  | Scorch (DoT) | 1/12 max HP per turn and ATK x0.75 | 4 turns |
  | Venom (ramp) | 1/16, 2/16, 3/16... | until switched or cured |
  | Stun | lose the next action, then immune to Stun for 3 turns | 1 action |
  | Chill | SPD x0.5 and -1 energy regen | 3 turns |

  There is deliberately no random full-paralysis or sleep lock.

### 4.5 Types per world

- **N = 6-8** types. Use k = 2, or k = 3 when N = 8.
- Build the chart with the circulant solver plus thematic permutation from section 3. Super-effective is x2,
  reciprocal and self are x0.5, and there are no immunities.
- A creature's move of its own type gets STAB. Every move names one type.

### 4.6 Catching

```
p = clamp( R * (1 - 0.66 * hp_frac) * ball * status, 0.02, 0.95 )
```

- R by rarity: common 0.9, uncommon 0.6, rare 0.35, apex 0.15.
- ball: x1 / x1.5 / x2. status: x1.5, or x2 for Stun.
- Display three shakes, each passing with probability `p^(1/3)`.
- Pity: +0.05 to p for each failed throw on the same target.
- For a common: 31% at full HP, 60% at half, 87% near 0. For an apex: 5-15%. Bosses cannot be caught.

### 4.7 XP, party and progression

- `XP_total(L) = L^3`.
- Yield = `stage_base(50/100/170) * Le/5 * ((2Le + 10)/(Le + Lp + 10))^2.5`, x1.5 against trainers.
  The active creature gets 100% and the bench 50%.
- At or above the region cap, XP is x0.2 (a soft cap that stops over-grinding).
- That works out to about 3 same-level wild battles per level.
- **Party of 4**, plus storage. **1v1 singles** in v1; doubles later.
- **Region and boss levels**: bosses at `8 + 7i` for i = 0..5 (8, 15, 22, 29, 36, 43). Wild levels are
  region level ±2, where region level grows with hex distance from start or with bosses beaten.

### 4.8 Encounters and economy

- **Encounters**: 3-5 species per terrain type, weighted 50/30/15/5 across common to rare. There is a 12%
  check per wild hex entered, with a 2-hex grace period after a battle. A Repel item blocks checks.
  Visible roaming creatures are an option.
- **Money**:
  - Trainer prize = class base (regular 20, ace 40, boss 100) x the last creature's level.
  - Wild battles drop `2*L` coins.
  - Blackout: lose 10% and return to the last heal point.
- **Prices are fixed; effects are percentage-based** so items stay relevant at every level:

  | Item | Effect | Price |
  |---|---|---|
  | Tonic | heal 35% | 100 |
  | Elixir | heal 70% | 300 |
  | Revive | 50% HP | 500 |
  | Cleanse | cure status | 100 |
  | Charge | +4 energy | 150 |
  | Tier-1/2/3 capture device | x1 / x1.5 / x2 | 100 / 300 / 600 |
  | Move disc | teach a move (reusable; money sink) | 800-2000 |

  Using an item costs the creature's action.

### 4.9 Enemy AI (utility scoring; information must be fair)

Score every (move, target) pair:

```
s = w_dmg  * 100 * min(1, E[dmg]/target.hp)
  + (KO ? 60 : 0)
  + w_stat * status_value      (0 if the target already has a status or is immune)
  + w_setup * setup_value      (high on turn 1 and at high HP, 0 at max stages)
  + w_save  * (energy banked toward a finisher)
  - 1000 if the move would fail
  + noise ~ N(0, sigma)
```

- **Personality weight presets** that the LLM may *pick* (not tune):
  - Brute: dmg 1.3, setup 0.5
  - Trickster: status 1.5
  - Guardian: brace/heal 1.5
  - Feral: sigma high
- **Difficulty** comes from sigma (wild 25, trainer 10, boss 0), level offset and items. Trainers carry 1-2
  heals; bosses carry 2.
- **Switching** (trainers only): if the best score is below 30 and a bench creature resists the player's
  last-used type, switch. At most one switch per 3 turns.
- **Lookahead** (bosses only): 1-ply. Assume the player uses their highest-damage move. Prefer priority or
  Brace when about to be KO'd.
- **Fairness**: the AI never reads the player's current choice.

### 4.10 Bosses

- Level = region cap + 2. HP x2, shown as 2 bars.
- **Shield of 3-5 pips.** Super-effective hits and crits remove a pip. At 0 the boss is **Broken**: it skips
  its next action and takes x1.5 for one round, then the shield refills (Octopath [26]).
- **Telegraph**: big moves use the charge-turn tag, with an intent icon over the boss (Slay the Spire,
  Into the Breach). The player answers with Brace, a switch to a resisting type, or a burst to Break.
- **Phases at 66% and 33% HP**: the boss unlocks one new move, then gains an enrage stage or a second
  weakness shift. All of these come from engine templates.

### 4.11 Readability and juice

- **Timeline strip** showing the next 6 actors. Hovering an action previews the reorder (FFX CTB [32]).
- **Move buttons** show the cost pips, the effectiveness against the current target (x2 / x½ badge), a
  damage range as % of target HP, and a KO skull when the minimum roll kills.
- **Intent icons** above bosses, and above any enemy that is charging.
- **Hit feedback**:
  - Hit-stop of 60-100 ms, scaled by damage.
  - Screen shake proportional to % HP lost.
  - A white flash plus knockback on the sprite.
  - Type-coloured particles.
  - The HP bar drains with a lagging "ghost" chunk.
  - Damage numbers pop in size by effectiveness (big, gold and "WEAK!" for super-effective; small and grey
    for resisted; red-orange for crits).
  - See Juice it or Lose it [35].
- **Battle backdrop** built from the current hex. It has three parallax layers: sky gradient, far props from
  the tile's sprite layer (blurred and darkened), and a mid layer. Two elliptical ground platforms use the
  tile's ground material. Creatures idle-animate constantly (Pokémon B/W [36]).
- **Log line** for every event, driven by the same event stream as the rest of the UI.

---

## 5. Pitfalls

1. **Players have no memorised chart.** Every world is new, unlike Pokémon, so the chart must be taught in
   the UI: a badge on every move button from the first encounter, and a one-screen chart viewer. Types must
   look like their terrain so that "lava beats snow" is intuitive. Hence thematic-agreement optimisation.
2. **LLM bias breaks charts.** Left alone, it makes a "cool" type beat everything. Use the regular-graph
   solver and never accept a raw chart.
3. **Dual types, x4 and immunities** cause one-shots and dead turns. Exclude them from v1.
4. **Stacked randomness** (accuracy + crit + roll + secondary chance + full-para) feels unfair. Keep one
   visible random source per action at most. Sleep/para locks and evasion stacking are the classic
   frustrations; competitive Pokémon bans evasion boosting.
5. **Setup sweeping**: +6 stages snowball. Cap at ±3 and reset on switch.
6. **Speed dominance**: speed gives turn order at no cost. Cap SPD share, and give priority moves a real
   price.
7. **Grind-to-win.** Use scaled XP and a soft level cap so that strategy matters at boss gates.
8. **Heal stalling.** Diminishing heals, AI "finish" weighting and energy caps prevent infinite loops. Add a
   30-round hard limit that deals escalating damage to both sides.
9. **Hidden variance** (IVs) is invisible and feels arbitrary. Keep per-individual differences visible:
   temperament only.
10. **The LLM inventing numbers.** Generation is enum-only: archetype, type id, cost 0-5, effect tags,
    trait id, personality preset, rarity. Numbers come from formulas. Validate in `submit_*` tools and
    return errors, as the rest of HexWorld's agents already do.
11. **Catch frustration.** Use the pity bonus and the 0.95 cap. Never make an encounter the only source of a
    story-critical creature.
12. **Too many statuses or effects per world.** Keep 4 statuses and about 20 traits. The world restyles them;
    it does not add mechanics.
13. **Doubles too early.** Temtem's depth costs readability. Ship singles and add doubles with synergy later.

---

## Sources

1. Bulbapedia, Damage: https://bulbapedia.bulbagarden.net/wiki/Damage
2. smogon/damage-calc (reference implementation, all gens): https://github.com/smogon/damage-calc ; Critical hit: https://bulbapedia.bulbagarden.net/wiki/Critical_hit
3. Serebii, Stats: https://www.serebii.net/games/stats.shtml
4. Legends: Arceus Effort Levels: https://www.serebii.net/legendsarceus/effortlevels.shtml ; https://screenrant.com/pokemon-legends-arceus-effort-levels-ev-iv-systems/
5. Coromon Potential: https://coromon.wiki.gg/wiki/Potential ; SP and rest: https://www.rpgsite.net/review/12864-coromon-review
6. Gen V experience formula: https://bulbagarden.net/threads/the-actual-experience-formula-for-gen-5.103551/ ; https://bulbapedia.bulbagarden.net/wiki/Experience
7. Type chart statistics: https://icon-era.com/statistics/pokemon-type-effectiveness/
8. Status conditions: https://www.serebii.net/games/status.shtml ; https://bulbapedia.bulbagarden.net/wiki/Status_condition
9. Critical hits: https://www.serebii.net/games/criticalhits.shtml
10. Gen V capture mechanics: https://www.dragonflycave.com/mechanics/gen-v-capturing/ ; https://bulbapedia.bulbagarden.net/wiki/Catch_rate
11. Prize money: https://bulbapedia.bulbagarden.net/wiki/Prize_money
12. Gen IV trainer AI: https://gist.github.com/lhearachel/ff61af1f58c84c96592b0b8184dba096
13. Essentials Battle AI: https://essentialsdocs.fandom.com/wiki/Battle_AI ; Emerald AI: https://will-jj.github.io/gen4to3MowAI/
14. Cassette Beasts, Elements, Chemistry & Fusion: https://www.cassettebeasts.com/2022/11/30/elements-chemistry-fusion/
15. Cassette Beasts AP: https://wiki.cassettebeasts.com/wiki/AP
16. Cassette Beasts, Show Your Moves: https://www.cassettebeasts.com/2022/09/16/show-your-moves/
17. Temtem Techniques (stamina, hold, priority, damage formula): https://temtem.wiki.gg/wiki/Techniques
18. Temtem types: https://temtem.fandom.com/wiki/Temtem_types
19. Nexomon types: https://nexomon.fandom.com/wiki/Types
20. Digimon Cyber Sleuth battle mechanics: https://gamefaqs.gamespot.com/ps4/207680-digimon-story-cyber-sleuth-hackers-memory/faqs/76546/battle-mechanics
21. Monster Crown breeding: https://monstercrown.wiki.gg/wiki/Breeding_(Monster_Crown:_Red_King) ; https://www.siliconera.com/monster-crown-game-tries-make-monster-breeding-special/
22. Monster Crown types: https://monstercrown.fandom.com/wiki/Types
23. Monster Sanctuary shifting: https://monster-sanctuary.fandom.com/wiki/Monster_Shifting
24. Siralim Ultimate creatures and traits: https://siralimultimate.wiki.gg/wiki/Creatures
25. Press Turn System: https://megatenwiki.com/wiki/Press_Turn_System
26. Octopath Break and Boost: https://twinfinite.net/guides/break-and-boost-system-octopath-traveler-2-explained/
27. Slay the Spire intents: https://slaythespire.wiki.gg/wiki/Intent
28. Slay the Spire, Metrics Driven Design (GDC): https://www.gdcvault.com/play/1025731/-Slay-the-Spire-Metrics
29. Into the Breach Design Postmortem (GDC): https://www.gdcvault.com/play/1025772/-Into-the-Breach-Design
30. Road to the IGF, Into the Breach: https://www.gamedeveloper.com/game-platforms/road-to-the-igf-subset-games-i-into-the-breach-i-
31. Darkest Dungeon combat mechanics: https://darkestdungeon.wiki.gg/wiki/Combat_Mechanics_(Darkest_Dungeon)
32. FFX CTB: https://finalfantasy.fandom.com/wiki/Final_Fantasy_X_battle_system
33. Rock Paper Scissors graphs: https://www.kreativekorp.com/miscpages/rps/
34. Multiplayer Rock-Paper-Scissors (arXiv): https://arxiv.org/pdf/1903.07252
35. Juice it or Lose it: https://gamejuice.co.uk/resources/juice-it-or-lose-it
36. Pokémon B/W battle changes: https://www.serebii.net/blackwhite/battle.shtml
