"""Terrain/prop color knowledge and theme presets shared by the fake planner and the procedural
pixel-art engine."""

from __future__ import annotations

import colorsys

# keyword -> base color. First keyword contained in a terrain name wins (order matters).
# Saturated, readable "Terraria-ish" bases; ramps are derived with `shade`.
TERRAIN_COLORS: list[tuple[str, str]] = [
    ("deep", "#1d4f9c"),
    ("lava", "#f06a1d"),
    ("magma", "#f06a1d"),
    ("blight", "#4b7a5e"),
    ("murky", "#4a6b4f"),
    ("oasis", "#2e9bd6"),
    ("ice", "#a8e2f5"),
    ("snow", "#e8f2f8"),
    ("water", "#2f7fd8"),
    ("sea", "#2f7fd8"),
    ("ocean", "#245fb8"),
    ("lake", "#3a8ae0"),
    ("river", "#3a8ae0"),
    ("bog", "#56603a"),
    ("swamp", "#3f6b3c"),
    ("marsh", "#5f8a45"),
    ("mud", "#6e5236"),
    ("beach", "#f0d99a"),
    ("dune", "#e8bf6a"),
    ("sand", "#ecd08a"),
    ("desert", "#e3be73"),
    ("mesa", "#c2643a"),
    ("canyon", "#b35a36"),
    ("scrub", "#a3a24f"),
    ("savanna", "#c4b25a"),
    ("farm", "#d0b54a"),
    ("field", "#c7bb4e"),
    ("dead", "#8a8456"),
    ("bone", "#d9ceb0"),
    ("corrupt", "#5e3d73"),
    ("jungle", "#1f8a3a"),
    ("pine", "#1f6b45"),
    ("forest", "#2c8a3e"),
    ("wood", "#2c8a3e"),
    ("grass", "#5cc23e"),
    ("meadow", "#6fcf4a"),
    ("plain", "#8ccc52"),
    ("tundra", "#9fb89a"),
    ("hill", "#7fae4a"),
    ("ash", "#55535a"),
    ("basalt", "#34323c"),
    ("obsidian", "#2a1f3d"),
    ("scorch", "#6e4a2e"),
    ("mountain", "#7a7a86"),
    ("rock", "#8a8a96"),
    ("stone", "#9a9aa6"),
    ("cliff", "#7a6f66"),
    ("crystal", "#a07ce0"),
    ("void", "#1a1426"),
    ("boardwalk", "#9c6b3c"),
    ("road", "#c49a5e"),
    ("path", "#c49a5e"),
    ("track", "#b9c4d0"),
    ("wall", "#9a9aa6"),
    ("rail", "#5a5a5a"),
    ("town", "#a0522d"),
    ("city", "#9a6b4a"),
    ("village", "#a0522d"),
    ("castle", "#8f8f99"),
    ("ruin", "#8a8170"),
    ("dungeon", "#3b3346"),
    ("cave", "#4a4038"),
    ("mushroom", "#b0527a"),
    ("cloud", "#dfe8f2"),
    ("sky", "#8fc3e8"),
    ("gold", "#e8b83a"),
]


def base_color(name: str) -> str:
    n = name.lower()
    for key, color in TERRAIN_COLORS:
        if key in n:
            return color
    # Unknown terrain: deterministic hue from the name.
    h = (sum(ord(c) * (i + 1) for i, c in enumerate(n)) % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(h, 0.5, 0.45)
    return rgb_to_hex((int(r * 255), int(g * 255), int(b * 255)))


def hex_to_rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(v))) for v in rgb))


def shade(c: str, factor: float) -> str:
    """Lightness scale with a slight hue shift (warm highlights, cool shadows) for livelier ramps."""
    r, g, b = hex_to_rgb(c)
    h, lum, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    if factor <= 1:
        lum = max(0.0, lum * factor)
    else:  # approach white without reaching it, so pale materials keep distinct highlight tones
        lum = min(0.95, lum + (1 - lum) * min(1.0, (factor - 1) * 0.9))
    h = (h + (0.015 if factor < 1 else -0.01) * abs(1 - factor)) % 1.0
    s = max(0.0, min(1.0, s * (1.05 if factor < 1 else 0.95)))
    r2, g2, b2 = colorsys.hls_to_rgb(h, lum, s)
    return rgb_to_hex((round(r2 * 255), round(g2 * 255), round(b2 * 255)))


# Colors every world needs for props/sprites (outlines, wood, stone, roofs, fire, windows...).
PROP_COLORS: list[str] = [
    "#14141c",  # outline
    "#f4efe1",  # white / highlight
    "#5a3a22",
    "#8b5a2b",
    "#b98a52",  # wood ramp
    "#4f4f5a",
    "#8c8c94",
    "#c4c4cc",  # stone ramp
    "#7a2630",
    "#b8404a",  # roof ramp
    "#f28c28",
    "#ffd35a",  # flame / window glow
    "#e8dcc0",  # bone / cloth
    "#9b7fd1",
    "#d9c8ff",  # crystal ramp
]

SHADE_FACTORS = (0.55, 0.78, 1.0, 1.22)


def palette_for(terrains: list[str], connectors: list[str]) -> list[str]:
    """Master palette: a 4-step ramp per terrain/connector + the prop colors."""
    out: list[str] = []
    for t in terrains + connectors:
        b = base_color(t)
        for f in SHADE_FACTORS:
            c = shade(b, f)
            if c not in out:
                out.append(c)
    return ensure_prop_colors(out)


def ensure_prop_colors(palette: list[str], cap: int = 64) -> list[str]:
    out = [c.lower() for c in palette]
    for c in PROP_COLORS:
        if c not in out:
            out.append(c)
    return out[:cap]


def nearest_palette(color: str, palette: list[str]) -> str:
    r, g, b = hex_to_rgb(color)
    return min(
        palette, key=lambda p: sum((x - y) ** 2 for x, y in zip(hex_to_rgb(p), (r, g, b), strict=True))
    )


THEMES: dict[str, dict] = {
    "temperate": {
        "keywords": ["meadow", "valley", "river", "rolling hills", "shire", "farmland", "temperate"],
        "terrains": ["water", "sand", "grass", "forest", "hills", "rock", "snow"],
        "connectors": ["road", "river"],
        "features": {
            "grass": ["farmstead", "village house", "standing stones"],
            "forest": ["hunters lodge", "ancient oak"],
            "hills": ["watchtower", "castle"],
            "rock": ["mine entrance", "boulders"],
            "water": ["fishing boat"],
            "sand": ["fishing hut"],
            "snow": ["frozen peak"],
        },
    },
    "desert": {
        "keywords": ["desert", "dune", "sand", "egypt", "pharaoh", "oasis", "mirage", "arid"],
        "terrains": ["oasis_water", "sand", "dunes", "scrub", "mesa", "rock"],
        "connectors": ["caravan_road"],
        "features": {
            "sand": ["bleached bones", "tent camp"],
            "dunes": ["buried obelisk"],
            "mesa": ["cliff dwelling"],
            "oasis_water": ["palm trees"],
            "scrub": ["cactus patch"],
            "rock": ["tomb entrance"],
        },
    },
    "island": {
        "keywords": ["island", "ocean", "sea", "pirate", "archipelago", "coast", "tropical", "reef"],
        "terrains": ["deep_water", "water", "sand", "grass", "jungle", "rock"],
        "connectors": ["path"],
        "features": {
            "sand": ["shipwreck", "palm trees"],
            "jungle": ["ancient idol", "mushroom grove"],
            "rock": ["smugglers cave"],
            "grass": ["pirate camp"],
            "water": ["pirate ship"],
        },
    },
    "winter": {
        "keywords": ["snow", "ice", "frozen", "winter", "arctic", "tundra", "viking", "glacier", "frost"],
        "terrains": ["ice", "water", "tundra", "pine_forest", "snow", "rock"],
        "connectors": ["sled_track"],
        "features": {
            "tundra": ["mammoth bones", "viking longhouse"],
            "pine_forest": ["wolf den"],
            "snow": ["ice crystal spire"],
            "rock": ["frost giant cave"],
            "ice": ["fishing hole"],
        },
    },
    "volcanic": {
        "keywords": [
            "volcano",
            "volcanic",
            "lava",
            "fire",
            "hell",
            "inferno",
            "magma",
            "dragon",
            "molten",
            "demon",
        ],
        "terrains": ["lava", "obsidian", "basalt", "ash", "scorched_earth", "rock"],
        "connectors": ["lava_flow"],
        "features": {
            "lava": ["volcano"],
            "basalt": ["dragon bones", "dark tower"],
            "ash": ["burnt ruins", "brazier"],
            "obsidian": ["obsidian crystal"],
            "rock": ["demon forge", "dark castle"],
            "scorched_earth": ["charred tree", "skull totem"],
        },
    },
    "cursed": {
        "keywords": [
            "evil",
            "dark",
            "cursed",
            "undead",
            "haunted",
            "corrupt",
            "necro",
            "shadow",
            "blight",
            "spooky",
        ],
        "terrains": ["blight_water", "bog", "dead_grass", "corrupt_forest", "bone_field", "rock"],
        "connectors": ["cursed_road"],
        "features": {
            "dead_grass": ["graveyard", "haunted house"],
            "corrupt_forest": ["dead tree", "witch hut"],
            "bone_field": ["skull pile", "dark obelisk"],
            "rock": ["dark castle", "crypt entrance"],
            "bog": ["glowing mushrooms"],
        },
    },
    "swamp": {
        "keywords": ["swamp", "bog", "marsh", "bayou", "frog", "fen", "wetland"],
        "terrains": ["murky_water", "marsh", "mud", "swamp_forest", "grass"],
        "connectors": ["boardwalk"],
        "features": {
            "marsh": ["stilt hut", "giant mushroom"],
            "swamp_forest": ["witch hut", "dead tree"],
            "mud": ["frog idol"],
            "grass": ["campfire"],
        },
    },
}

# Genre -> gameplay attributes the fake super defines. A real super derives these from the prompt;
# nothing (not even elevation) is assumed.
GENRES: list[tuple[tuple[str, ...], str, list[dict]]] = [
    (
        ("board game", "card", "deck", "race", "players", "victory", "tabletop"),
        "board game",
        [
            {
                "name": "space_type",
                "type": "enum",
                "description": "What landing here does",
                "enum_values": ["blank", "draw_card", "bonus_move", "trap", "shortcut", "checkpoint"],
                "minimum": None,
                "maximum": None,
            },
            {
                "name": "victory_points",
                "type": "integer",
                "description": "Points for controlling this space",
                "enum_values": [],
                "minimum": 0,
                "maximum": 5,
            },
            {
                "name": "card_deck",
                "type": "enum",
                "description": "Deck drawn from on this space",
                "enum_values": ["none", "fortune", "peril", "treasure"],
                "minimum": None,
                "maximum": None,
            },
        ],
    ),
    (
        ("tactics", "combat", "war", "battle", "siege", "army", "turn-based", "turn based"),
        "turn-based tactics",
        [
            {
                "name": "cover",
                "type": "enum",
                "description": "Defensive cover for units standing here",
                "enum_values": ["none", "half", "full"],
                "minimum": None,
                "maximum": None,
            },
            {
                "name": "move_cost",
                "type": "integer",
                "description": "Movement points to enter",
                "enum_values": [],
                "minimum": 1,
                "maximum": 4,
            },
            {
                "name": "hazard_damage",
                "type": "integer",
                "description": "Damage per turn spent here",
                "enum_values": [],
                "minimum": 0,
                "maximum": 5,
            },
        ],
    ),
    (
        ("survival", "survive", "colony", "craft"),
        "survival",
        [
            {
                "name": "forage",
                "type": "enum",
                "description": "Resource that can be gathered",
                "enum_values": ["none", "food", "wood", "stone", "ore", "water"],
                "minimum": None,
                "maximum": None,
            },
            {
                "name": "temperature",
                "type": "integer",
                "description": "-2 freezing .. +2 scorching",
                "enum_values": [],
                "minimum": -2,
                "maximum": 2,
            },
            {
                "name": "shelter",
                "type": "boolean",
                "description": "Can a camp be made here?",
                "enum_values": [],
                "minimum": None,
                "maximum": None,
            },
        ],
    ),
]

ADVENTURE_ATTRIBUTES = [
    {
        "name": "encounter",
        "type": "enum",
        "description": "What the party meets here",
        "enum_values": ["none", "wildlife", "bandits", "monster", "merchant", "mystery"],
        "minimum": None,
        "maximum": None,
    },
    {
        "name": "danger",
        "type": "integer",
        "description": "0 safe .. 5 deadly",
        "enum_values": [],
        "minimum": 0,
        "maximum": 5,
    },
    {
        "name": "loot",
        "type": "enum",
        "description": "Treasure found by exploring",
        "enum_values": ["none", "coins", "gear", "relic"],
        "minimum": None,
        "maximum": None,
    },
]


def pick_theme(prompt: str, default: str = "temperate") -> str:
    """Theme with the most keyword hits (ties -> declaration order)."""
    p = prompt.lower()
    best, best_hits = default, 0
    for name, t in THEMES.items():
        hits = sum(1 for k in t["keywords"] if k in p)
        if hits > best_hits:
            best, best_hits = name, hits
    return best


def pick_genre(prompt: str) -> tuple[str, list[dict]]:
    p = prompt.lower()
    for keys, genre, attrs in GENRES:
        if any(k in p for k in keys):
            return genre, attrs
    return "adventure", ADVENTURE_ATTRIBUTES
