// Mirrors backend/hexworld/hex: pointy-top axial coordinates.
// Screen/pixel y (down) maps to world +z; the board lies in the XZ plane.

export const SQRT3 = Math.sqrt(3);
export const HEX_SIZE = 1; // circumradius in world units
export const DIRECTIONS: ReadonlyArray<[number, number]> = [
  [1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1],
];
export const DIRECTION_NAMES = ["E", "NE", "NW", "W", "SW", "SE"] as const;

export type Axial = { q: number; r: number };

export const hexKey = (q: number, r: number) => `${q},${r}`;

export function parseKey(key: string): Axial {
  const [q, r] = key.split(",").map(Number);
  return { q, r };
}

export function hexToWorld(q: number, r: number, size = HEX_SIZE): [number, number] {
  return [size * SQRT3 * (q + r / 2), size * 1.5 * r];
}

export function hexDistance(a: Axial, b: Axial): number {
  const dq = a.q - b.q;
  const dr = a.r - b.r;
  return Math.max(Math.abs(dq), Math.abs(dr), Math.abs(dq + dr));
}

export function hexesWithin(radius: number): Axial[] {
  const out: Axial[] = [];
  for (let q = -radius; q <= radius; q++) {
    for (let r = Math.max(-radius, -q - radius); r <= Math.min(radius, -q + radius); r++) {
      out.push({ q, r });
    }
  }
  return out;
}

/** Corner i of a pointy-top hex (angles -30 + 60i degrees), as world [x, z]. */
export function hexCorner(i: number, size = HEX_SIZE): [number, number] {
  const a = ((-30 + 60 * i) * Math.PI) / 180;
  return [size * Math.cos(a), size * Math.sin(a)];
}

/** World [x, z] -> containing hex (cube rounding). */
export function worldToHex(x: number, z: number, size = HEX_SIZE): Axial {
  const qf = ((SQRT3 / 3) * x - z / 3) / size;
  const rf = ((2 / 3) * z) / size;
  const sf = -qf - rf;
  let q = Math.round(qf);
  let r = Math.round(rf);
  const s = Math.round(sf);
  const dq = Math.abs(q - qf);
  const dr = Math.abs(r - rf);
  const ds = Math.abs(s - sf);
  if (dq > dr && dq > ds) q = -r - s;
  else if (dr > ds) r = -q - s;
  return { q: q + 0, r: r + 0 };
}

/** Critically-tunable spring (semi-implicit Euler). */
export class Spring {
  x: number;
  v = 0;
  constructor(x = 0) {
    this.x = x;
  }
  step(target: number, dt: number, k = 170, c = 16) {
    const h = Math.min(dt, 1 / 30);
    this.v += (k * (target - this.x) - c * this.v) * h;
    this.x += this.v * h;
    return this.x;
  }
  snap(x: number) {
    this.x = x;
    this.v = 0;
  }
}
