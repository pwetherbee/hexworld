"""Tile duplication: shallow (linked instance) and deep (independent snapshot) copies.

A copy costs no LLM or image calls. It must still honor the continuity contract: its edge specs
must match every accepted neighbor, and its pixels must pass the same seam check as a generated
tile. Otherwise the orchestrator falls back to generating the slot normally.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from hexworld.art.pixelize import seam_delta
from hexworld.domain import Coord, Tile, TileStatus
from hexworld.hex import Hex, opposite


def resolve_root(tiles: dict[Hex, Tile], h: Hex, max_depth: int = 8) -> Hex:
    """Follow copy_of links to the original prototype (copies of copies collapse to the root)."""
    seen = 0
    t = tiles.get(h)
    while t is not None and t.copy_of is not None and seen < max_depth:
        h = t.copy_of.hex
        t = tiles.get(h)
        seen += 1
    return h


def copy_fits(
    target: Hex,
    source: Tile,
    tiles: dict[Hex, Tile],
    array: Callable[[str], np.ndarray],
    max_seam_delta: float,
    check_pixels: bool = True,
) -> tuple[bool, str, dict[str, float]]:
    """Edge contract always; pixel seams only when the copy will reuse the prototype's pixels
    (a copy re-rendered in place by a deterministic ground renderer is seamless by construction)."""
    if source.status != TileStatus.accepted or not source.asset_id or not source.edges:
        return False, "prototype is not an accepted tile", {}
    src_img = array(source.ground_asset_id or source.asset_id)
    seams: dict[str, float] = {}
    for i in range(6):
        n = tiles.get(target.neighbor(i))
        if not (n and n.status == TileStatus.accepted and n.edges and n.asset_id):
            continue
        facing = n.edges[opposite(i)]
        if not source.edges[i].compatible_with(facing):
            return (
                False,
                f"edge {i} mismatch: prototype has {source.edges[i].terrain}{source.edges[i].connectors}, "
                f"neighbor needs {facing.terrain}{facing.connectors}",
                seams,
            )
        if not check_pixels:
            continue
        d = seam_delta(src_img, i, array(n.ground_asset_id or n.asset_id))
        seams[str(i)] = d
        if d > max_seam_delta:
            return False, f"visible seam on edge {i} (delta {d:.2f})", seams
    return True, "", seams


def apply_copy(target: Tile, source: Tile, mode: str) -> None:
    """Materialize a copy onto `target`. A deep copy snapshots the data. A shallow copy is kept in
    sync with its prototype by `sync_shallow_copies`."""
    target.status = TileStatus.accepted
    target.biome = source.biome
    target.summary = source.summary
    target.attributes = dict(source.attributes)
    target.edges = [e.model_copy(deep=True) for e in source.edges or []]
    target.asset_id = source.asset_id  # assets are immutable + content-addressed: safe to share
    target.ground_asset_id = source.ground_asset_id
    target.layers = [layer.model_copy() for layer in source.layers]
    target.relief = source.relief
    target.side_color = source.side_color
    target.art_prompt = source.art_prompt
    target.preview_asset_id = None
    target.copy_of = Coord(q=source.q, r=source.r)
    target.copy_mode = mode  # type: ignore[assignment]


def sync_shallow_copies(source: Tile, tiles: dict[Hex, Tile]) -> list[Tile]:
    """Push a prototype's current art and data to all of its shallow instances. Deep copies are
    left alone."""
    changed = []
    for t in tiles.values():
        if t is source or t.copy_mode != "shallow" or t.copy_of is None:
            continue
        if (t.copy_of.q, t.copy_of.r) != (source.q, source.r):
            continue
        apply_copy(t, source, "shallow")
        changed.append(t)
    return changed
