import { describe, expect, it } from "vitest";
import { zoomLevels, type Levels } from "./relief";

function levels(C: number, fill: (i: number, j: number) => [number, number]): Levels {
  const n = C * C;
  const lv: Levels = {
    C,
    data: new Uint8Array(n),
    liquid: new Uint8Array(n),
    code: new Uint8Array(n),
    floor: new Uint8Array(n),
  };
  for (let j = 0; j < C; j++)
    for (let i = 0; i < C; i++) {
      const [level, code] = fill(i, j);
      lv.data[j * C + i] = level;
      lv.code[j * C + i] = code;
    }
  return lv;
}

describe("zoomLevels", () => {
  it("raises buildings a full zoom per floor on ground that only grows by the landform share", () => {
    // level-1 ground, a 4-floor building (level 5) in the middle, a level-5 hill on the right edge
    const lv = levels(8, (i, j) => (i >= 3 && i <= 4 && j >= 3 && j <= 4 ? [5, 33] : i === 7 ? [5, 0] : [1, 0]));
    const z = zoomLevels(lv, 7);
    expect(z.data[0]).toBe(1); // ground stays where the region's ground is
    expect(z.data[3 * 8 + 3]).toBe(1 + 4 * 7); // 4 floors, 7 levels each
    expect(z.floor[3 * 8 + 3]).toBe(7); // windows per real floor
    expect(z.data[7]).toBe(Math.round(1 + 4 * 7 * 0.25)); // a hill rises by the landform share
  });
});
