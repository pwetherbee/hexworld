import { describe, expect, it } from "vitest";
import type { Event as HwEvent } from "../api/types.gen";
import { buildSpans } from "../ui/spans";
import { RateLimiter, activityFrame } from "./CameraDirector";
import { hexCorner, hexDistance, hexToWorld, hexesWithin, SQRT3 } from "./hexMath";

describe("hexMath (mirrors backend conventions)", () => {
  it("lays out pointy-top axial coords", () => {
    expect(hexToWorld(1, 0)).toEqual([SQRT3, 0]);
    expect(hexToWorld(0, 1)[1]).toBeCloseTo(1.5);
    const [x, z] = hexCorner(2);
    expect(x).toBeCloseTo(0);
    expect(z).toBeCloseTo(1); // a corner points straight "down" (+z)
  });
  it("counts hexes within a radius", () => {
    expect(hexesWithin(3)).toHaveLength(1 + 3 * 3 * 4);
    expect(hexDistance({ q: 0, r: 0 }, { q: 2, r: -1 })).toBe(2);
  });
});

describe("camera director", () => {
  it("rate limits retargets", () => {
    const l = new RateLimiter(1000);
    expect(l.ready(0)).toBe(true);
    l.fire(0);
    expect(l.ready(500)).toBe(false);
    expect(l.ready(1000)).toBe(true);
  });
  it("frames activity: centroid + distance grows with spread", () => {
    const one = activityFrame(["0,0"])!;
    const spread = activityFrame(["-3,0", "3,0"])!;
    expect(one.target.x).toBeCloseTo(0);
    expect(spread.target.x).toBeCloseTo(0);
    expect(spread.distance).toBeGreaterThan(one.distance);
    expect(activityFrame([])).toBeNull();
  });
});

describe("spans", () => {
  it("rebuilds a nested trace from flat events", () => {
    const ev = (id: number, type: string, span: string, parent: string | null, ts: number): HwEvent => ({
      id, ts, type, world_id: "w", run_id: "r", span_id: span, parent_span_id: parent, q: null, r: null, data: {},
    });
    const rows = buildSpans(
      [
        ev(1, "run.started", "a", null, 0),
        ev(2, "wave.started", "b", "a", 1),
        ev(3, "llm.call.started", "c", "b", 2),
        ev(4, "llm.call.finished", "c", "b", 3),
        ev(5, "wave.finished", "b", "a", 4),
        ev(6, "run.finished", "a", null, 5),
      ],
      "r",
    );
    expect(rows.map((r) => [r.name, r.depth])).toEqual([
      ["run", 0],
      ["wave", 1],
      ["llm.call", 2],
    ]);
    expect(rows[2].end).toBe(3);
  });
});
