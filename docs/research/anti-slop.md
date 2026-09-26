# Anti-slop for generated game content: research and techniques for HexWorld

Date: 2026-09-26. Scope: turning LLM-generated HexWorld maps into a Pokémon-like turn-based adventure (creatures, NPCs, shops, items, quests, bosses), generated at game start and during play, without "AI slop".

---

## 1. What makes AI game content feel sloppy (the failure modes)

| Failure mode | Evidence |
|---|---|
| **No persistent state, so no object permanence** | Players describe AI Dungeon's memory problems as "the goldfish problem" and say the AI "keeps treating me like a stranger" ([Dungeons Deep](https://dungeonsdeep.ai/blog/why-ai-game-masters-forget-your-campaign-and-how-dungeonsdeepai-doesnt)). Oasis (Decart's AI Minecraft) rearranges the world when you turn around because it stores no world state, only the next frame ([PC Gamer](https://www.pcgamer.com/software/ai/ai-generated-minecraft-unveiled-showcasing-ais-unlimited-ability-to-copy-things-but-worse/), [AI Weirdness](https://www.aiweirdness.com/minecraft-with-object-impermanence/)). |
| **The LLM does the math, and does it wrong** | A loud complaint about LLM-first game masters is fudged dice and wrong damage numbers. They also "let you do anything," even impossible actions ([dev.to](https://dev.to/pracode_2503/llms-as-dungeon-masters-can-ai-run-a-tabletop-game-without-cheating-425m), [Wayline](https://www.wayline.io/blog/ai-dungeon-masters-algorithmic-storytelling)). AI Roguelite goes further: an attack succeeds based on the item's name and description plus the AI's plausibility judgment. It is fun as a toy, but nothing is balanced ([Steam](https://store.steampowered.com/app/1889620/AI_Roguelite/)). |
| **Sameness and mode collapse** | Recurring "promptonyms" such as Elara Voss, Aris Thorne, "Whispering Woods" and Eldoria. Patching out one attractor just moves the model to the next cluster (Mira/Mara/Maren) ([Chris Thomas, "The Elara problem"](https://microblog.christhomas.co.uk/blog/the-elara-bias), [TomLikesRobots name blocklist](https://x.com/TomLikesRobots/article/2074504762448339243)). NoveltyBench found that state-of-the-art models produce much less diversity than humans, and that *larger models are often less diverse* ([arXiv 2504.05228](https://arxiv.org/abs/2504.05228)). Verbalized Sampling traces the cause to typicality bias in preference data ([arXiv 2510.01171](https://arxiv.org/abs/2510.01171)). |
| **Slop lexicon and purple prose** | Research lists overused "focal words": delve, tapestry, testament, realm, pivotal, intricate, meticulous, resonate, unwavering ([arXiv 2412.11385](https://arxiv.org/pdf/2412.11385), [Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)). The Antislop paper found some patterns appear more than 1000x more often in LLM output than in human text ([arXiv 2510.15061](https://arxiv.org/abs/2510.15061)). Roleplay users notice the same "*smiles softly*" action across different characters ([bex.co](https://bex.co/blog/2025/04/17/negative-feedback-on-llm-powered-storytelling-and-roleplay-apps)). |
| **Flat, interchangeable, positive-by-default NPCs** | Critics called Ubisoft NEO NPC's Bloom soulless. Aftermath: the conversation has "no rising and falling action" and reads like box-ticking exposition ([Aftermath](https://aftermath.site/ubisoft-ai-npcs/), [Dexerto](https://www.dexerto.com/gaming/internet-roasts-ubisofts-npc-ai-as-soulless-2600380/)). In Vaudeville, some NPCs sound like exact copies of others ([Game8](https://game8.co/articles/reviews/vaudeville-review)). Roleplay users say responses become "canned, overly positive" ([bex.co](https://bex.co/blog/2025/04/17/negative-feedback-on-llm-powered-storytelling-and-roleplay-apps)). |
| **Generated text with no mechanic behind it** | Vaudeville's generated dialogue has no clue board or investigation system to plug into, so talking goes "in circles" ([Game8](https://game8.co/articles/reviews/vaudeville-review), [KeenGamer](https://www.keengamer.com/articles/previews/vaudeville-preview-the-ai-questioning-to-nowhere/)). Emily Short: "the key question in oatmeal-avoidance is whether the generation is connected to anything mechanical" ([emshort.blog](https://emshort.blog/2016/09/21/bowls-of-oatmeal-and-text-generation/)). |
| **Mathematically unique but perceptually the same ("oatmeal")** | Kate Compton's "10,000 bowls of oatmeal": each bowl is technically unique, but players see only oatmeal. What counts is *perceptual* uniqueness ([Compton](https://galaxykate0.tumblr.com/post/139774965871/so-you-want-to-build-a-generator)). |
| **Drift and loops in long sessions** | Stories "go off the rails," restate earlier text almost word for word, and forget character cards ([bex.co](https://bex.co/blog/2025/04/17/negative-feedback-on-llm-powered-storytelling-and-roleplay-apps)). |
| **Latency that breaks the game** | A single cloud call takes about 0.5 to 2 s, and p99 exceeds 5 s. "An NPC that freezes for 2 seconds, then speaks, feels broken" ([The Neural Base](https://theneuralbase.com/ai-for-gaming/learn/beginner/llm-latency-breaking-immersion/)). AI Roguelite reviewers mention waiting while the AI thinks ([Steam reviews](https://steamcommunity.com/app/1889620/reviews/?browsefilter=toprated)). |

**What the positive examples have in common:** the generated content always feeds a mechanic, and the engine owns the truth.
- **1001 Nights:** you win by steering the AI king into saying words like "sword," which then become real weapons ([PreMortem](https://premortem.games/2024/09/23/ada-edens-ai-powered-1001-nights-is-a-story-about-narrative-power/), [arXiv 2308.12915](https://ar5iv.labs.arxiv.org/html/2308.12915)). Its creator also notes that pixel art tolerates varied generated assets well, which is directly relevant to HexWorld.
- **Suck Up!:** persuasion itself is the goal ([HowToGeek](https://www.howtogeek.com/these-games-prove-theres-a-right-way-to-use-modern-ai-in-gaming/)).
- **Infinite Craft:** each result is generated once, cached globally and deterministic, which makes "First Discovery" meaningful ([Arthur O'Dwyer](https://quuxplusone.github.io/blog/2024/02/08/infinite-craft/)).

---

## 2. Techniques that work

### 2.1 Skeleton plus skin: designed mechanics, generated flavor
**Hidden Door** is the clearest production example ([Engadget](https://www.engadget.com/how-do-you-prevent-an-ai-generated-game-from-losing-the-plot-170002788.html), [PC Gamer](https://www.pcgamer.com/hidden-door-ai-game-narrative-rpg/)):
- Writers author **story thread templates** at the level of "a cursed village," and the engine strings three or four of them into an arc.
- The basic unit is a **trope**, such as a bar brawl.
- A **structured database** tracks characters, locations, items, relationships and their conditions.
- It uses about 16 specialized algorithms rather than one model, and constrains wording ("no word … that's not in our dictionary").
- A **plot-prediction model is deliberately detuned**, because always taking the top prediction made stories dull.
- A **"Chekhov's Armory"** brings back earlier threads and wronged enemies.

**Wildermyth** takes the same approach:
- When a situation needs a story, the game searches its database of hand-written events for ones that fit and picks one at random.
- Lines are written in variants per personality.
- Consequences persist: a lost eye means an eyepatch from then on, and lovers can have a child who joins the party ([Wildermyth wiki](https://wildermyth.com/wiki/Event_Types), [cjleo](https://cjleo.com/blog/the-power-of-wildermyths-modular-storytelling-in-game-design/), [Steam discussion](https://steamcommunity.com/app/763890/discussions/0/2647504242056635823/)).

**For HexWorld:** designers (or we, once) author a finite set of **mechanic archetypes**:
- creature roles such as tank, glass-cannon, status-inflicter and evasive
- move effects such as damage, DoT, buff, debuff, heal and field effect
- quest shapes such as fetch, escort, clear, deliver-to, investigate, gate/key and rival
- shop types and boss phase patterns

The LLM **picks an archetype and fills the flavor slots** (name, look, one-line description, sprite brief). It never invents new rule types. New verbs get added to the engine deliberately, the same way the material DSL is extended.

### 2.2 Engine-owned numbers
The LLM never writes HP, damage, price, drop rate or XP.
- It selects `archetype`, `tier` (1 to 5), `element` (an enum) and qualitative knobs such as `speed: fast`.
- A deterministic stat function turns (archetype, tier, biome difficulty, distance from start) into numbers.
- Prices are computed from item power. Encounter tables are built from hex distance and biome.

This is the fix for the AI Roguelite and AI-DM "fudged dice" problems. HexWorld's `submit_*` validators are the natural enforcement point. Reject any payload that contains numbers the schema does not allow.

### 2.3 Ground everything in structured world state
**Caves of Qud** generates sultan histories with a **state machine plus a Tracery-like replacement grammar** ([Grinblat & Bucklew, FDG'17](https://www.pcgworkshop.com/archive/grinblat2017subverting.pdf), [GDC Vault](https://gdcvault.com/play/1024990/Procedurally-Generating-History-in-Caves)):
- Events are chosen at random and then **rationalized after the fact from the sultan's current state**. If no cause exists, the event invents one by mutating state; for example, it adds "allied with frogs" and then cites "the persecution of frogs."
- Each sultan has a **domain** (ice, glass, stars, might). Almost every text pattern references it, and that shared state is "the glue" that makes about 13 random events read as one mythic life.
- Players assemble the gospels out of order from shrines and NPCs, and apophenia (seeing patterns) does the rest.

**Dwarf Fortress** goes the other way. It runs "a giant zero-player strategy game" for centuries, and history is "just a record of that" ([Game Developer](https://www.gamedeveloper.com/design/-i-dwarf-fortress-i-figuring-out-how-to-simulate-the-universe-one-step-at-a-time)). In both cases, **text is rendered from state and never the other way round**.

**For HexWorld:** keep a canon store: factions, settlements, named NPCs, creature species per biome, items, events and player deeds. Each has an ID and a small set of properties, including a Qud-style **domain/motif** for each region and culture. Every generation prompt gets a **retrieved fact pack**: tile biome, nearby landmarks, and the local faction with its domain and grievances. Validators check that every entity the output references resolves to a canon ID. A dependency-ordered pipeline passes schema'd JSON from world → NPCs → campaign plan → quest expansion. It reduced drift and hallucination in a recent RPG-generation study ([arXiv 2604.25482](https://arxiv.org/abs/2604.25482)).

### 2.4 Constrained output
- Use JSON schemas, enums and length caps on every field.
- For names and dialogue, cap tokens hard. For example: NPC line ≤ 2 sentences / 30 words, item description ≤ 20 words, quest pitch ≤ 3 sentences.
- Pokémon's own flavor text is short. Hard length caps are the cheapest anti-purple-prose tool available.
- Use enums for tone (`gruff`, `nervous`, `mercenary`, …) and for speech quirks, assigned by the engine.

### 2.5 Names from phonology, not from the LLM
Martin O'Leary's naming-language generator is based on the Language Construction Kit. It builds phoneme inventories, phonotactics, orthography and morphology, so each culture gets names that sound related to each other and different from other cultures ([mewo2/naming-language](https://github.com/mewo2/naming-language), [write-up](https://procedural-generation.isaackarth.com/2016/08/02/generating-naming-languages-for-nanogenmo-2016.html)).

**For HexWorld:** generate one small naming language per culture/region at world start. Seed it with parameters the LLM chooses from enums (harsh or soft, syllable shape). The engine then mints the names, and the LLM may only pick among engine-minted candidates or add a descriptive epithet ("X of the Salt Flats"). Add a **blocklist of promptonyms**: Elara, Eldoria, Aria, Kael, Thorne, Voss, Lyra, Seraphina, Whispering *, Shadow*, Ember*, and so on. Note that blocklisting alone just moves the model to a new attractor, so minting is the real fix.

### 2.6 Banned phrases and a style bible
- The Antislop Sampler **backtracks and resamples** when a banned string or regex appears. It suppressed 8,000+ patterns without breaking the text, whereas plain token banning became unusable around 2,000 ([GitHub](https://github.com/sam-paech/antislop-sampler), [arXiv 2510.15061](https://arxiv.org/abs/2510.15061)).
- With API models we cannot backtrack mid-stream, so we emulate it: **detect the banned string, then repair or regenerate** with the offending phrase named in the error. This is the same loop as our `submit_*` validators.
- Keep a per-world **style bible**: 5 to 10 lines of voice rules, register and humor level, plus 3 to 6 **few-shot exemplars** written in the target voice, short and concrete.

### 2.7 Specificity heuristics
Oatmeal comes from abstraction. A validator can require:
- at least one concrete noun drawn from the fact pack (a local landmark, material or creature)
- zero abstract slop nouns (destiny, ancient power, darkness, balance)
- a stated want or grievance for each NPC

Emily Short's example: generated dialogue that reflects what the player actually changed (a robot that picks up a cowgirl accent after being taught about cowgirls) reads as both status information and reward ([emshort.blog](https://emshort.blog/2016/09/21/bowls-of-oatmeal-and-text-generation/)).

### 2.8 Diversity by construction
- Sample the *structure* with engine randomness, not with LLM temperature. The engine rolls the archetype, motif, quirk, want and complication, then the LLM writes to the roll. Qud and Wildermyth both work this way.
- **Verbalized Sampling:** ask for N candidates with probabilities, then sample from the low-probability tail ([arXiv 2510.01171](https://arxiv.org/abs/2510.01171)).
- **Novelty check:** embed each new name, description or quest and reject it when its cosine similarity to anything already in the world is above a threshold (for example 0.9). Also cap how often any archetype or motif can repeat within a region.
- **Rarity budgets:** a world gets N legendary creatures, one boss per region and a quota of comic NPCs, so "special" stays special.

### 2.9 Consequence tracking ("yes-and")
- Every player action that matters writes a **deed** to canon: killed X, helped Y, stole from shop Z.
- Later generation must retrieve deeds and reference at least one when relevant (Hidden Door's Chekhov's Armory, Wildermyth's eyepatch).
- Quests resolve into **state mutations** such as faction reputation, shop inventory, a new NPC, or a tile modification, never text alone.

### 2.10 Critic and judge models
Judges are useful but biased. They show length bias (about +17% preference for longer responses), position bias and self-preference ([Tian Pan](https://tianpan.co/blog/2026-04-27-llm-judge-bias-audit-length-position-format), [llm-judge-bias](https://llm-judge-bias.github.io/)). Practices that reduce this:
- Use decomposed rubrics with independent 1 to 5 criteria.
- Tell the judge explicitly that shorter is better.
- Randomize order in pairwise comparisons.
- Use a judge from a different model family where possible.
- Make the judge **quote the offending span** so that its critique can go back to the owning agent as actionable feedback, as the existing HexWorld reviewer already does.

---

## 3. Latency and caching during play

1. **Generate at the frontier.** HexWorld already grows tiles outward. Content should follow the same rule:
   - Everything on tiles within radius R of the player (NPC rosters, encounter tables, shop stock) is generated before the player can reach it.
   - Priority is ordered by path distance and the likely direction of travel.
   - This matches the Inworld-style advice to pre-generate during idle time and "never block player input on LLM latency" ([The Neural Base](https://theneuralbase.com/ai-for-gaming/learn/beginner/llm-latency-breaking-immersion/)).
2. **Two tiers: skeleton now, skin later.** The skeleton (archetype, stats, IDs, quest graph) is deterministic and instant. The skin (names from the naming language, sprite, dialogue) streams in behind it. If the skin is late, show the grammar-rendered fallback. Qud's grammar approach doubles as the offline fallback.
3. **Global content cache keyed by canonical inputs,** as in Infinite Craft ([O'Dwyer](https://quuxplusone.github.io/blog/2024/02/08/infinite-craft/)). For example, key on (species archetype, biome, motif), single-flighted like `World.materials`. This gives determinism and consistency, cuts cost, and makes "first discovery" possible.
4. **Speculative branches.** Pre-generate the 2 or 3 likely quest outcomes and NPC reactions before the player commits, then discard the ones that are not used.
5. **Bounded synchronous calls only where waiting is itself diegetic,** such as free-text conversation with a boss. Cover the wait with animation and keep a pool of hand-authored or pre-generated barks for timeouts.
6. **Time budgets on validation loops.** Allow at most k repair rounds, then fall back to the archetype's default skin. Never ship a failed validator silently.

---

## 4. Measuring slop

- **Lexical:** slop-list hit rate per 1k words (the EQ-Bench "Slop" column matches outputs against a master list of over-represented words and phrases). Also measure a repetition score from the frequency of the top words, bigrams and trigrams ([EQ-Bench](https://eqbench.com/creative_writing.html), [repo](https://github.com/EQ-bench/creative-writing-bench)).
- **Diversity:** distinct-n, and mean pairwise embedding similarity within a world and across worlds generated from the same seed prompt. Track the **name-collision rate across worlds**, which is the promptonym detector. NoveltyBench-style metric: how many functionally distinct outputs appear in k samples ([arXiv 2504.05228](https://arxiv.org/abs/2504.05228)).
- **Groundedness:** the fraction of referenced entities that resolve to canon IDs, and the fraction of NPC lines that cite a local fact or a player deed.
- **Mechanical integrity:** a simulated-battle win-rate matrix across creature archetypes and tiers, TTK distributions, and economy sanity checks (no item sells for more than it costs, quest rewards scaled to distance). Automated playtest bots check that the critical path is completable.
- **Human loop:** a weekly blind review of about 30 random samples per content type, scored with the same rubric as the judge. Track agreement between judge and human (Cohen's kappa), and add every human "slop" flag to the banned-phrase list or to a regression fixture.
- **Perceptual uniqueness test (Compton):** show a reviewer 5 creatures or NPCs from one world. Can they tell each one apart from a one-line description? If not, it is oatmeal.

---

## 5. Checklist: reusable "anti-slop skills" (a prompt module plus a validator for each)

Each skill = a prompt fragment + a deterministic validator + an optional judge rubric, all returning structured errors to the owning agent. This plugs straight into the `submit_*` pattern.

1. **FactPack builder:** retrieves canon (tile, region motif, faction, nearby NPCs, recent player deeds) into a compact JSON block injected into every content prompt. *Validator:* every entity ID in the output exists in canon or is declared as new with required fields.
2. **ArchetypePicker:** the LLM chooses from an enum of designer archetypes (creature role, move effect, quest shape, shop type, boss pattern) and fills flavor slots only. *Validator:* schema check; no free numeric fields; archetype quota per region.
3. **StatForge (engine-only):** deterministic stats, prices, drops and XP from (archetype, tier, distance, biome). No LLM involved. Unit-tested balance invariants.
4. **NameMint:** per-culture naming language (phonemes, syllable shapes, morphology) built at world start. The LLM picks from minted candidates or adds epithets. *Validator:* promptonym blocklist, edit-distance collision check against all world names, phonotactic conformity.
5. **SlopFilter:** banned words and phrases plus regexes (tapestry, testament, whispering, "a sense of", "little did", "ancient evil", *smiles softly*, triads of adjectives). *Validator:* reject with the matched span and ask for a rewrite. Grow the list from human flags and cross-world frequency analysis.
6. **LengthGovernor:** hard per-field word caps and sentence caps. Reject overruns instead of truncating them.
7. **Specificity check:** the output must contain at least one concrete noun from the FactPack and no more than N abstract nouns from a list. NPCs must have `want`, `fear` and `quirk` enums plus one concrete local detail.
8. **VoiceCard:** engine-assigned speech register and quirk per NPC (terse, formal, dialect marker, catchphrase budget of one use per conversation). *Judge:* "could this line be swapped onto a different NPC unnoticed?" If yes, fail.
9. **NoveltyGate:** embedding similarity against the world's existing content of the same type (and a cross-world corpus). Reject above threshold with a note on "too similar to X". Motif and archetype repeat caps.
10. **DiversitySampler:** the engine rolls structure (motif, complication, twist); Verbalized-Sampling-style candidate lists then pick a tail candidate.
11. **ConsequenceLedger:** every quest must declare the state mutations its outcomes cause, and every NPC generation must consult the deeds list. *Validator:* each quest outcome maps to at least one world mutation; referenced deeds exist.
12. **Grammar fallback (Qud-style):** a Tracery-like grammar per content type, fed by canon state and motif. It serves as the instant skeleton text and the timeout fallback.
13. **CriticRubric:** a decomposed judge (grounded, specific, in-voice, concise, mechanically meaningful, consistent), each criterion scored 1 to 5 with a quoted evidence span. It prefers shorter, and ideally uses a different model family. Feedback is routed to the owning agent's session.
14. **FrontierPrefetcher:** scheduler that keeps radius R around the player fully "skinned" and single-flights content by canonical key. Speculative outcome branches. Hard timeouts with fallback.
15. **SlopDashboard / eval harness:** offline pytest-style runs over N seeded worlds reporting slop hits/1k, distinct-n, embedding self-similarity, cross-world name collisions, groundedness %, battle win-rate matrix and judge-vs-human agreement. Fail CI on regressions.

**Main rule:** the LLM chooses and describes, and the engine decides and remembers. Every piece of generated text must be rendered from canon state and must feed a mechanic. If it does neither, cut it.
