# Principles: no slop, no half-measures

These are the tests every template, mechanic and piece of generated content must pass. When a spec
elsewhere conflicts with this page, this page wins (or we change it deliberately).

## 1. Designed rules, generated content

- **Rules are code we design, test and balance.** A template is a real game, shippable with
  placeholder content. The LLM never writes rules, never adjudicates an action, and never sets a
  number that affects balance (damage, prices, rates, HP). It picks from designed options: a move
  *archetype*, a creature *role*, an item *effect*, a boss *mechanic*. The engine turns those into
  numbers from budgets and tiers.
- **Content is generated, specific and checked.** Names, looks, personalities, dialogue, places,
  quests and their reasons come from agents, bound to typed schemas, grounded in the world bible and
  checked before they reach the player.
- *Why:* the automated-design literature is unanimous that free-form LLM rules are unreliable
  (Boardwalk 2025: ~56% error-free at best), while "skeleton designed, skin generated" is how every
  procedural game that people love works (Caves of Qud, Wildermyth, Dwarf Fortress legends).

## 2. Nothing could have come from a different world

- Every generated thing must reference **at least two specifics of its world**: a terrain, a place, a
  faction, a historical event, a material, another creature, a person. A "Fire Wolf" fails; a
  kiln-ash jackal that dens in the Redglass Canyon's pottery slag heaps and follows the salt caravans
  passes.
- Names follow the world's **naming language** (phonology rules per culture), not the model's
  default fantasy register. No "Eldoria", no "Shadowfang", no "Whispering Woods".
- Evidence over exposition: lore appears as things on the map (a ruin, a shrine, a creature's
  habitat), not as paragraphs.

## 3. Consequence is the product

- Player actions change the world visibly and permanently: a cleared camp stays cleared, a helped
  town's shop stocks change, over-hunting thins a species and brings its predator.
- Every piece of content has a **job** in the game: a reason to exist mechanically (a creature fills
  an affinity gap on a route; an NPC gates, trades, teaches or points somewhere). Content without a
  job is cut, however pretty.

## 4. Short, sharp, in voice

- Dialogue: one to three lines, each doing something (a hint, a want, a reaction). Item and creature
  descriptions: one sentence. No purple prose, no tapestry, no "testament to", no whispered secrets.
- Tone comes from the world's **voice guide** (written once per world: register, humour, era, taboo
  words), not from the model's default.

## 5. Legible and fair

- Every rule is visible in the UI when it matters: type effectiveness, enemy intent, turn order,
  status durations, prices. Losses must feel like the player's own mistake.
- Randomness is small, bounded and shown. Bosses telegraph.

## 6. Never wait, never break

- Play never blocks on an LLM. Content is generated ahead of the player (the frontier), and every
  slot has a valid fallback (a less specific but still correct piece), so a failed or slow
  generation degrades quality, never function.
- Generated content is stored once and replayed deterministically: saves and replays never
  regenerate.

## 7. Done means done

A template ships only when:
- its rules pass a unit-test suite and a balance simulation;
- a playtest bot can finish a generated game on at least 20 different generated worlds;
- a human playthrough of at least 3 worlds finds no generic content above the agreed rate (see
  content-and-anti-slop.md, "Evaluation");
- every screen has its animations, sounds and empty/error states.
