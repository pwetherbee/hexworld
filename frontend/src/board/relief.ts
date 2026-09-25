import { useEffect, useState } from "react";
import * as THREE from "three";
import { assetUrl } from "../api/client";
import { SQRT3, hexToWorld } from "./hexMath";

/**
 * 3D relief from a tile's heightmap layer (backend art/relief.py): the ground texture holds flat
 * surface colours on the world pixel grid; this extrudes each pixel to its level as terraces with
 * real walls. Top faces are merged per row run and clipped exactly to the hex (straight rims); walls
 * sit on pixel boundaries where the level changes, coloured from the higher pixel and shaded by
 * the way they face (light from the north-west, like the art).
 */

export const LEVEL_STEP = 0.055; // world units per relief level (1 hex radius = 32 texels)
const LEVEL_SCALE = 40; // heightmap PNG value per level

export type Levels = { C: number; data: Uint8Array };

const cache = new Map<string, Levels>();
const pending = new Map<string, Promise<Levels>>();

async function loadLevels(id: string): Promise<Levels> {
  const res = await fetch(assetUrl(id));
  const bmp = await createImageBitmap(await res.blob());
  const cv = document.createElement("canvas");
  cv.width = bmp.width;
  cv.height = bmp.height;
  const ctx = cv.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("no 2d context");
  ctx.drawImage(bmp, 0, 0);
  const px = ctx.getImageData(0, 0, bmp.width, bmp.height).data;
  const data = new Uint8Array(bmp.width * bmp.height);
  for (let k = 0; k < data.length; k++) data[k] = Math.round(px[k * 4] / LEVEL_SCALE);
  return { C: bmp.width, data };
}

/** The heightmap for `id`, or null while it loads (never a previous id's levels). */
export function useLevels(id: string | null | undefined): Levels | null {
  const [state, setState] = useState<{ id: string; lv: Levels } | null>(() => {
    const hit = id ? cache.get(id) : undefined;
    return id && hit ? { id, lv: hit } : null;
  });
  useEffect(() => {
    if (!id) return;
    let alive = true;
    const hit = cache.get(id);
    if (hit) {
      setState({ id, lv: hit });
      return;
    }
    let p = pending.get(id);
    if (!p) {
      p = loadLevels(id).then((l) => {
        cache.set(id, l);
        pending.delete(id);
        return l;
      });
      pending.set(id, p);
    }
    p.then((l) => alive && setState({ id, lv: l })).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id]);
  if (!id) return null;
  if (state?.id === id) return state.lv;
  return cache.get(id) ?? null;
}

type Frame = { s: number; C: number; cx: number; cy: number; ox: number; oy: number };

function frameOf(q: number, r: number, P: number): Frame {
  const s = P / 2;
  const [wx, wz] = hexToWorld(q, r, 1);
  const cx = wx * s;
  const cy = wz * s;
  return { s, C: P + 3, cx, cy, ox: Math.floor(cx - s) - 1, oy: Math.floor(cy - s) - 1 };
}

/** Relief level under a tile-local point (hex radii), e.g. for standing sprites on the surface. */
export function levelAt(lv: Levels, q: number, r: number, x: number, z: number): number {
  const f = frameOf(q, r, lv.C - 3);
  const i = Math.floor(f.cx + x * f.s - f.ox);
  const j = Math.floor(f.cy + z * f.s - f.oy);
  if (i < 0 || j < 0 || i >= lv.C || j >= lv.C) return 0;
  return lv.data[j * lv.C + i];
}

// pointy-top hex of circumradius 1, corners at -30 + 60k degrees (x east, z south)
const HEX: Array<[number, number]> = Array.from({ length: 6 }, (_, k) => {
  const a = ((-30 + 60 * k) * Math.PI) / 180;
  return [Math.cos(a), Math.sin(a)];
});

function clipToHex(poly: Array<[number, number]>): Array<[number, number]> {
  let out = poly;
  for (let k = 0; k < 6 && out.length; k++) {
    const [ax, az] = HEX[k];
    const [bx, bz] = HEX[(k + 1) % 6];
    // inside = same side as the centre
    const side = (px: number, pz: number) => (bx - ax) * (pz - az) - (bz - az) * (px - ax);
    const centre = side(0, 0) > 0 ? 1 : -1;
    const inp = out;
    out = [];
    for (let n = 0; n < inp.length; n++) {
      const p = inp[n];
      const q = inp[(n + 1) % inp.length];
      const sp = side(p[0], p[1]) * centre;
      const sq = side(q[0], q[1]) * centre;
      if (sp >= 0) out.push(p);
      if (sp >= 0 !== sq >= 0) {
        const t = sp / (sp - sq);
        out.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]);
      }
    }
  }
  return out;
}

/** z-extent of the hex at x (null outside). */
function hexZRange(x: number): [number, number] | null {
  const ax = Math.abs(x);
  if (ax > SQRT3 / 2) return null;
  const h = 1 - ax / SQRT3;
  return [-h, h];
}

/** x-extent of the hex at z (null outside). */
function hexXRange(z: number): [number, number] | null {
  const az = Math.abs(z);
  if (az > 1) return null;
  const w = Math.min(SQRT3 / 2, SQRT3 * (1 - az));
  return [-w, w];
}

const geoCache = new Map<string, THREE.BufferGeometry>();

export function reliefGeometry(q: number, r: number, heightId: string, lv: Levels): THREE.BufferGeometry {
  const key = `${heightId}@${q},${r}`;
  const hit = geoCache.get(key);
  if (hit) return hit;
  const f = frameOf(q, r, lv.C - 3);
  const { s, C, cx, cy, ox, oy } = f;
  const L = (i: number, j: number) =>
    i < 0 || j < 0 || i >= C || j >= C ? -1 : lv.data[j * C + i];
  const X = (px: number) => (px - cx) / s; // world pixel -> local units
  const Z = (py: number) => (py - cy) / s;
  const U = (x: number) => (cx + x * s - ox) / C;
  const V = (z: number) => 1 - (cy + z * s - oy) / C;

  const pos: number[] = [];
  const uv: number[] = [];
  const col: number[] = [];
  const vert = (x: number, y: number, z: number, u: number, v: number, c: number) => {
    pos.push(x, y, z);
    uv.push(u, v);
    col.push(c, c, c);
  };
  const quad = (
    a: [number, number, number],
    b: [number, number, number],
    c: [number, number, number],
    d: [number, number, number],
    u: number,
    v: number,
    shadeTop: number,
    shadeBottom: number,
  ) => {
    // a,b top edge; c,d bottom edge (same uv: the wall takes the colour of the pixel above it)
    vert(...a, u, v, shadeTop);
    vert(...b, u, v, shadeTop);
    vert(...c, u, v, shadeBottom);
    vert(...a, u, v, shadeTop);
    vert(...c, u, v, shadeBottom);
    vert(...d, u, v, shadeBottom);
  };

  // --- top faces: per row, runs of equal level, clipped to the hex
  const pad = 1.5 / s;
  for (let j = 0; j < C; j++) {
    const z0 = Z(oy + j);
    const z1 = Z(oy + j + 1);
    if (z1 < -1 - pad || z0 > 1 + pad) continue;
    let i = 0;
    while (i < C) {
      const lvl = L(i, j);
      let k = i + 1;
      while (k < C && L(k, j) === lvl) k++;
      const x0 = X(ox + i);
      const x1 = X(ox + k);
      const poly = clipToHex([
        [x0, z0],
        [x1, z0],
        [x1, z1],
        [x0, z1],
      ]);
      if (poly.length >= 3) {
        const y = lvl * LEVEL_STEP;
        for (let n = 1; n < poly.length - 1; n++) {
          for (const p of [poly[0], poly[n + 1], poly[n]]) vert(p[0], y, p[1], U(p[0]), V(p[1]), 1);
        }
      }
      i = k;
    }
  }

  // --- walls between pixels of different level
  for (let j = 0; j < C; j++) {
    for (let i = 0; i < C; i++) {
      const a = L(i, j);
      if (a < 0) continue;
      // east neighbour: wall on the vertical line x = ox + i + 1
      const b = L(i + 1, j);
      if (b >= 0 && b !== a) {
        const x = X(ox + i + 1);
        const zr = hexZRange(x);
        if (zr) {
          const za = Math.max(Z(oy + j), zr[0]);
          const zb = Math.min(Z(oy + j + 1), zr[1]);
          if (zb > za) {
            const hi = Math.max(a, b) * LEVEL_STEP;
            const lo = Math.min(a, b) * LEVEL_STEP;
            const hiI = a > b ? i : i + 1; // the higher pixel colours the wall
            const u = (hiI + 0.5) / C;
            const v = 1 - (j + 0.5) / C;
            const shade = a > b ? 0.62 : 0.8; // faces east : faces west (lit)
            quad([x, hi, za], [x, hi, zb], [x, lo, zb], [x, lo, za], u, v, shade, shade * 0.8);
          }
        }
      }
      // south neighbour: wall on the horizontal line z = oy + j + 1
      const c = L(i, j + 1);
      if (c >= 0 && c !== a) {
        const z = Z(oy + j + 1);
        const xr = hexXRange(z);
        if (xr) {
          const xa = Math.max(X(ox + i), xr[0]);
          const xb = Math.min(X(ox + i + 1), xr[1]);
          if (xb > xa) {
            const hi = Math.max(a, c) * LEVEL_STEP;
            const lo = Math.min(a, c) * LEVEL_STEP;
            const hiJ = a > c ? j : j + 1;
            const u = (i + 0.5) / C;
            const v = 1 - (hiJ + 0.5) / C;
            const shade = a > c ? 0.58 : 0.72; // faces south (towards the usual camera) : north
            quad([xa, hi, z], [xb, hi, z], [xb, lo, z], [xa, lo, z], u, v, shade, shade * 0.72);
          }
        }
      }
    }
  }

  // --- rim skirt: closes the relief down to the tile body where no neighbour does
  const SEG = 28;
  for (let k = 0; k < 6; k++) {
    const [ax, az] = HEX[k];
    const [bx, bz] = HEX[(k + 1) % 6];
    for (let n = 0; n < SEG; n++) {
      const t0 = n / SEG;
      const t1 = (n + 1) / SEG;
      const mx = ax + (bx - ax) * (t0 + t1) * 0.5;
      const mz = az + (bz - az) * (t0 + t1) * 0.5;
      const i = Math.floor(cx + mx * 0.985 * s - ox);
      const j = Math.floor(cy + mz * 0.985 * s - oy);
      const lvl = L(i, j);
      if (lvl <= 0) continue;
      const p0: [number, number] = [ax + (bx - ax) * t0, az + (bz - az) * t0];
      const p1: [number, number] = [ax + (bx - ax) * t1, az + (bz - az) * t1];
      const y = lvl * LEVEL_STEP;
      const u = (i + 0.5) / C;
      const v = 1 - (j + 0.5) / C;
      quad([p0[0], y, p0[1]], [p1[0], y, p1[1]], [p1[0], 0, p1[1]], [p0[0], 0, p0[1]], u, v, 0.6, 0.42);
    }
  }

  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.computeBoundingSphere();
  if (geoCache.size > 3000) geoCache.clear();
  geoCache.set(key, g);
  return g;
}
