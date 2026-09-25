"""LLM provider layer.

`LLMClient` is the only thing that talks to a model. Everything else goes through
`LLMGateway`, which adds: concurrency limits, tracing spans, transient-error retries,
schema validation with one repair round-trip, budget accounting, and recording.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar

import jsonschema
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from hexworld.domain import RunStats
from hexworld.telemetry import Span, Tracer

Role = Literal["super", "tile", "artist"]
T = TypeVar("T", bound=BaseModel)


# --------------------------------------------------------------------------- request / result


@dataclass
class ImagePart:
    png: bytes
    label: str | None = None
    detail: Literal["low", "high", "auto"] = "low"

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.png).hexdigest()[:16]


@dataclass
class LLMRequest:
    role: Role
    task: str  # also the structured-output schema name
    system: str
    payload: dict[str, Any]  # stable-first key order: helps provider-side prompt caching
    schema: dict[str, Any]
    images: list[ImagePart] = field(default_factory=list)

    def cache_key(self) -> str:
        blob = json.dumps(
            {"role": self.role, "task": self.task, "system": self.system, "payload": self.payload},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:32]


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    replayed: bool = False


class LLMClient(Protocol):
    name: str

    def model_for(self, role: Role) -> str: ...

    async def complete(self, req: LLMRequest) -> LLMResult: ...


class TransientLLMError(Exception):
    """Raised by clients for errors worth retrying (rate limits, 5xx, timeouts)."""


class BudgetExceeded(Exception):
    pass


class LLMOutputError(Exception):
    pass


# --------------------------------------------------------------------------- strict schema


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON Schema → OpenAI strict-mode compatible schema."""
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

# USD per 1M tokens: (input, cached input, output). Approximate; override via code as needed.
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


UNKNOWN_MODEL_PRICING = (2.50, 0.25, 15.00)


def estimate_cost(model: str, input_tokens: int, cached: int, output_tokens: int) -> float:
    match = max((m for m in PRICING if model.startswith(m)), key=len, default=None)
    # Unknown (newer) models: a deliberately conservative estimate so per-run cost caps still bite.
    pin, pcached, pout = PRICING[match] if match else UNKNOWN_MODEL_PRICING
    return ((input_tokens - cached) * pin + cached * pcached + output_tokens * pout) / 1_000_000


# --------------------------------------------------------------------------- OpenAI


class OpenAIClient:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        super_model: str,
        tile_model: str,
        super_reasoning: str = "",
        tile_reasoning: str = "",
        artist_model: str = "",
        artist_reasoning: str = "",
        timeout_s: float = 120.0,
    ):
        from openai import AsyncOpenAI

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set (required for HEXWORLD_LLM=openai)")
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0)
        self._models = {"super": super_model, "tile": tile_model, "artist": artist_model or tile_model}
        self._effort = {
            "super": super_reasoning,
            "tile": tile_reasoning,
            "artist": artist_reasoning or tile_reasoning,
        }

    def model_for(self, role: Role) -> str:
        return self._models[role]

    async def complete(self, req: LLMRequest) -> LLMResult:
        import openai

        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": json.dumps(req.payload, ensure_ascii=False, default=str)}
        ]
        for img in req.images:
            if img.label:
                content.append({"type": "input_text", "text": img.label})
            content.append(
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64," + base64.b64encode(img.png).decode(),
                    "detail": img.detail,
                }
            )
        kwargs: dict[str, Any] = {
            "model": self._models[req.role],
            "instructions": req.system,
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {"type": "json_schema", "name": req.task, "schema": req.schema, "strict": True}
            },
        }
        if self._effort[req.role]:
            kwargs["reasoning"] = {"effort": self._effort[req.role]}
        try:
            resp = await self._client.responses.create(**kwargs)
        except (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.InternalServerError,
        ) as e:
            raise TransientLLMError(str(e)) from e
        if getattr(resp, "status", "completed") == "incomplete":
            reason = getattr(getattr(resp, "incomplete_details", None), "reason", "unknown")
            raise LLMOutputError(f"response incomplete: {reason}")
        text = resp.output_text
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMOutputError(f"non-JSON output: {text[:200]!r}") from e
        usage = resp.usage
        itok = getattr(usage, "input_tokens", 0) or 0
        otok = getattr(usage, "output_tokens", 0) or 0
        cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        model = resp.model or self._models[req.role]
        return LLMResult(
            data=data,
            model=model,
            input_tokens=itok,
            cached_input_tokens=cached,
            output_tokens=otok,
            cost_usd=estimate_cost(model, itok, cached, otok),
        )

    async def list_models(self) -> list[str]:
        page = await self._client.models.list()
        return sorted(m.id for m in page.data)


# --------------------------------------------------------------------------- record / replay


class RecordingClient:
    """Wraps a real client and stores each response so the run can be replayed for free."""

    def __init__(self, inner: LLMClient, store: Any):
        self.inner = inner
        self.store = store
        self.name = f"{inner.name}+rec"

    def model_for(self, role: Role) -> str:
        return self.inner.model_for(role)

    async def complete(self, req: LLMRequest) -> LLMResult:
        res = await self.inner.complete(req)
        key = req.cache_key()
        seq = 0
        while self.store.get_llm_record(key, seq) is not None:
            seq += 1
        self.store.put_llm_record(
            key,
            seq,
            {
                "data": res.data,
                "model": res.model,
                "input_tokens": res.input_tokens,
                "cached_input_tokens": res.cached_input_tokens,
                "output_tokens": res.output_tokens,
                "cost_usd": res.cost_usd,
            },
        )
        return res


class ReplayClient:
    """Serves recorded responses by request key; identical requests replay in recorded order."""

    name = "replay"

    def __init__(self, store: Any, fallback: LLMClient | None = None):
        self.store = store
        self.fallback = fallback
        self._seq: dict[str, int] = defaultdict(int)

    def model_for(self, role: Role) -> str:
        return "replay"

    async def complete(self, req: LLMRequest) -> LLMResult:
        key = req.cache_key()
        seq = self._seq[key]
        rec = self.store.get_llm_record(key, seq) or (self.store.get_llm_record(key, 0) if seq else None)
        if rec is None:
            if self.fallback is None:
                raise LLMOutputError(f"no recorded response for {req.task} key={key[:8]}")
            return await self.fallback.complete(req)
        self._seq[key] = seq + 1
        return LLMResult(
            data=rec["data"],
            model=rec["model"],
            input_tokens=rec["input_tokens"],
            cached_input_tokens=rec["cached_input_tokens"],
            output_tokens=rec["output_tokens"],
            cost_usd=0.0,
            replayed=True,
        )


# --------------------------------------------------------------------------- gateway


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

    def charge(self, res: LLMResult) -> None:
        s = self.stats
        s.llm_calls += 1
        s.input_tokens += res.input_tokens
        s.cached_input_tokens += res.cached_input_tokens
        s.output_tokens += res.output_tokens
        s.cost_usd = round(s.cost_usd + res.cost_usd, 6)


class LLMGateway:
    def __init__(self, client: LLMClient, *, concurrency: int, tracer: Tracer, budget: RunBudget):
        self.client = client
        self.sem = asyncio.Semaphore(concurrency)
        self.tracer = tracer
        self.budget = budget

    async def call(
        self,
        req: LLMRequest,
        model_type: type[T] | None,
        *,
        parent: Span | None,
        validate: Callable[[dict[str, Any]], Any] | None = None,
    ) -> tuple[T | dict[str, Any], LLMResult]:
        """Run one structured call. Validates against the JSON schema, then the pydantic model /
        custom validator; on failure, re-asks once with the error appended ("repair")."""
        last_err: str | None = None
        for repair in range(2):
            r = req
            if last_err:
                r = LLMRequest(
                    role=req.role,
                    task=req.task,
                    system=req.system,
                    schema=req.schema,
                    images=req.images,
                    payload={**req.payload, "previous_output_error": last_err},
                )
            self.budget.check()
            async with (
                self.sem,
                self.tracer.span(
                    "llm.call",
                    parent,
                    role=req.role,
                    task=req.task,
                    model=self.client.model_for(req.role),
                    images=len(req.images),
                    repair=repair,
                ) as span,
            ):
                res = await self._complete_with_retry(r)
                self.budget.charge(res)
                span.set(
                    input_tokens=res.input_tokens,
                    cached_input_tokens=res.cached_input_tokens,
                    output_tokens=res.output_tokens,
                    cost_usd=round(res.cost_usd, 6),
                    replayed=res.replayed,
                    output=_truncate(res.data),
                )
                try:
                    jsonschema.validate(res.data, req.schema)
                    obj: Any = model_type.model_validate(res.data) if model_type else res.data
                    if validate:
                        validate(obj)
                    return obj, res
                except (jsonschema.ValidationError, ValidationError, ValueError) as e:
                    last_err = _short_error(e)
                    span.set(invalid=last_err)
        raise LLMOutputError(f"{req.task}: invalid output after repair: {last_err}")

    async def _complete_with_retry(self, req: LLMRequest) -> LLMResult:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(4),
            wait=wait_exponential_jitter(initial=1, max=20),
            retry=retry_if_exception(lambda e: isinstance(e, TransientLLMError)),
            reraise=True,
        ):
            with attempt:
                return await self.client.complete(req)
        raise AssertionError("unreachable")


def _short_error(e: Exception) -> str:
    if isinstance(e, jsonschema.ValidationError):
        path = "/".join(str(p) for p in e.absolute_path)
        return f"schema error at '{path}': {e.message}"[:600]
    return str(e)[:600]


def _truncate(data: Any, limit: int = 4000) -> Any:
    s = json.dumps(data, default=str)
    return data if len(s) <= limit else s[:limit] + "…"
