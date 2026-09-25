import * as THREE from "three";
import { HEX_SIZE, hexCorner } from "./hexMath";

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
  prism: hexPrismGeometry(0.985),
};
