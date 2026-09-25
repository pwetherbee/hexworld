"""Terrain color knowledge shared by the fake planner and the procedural stub renderer."""

from __future__ import annotations

import colorsys

# keyword -> base color. First keyword contained in a terrain name wins (order matters).
TERRAIN_COLORS: list[tuple[str, str]] = [
    ("deep", "#1f3f6e"),
    ("lava", "#e2502c"),
    ("magma", "#e2502c"),
    ("oasis", "#3f8fb0"),
    ("ice", "#bfe3f2"),
    ("snow", "#eef3f7"),
    ("water", "#3a6ea5"),
    ("sea", "#3a6ea5"),
    ("ocean", "#2c5a8c"),
    ("lake", "#3f7fb5"),
    ("river", "#4a86c5"),
    ("swamp", "#4f6b43"),
    ("marsh", "#5b7a4a"),
    ("beach", "#e3cf96"),
    ("dune", "#e0b872"),
    ("sand", "#d9c38a"),
    ("desert", "#d6b577"),
    ("mesa", "#b5653a"),
    ("canyon", "#a9573a"),
    ("scrub", "#9c9a5a"),
    ("savanna", "#b8ad5b"),
    ("farm", "#c2b04a"),
    ("field", "#b7b24e"),
    ("jungle", "#2e7d32"),
    ("pine", "#2c5a3c"),
    ("forest", "#2f6b3a"),
    ("wood", "#3a6f3a"),
    ("grass", "#6aa84f"),
    ("meadow", "#7cb35a"),
    ("plain", "#8bb85a"),
    ("tundra", "#a7b59a"),
    ("hill", "#8a9a5b"),
    ("ash", "#4a4a4a"),
    ("basalt", "#2f2f35"),
    ("obsidian", "#231c2e"),
    ("scorch", "#6b4a2a"),
    ("mountain", "#6b6b6b"),
    ("rock", "#7d7d7d"),
    ("stone", "#8c8c8c"),
    ("cliff", "#6f6a64"),
    ("crystal", "#9b7fd1"),
    ("void", "#1a1426"),
    ("road", "#b08a5a"),
    ("path", "#b08a5a"),
    ("wall", "#8c8c8c"),
    ("rail", "#5a5a5a"),
    ("town", "#a0522d"),
    ("city", "#9a6b4a"),
    ("village", "#a0522d"),
    ("castle", "#8f8f99"),
    ("ruin", "#8a8170"),
    ("dungeon", "#3b3346"),
    ("cave", "#4a4038"),
    ("mushroom", "#b0527a"),
    ("corrupt", "#5b2a5e"),
    ("cloud", "#dfe8f2"),
    ("sky", "#8fc3e8"),
    ("gold", "#d4a634"),
]


def base_color(name: str) -> str:
    n = name.lower()
    for key, color in TERRAIN_COLORS:
        if key in n:
            return color
    # Unknown terrain: deterministic muted hue from the name.
    h = (sum(ord(c) * (i + 1) for i, c in enumerate(n)) % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(h, 0.5, 0.35)
    return rgb_to_hex((int(r * 255), int(g * 255), int(b * 255)))


def hex_to_rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(v))) for v in rgb))


def shade(c: str, factor: float) -> str:
    r, g, b = hex_to_rgb(c)
    h, lum, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    lum = max(0.0, min(1.0, lum * factor))
    r2, g2, b2 = colorsys.hls_to_rgb(h, lum, s)
    return rgb_to_hex((round(r2 * 255), round(g2 * 255), round(b2 * 255)))


def palette_for(terrains: list[str], connectors: list[str], accents: int = 2) -> list[str]:
    out: list[str] = []
    for t in terrains + connectors:
        b = base_color(t)
        for f in (0.72, 1.0, 1.22):
            c = shade(b, f)
            if c not in out:
                out.append(c)
    for c in ("#1b1b22", "#f4efe1", "#c9a227", "#8e3b46")[: accents + 2]:
        if c not in out:
            out.append(c)
    return out[:40]


def nearest_palette(color: str, palette: list[str]) -> str:
    r, g, b = hex_to_rgb(color)
    return min(
        palette, key=lambda p: sum((x - y) ** 2 for x, y in zip(hex_to_rgb(p), (r, g, b), strict=True))
    )


THEMES: dict[str, dict] = {
    "temperate": {
        "keywords": [],
        "terrains": ["water", "sand", "grass", "forest", "hills", "rock", "snow"],
        "connectors": ["road", "river"],
        "genre": "adventure",
        "features": {
            "grass": ["farmstead", "wildflowers", "standing stones"],
            "forest": ["oak grove", "hunter's lodge"],
            "hills": ["watchtower", "sheep pasture"],
            "rock": ["mine entrance", "boulders"],
            "water": ["small island", "reef"],
            "sand": ["driftwood", "fishing hut"],
            "snow": ["frozen peak"],
        },
    },
    "desert": {
        "keywords": ["desert", "dune", "sand", "egypt", "pharaoh", "oasis", "mirage"],
        "terrains": ["oasis_water", "sand", "dunes", "scrub", "mesa", "rock"],
        "connectors": ["caravan_road"],
        "genre": "adventure",
        "features": {
            "sand": ["bleached bones"],
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
        "genre": "adventure",
        "features": {
            "sand": ["shipwreck", "palm trees"],
            "jungle": ["ancient idol", "parrots"],
            "rock": ["smugglers' cave"],
            "grass": ["pirate camp"],
            "water": ["coral reef"],
            "deep_water": ["sea serpent wake"],
        },
    },
    "winter": {
        "keywords": ["snow", "ice", "frozen", "winter", "arctic", "tundra", "viking", "glacier"],
        "terrains": ["ice", "water", "tundra", "pine_forest", "snow", "rock"],
        "connectors": ["sled_track"],
        "genre": "survival adventure",
        "features": {
            "tundra": ["mammoth bones"],
            "pine_forest": ["wolf den"],
            "snow": ["ice spire"],
            "rock": ["frost giant cave"],
            "ice": ["fishing hole"],
            "water": ["ice floes"],
        },
    },
    "volcanic": {
        "keywords": ["volcano", "lava", "fire", "hell", "inferno", "magma", "dragon"],
        "terrains": ["lava", "basalt", "ash", "scorched_grass", "rock", "obsidian"],
        "connectors": ["lava_flow"],
        "genre": "adventure",
        "features": {
            "lava": ["fire elemental"],
            "basalt": ["dragon bones"],
            "ash": ["burnt village"],
            "obsidian": ["obsidian shards"],
            "rock": ["forge"],
            "scorched_grass": ["charred trees"],
        },
    },
}


def pick_theme(prompt: str) -> str:
    p = prompt.lower()
    for name, t in THEMES.items():
        if any(k in p for k in t["keywords"]):
            return name
    return "temperate"
