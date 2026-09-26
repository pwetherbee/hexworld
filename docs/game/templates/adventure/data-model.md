# Adventure: data model

Schemas as they would appear in code (pydantic, abbreviated). Content types are what agents fill;
engine types are computed. Every content object carries `id`, `provenance` (skill, model, facts
used, rolls, scores) and `version`.

---

## 1. Game and canon

```python
class AdventureOptions(BaseModel):
    length: Literal["short", "standard", "long"] = "standard"
    difficulty: Literal["relaxed", "balanced", "hard", "hardcore"] = "balanced"
    creatures: Literal["auto", "wildlife", "spirits", "machines", "custom"] = "auto"
    creatures_custom: str = ""
    tone: Literal["auto", "cozy", "adventurous", "eerie", "comic"] = "auto"
    party_size: Literal[3, 4, 6] = 4
    hidden_encounters: bool = False
    notes: str = ""

class Game(BaseModel):
    id: str; world_id: str; template: Literal["adventure"]; template_version: str
    options: AdventureOptions
    status: Literal["drafting", "generating", "ready", "needs_attention", "archived"]
    canon_id: str; registry_id: str

class VoiceGuide(BaseModel):
    register: str; era: str; humour: Literal["none", "dry", "warm", "silly"]
    rules: list[str]            # 5-8, each <= 15 words
    exemplars: list[str]        # 3-6 lines in voice
    taboo: list[str]            # extra banned words for this world

class NamingLanguage(BaseModel):  # parameters chosen by an LLM from enums; names minted by the engine
    id: str; culture: str
    consonants: list[str]; vowels: list[str]; syllables: list[str]   # e.g. "CVC", "CV", "V"
    morphemes: dict[str, str]   # "sea" -> "mar", generated per language
    sample: list[str]

class Faction(BaseModel):
    id: str; name: str; motif: str; want: str; grievance: str
    seat_tile: Coord; relations: dict[str, int]   # faction id -> -2..+2

class HistoryEvent(BaseModel):
    id: str; summary: str       # <= 25 words
    cause_ids: list[str]; evidence: list[Evidence]   # a sprite/vignette on a tile, a lore item

class Conflict(BaseModel):
    source: str; agent_id: str  # a faction, an NPC or a creature
    wants: str; shows_as: list[str]   # visible signs on the map

class Canon(BaseModel):
    voice: VoiceGuide; languages: list[NamingLanguage]
    factions: list[Faction]; history: list[HistoryEvent]; conflict: Conflict
    creature_concept: CreatureConcept
    affinities: list[Affinity]; chart: AffinityChart
    places: dict[Coord, Place]          # role, name, region, motif
    regions: list[Region]               # spine order, warden id, level band, key needed
    deeds: list[Deed]                   # append-only during play
```

## 2. Combat content

```python
class Affinity(BaseModel):
    id: str; name: str; terrains: list[str]; colour: str; icon_sprite: str
    status_skin: dict[Literal["scorch", "venom", "stun", "chill"], str] | None   # optional renames

class AffinityChart(BaseModel):     # engine-solved (combat.md §3.2)
    order: list[str]; offsets: list[int]; k: int
    honoured_proposals: list[tuple[str, str]]; dropped_proposals: list[tuple[str, str]]

class MoveSpec(BaseModel):          # filled by MoveSkin; numbers compiled by the engine
    id: str; name: str; flavour: str   # flavour <= 16 words
    archetype: MoveArchetype; affinity: str; cost: conint(ge=0, le=5)
    tags: list[EffectTag]               # from the pricing table

class Move(MoveSpec):               # compiled
    power: int; accuracy: float; priority: int; effects: list[Effect]

class SpeciesSpec(BaseModel):       # creatures.md §2.2
    ...

class Species(SpeciesSpec):         # compiled
    base: Stats                     # from stage budget + archetype + tilt
    learnset: list[tuple[int, str]]
    sprite: SpriteRefs              # battle (frames), map, silhouette

class Trait(BaseModel):             # engine catalog, not generated
    id: str; params: dict[str, float]
```

## 3. People, items, quests

```python
class NPCSpec(BaseModel):
    id: str; name: str; role: NPCRole; tile: Coord; faction: str | None
    want: str; fear: str; quirk: str; temperament: Temperament       # rolled, then written
    local_detail: str; voice: VoiceCard; schedule: list[tuple[int, str]]
    sprite: str; team: list[TeamSlot] | None                          # trainers, wardens, rival

class ItemSpec(BaseModel):
    id: str; name: str; flavour: str; effect: ItemEffect; tier: int   # price compiled
class ShopSpec(BaseModel):
    id: str; npc: str; identity: str; stock_policy: StockPolicy        # stock compiled per day

class QuestSpec(BaseModel):
    id: str; shape: QuestShape; title: str; pitch: str                # pitch <= 3 sentences
    giver: str; places: list[Coord]; items: list[str]; creatures: list[str]
    steps: list[QuestStep]
    outcomes: list[Outcome]         # each with >= 1 WorldMutation (validated)
    reward_tier: int                # rewards compiled

class WardenSpec(NPCSpec):
    affinity: str; mechanic: BossMechanic; arena_tile: Coord; mark: str; key: KeyClass
```

## 4. Game state (engine)

```python
class Creature(BaseModel):          # an individual
    uid: str; species: str; nickname: str | None
    level: int; xp: int; temperament: Temperament
    hp: int; status: Status | None; moves: list[str]; bond: int; held: str | None

class Player(BaseModel):
    tile: Coord; party: list[str]; storage: list[str]
    bag: dict[str, int]; money: int; marks: list[str]; keys: list[str]
    compendium: dict[str, Literal["seen", "bonded"]]; flags: dict[str, Any]

class WorldState(BaseModel):
    time: GameTime; weather: dict[str, str]
    visibility: dict[Coord, Literal["hidden", "seen", "visited"]]
    populations: dict[tuple[Coord, str], float]
    npc_state: dict[str, NPCState]  # opinion, memory, position
    quests: dict[str, QuestState]; tile_mutations: list[WorldMutation]

class Battle(BaseModel):
    kind: Literal["wild", "trainer", "warden", "rival"]
    sides: list[Side]; round: int; field: Field | None; log: list[BattleEvent]
    rng_state: int

class SaveState(BaseModel):
    player: Player; world: WorldState; battle: Battle | None; creatures: dict[str, Creature]
```

## 5. Commands and events

```python
Command = Move(tile) | Interact(target) | Choose(option) | BattleAction(action)
        | UseItem(item, target) | Reorder(party) | Rest() | Save()

Event   = Moved | Revealed(tiles) | EncounterStarted | BattleRound(actions, results)
        | Fainted | Bonded | LevelUp | Evolved | LearnedMove | ItemGained | MoneyChanged
        | DialogueShown(npc, line_id) | QuestUpdated | ShopTransaction | MarkEarned | KeyEarned
        | WorldMutated(mutation) | DirectorEvent(kind, content_ids) | TimeAdvanced | WeatherChanged
```

- The reducer is `step(state, command, rng) -> (state, events)`; the rng is derived from the save seed and
  the command index, so replays are exact.
- Every `*_id` in an event points to registry content; events never embed generated prose.

## 6. Registry entries

```python
class RegistryEntry(BaseModel):
    id: str                          # content hash of the compiled object
    kind: str; payload: dict
    provenance: Provenance           # skill, model, prompt hash, facts[], rolls, critic scores
    depends_on_tiles: list[Coord]    # for "world changed" impact analysis
    created_at: float; game_id: str
```
