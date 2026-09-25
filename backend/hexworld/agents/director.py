"""Super director (Google ADK): manages the build between rings.

After each ring it looks at the map so far and can steer the rest of the run: re-plan tiles that
haven't been generated yet, commission sprites ahead of time, or order an accepted tile redone
with feedback. It ends its turn with `finish(note)`. Notes carry over to the next ring.
"""

from typing import Any

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field

from hexworld.agents import prompts
from hexworld.agents.kit import AgentKit, coerce, image_part, submitted, text_part
from hexworld.domain import World
from hexworld.telemetry import Span


class TileChange(BaseModel):
    q: int
    r: int
    biome: str | None = Field(default=None, description="new biome (from terrain_vocabulary)")
    intent: str | None = Field(default=None, description="new one-line intent")
    features: list[str] | None = Field(default=None, description="new landmark list (0 or 1 item)")
    leave_empty: bool | None = Field(default=None, description="true to drop the slot")


async def direct(
    kit: AgentKit,
    *,
    api: Any,
    world: World,
    ring: int,
    rings_total: int,
    notes: list[str],
    parent: Span | None,
) -> str | None:
    holder: dict[str, Any] = {}

    def view_map() -> dict:
        """See everything built so far (top-down render) with progress numbers."""
        return {"progress": api.progress(), "map": image_part(api.map_png())}

    def list_pending() -> dict:
        """Tiles planned but not generated yet (you can still change these)."""
        return {"tiles": api.pending()}

    def update_tiles(changes: list[TileChange]) -> dict:
        """Re-plan pending tiles: change biome, intent or landmark, or drop a slot."""
        try:
            changes = [coerce(TileChange, c) for c in changes]
        except ValueError as e:
            return {"error": str(e)[:700]}
        return api.update_tiles(changes)

    async def commission_sprite(kind: str, brief: str) -> dict:
        """Have the sprite artist design a landmark now (e.g. before tiles that will use it)."""
        entry, _ = await api.commission_sprite(kind, brief, None, None)
        return (
            {"kind": entry.kind, "size_px": [entry.px_w, entry.px_h]} if entry else {"error": "artist failed"}
        )

    def redo_tile(q: int, r: int, feedback: str) -> dict:
        """Order an already accepted tile to be regenerated, with feedback for its tile agent."""
        return api.redo_tile(q, r, feedback)

    def finish(note: str, tool_context: ToolContext) -> dict:
        """End this check-in with a short note for your future self (what you changed and why)."""
        return submitted(tool_context, holder, note=note)

    h = kit.agent(
        name="super_director",
        role="super",
        instruction=prompts.SUPER_DIRECT,
        tools=[view_map, list_pending, update_tiles, commission_sprite, redo_tile, finish],
        label=f"direct after ring {ring}",
        holder=holder,
    )
    payload = {
        "task": "direct",
        "world": world.spec.model_dump() if world.spec else None,
        "ring_completed": ring,
        "rings_total": rings_total,
        "progress": api.progress(),
        "your_notes_so_far": notes[-8:],
    }
    res = await h.run(
        [text_part(payload), text_part("The map so far:"), image_part(api.map_png())], parent, max_calls=8
    )
    return res.get("note")
