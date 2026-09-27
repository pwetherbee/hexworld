import { describe, expect, it } from "vitest";
import { hexKey } from "./board/hexMath";
import { findPath } from "./play";

describe("findPath", () => {
  it("walks the shortest way over built tiles and around gaps", () => {
    const built = new Set([hexKey(0, 0), hexKey(1, 0), hexKey(2, 0), hexKey(1, -1), hexKey(2, -1), hexKey(3, -1)]);
    const ok = (k: string) => built.has(k);
    expect(findPath(hexKey(0, 0), hexKey(0, 0), ok)).toEqual([]);
    expect(findPath(hexKey(0, 0), hexKey(2, 0), ok)).toEqual([hexKey(1, 0), hexKey(2, 0)]);
    expect(findPath(hexKey(0, 0), hexKey(3, -1), ok)?.length).toBe(3);
    expect(findPath(hexKey(0, 0), hexKey(5, 5), ok)).toBeNull(); // not reachable over built tiles
  });
});
