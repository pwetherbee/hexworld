# Play mode UX

How a player turns a world into a game and plays it. Wireframes are ASCII: proportions, not
pixels. Visual language follows the build UI: glass panels, the world's palette, the same easing and
sound set.

---

## 1. The game button (top middle)

- Appears when the world has at least one completed run (an empty world has no button).
- Lives at the top centre, between the world pill (left) and the controls (right).
- One compact pill whose content reflects the game state:

| state | pill | click |
|---|---|---|
| no game yet | 🎮 **Make it a game** | opens the setup panel |
| generating | 🎮 Adventure · writing the bible… (progress ring) | opens the progress view |
| ready | 🎮 **Play** · Adventure | enters play mode (continue the latest save) |
| in play | ⏏ **Exit to editor** | returns to build mode (auto-saves) |
| needs attention | 🎮 Adventure · 2 issues | shows what failed (e.g. the spine isn't completable) and the fix options |

- A small chevron on the pill opens a menu: *Play / New save / Saves… / Game settings / Change
  game type / Delete game*.

```
┌──────────────┐              ┌───────────────────────────┐              ┌─────────┐
│ ⬢ Brinehook ▾│              │ 🎮 Play · Adventure    ▾ │              │ ● ◎ ♪ ▣ │
└──────────────┘              └───────────────────────────┘              └─────────┘
```

> **Decision:** the world keeps being editable while a game exists. Editing tiles that the game has
> already used shows a warning ("3 NPCs and a quest reference this tile"); the canon records it and
> the director adapts (or the user regenerates the affected content).

---

## 2. Setup panel

A sheet that drops from the pill. Two steps.

### Step 1: choose a game type

```
┌─────────────────────────── Make Brinehook Cove a game ───────────────────────────┐
│                                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  ⚔ Adventure │  │ ⚒ Sandbox   │  │ ⚀ Board race│  │ ⬡ Settlers  │              │
│  │ explore,     │  │ run a colony│  │ race to the │  │ settle,     │              │
│  │ battle, bond │  │ or a city   │  │ goal        │  │ trade, build│              │
│  │  [available] │  │  [later]    │  │  [later]    │  │  [later]    │              │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘              │
│                                                                                   │
│  Suggested for this world: Adventure (a coast with caves, a village, a lighthouse)│
└───────────────────────────────────────────────────────────────────────────────────┘
```

- The game designer agent suggests a type from the world (one line why). "Later" cards are
  visible but disabled, so users see where it's going.

### Step 2: details (template options)

For Adventure (full list in `templates/adventure/README.md`):

```
┌──────────────────────────── Adventure in Brinehook Cove ─────────────────────────┐
│ Length       ○ Short (1h)   ● Standard (3h)   ○ Long (8h+)                        │
│ Difficulty   ○ Relaxed   ● Balanced   ○ Hard   ○ Nuzlocke-ish                      │
│ Creatures    ● Native wildlife   ○ Spirits   ○ Machines   ○ Let the world decide   │
│ Tone         ○ Cozy   ● Adventurous   ○ Eerie   ○ Comic                            │
│ Party size   ○ 3   ● 4   ○ 6                                                       │
│ Anything else?  [ the lighthouse keeper is hiding something…                   ]  │
│                                                                                   │
│                                     [ Cancel ]   [ Generate the game → ]           │
└───────────────────────────────────────────────────────────────────────────────────┘
```

- Every option has a one-line explanation on hover. Sensible defaults are pre-selected from the
  world (a cozy village prompt defaults to Relaxed + Cozy).
- The free-text box feeds the bible writer as a strong hint, not a command.

### Step 3: generation progress

The same pipeline view as a world build: stages light up with live counts and thumbnails as they
land (the bible's factions, creature silhouettes filling a grid, warden portraits). Failures show
inline with what the system is doing about them. When ready: a title card with the game's name,
the premise in two sentences and **Play**.

---

## 3. Play mode

Entering play mode is a transition, not a page change: build chrome slides out, the camera swoops
down to the avatar at the start tile, the HUD slides in.

### 3.1 Overworld HUD (Adventure)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ ⬢ Brinehook Cove › Tidepool Steps            ☀ Day 3, dusk          ⏏  ☰          │
│                                                                                  │
│                                                                                  │
│                         (the world, camera following the avatar)                 │
│                                                                                  │
│ ┌──────────────┐                                           ┌──────────────────┐   │
│ │ ◉ Quest       │                                           │   minimap / fog   │   │
│ │ Find the     │                                           │                   │   │
│ │ keeper's log │                                           └──────────────────┘   │
│ └──────────────┘                                                                  │
│  [🐚 32/32] [🦀 18/25] [🐦 25/25] [   ]                      ◐ Compendium 9/24     │
└──────────────────────────────────────────────────────────────────────────────────┘
```

- Movement: click a reachable tile (reachable tiles tint on hover, cost shown), or WASD/arrows hop
  hex-by-hex. The avatar hops with the build UI's easing and a per-material footstep.
- Things on the map are **visible**: roaming creatures (symbol encounters), NPC sprites, shops,
  gates. Hover shows a card; click walks there and interacts.
- `☰` opens: Party, Bag, Compendium, Quests, Map, Save, Settings.

### 3.2 Screens

| screen | shape |
|---|---|
| Battle | full-screen overlay: the tile's layered background, the two sides, a command bar, turn-order strip, intent icons (see templates/adventure/combat.md) |
| Dialogue | bottom box with the NPC portrait (their sprite, enlarged) and 1–3 lines; choices as buttons; the world stays visible and dimmed |
| Shop | a two-column trade sheet; stock reflects the place and the story |
| Party / creature | stat card, moves with clear effect text, affinity chips, bond level |
| Compendium | a grid of silhouettes by habitat; seen/caught/variant states; habitat hints |
| Map | the whole world with fog, discovered places, quest markers |

### 3.3 Transitions and feel

- Encounter: the roaming creature and avatar touch → a swirl in the tile's palette → the battle
  background slides in layer by layer (sky, far, mid, near).
- Entering a town or building: the drill dive from the VISION doc; the banner announces the rules
  ("Safe: healing, shops").
- Every command acknowledges within 100 ms (sound + motion), even while the engine resolves.

---

## 4. Saves

- Autosave on every meaningful event (after battles, on entering places) plus manual slots.
- Saves list: thumbnail (the current tile), playtime, party icons, the latest quest.
- A save is tiny (event log + snapshot) and refers to shared content, so many saves are cheap.

> **Open:** share links. A shared world+game could be played by anyone (read-only world, own saves).
> Worth designing the ids and permissions for from the start.

---

## 5. Editing while a game exists

- Build mode keeps working. The game button shows **"world changed"** when tiles the game depends on
  were edited.
- The canon tracks which content depends on which tiles (provenance), so the impact is precise:
  "rebuilding Tidepool Steps affects 2 NPCs, 1 shop, 1 quest. Regenerate them / keep them".

## 6. Accessibility and comfort

- All combat and menus fully keyboard and controller navigable; text size setting; colour-blind
  safe affinity chips (icon + colour, never colour alone); reduced-motion mode (no screen shake,
  shorter transitions); battle speed setting; text speed setting.
