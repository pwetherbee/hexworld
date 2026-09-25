"""Artist sub-agents (Google ADK): design materials and sprites, looking at their own renders.

Each artist drafts a program, calls its render tool to SEE the result (an image comes back to the
model), revises, and submits. The submit tool is the only way a result enters the world library.
The sprite artist's session persists, so the super's `sprite_feedback` can be sent back to the
same artist, which revises in context.
"""

from typing import Any, Literal

from google.adk.tools import ToolContext
from pydantic import ValidationError

from hexworld.agents import prompts
from hexworld.agents.kit import AgentHandle, AgentKit, coerce, image_part, submitted, text_part
from hexworld.art.paint import pixelize_sprite, style_frame
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
    """One sprite artist per library sprite; keeps its session for later feedback rounds.

    With a painter (image model) the artist ART-DIRECTS: it writes a subject description, the
    painter paints it in the house style, the engine pixelizes it to game scale, and the artist
    looks at that result and repaints until it reads well. Without one it draws with the sprite DSL.
    Either way the result is a SpriteArt in `holder["art"]`.
    """

    def __init__(self, kit: AgentKit, *, world: World, kind: str, painter: Any = None):
        self.world = world
        self.kind = kind
        self.painter = painter
        self.holder: dict[str, Any] = {}
        self.renders = 0
        self._last: dict[str, Any] = {}

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

        def submit_program(program: SpriteProgram, tool_context: ToolContext) -> dict:
            """Submit the final sprite program to the world library."""
            try:
                program = coerce(SpriteProgram, program)
            except (ValidationError, ValueError) as e:
                return {"error": str(e)[:700]}
            return submitted(tool_context, self.holder, art=rasterize(program), program=program)

        async def paint_sprite(subject: str, size: Literal["small", "medium", "large"]) -> dict:
            """Paint the prop with the image model (the house pixel-art style is added for you), then
            LOOK at the pixelized result at game scale. `subject`: what it is, its materials,
            colours (from the world palette), silhouette and distinctive details."""
            if self.renders >= MAX_RENDERS:
                return {"error": "paint budget used (3): submit the best version with submit_sprite"}
            self.renders += 1
            png = await self.painter.paint(style_frame(self.world.style, subject))
            try:
                art = pixelize_sprite(png, size)
            except ValueError as e:
                return {"error": str(e)}
            self._last = {"art": art, "prompt": subject}
            return {"size_px": [art.w, art.h], "result": image_part(preview_png(art, scale=6))}

        def submit_sprite(
            motion: Literal["none", "sway", "bob", "flicker", "pulse"], tool_context: ToolContext
        ) -> dict:
            """Submit your latest painted sprite to the world library, with its idle motion."""
            if not self._last:
                return {"error": "paint the sprite first with paint_sprite"}
            art = self._last["art"]
            art.motion = motion
            return submitted(tool_context, self.holder, art=art, program=None, prompt=self._last["prompt"])

        tools = [paint_sprite, submit_sprite] if painter is not None else [render_sprite, submit_program]
        if painter is None:
            submit_program.__name__ = "submit_sprite"
        self.handle: AgentHandle = kit.agent(
            name="sprite_artist",
            role="artist",
            instruction=prompts.ARTIST_SPRITE_PAINT if painter is not None else prompts.ARTIST_SPRITE,
            tools=tools,
            holder=self.holder,
            label=f"sprite: {kind}",
        )

    async def design(
        self, *, context: str, anchor_png: bytes | None, parent: Span | None
    ) -> dict[str, Any] | None:
        w = self.world
        payload = {
            "task": "sprite_design",
            "world": {"title": w.spec.title, "theme": w.spec.theme} if w.spec else None,
            "style_keywords": w.style.style_keywords if w.style else "",
            "palette": (w.style.palette[:32] if w.style else []),
            "library": {k: [e.px_w, e.px_h] for k, e in w.sprites.items()},
            "kind": self.kind,
            "context": context,
        }
        self.renders = 0
        res = await self.handle.run([text_part(payload)], parent, max_calls=7)
        return res if "art" in res else None

    async def revise(self, feedback: str, *, parent: Span | None) -> dict[str, Any] | None:
        """Agent-to-agent feedback: the super's note continues this artist's own session."""
        self.renders = 0
        msg = (
            f"Feedback from the super agent on your '{self.kind}' sprite as seen on the map: {feedback}\n"
            "Revise it and submit the new version with submit_sprite."
        )
        res = await self.handle.run([text_part(msg)], parent, max_calls=6)
        return res if "art" in res else None
