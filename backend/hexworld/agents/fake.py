"""Deterministic offline LLM. Produces plausible, schema-valid outputs for every task so the
whole system (scheduler, validators, review loop, UI) can be exercised without API cost.

It is NOT an agent: it maps prompts to hand-made theme/genre presets by keyword. Real prompt
understanding needs HEXWORLD_LLM=openai."""

from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any

from hexworld.agents.themes import THEMES, palette_for, pick_genre, pick_theme
from hexworld.hex import Hex


def _rng(*parts: Any) -> random.Random:
    h = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


class FakeClient:
    """The 'brain' behind FakeAdkLlm (agents/kit.py): given an agent's task payload and what it has
    done so far in the session, returns the next tool call a well-behaved agent would make."""

    name = "fake"

    def __init__(self, *, latency_s: float = 0.0, reject_rate: float = 0.15, duplicate_rate: float = 0.3):
        self.latency_s = latency_s
        self.reject_rate = reject_rate
        self.duplicate_rate = duplicate_rate

    SUBMIT = {
        "world_plan": ("submit_plan", "plan"),
        "tile_design": ("submit_design", "design"),
        "wave_review": ("submit_verdicts", None),
        "material_design": ("submit_material", "spec"),
        "sprite_design": ("submit_sprite", "program"),
    }
    RENDER = {"material_design": "render_material", "sprite_design": "render_sprite"}

    def act(
        self,
        payload: dict[str, Any],
        called: list[str],
        last_response: dict[str, Any] | None,
        followups: list[str],
        tools: set[str],
    ) -> tuple[str, dict[str, Any]]:
        task = payload.get("task", "")
        if task == "direct":
            return (
                ("finish", {"note": "on track"})
                if "view_map" in called or "view_map" not in tools
                else ("view_map", {})
            )
        rng = _rng(task, payload, len(followups))
        data = getattr(self, f"_{task}")(payload, rng)
        if task == "world_plan" and "submit_world" in tools:  # two-step plan: header, then tiles
            o = payload["origin"]
            origin_tile = next(t for t in data["tiles"] if (t["q"], t["r"]) == (o["q"], o["r"]))
            if "submit_world" not in called:
                header = {k: data[k] for k in ("world", "style", "tile_attributes")}
                return "submit_world", {"header": {**header, "origin_tile": origin_tile}}
            return "submit_tiles", {"tiles": data["tiles"]}
        render = self.RENDER.get(task)
        arg_name = self.SUBMIT[task][1]
        if render and render in tools and render not in called:  # look at the draft once
            return render, {arg_name: data}
        name, key = self.SUBMIT[task]
        return name, ({key: data} if key else data)

    # ------------------------------------------------------------------ world_plan
    def _world_plan(self, p: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        existing = p.get("existing_world")
        prompt: str = p["user_prompt"]
        origin = Hex(p["origin"]["q"], p["origin"]["r"])
        theme_name = pick_theme(prompt, default="")
        if existing:
            # Extending: keep the world's style/attributes, but the NEW prompt decides this region.
            world = json.loads(json.dumps(existing["world"]))
            style = json.loads(json.dumps(existing["style"]))
            attrs = existing["tile_attributes"]
            theme = THEMES.get(theme_name) or THEMES["temperate"]
            if theme_name:
                terrains = list(theme["terrains"])
                for t in terrains:
                    if t not in world["terrain_vocabulary"]:
                        world["terrain_vocabulary"].append(t)
                for c in theme["connectors"]:
                    if c not in world["connector_vocabulary"]:
                        world["connector_vocabulary"].append(c)
                extra = palette_for(terrains, theme["connectors"])
                style["palette"] = style["palette"] + [c for c in extra if c not in style["palette"]]
            else:
                terrains = world["terrain_vocabulary"]
        else:
            theme_name = theme_name or "temperate"
            theme = THEMES[theme_name]
            terrains = list(theme["terrains"])
            genre, attrs = pick_genre(prompt)
            title = prompt.strip().split(".")[0][:48] or "Untitled Realm"
            world = {
                "title": title.title(),
                "genre": genre,
                "theme": f"{theme_name} world: {prompt[:120]}",
                "lore": f"A {theme_name} land shaped by the words: '{prompt[:100]}'. Explorers set out from the "
                "central tile to chart what lies beyond.",
                "terrain_vocabulary": terrains,
                "connector_vocabulary": list(theme["connectors"]),
                "directional_notes": "Lower terrain toward the outer rings, higher ground near the heart of the region.",
            }
            style = {
                "palette": palette_for(terrains, theme["connectors"]),
                "tile_px": 32,
                "view": "top-down ground, props as side-view sprites",
                "light_direction": "from the top-left",
                "outline": "1px dark outline on props and raised materials",
                "style_keywords": "Terraria-style pixel art, chunky crisp pixels, bold outlines, vibrant 4-step shading ramps, no dithering",
            }

        seed = rng.random() * 1000
        radius = max((c["ring"] for c in p["candidate_coords"]), default=1) or 1
        tiles = []
        for c in p["candidate_coords"]:
            h = Hex(c["q"], c["r"])
            n = _noise(h, seed)
            falloff = 0.35 * (h.distance(origin) / radius)
            elev = min(0.999, max(0.0, 0.62 + 0.45 * n - falloff))
            biome = terrains[int(elev * len(terrains))]
            leave_empty = h != origin and c["ring"] == radius and _rng(seed, h.key).random() < 0.08
            feats = theme["features"].get(biome, [])
            features = (
                [feats[_rng(seed, "f", h.key).randrange(len(feats))]]
                if feats and _rng(seed, "g", h.key).random() < 0.3
                else []
            )
            tiles.append(
                {
                    "q": h.q,
                    "r": h.r,
                    "leave_empty": leave_empty,
                    "biome": biome,
                    "intent": f"{biome.replace('_', ' ')} tile"
                    + (f" featuring {features[0]}" if features else ""),
                    "features": features,
                    "edge_hints": [],
                    "priority": 5 if h == origin else 3,
                    "duplicate": {"mode": "none", "source_q": 0, "source_r": 0},
                }
            )
        # Filler reuse: an outer tile whose biome already has a generated prototype closer to
        # the origin (and no features of its own) sometimes becomes a shallow/deep copy.
        prototypes: dict[str, dict[str, Any]] = {}
        for t in sorted(tiles, key=lambda t: Hex(t["q"], t["r"]).distance(origin)):
            h = Hex(t["q"], t["r"])
            if t["leave_empty"]:
                continue
            proto = prototypes.get(t["biome"])
            roll = _rng(seed, "dup", h.key).random()
            if proto and h.distance(origin) >= 2 and not t["features"] and roll < self.duplicate_rate:
                mode = "shallow" if roll < self.duplicate_rate / 2 else "deep"
                t["duplicate"] = {"mode": mode, "source_q": proto["q"], "source_r": proto["r"]}
            elif proto is None:
                prototypes[t["biome"]] = t
        return {"world": world, "style": style, "tile_attributes": attrs, "tiles": tiles}

    # ------------------------------------------------------------------ tile_design
    def _tile_design(self, p: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        d = p["directive"]
        world = p["world"]
        terrains: list[str] = world["terrain_vocabulary"]
        connectors: list[str] = world["connector_vocabulary"]
        biome = d["biome"] if d["biome"] in terrains else terrains[0]
        edges = []
        by_edge = {n["edge"]: n for n in p["neighbors"]}
        for i in range(6):
            n = by_edge.get(i)
            if n and n.get("facing_edge"):
                edges.append(dict(n["facing_edge"]))
                continue
            terrain = biome
            if n and n.get("biome") in terrains and rng.random() < 0.35:
                terrain = n["biome"]  # start transitioning toward a planned neighbor
            edges.append({"terrain": terrain, "connectors": []})
        # Continue incoming connectors (roads/rivers), sometimes start a new one.
        incoming = [(i, c) for i, e in enumerate(edges) for c in e["connectors"]]
        free = [i for i in range(6) if not (by_edge.get(i) or {}).get("facing_edge")]
        if connectors and free:
            if incoming and rng.random() < 0.8:
                c = incoming[0][1]
                edges[rng.choice(free)]["connectors"] = [c]
            elif not incoming and biome not in terrains[:1] and rng.random() < 0.12:
                c = rng.choice(connectors)
                for i in rng.sample(free, k=min(2, len(free))):
                    edges[i]["connectors"] = [c]
        attrs = {}
        level = terrains.index(biome) / max(1, len(terrains) - 1)
        for a in p["attributes"]:
            name, t = a["name"], a["type"]
            if t == "boolean":
                attrs[name] = "water" not in biome and "lava" not in biome
            elif t in ("integer", "number"):
                lo = a["minimum"] if a["minimum"] is not None else 0
                hi = a["maximum"] if a["maximum"] is not None else 10
                v = lo + (hi - lo) * (level if "elev" in name else rng.random())
                attrs[name] = int(round(v)) if t == "integer" else round(v, 2)
            elif t == "enum":
                attrs[name] = rng.choice(a["enum_values"])
            elif t == "enum_list":
                attrs[name] = rng.sample(a["enum_values"], k=min(1, len(a["enum_values"])))
            else:
                attrs[name] = ""
        feats = ", ".join(d["features"]) or "natural detail"
        fb = f" (revised: {d['feedback'][-1][:60]})" if d.get("feedback") else ""
        relief = (
            0
            if any(k in biome for k in ("water", "lava", "sea"))
            else 2
            if any(k in biome for k in ("rock", "forest", "hill", "mountain"))
            else 1
        )
        props = []
        for k, feat in enumerate(d["features"][:2]):
            ang = rng.random() * math.tau
            rad = 0.1 + rng.random() * 0.25
            props.append(
                {
                    "kind": feat,
                    "x": round(math.cos(ang) * rad, 2),
                    "y": round(math.sin(ang) * rad + 0.1 * k, 2),
                    "scale": 1.0,
                }
            )
        return {
            "biome": biome,
            "summary": f"{biome.replace('_', ' ').title()} with {feats}{fb}",
            "attributes": attrs,
            "edges": edges,
            "art_prompt": f"{biome.replace('_', ' ')} ground seen from above with {feats}",
            "negative_prompt": "text, people, ui",
            "relief": relief,
            "props": props,
        }

    # ------------------------------------------------------------------ review / anchor
    def _wave_review(self, p: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        verdicts = []
        for c in p["candidates"]:
            r = _rng("review", c["coord"], c["attempt"]).random()
            reject = c["attempt"] == 1 and r < self.reject_rate
            worst = max(c["metrics"].get("seam_delta", {}).values(), default=0.0)
            verdicts.append(
                {
                    "label": c["label"],
                    "accept": not reject,
                    "scores": {
                        "style": 2 if reject else 4,
                        "fidelity": 3 if reject else 4,
                        "edge_continuity": 5 - min(4, int(worst * 10)),
                        "directive_fit": 4,
                    },
                    "feedback": "Increase contrast between ground and props; props read as noise at this scale."
                    if reject
                    else "",
                }
            )
        return {"verdicts": verdicts}

    # Test-double artists: minimal, valid programs so the pipeline can be exercised in tests.
    def _material_design(self, p: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        from hexworld.agents.themes import base_color

        liquid = any(k in p["material"] for k in ("water", "lava", "sea", "ocean"))
        return {
            "base_color": base_color(p["material"]),
            "accent_color": "#ffd35a",
            "base_tone": "base",
            "liquid": liquid,
            "rank": 1 if liquid else 4,
            "boundary": "foam" if liquid else "lip",
            "ops": [
                {"op": "patches", "tone": "light", "scale": 7, "amount": 0.35, "angle": 0, "pixels": []},
                {
                    "op": "decals",
                    "tone": "dark",
                    "scale": 6,
                    "amount": 0.4,
                    "angle": 0,
                    "pixels": [{"dx": 0, "dy": 0, "tone": "dark"}, {"dx": 1, "dy": 0, "tone": "light"}],
                },
            ],
            "scatter": [] if (liquid or p["is_connector"]) else [{"kind": "shrub", "count": 1}],
        }

    def _sprite_design(self, p: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        return {
            "width": 10,
            "height": 12,
            "colors": ["#8b5a2b", "#3f8f3a"],
            "frames": 1,
            "fps": 0,
            "motion": "sway",
            "shapes": [
                {
                    "op": "rect",
                    "x": 4,
                    "y": 7,
                    "w": 2,
                    "h": 5,
                    "color": 0,
                    "tone": "base",
                    "shade": False,
                    "frames": [],
                },
                {
                    "op": "ellipse",
                    "x": 5,
                    "y": 4.5,
                    "w": 4.5,
                    "h": 4,
                    "color": 1,
                    "tone": "base",
                    "shade": True,
                    "frames": [],
                },
            ],
        }


def _noise(h: Hex, seed: float) -> float:
    x, y = h.to_pixel(1.0)
    v = (
        math.sin(x * 0.55 + seed) * 0.5
        + math.sin(y * 0.47 - seed * 1.3) * 0.35
        + math.sin((x + y) * 0.9 + seed * 0.7) * 0.25
    )
    return v / 1.1
