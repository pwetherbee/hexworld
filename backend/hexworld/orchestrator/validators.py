"""Deterministic candidate checks: cheap, exact, run before any (expensive, fuzzy) vision review."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from hexworld.art.grid import TileCanvas, seam_delta
from hexworld.art.pixelize import PixelTile
from hexworld.hex import DIRECTION_NAMES


@dataclass
class CheckResult:
    ok: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    @property
    def feedback(self) -> str:
        return "; ".join(self.failures)


def check_candidate(
    pix: PixelTile,
    canvas: TileCanvas,
    accepted_neighbors: dict[int, np.ndarray],
    *,
    max_seam_delta: float,
    min_coverage: float,
    min_distinct_colors: int,
) -> CheckResult:
    res = CheckResult(ok=True)
    res.metrics["coverage"] = round(pix.coverage, 4)
    res.metrics["distinct_colors"] = pix.distinct_colors
    res.metrics["pixelize"] = pix.method
    # Palette compliance holds by construction (every pixel is a palette index), so it's
    # asserted rather than measured.
    res.metrics["palette_compliance"] = 1.0

    if pix.coverage < min_coverage:
        res.failures.append(
            f"image does not fill the hex ({pix.coverage:.0%} coverage); paint ground edge-to-edge"
        )
    if pix.distinct_colors < min_distinct_colors:
        res.failures.append(f"image is nearly flat ({pix.distinct_colors} colors); add texture and detail")

    seams: dict[str, float] = {}
    for edge, nb in accepted_neighbors.items():
        d = seam_delta(pix.rgba, canvas, edge, nb, TileCanvas(canvas.h.neighbor(edge), canvas.P))
        seams[str(edge)] = d
        if d > max_seam_delta:
            res.failures.append(
                f"visible seam on the {DIRECTION_NAMES[edge]} edge (delta {d:.2f}); continue the "
                f"neighbor's ground colors and texture right up to that edge"
            )
    res.metrics["seam_delta"] = seams
    res.ok = not res.failures
    return res
