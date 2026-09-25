"""Artist sub-agents (Google ADK): design materials and sprites, looking at their own renders.

Each artist drafts a program, calls its render tool to SEE the result (an image comes back to the
model), revises, and submits. The submit tool is the only way a result enters the world library.
The sprite artist's session persists, so the super's `sprite_feedback` can be sent back to the
same artist, which revises in context.
"""

from typing import Any

from google.adk.tools import ToolContext
from pydantic import ValidationError

from hexworld.agents import prompts
from hexworld.agents.kit import AgentHandle, AgentKit, coerce, image_part, submitted, text_part
from hexworld.art.procedural import material_preview_png
from hexworld.art.sprites import lint, preview_png, rasterize
from hexworld.domain import World
from hexworld.domain.art import MaterialSpec, SpriteProgram
from hexworld.telemetry import Span

MAX_RENDERS = 3


def _style_payload(world: World) -> dict[str, Any]:
    assert world.spec is not None and world.style is not None
    return {
        "world": {"title": world.spec.title, "theme": world.spec.theme, "genre": world.spec.genre},
        "style": world.style.model_dump(),
    }


class MaterialArtist:
    """One material artist per terrain; keeps its session so the super's material_feedback can
    come back to the artist who designed it."""

    def __init__(self, kit: AgentKit, *, world: World, name: str, is_connector: bool):
        self.world = world
        self.name = name
        self.is_connector = is_connector
        self.holder: dict[str, Any] = {}
        self.renders = 0
        tile_px = world.style.tile_px if world.style else 32

        def render_material(spec: MaterialSpec) -> dict:
            """Render your material on a patch of hex tiles (4 tiles of it, plus one tile bordering
            a contrasting material) and LOOK at the image before submitting."""
            try:
                spec = coerce(MaterialSpec, spec)
            except (ValidationError, ValueError) as e:
                return {"error": str(e)[:700]}
            self.renders += 1
            out: dict[str, Any] = {"render": image_part(material_preview_png(name, spec, tile_px))}
            if self.renders >= MAX_RENDERS:
                out["note"] = "render budget used: submit your best version now with submit_material"
            return out

        def submit_material(spec: MaterialSpec, tool_context: ToolContext) -> dict:
            """Submit the final material to the world library."""
            try:
                spec = coerce(MaterialSpec, spec)
            except (ValidationError, ValueError) as e:
                return {"error": str(e)[:700]}
            return submitted(tool_context, self.holder, spec=spec)

        self.handle: AgentHandle = kit.agent(
            name="material_artist",
            role="artist",
            instruction=prompts.ARTIST_MATERIAL,
            tools=[render_material, submit_material],
            holder=self.holder,
            label=f"material: {name}",
        )

    async def design(self, *, parent: Span | None) -> MaterialSpec | None:
        w = self.world
        payload = {
            "task": "material_design",
            **_style_payload(w),
            "existing_materials": {
                k: {"base_color": v.base_color, "rank": v.rank} for k, v in w.materials.items()
            },
            "material": self.name,
            "is_connector": self.is_connector,
        }
        self.renders = 0
        res = await self.handle.run([text_part(payload)], parent, max_calls=6)
        return res.get("spec")

    async def revise(self, feedback: str, *, parent: Span | None) -> MaterialSpec | None:
        """Agent-to-agent feedback: the super's note on how this terrain reads on the map."""
        self.renders = 0
        msg = (
            f"Feedback from the super agent on '{self.name}' as it looks across the map: {feedback}\n"
            "Revise the material (render to check) and submit it with submit_material. Every tile using "
            "it will be repainted with your new version."
        )
        res = await self.handle.run([text_part(msg)], parent, max_calls=6)
        return res.get("spec")


class SpriteArtist:
    """One sprite artist per library sprite; keeps its session for later feedback rounds."""

    def __init__(self, kit: AgentKit, *, world: World, kind: str):
        self.world = world
        self.kind = kind
        self.holder: dict[str, Any] = {}
        self.renders = 0

        def render_sprite(program: SpriteProgram) -> dict:
            """Rasterize your sprite program and LOOK at the result (all frames, enlarged, on a
            ground line), with automatic lint notes. Use it to check and refine before submitting."""
            try:
                program = coerce(SpriteProgram, program)
            except (ValidationError, ValueError) as e:
                return {"error": str(e)[:700]}
            self.renders += 1
            art = rasterize(program)
            out: dict[str, Any] = {
                "size": [art.w, art.h],
                "frames": len(art.frames),
                "lint": lint(program, art),
                "render": image_part(preview_png(art)),
            }
            if self.renders >= MAX_RENDERS:
                out["note"] = "render budget used: submit your best version now with submit_sprite"
            return out

        def submit_sprite(program: SpriteProgram, tool_context: ToolContext) -> dict:
            """Submit the final sprite program to the world library."""
            try:
                program = coerce(SpriteProgram, program)
            except (ValidationError, ValueError) as e:
                return {"error": str(e)[:700]}
            return submitted(tool_context, self.holder, program=program)

        self.handle: AgentHandle = kit.agent(
            name="sprite_artist",
            role="artist",
            instruction=prompts.ARTIST_SPRITE,
            tools=[render_sprite, submit_sprite],
            holder=self.holder,
            label=f"sprite: {kind}",
        )

    async def design(
        self, *, context: str, anchor_png: bytes | None, parent: Span | None
    ) -> SpriteProgram | None:
        w = self.world
        payload = {
            "task": "sprite_design",
            **_style_payload(w),
            "library": {k: [e.px_w, e.px_h] for k, e in w.sprites.items()},
            "tile_px": w.style.tile_px if w.style else 32,
            "kind": self.kind,
            "context": context,
        }
        parts = [text_part(payload)]
        if anchor_png:
            parts += [text_part("World anchor tile (match its look):"), image_part(anchor_png)]
        self.renders = 0
        res = await self.handle.run(parts, parent, max_calls=7)
        return res.get("program")

    async def revise(self, feedback: str, *, parent: Span | None) -> SpriteProgram | None:
        """Agent-to-agent feedback: the super's note continues this artist's own session."""
        self.renders = 0
        msg = (
            f"Feedback from the super agent on your '{self.kind}' sprite as seen on the map: {feedback}\n"
            "Revise it (render to check) and submit the new version with submit_sprite."
        )
        res = await self.handle.run([text_part(msg)], parent, max_calls=6)
        return res.get("program")
