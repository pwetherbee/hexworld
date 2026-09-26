"""Google ADK integration: builds agents, runs them in persistent sessions, and bridges everything
into HexWorld's budgets and event stream.

- Every agent is an ADK `LlmAgent` with tools. Results come back through `submit_*` tools, which
  validate their input: errors return to the agent, which fixes and resubmits. A successful
  submit sets `skip_summarization` to end the turn.
- Sessions persist per agent instance (a tile agent across attempts, the reviewer across waves,
  the director across rings), so feedback continues the same conversation.
- Model callbacks enforce the run budget and emit `llm.call` spans with token usage and cost.
  Tool calls and results become `agent.tool` events. Each agent turn is an `agent` span.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.adk.agents.run_config import RunConfig
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from hexworld.agents.llm import BudgetExceeded, Role, RunBudget, estimate_cost
from hexworld.telemetry import Span, Tracer, new_id

APP = "hexworld"
USER = "hexworld"


def text_part(obj: Any) -> types.Part:
    return types.Part.from_text(
        text=obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    )


def image_part(png: bytes) -> types.Part:
    return types.Part.from_bytes(data=png, mime_type="image/png")


def _clip(v: Any, n: int = 600) -> Any:
    s = json.dumps(v, default=str)
    return v if len(s) <= n else s[:n] + "…"


@dataclass
class AgentHandle:
    """One agent + its persistent session. `run()` sends a message and returns whatever the
    agent's submit tool stored in `result`."""

    kit: AgentKit
    agent: LlmAgent
    session_id: str
    label: str
    q: int | None = None
    r: int | None = None
    result: dict[str, Any] = field(default_factory=dict)
    turns: int = 0

    async def run(
        self, parts: list[types.Part], parent: Span | None, *, max_calls: int = 8
    ) -> dict[str, Any]:
        self.result.clear()
        self.turns += 1
        await self.kit._run(self, parts, parent, max_calls)
        return dict(self.result)


class AgentKit:
    def __init__(
        self,
        *,
        tracer: Tracer,
        budget: RunBudget,
        model_factory: Callable[[Role], BaseLlm],
        concurrency: int = 8,
    ):
        self.tracer = tracer
        self.budget = budget
        self.model_factory = model_factory
        self.sessions = InMemorySessionService()
        self.sem = asyncio.Semaphore(concurrency)
        self._agent_spans: dict[str, Span] = {}  # session id -> current agent span
        self._calls: dict[str, tuple[str, float]] = {}  # session id -> (llm span id, t0)
        self._models: dict[str, str] = {}  # agent name -> model name

    # ------------------------------------------------------------------ building
    def agent(
        self,
        *,
        name: str,
        role: Role,
        instruction: str,
        tools: list[Any],
        label: str,
        q: int | None = None,
        r: int | None = None,
        holder: dict[str, Any] | None = None,
    ) -> AgentHandle:
        model = self.model_factory(role)
        agent = LlmAgent(
            name=name,
            model=model,
            instruction=instruction,
            tools=tools,
            before_model_callback=self._before_model,
            after_model_callback=self._after_model,
            on_tool_error_callback=self._on_tool_error,
        )
        self._models[name] = getattr(model, "model", str(model))
        return AgentHandle(
            self, agent, new_id("sess"), label, q, r, result=holder if holder is not None else {}
        )

    # ------------------------------------------------------------------ running
    async def _run(
        self, h: AgentHandle, parts: list[types.Part], parent: Span | None, max_calls: int
    ) -> None:
        runner = Runner(agent=h.agent, app_name=APP, session_service=self.sessions, auto_create_session=True)
        async with (
            self.sem,
            self.tracer.span(
                "agent",
                parent,
                q=h.q,
                r=h.r,
                agent=h.agent.name,
                label=h.label,
                turn=h.turns,
                model=self._models.get(h.agent.name),
            ) as sp,
        ):
            self._agent_spans[h.session_id] = sp
            try:
                async for ev in runner.run_async(
                    user_id=USER,
                    session_id=h.session_id,
                    new_message=types.Content(role="user", parts=parts),
                    run_config=RunConfig(max_llm_calls=max_calls),
                ):
                    self._on_event(h, ev, sp)
            except LlmCallsLimitExceededError:
                sp.set(stopped="per-agent call limit reached")
            finally:
                self._agent_spans.pop(h.session_id, None)
            sp.set(submitted=bool(h.result))

    def _on_event(self, h: AgentHandle, ev: Any, sp: Span) -> None:
        for fc in ev.get_function_calls() or []:
            sp.event("agent.tool_call", agent=h.agent.name, tool=fc.name, args=_clip(fc.args or {}))
        for fr in ev.get_function_responses() or []:
            resp = fr.response or {}
            sp.event(
                "agent.tool_result",
                agent=h.agent.name,
                tool=fr.name,
                response=_clip(resp, 400),
                error=resp.get("error") if isinstance(resp, dict) else None,
            )
        content = getattr(ev, "content", None)
        if ev.author != "user" and content and content.parts and not ev.partial:
            text = " ".join(
                p.text for p in content.parts if getattr(p, "text", None) and not getattr(p, "thought", False)
            )
            if text.strip():
                sp.event("agent.message", agent=h.agent.name, text=text[:800])

    # ------------------------------------------------------------------ callbacks
    def _before_model(self, callback_context: Any, llm_request: LlmRequest) -> LlmResponse | None:
        self.budget.check()  # raises BudgetExceeded -> aborts the agent turn
        sid = callback_context.session.id
        parent = self._agent_spans.get(sid)
        span_id = new_id("sp")
        self.tracer.emit(
            "llm.call.started",
            span_id=span_id,
            parent_span_id=parent.id if parent else None,
            q=parent.base.get("q") if parent else None,
            r=parent.base.get("r") if parent else None,
            data={
                "agent": callback_context.agent_name,
                "model": self._models.get(callback_context.agent_name),
            },
        )
        self._calls[sid] = (span_id, time.perf_counter())
        return None

    def _after_model(self, callback_context: Any, llm_response: LlmResponse) -> LlmResponse | None:
        sid = callback_context.session.id
        span_id, t0 = self._calls.pop(sid, (new_id("sp"), time.perf_counter()))
        parent = self._agent_spans.get(sid)
        u = llm_response.usage_metadata
        itok = (u.prompt_token_count or 0) if u else 0
        otok = ((u.candidates_token_count or 0) + (u.thoughts_token_count or 0)) if u else 0
        cached = (u.cached_content_token_count or 0) if u else 0
        model = self._models.get(callback_context.agent_name, "")
        cost = estimate_cost(model, itok, cached, otok)
        self.budget.charge(input_tokens=itok, cached_input_tokens=cached, output_tokens=otok, cost_usd=cost)
        calls = [
            p.function_call.name
            for p in (
                llm_response.content.parts if llm_response.content and llm_response.content.parts else []
            )
            if p.function_call
        ]
        self.tracer.emit(
            "llm.call.finished",
            span_id=span_id,
            parent_span_id=parent.id if parent else None,
            q=parent.base.get("q") if parent else None,
            r=parent.base.get("r") if parent else None,
            data={
                "ok": not llm_response.error_code,
                "agent": callback_context.agent_name,
                "model": model,
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                "input_tokens": itok,
                "cached_input_tokens": cached,
                "output_tokens": otok,
                "cost_usd": round(cost, 6),
                "tool_calls": calls,
                "error": llm_response.error_message,
            },
        )
        return None

    def _on_tool_error(self, tool: Any, args: dict, tool_context: Any, error: Exception) -> dict | None:
        if isinstance(error, (BudgetExceeded, asyncio.CancelledError)):
            return None  # propagate
        return {
            "error": f"{type(error).__name__}: {error}"[:900],
            "hint": "fix the arguments and call the tool again",
        }


# --------------------------------------------------------------------------- submit helper


def submitted(tool_context: Any, holder: dict[str, Any], **values: Any) -> dict[str, Any]:
    """Store a submit tool's validated result and end the agent's turn (no summarization call)."""
    holder.update(values)
    tool_context.actions.skip_summarization = True
    return {"status": "submitted"}


# --------------------------------------------------------------------------- models


def openai_model_factory(settings: Any) -> Callable[[Role], BaseLlm]:
    from google.adk.models.lite_llm import LiteLlm

    def make(role: Role) -> BaseLlm:
        name = {
            "super": settings.super_model,
            "tile": settings.tile_model,
            "artist": settings.artist_model or settings.tile_model,
        }[role]
        effort = {
            "super": settings.super_reasoning,
            "tile": settings.tile_reasoning,
            "artist": settings.artist_reasoning or settings.tile_reasoning,
        }[role]
        kwargs: dict[str, Any] = {
            "api_key": settings.openai_api_key,
            "drop_params": True,
            "timeout": settings.llm_timeout_s if role == "super" else settings.small_llm_timeout_s,
            "num_retries": 3,
        }
        if effort:
            kwargs["reasoning_effort"] = effort
        if settings.openai_base_url:
            kwargs["api_base"] = settings.openai_base_url
        return LiteLlm(model=f"openai/{name}", **kwargs)

    return make


class FakeAdkLlm(BaseLlm):
    """Test double: a scripted 'model' that reads the task payload from the first user message
    and answers with the tool calls a well-behaved agent would make (via FakeClient's handlers)."""

    brain: Any = None
    latency_s: float = 0.0

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        payload: dict[str, Any] = {}
        called: list[str] = []
        last_response: dict[str, Any] | None = None
        user_texts: list[str] = []
        for c in llm_request.contents:
            for p in c.parts or []:
                if p.text and c.role == "user":
                    user_texts.append(p.text)
                    if not payload:
                        try:
                            payload = json.loads(p.text)
                        except (ValueError, TypeError):
                            pass
                if p.function_call:
                    called.append(p.function_call.name)
                if p.function_response:
                    last_response = p.function_response.response or {}
        name, args = self.brain.act(
            payload, called, last_response, user_texts[1:], set(llm_request.tools_dict)
        )
        part = types.Part.from_function_call(name=name, args=args)
        n_in = sum(len(t) for t in user_texts) // 4 + 200
        yield LlmResponse(
            content=types.Content(role="model", parts=[part]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=n_in,
                candidates_token_count=len(json.dumps(args)) // 4 + 5,
                cached_content_token_count=0,
                total_token_count=n_in + 50,
            ),
        )


def fake_model_factory(brain: Any, latency_s: float = 0.0) -> Callable[[Role], BaseLlm]:
    def make(role: Role) -> BaseLlm:
        return FakeAdkLlm(model=f"fake-{role}", brain=brain, latency_s=latency_s)

    return make


def coerce(model_cls: Any, value: Any) -> Any:
    """Tool args normally arrive as validated models, but a model sometimes sends a raw dict (or a
    JSON string). Normalise to the model class; raises pydantic's ValidationError with details."""
    if isinstance(value, model_cls):
        return value
    if isinstance(value, str):
        value = json.loads(value)
    return model_cls.model_validate(value)
