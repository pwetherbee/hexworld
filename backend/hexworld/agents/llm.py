"""Model plumbing shared by the agents: pricing, per-run budgets, strict JSON schema helper, and a
model lister. Agents themselves run on Google ADK (see agents/kit.py)."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel

from hexworld.domain import RunStats

Role = Literal["super", "tile", "artist"]


class BudgetExceeded(Exception):
    pass


# --------------------------------------------------------------------------- strict schema


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON Schema -> OpenAI strict-mode compatible schema (closed objects, all required)."""
    return _strict(model.model_json_schema())


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(n) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return {"$ref": node["$ref"]}
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k in ("default", "title", "examples"):
            continue
        if k in ("properties", "$defs", "definitions"):
            out[k] = {name: _strict(sub) for name, sub in v.items()}
        else:
            out[k] = _strict(v)
    if out.get("type") == "object" or "properties" in out:
        out.setdefault("properties", {})
        out["additionalProperties"] = False
        out["required"] = list(out["properties"].keys())
    return out


# --------------------------------------------------------------------------- pricing

# USD per 1M tokens: (input, cached input, output).
PRICING: dict[str, tuple[float, float, float]] = {
    # GPT-6 family (published per-1M prices; cached input assumed at 10% of input)
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "gpt-6-sol": (2.00, 0.20, 10.00),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-5.6-sol": (4.00, 0.40, 20.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4o": (2.50, 1.25, 10.00),
}
UNKNOWN_MODEL_PRICING = (2.50, 0.25, 15.00)  # conservative, so per-run cost caps still bite


# Image models, per 1M tokens: (text input, image input, image output)
IMAGE_PRICING: dict[str, tuple[float, float, float]] = {
    "gpt-image-2.5-flare": (5.00, 8.00, 30.00),
    "gpt-image-2.5-sunburst": (5.00, 8.00, 30.00),
    "gpt-image-1": (5.00, 10.00, 40.00),
}
UNKNOWN_IMAGE_PRICING = (5.00, 10.00, 40.00)


def estimate_image_cost(model: str, usage: dict[str, int]) -> float:
    match = max((m for m in IMAGE_PRICING if model.startswith(m)), key=len, default=None)
    ptext, pimg_in, pout = IMAGE_PRICING[match] if match else UNKNOWN_IMAGE_PRICING
    text_in = usage.get("text_input_tokens", usage.get("input_tokens", 0))
    img_in = usage.get("image_input_tokens", 0)
    return (text_in * ptext + img_in * pimg_in + usage.get("output_tokens", 0) * pout) / 1_000_000


def estimate_cost(model: str, input_tokens: int, cached: int, output_tokens: int) -> float:
    model = model.split("/")[-1]
    match = max((m for m in PRICING if model.startswith(m)), key=len, default=None)
    pin, pcached, pout = PRICING[match] if match else UNKNOWN_MODEL_PRICING
    return ((input_tokens - cached) * pin + cached * pcached + output_tokens * pout) / 1_000_000


# --------------------------------------------------------------------------- budget


class RunBudget:
    def __init__(self, stats: RunStats, *, max_calls: int, max_cost_usd: float, max_seconds: float):
        self.stats = stats
        self.max_calls = max_calls
        self.max_cost_usd = max_cost_usd
        self.deadline = time.monotonic() + max_seconds

    def check(self) -> None:
        if self.stats.llm_calls >= self.max_calls:
            raise BudgetExceeded(f"llm call budget exhausted ({self.max_calls})")
        if self.stats.cost_usd >= self.max_cost_usd:
            raise BudgetExceeded(f"cost budget exhausted (${self.max_cost_usd:.2f})")
        if time.monotonic() > self.deadline:
            raise BudgetExceeded("wall-clock budget exhausted")

    def charge(
        self, *, input_tokens: int, cached_input_tokens: int, output_tokens: int, cost_usd: float
    ) -> None:
        s = self.stats
        s.llm_calls += 1
        s.input_tokens += input_tokens
        s.cached_input_tokens += cached_input_tokens
        s.output_tokens += output_tokens
        s.cost_usd = round(s.cost_usd + cost_usd, 6)

    def charge_image(self, cost_usd: float) -> None:
        """Image-model spend (painted sprites): counts toward the run's $ budget."""
        self.stats.cost_usd = round(self.stats.cost_usd + cost_usd, 6)
        self.stats.image_cost_usd = round(self.stats.image_cost_usd + cost_usd, 6)


# --------------------------------------------------------------------------- model listing


async def list_openai_models(api_key: str | None, base_url: str | None) -> list[str]:
    from openai import AsyncOpenAI

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    page = await AsyncOpenAI(api_key=api_key, base_url=base_url).models.list()
    return sorted(m.id for m in page.data)
