import * as THREE from "three";
import { HEX_SIZE, hexCorner, hexToWorld } from "./hexMath";

/**
 * Flat hex face in the XZ plane (normal +Y) whose UVs map the canonical tile PNG:
 * the backend inscribes the pointy-top hex in a square with circumradius = width / 2,
 * so u = 0.5 + x / 2s and v = 0.5 - z / 2s (texture flipY = true).
 */
export function hexFaceGeometry(size = HEX_SIZE): THREE.BufferGeometry {
  const pos: number[] = [0, 0, 0];
  const uv: number[] = [0.5, 0.5];
  for (let i = 0; i < 6; i++) {
    const [x, z] = hexCorner(i, size);
    pos.push(x, 0, z);
    uv.push(0.5 + x / (2 * size), 0.5 - z / (2 * size));
  }
  const idx: number[] = [];
  for (let i = 0; i < 6; i++) {
    const a = 1 + i;
    const b = 1 + ((i + 1) % 6);
    idx.push(0, b, a); // counter-clockwise seen from +Y
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/**
 * Hex face whose UVs sample the tile's canvas on the WORLD pixel grid (backend art/grid.py): the
 * canvas of hex (q, r) with tile_px P starts at the integer world pixel
 *   origin = (floor(cx - s) - 1, floor(cy - s) - 1),  size C = P + 3,  s = P / 2
 * where (cx, cy) is the hex centre in pixels. One world unit = s pixels. Neighbouring faces meet
 * exactly and sample one continuous pixel grid, so borders are straight geometric cuts with the
 * texture continuing across them (the ground PNG carries a bleed ring past the rim for this).
 */
const faceCache = new Map<string, THREE.BufferGeometry>();
export function tileFaceGeometry(q: number, r: number, P: number, size = HEX_SIZE): THREE.BufferGeometry {
  const key = `${q},${r},${P}`;
  const hit = faceCache.get(key);
  if (hit) return hit;
  const s = P / 2;
  const C = P + 3;
  const [wx, wz] = hexToWorld(q, r, 1);
  const cx = wx * s;
  const cy = wz * s;
  const ox = Math.floor(cx - s) - 1;
  const oy = Math.floor(cy - s) - 1;
  const uvOf = (x: number, z: number): [number, number] => [(cx + x * s - ox) / C, 1 - (cy + z * s - oy) / C];
  const pos: number[] = [0, 0, 0];
  const uv: number[] = [...uvOf(0, 0)];
  for (let i = 0; i < 6; i++) {
    const [x, z] = hexCorner(i, size);
    pos.push(x, 0, z);
    uv.push(...uvOf(x / size, z / size));
  }
  const idx: number[] = [];
  for (let i = 0; i < 6; i++) idx.push(0, 1 + ((i + 1) % 6), 1 + i);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  if (faceCache.size > 4000) faceCache.clear();
  faceCache.set(key, g);
  return g;
}

/** Closed hex outline (line loop points) in the XZ plane. */
export function hexOutlinePoints(size = HEX_SIZE, y = 0): THREE.Vector3[] {
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i <= 6; i++) {
    const [x, z] = hexCorner(i % 6, size);
    pts.push(new THREE.Vector3(x, y, z));
  }
  return pts;
}

/** Hex prism body: cylinder with 6 radial segments (corners on ±Z, matching pointy-top). */
export function hexPrismGeometry(size = HEX_SIZE): THREE.CylinderGeometry {
  return new THREE.CylinderGeometry(size, size, 1, 6, 1, false);
}

export const SHARED = {
  face: hexFaceGeometry(0.985),
  emptyFace: hexFaceGeometry(0.94),
  prism: hexPrismGeometry(1.0),
};
