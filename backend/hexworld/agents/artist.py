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
from hexworld.agents.llm import estimate_image_cost
from hexworld.art.paint import pixelize_sprite, style_frame
from hexworld.art.procedural import material_preview_png
from hexworld.art.sprites import lint, preview_png, rasterize
from hexworld.domain import World
from hexworld.domain.art import MaterialSpec, PackItem, Repaint, SpriteProgram
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

    def __init__(
        self,
        kit: AgentKit,
        *,
        world: World,
        name: str,
        is_connector: bool,
        reference: MaterialSpec | None = None,
    ):
        self.world = world
        self.name = name
        self.is_connector = is_connector
        self.reference = reference  # this terrain as drawn on the map above (a drilled layer)
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
            old = self.world.materials.get(self.name)
            if old is not None and old.buildings is not None and spec.buildings is None:
                return {
                    "error": f"'{self.name}' is a built terrain and tiles are laid out around its "
                    "buildings: keep `buildings` (revise how they look instead)"
                }
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
            "connectors": list(w.spec.connector_vocabulary) if w.spec else [],
            "scale": w.scale_note or "a tile is a landscape chunk or a city block",
        }
        if self.reference is not None:
            payload["on_the_map_above"] = {
                "note": "this terrain as drawn on the map this layer zooms into: keep its colours, "
                "character and (if built) its buildings, drawn at this closer scale",
                "spec": self.reference.model_dump(exclude_defaults=True),
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
            if hasattr(self.painter, "paint_subject"):  # batches into sprite sheets
                png, usage = await self.painter.paint_subject(subject, self.world.style)
            else:
                png, usage = await self.painter.paint(style_frame(self.world.style, subject))
            cost = estimate_image_cost(self.painter.model, usage)
            kit.budget.charge_image(cost)
            kit.tracer.emit(
                "image.painted",
                data={
                    "sprite": kind,
                    "model": self.painter.model,
                    "usage": usage,
                    "cost_usd": round(cost, 6),
                },
            )
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


class SpriteDirector:
    """Art-directs sprite PACKS: one session describes many sprites in one call, reviews the painted
    pack once, and takes later feedback on any of them. Replaces one artist session per sprite."""

    def __init__(self, kit: AgentKit, *, world: World):
        self.world = world
        self.holder: dict[str, Any] = {}

        def submit_pack(
            items: list[PackItem], tool_context: ToolContext, extras: list[PackItem] | None = None
        ) -> dict:
            """Submit one item per requested kind (subject, size, motion), plus optional `extras`:
            new ambient kinds for the pack's free cells, each with the `terrain` it lives on."""
            try:
                items = [coerce(PackItem, it) for it in items]
                extras = [coerce(PackItem, it) for it in (extras or [])]
            except (ValidationError, ValueError) as e:
                return {"error": str(e)[:700]}
            if not items:
                return {"error": "give one item per kind"}
            return submitted(tool_context, self.holder, items=items, extras=extras)

        def submit_repaints(repaints: list[Repaint], tool_context: ToolContext) -> dict:
            """Up to 4 sprites to repaint (with sharper subjects); an empty list if all read well."""
            try:
                repaints = [coerce(Repaint, r) for r in repaints][:4]
            except (ValidationError, ValueError) as e:
                return {"error": str(e)[:700]}
            return submitted(tool_context, self.holder, repaints=repaints)

        self.handle: AgentHandle = kit.agent(
            name="sprite_director",
            role="artist",
            instruction=prompts.ARTIST_SPRITE_PACK,
            tools=[submit_pack, submit_repaints],
            holder=self.holder,
            label="sprite director",
        )

    def _payload(self, kinds: dict[str, str], free: int = 0) -> dict[str, Any]:
        w = self.world
        extra = (
            {
                "free_cells": free,
                "terrains": [t for t in (w.spec.terrain_vocabulary if w.spec else [])],
            }
            if free > 0
            else {}
        )
        return {
            **extra,
            "task": "sprite_pack",
            "world": {"title": w.spec.title, "theme": w.spec.theme} if w.spec else None,
            "style_keywords": w.style.style_keywords if w.style else "",
            "palette": (w.style.palette[:32] if w.style else []),
            "already_painted": sorted(w.sprites)[:40],
            "kinds": [{"kind": k, "appears": ctx[:160]} for k, ctx in kinds.items()],
        }

    async def direct(
        self, kinds: dict[str, str], parent: Span | None, free: int = 0
    ) -> tuple[dict[str, PackItem], list[PackItem]]:
        """-> (one item per requested kind, extra ambient kinds for the free cells)."""
        self.holder.pop("items", None)
        self.holder.pop("extras", None)
        res = await self.handle.run([text_part(self._payload(kinds, free))], parent, max_calls=3)
        got = {it.kind: it for it in res.get("items", [])}
        out: dict[str, PackItem] = {}
        for k in kinds:  # the engine keeps the requested keys even if the model renames one
            it = got.get(k) or next((v for kk, v in got.items() if kk.lower().strip() == k), None)
            out[k] = (
                it.model_copy(update={"kind": k}) if it else PackItem(kind=k, subject=k.replace("_", " "))
            )
        extras = [e for e in res.get("extras") or [] if e.kind.strip() and e.kind not in out][:free]
        return out, extras

    async def review(self, sheet_png: bytes, kinds: list[str], parent: Span | None) -> list[Repaint]:
        self.holder.pop("repaints", None)
        msg = (
            "Here is the painted pack at game scale, left to right: "
            + ", ".join(kinds)
            + ". Call submit_repaints with the ones that don't read (max 4), or an empty list."
        )
        res = await self.handle.run([text_part(msg), image_part(sheet_png)], parent, max_calls=2)
        return [r for r in res.get("repaints", []) if r.kind in kinds]

    async def revise_many(self, notes: dict[str, str], parent: Span | None) -> list[PackItem]:
        """Feedback on several sprites at once -> improved items (painted together as one pack)."""
        self.holder.pop("items", None)
        msg = (
            "Feedback from the super agent on sprites as seen on the map:\n"
            + "\n".join(f"- '{k}': {fb}" for k, fb in notes.items())
            + "\nCall submit_pack with just these kinds, each improved."
        )
        res = await self.handle.run([text_part(msg)], parent, max_calls=2)
        out = []
        for it in res.get("items") or []:
            k = next((kk for kk in notes if kk == it.kind or kk == it.kind.lower().strip()), None)
            if k is not None:
                out.append(it.model_copy(update={"kind": k}))
        return out

    async def revise(self, kind: str, feedback: str, parent: Span | None) -> PackItem | None:
        self.holder.pop("items", None)
        msg = (
            f"Feedback from the super agent on the '{kind}' sprite as seen on the map: {feedback} "
            f"Call submit_pack with just '{kind}', improved."
        )
        res = await self.handle.run([text_part(msg)], parent, max_calls=2)
        items = res.get("items") or []
        return items[0].model_copy(update={"kind": kind}) if items else None
