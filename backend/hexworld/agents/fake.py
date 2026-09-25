"""Deterministic offline LLM. Produces plausible, schema-valid outputs for every task so the
whole system (scheduler, validators, review loop, UI) can be exercised without API cost."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
from typing import Any

from hexworld.agents.llm import LLMRequest, LLMResult, Role
from hexworld.agents.themes import THEMES, palette_for, pick_theme
from hexworld.hex import Hex


def _rng(*parts: Any) -> random.Random:
    h = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


class FakeClient:
    name = "fake"

    def __init__(self, *, latency_s: float = 0.35, reject_rate: float = 0.15, duplicate_rate: float = 0.3):
        self.latency_s = latency_s
        self.reject_rate = reject_rate
        self.duplicate_rate = duplicate_rate

    def model_for(self, role: Role) -> str:
        return f"fake-{role}"

    async def complete(self, req: LLMRequest) -> LLMResult:
        rng = _rng(req.task, req.payload)
        if self.latency_s:
            await asyncio.sleep(self.latency_s * (0.5 + rng.random()))
        handler = getattr(self, f"_{req.task}")
        data = handler(req.payload, rng)
        itok = len(json.dumps(req.payload, default=str)) // 4 + 85 * len(req.images) + len(req.system) // 4
        return LLMResult(
            data=data,
            model=self.model_for(req.role),
            input_tokens=itok,
            cached_input_tokens=len(req.system) // 4,
            output_tokens=len(json.dumps(data)) // 4,
        )

    # ------------------------------------------------------------------ world_plan
    def _world_plan(self, p: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        existing = p.get("existing_world")
        prompt: str = p["user_prompt"]
        origin = Hex(p["origin"]["q"], p["origin"]["r"])
        if existing:
            world = existing["world"]
            style = existing["style"]
            attrs = existing["tile_attributes"]
            terrains = world["terrain_vocabulary"]
            theme = THEMES.get(pick_theme(prompt), THEMES["temperate"])
        else:
            theme_name = pick_theme(prompt)
            theme = THEMES[theme_name]
            terrains = list(theme["terrains"])
            title = prompt.strip().split(".")[0][:48] or "Untitled Realm"
            world = {
                "title": title.title(),
                "genre": theme["genre"],
                "theme": f"{theme_name} world: {prompt[:120]}",
                "lore": f"A {theme_name} land shaped by the words: '{prompt[:100]}'. Explorers set out from the "
                "central tile to chart what lies beyond.",
                "terrain_vocabulary": terrains,
                "connector_vocabulary": list(theme["connectors"]),
                "directional_notes": "Lower terrain toward the outer rings, higher ground near the heart of the region.",
            }
            style = {
                "palette": palette_for(terrains, theme["connectors"]),
                "tile_px": 48,
                "view": "top-down orthographic",
                "light_direction": "from the top-left",
                "outline": "no outlines on terrain, 1px dark outline on props",
                "style_keywords": "16-bit SNES era pixel art, crisp pixels, limited palette, soft dithering",
            }
            attrs = [
                {
                    "name": "elevation",
                    "type": "integer",
                    "description": "0 sea level .. 5 peaks",
                    "enum_values": [],
                    "minimum": 0,
                    "maximum": 5,
                },
                {
                    "name": "passable",
                    "type": "boolean",
                    "description": "Can units walk here?",
                    "enum_values": [],
                    "minimum": None,
                    "maximum": None,
                },
                {
                    "name": "movement_cost",
                    "type": "integer",
                    "description": "Movement points to enter",
                    "enum_values": [],
                    "minimum": 1,
                    "maximum": 5,
                },
                {
                    "name": "resource",
                    "type": "enum",
                    "description": "Harvestable resource",
                    "enum_values": ["none", "wood", "stone", "food", "gold"],
                    "minimum": None,
                    "maximum": None,
                },
            ]

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
        return {
            "biome": biome,
            "summary": f"{biome.replace('_', ' ').title()} with {feats}{fb}",
            "attributes": attrs,
            "edges": edges,
            "art_prompt": f"{biome.replace('_', ' ')} ground seen from above with {feats}",
            "negative_prompt": "text, people, ui",
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

    def _anchor_pick(self, p: dict[str, Any], rng: random.Random) -> dict[str, Any]:
        return {"best_label": 1 + rng.randrange(p["num_candidates"]), "reason": "Cleanest read of the biome."}


def _noise(h: Hex, seed: float) -> float:
    x, y = h.to_pixel(1.0)
    v = (
        math.sin(x * 0.55 + seed) * 0.5
        + math.sin(y * 0.47 - seed * 1.3) * 0.35
        + math.sin((x + y) * 0.9 + seed * 0.7) * 0.25
    )
    return v / 1.1
