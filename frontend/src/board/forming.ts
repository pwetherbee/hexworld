import * as THREE from "three";
import type { MaterialSpec } from "../api/types.gen";

/**
 * The look of a tile that is not built yet, driven by the tile's own palette (its biome material's
 * ramp as soon as the material artist has designed it, a biome tint before that). One shader covers
 * every pre-accept state so they blend into each other:
 *
 *   planned    : a faint constellation of palette pixels twinkling on the world pixel grid;
 *                it flares when a neighbouring tile lands
 *   generating : the surface fills with flickering palette pixels while the agent works,
 *                a light sweep passes over it
 *   reviewing  : the real ground dissolves in pixel by pixel, then a gold scan line sweeps
 *   rejected   : a red row-glitch scrambles the candidate back into palette pixels
 *
 * Cells are world texels (the face UVs map the tile canvas, see geometry.ts), so the effect is
 * pixel art on the same grid as the finished tile.
 */

const RAMP = [0.42, 0.72, 1.0, 1.24, 1.5]; // outline, dark, base, light, hi (as the backend ramps)

function rampColor(hex: string, f: number): THREE.Color {
  const c = new THREE.Color(hex);
  const hsl = { h: 0, s: 0, l: 0 };
  c.getHSL(hsl);
  let l = Math.min(hsl.l, 0.8);
  l = f <= 1 ? l * f : Math.min(0.95, l + (1 - l) * Math.min(1, (f - 1) * 0.9));
  return new THREE.Color().setHSL((hsl.h + (f < 1 ? 0.015 : -0.01) * Math.abs(1 - f) + 1) % 1, hsl.s, l);
}

function biomeTint(biome: string | null | undefined): string {
  if (!biome) return "#94a3b8";
  let h = 0;
  for (const c of biome) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h}, 45%, 55%)`;
}

/** 6 colours: outline, dark, base, light, hi, accent. */
export function tilePalette(biome: string | null | undefined, mat: MaterialSpec | undefined): THREE.Color[] {
  const base = mat?.base_color ?? `#${new THREE.Color(biomeTint(biome)).getHexString()}`;
  const accent = mat?.accent_color ? new THREE.Color(mat.accent_color) : rampColor(base, 1.35);
  return [...RAMP.map((f) => rampColor(base, f)), accent];
}

export type FormingUniforms = {
  uTime: { value: number };
  uState: { value: number }; // 0 planned, 1 forming
  uAppear: { value: number };
  uPulse: { value: number };
  uFill: { value: number };
  uReveal: { value: number };
  uScan: { value: number };
  uGlitch: { value: number };
  uHasMap: { value: number };
  uMap: { value: THREE.Texture | null };
  uSeed: { value: number };
  uCells: { value: number };
  uPal: { value: THREE.Color[] };
};

const vertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const fragment = /* glsl */ `
uniform float uTime, uState, uAppear, uPulse, uFill, uReveal, uScan, uGlitch, uHasMap, uSeed, uCells;
uniform vec3 uPal[6];
uniform sampler2D uMap;
varying vec2 vUv;

float h21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

vec3 tone(float r) {
  // weighted pick: mostly base/dark/light, a little highlight and accent
  if (r < 0.30) return uPal[2];
  if (r < 0.52) return uPal[1];
  if (r < 0.74) return uPal[3];
  if (r < 0.86) return uPal[4];
  if (r < 0.95) return uPal[5];
  return uPal[0];
}

void main() {
  vec2 cell = floor(vUv * uCells);
  vec2 art = floor(vUv * uCells * 0.5);  // 2px art cells: the grain of the finished ground
  float h = h21(cell + uSeed);
  float h2 = h21(cell.yx * 1.37 + uSeed + 3.1);
  float ha = h21(art + uSeed * 0.7);
  // most art cells hold a steady tone; ~40% shimmer, re-rolling a couple of times a second
  vec3 steady = tone(0.62 * h21(art * 1.13 + uSeed + 7.7));
  float tick = floor(uTime * (1.6 + 2.2 * ha) + ha * 19.0);
  vec3 live = tone(h21(art + vec2(tick * 0.173, tick * 0.311) + uSeed));
  vec3 paint = mix(steady, live, step(0.6, ha));

  vec3 col;
  float alpha;
  if (uState < 0.5) {
    // planned: sparse twinkling palette pixels over a faint wash of the base colour
    float density = 0.05 + 0.22 * uPulse;
    float lit = step(h, density);
    float tw = 0.5 + 0.5 * sin(uTime * (1.2 + 2.5 * h2) + h * 40.0);
    col = mix(uPal[1] * 0.6, paint, lit);
    alpha = uAppear * (0.07 + lit * (0.25 + 0.6 * tw) + 0.25 * uPulse * lit);
  } else {
    // forming: cells fill with flickering paint as the work progresses
    float filled = step(ha, uFill);
    vec3 dark = uPal[0] * 0.55;
    float grid = step(0.86, fract(vUv.x * uCells)) + step(0.86, fract(vUv.y * uCells));
    col = mix(dark * (1.0 - 0.25 * min(grid, 1.0)), paint, filled);
    // soft light sweep across the surface
    float s = fract((vUv.x * 0.8 + vUv.y) * 0.6 - uTime * 0.28);
    float band = smoothstep(0.0, 0.05, s) * (1.0 - smoothstep(0.05, 0.16, s));
    col += band * 0.45 * mix(uPal[4], vec3(1.0), 0.3) * (0.4 + 0.6 * filled);
    alpha = 1.0;

    if (uHasMap > 0.5) {
      vec2 uv = vUv;
      float row = floor(vUv.y * uCells);
      float jitter = h21(vec2(row, floor(uTime * 24.0))) - 0.5;
      uv.x += uGlitch * jitter * 0.22 * step(0.55, h21(vec2(row, floor(uTime * 9.0))));
      vec4 tx = texture2D(uMap, uv);
      float shown = step(h2, uReveal) * step(0.5, tx.a);
      col = mix(col, tx.rgb, shown);
      // review: a slow diagonal wave of 2px art cells flips one shade toward the tile's own
      // highlight as it passes (with dropout, so it reads as pixels flipping, not a light bar)
      float diag = (art.x + (uCells * 0.5 - art.y)) / uCells;          // 0..1, NW -> SE
      float wave = fract(diag - uTime * 0.22);
      float inBand = step(wave, 0.09) * step(0.35, h21(art + floor(uTime * 6.0) * 0.61));
      float trail = step(wave, 0.2) * step(0.8, h21(art * 1.7 + floor(uTime * 4.0)));
      col = mix(col, uPal[4], uScan * (0.38 * inBand + 0.18 * trail));
    }
    // rejection tint
    col = mix(col, vec3(0.9, 0.12, 0.1) * (0.6 + 0.4 * h), uGlitch * 0.55 * step(0.5, h2 + 0.2));
  }
  gl_FragColor = vec4(col, alpha);
  #include <colorspace_fragment>
}
`;

export function makeFormingMaterial(seed: number): THREE.ShaderMaterial {
  const uniforms: FormingUniforms = {
    uTime: { value: 0 },
    uState: { value: 0 },
    uAppear: { value: 0 },
    uPulse: { value: 0 },
    uFill: { value: 0 },
    uReveal: { value: 0 },
    uScan: { value: 0 },
    uGlitch: { value: 0 },
    uHasMap: { value: 0 },
    uMap: { value: null },
    uSeed: { value: seed },
    uCells: { value: 67 },
    uPal: { value: Array.from({ length: 6 }, () => new THREE.Color()) },
  };
  return new THREE.ShaderMaterial({
    uniforms,
    vertexShader: vertex,
    fragmentShader: fragment,
    transparent: true,
    depthWrite: false,
  });
}
