import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import { api } from "../api/client";
import type { Tile } from "../api/types.gen";
import { usePlay } from "../play";
import { useStore } from "../store";
import { tileFaceGeometry } from "./geometry";
import { hexDistance, hexToWorld } from "./hexMath";
import { SURFACE_TIME } from "./relief";
import { usePixelTexture } from "./textures";

/**
 * Inside a region (a world entered from a tile of its parent), the parent's own tiles are drawn around
 * it at the region's scale: the entered tile under and around the region's rim, its neighbours
 * beyond. They fade into a dithered, pixelated fog with distance, so the detailed region stays in
 * focus and the world visibly continues. In play mode a neighbour can be clicked to travel there.
 */

const RING = 2; // parent tiles within this many steps of the entered tile
const FOG = new THREE.Color("#090a0f");
const NO_RAYCAST = () => undefined;

/** Circumradius (in region tile units) of one parent tile drawn around a region of radius R: just
 * large enough that the parent hex contains the whole region. */
export function contextScale(radius: number) {
  return 2 * radius + 1.5;
}

const parentCache = new Map<string, Tile[]>();

export function ContextRing() {
  const world = useStore((s) => s.world);
  const parent = world?.parent;
  const [tiles, setTiles] = useState<Tile[] | null>(parent ? (parentCache.get(parent.world_id) ?? null) : null);
  useEffect(() => {
    if (!parent) return;
    let alive = true;
    void api.getWorld(parent.world_id).then((d) => {
      parentCache.set(parent.world_id, d.tiles);
      if (alive) setTiles(d.tiles);
    });
    return () => {
      alive = false;
    };
  }, [parent]);
  if (!world || !parent || !tiles) return null;
  const S = contextScale(world.radius);
  const P = world.style?.tile_px ?? 64;
  const near = tiles.filter(
    (t) => t.status === "accepted" && t.asset_id && hexDistance(t, parent) <= RING,
  );
  return (
    <group>
      {near.map((t) => (
        <ContextTile key={`${t.q},${t.r}`} tile={t} pq={parent.q} pr={parent.r} S={S} P={P} R={world.radius} />
      ))}
      <CloudVeil R={world.radius} S={S} P={P} />
    </group>
  );
}

function ContextTile({ tile, pq, pr, S, P, R }: { tile: Tile; pq: number; pr: number; S: number; P: number; R: number }) {
  const tex = usePixelTexture(tile.asset_id);
  const geo = useMemo(() => tileFaceGeometry(tile.q, tile.r, P), [tile.q, tile.r, P]);
  const self = tile.q === pq && tile.r === pr;
  const [x, z] = hexToWorld(tile.q - pq, tile.r - pr);
  const hovered = usePlay((s) => s.hoverRegion?.q === tile.q && s.hoverRegion?.r === tile.r);
  const mat = useMemo(() => makeFogMaterial(R, S, P), [R, S, P]);
  useEffect(() => {
    mat.map = tex;
    mat.needsUpdate = true;
  }, [mat, tex]);
  useEffect(() => {
    (mat.userData.uniforms as FogUniforms).uHover.value = hovered ? 1 : 0;
  }, [mat, hovered]);
  useEffect(() => () => mat.dispose(), [mat]);
  if (!tex) return null;
  return (
    <mesh
      geometry={geo}
      material={mat}
      position={[x * S, self ? 0.004 : 0.002, z * S]}
      scale={[S * 1.012, 1, S * 1.012]} // a hair of overlap hides the hex seams
      raycast={self ? NO_RAYCAST : undefined}
      onPointerMove={(e) => {
        e.stopPropagation();
        if (!usePlay.getState().active) return;
        const h = usePlay.getState().hoverRegion;
        if (h?.q !== tile.q || h?.r !== tile.r) usePlay.setState({ hoverRegion: { q: tile.q, r: tile.r, biome: tile.biome ?? "" } });
      }}
      onPointerOut={() => {
        const h = usePlay.getState().hoverRegion;
        if (h?.q === tile.q && h?.r === tile.r) usePlay.setState({ hoverRegion: null });
      }}
      onClick={(e) => {
        e.stopPropagation();
        if (e.delta > 5) return;
        if (usePlay.getState().active) void usePlay.getState().travel(tile.q, tile.r);
      }}
    />
  );
}

type FogUniforms = {
  uInner: { value: number };
  uOuter: { value: number };
  uTexRes: { value: number };
  uFog: { value: THREE.Color };
  uHover: { value: number };
};

/** Shared GLSL: value noise on integer cells, and fbm, for the pixel clouds. */
const NOISE_GLSL = `
  float hash21(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
  float vnoise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash21(i), hash21(i + vec2(1.0, 0.0)), f.x), mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), f.x), f.y);
  }
  float fbm(vec2 p) { return 0.55 * vnoise(p) + 0.3 * vnoise(p * 2.03 + 7.1) + 0.15 * vnoise(p * 4.1 + 3.7); }
`;

/**
 * The surrounding tiles: their own art, dimmed and desaturated, turning into a coarser mosaic with
 * distance (a pixelated blur) and fading into the night in a few hard bands. The mosaic never gets
 * finer than a screen pixel (chosen from the texel footprint, like a mip level), so zooming out
 * doesn't shimmer.
 */
function makeFogMaterial(R: number, S: number, P: number): THREE.MeshBasicMaterial {
  const inner = Math.sqrt(3) * R + 1.2; // the region's rim
  const uniforms: FogUniforms = {
    uInner: { value: inner + S * 0.15 },
    uOuter: { value: inner + S * 3.0 },
    uTexRes: { value: P + 3 },
    uFog: { value: FOG },
    uHover: { value: 0 },
  };
  const m = new THREE.MeshBasicMaterial({ transparent: false, fog: false }); // its own fog, not the camera's
  m.userData.uniforms = uniforms;
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vWorld;")
      .replace("#include <worldpos_vertex>", "#include <worldpos_vertex>\nvWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;");
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
        varying vec3 vWorld;
        uniform float uInner; uniform float uOuter; uniform float uTexRes; uniform vec3 uFog; uniform float uHover;`,
      )
      .replace(
        "#include <map_fragment>",
        `#ifdef USE_MAP
          float fd = smoothstep(uInner, uOuter, length(vWorld.xz));
          vec2 texel = vMapUv * uTexRes;
          float fw = max(max(fwidth(texel.x), fwidth(texel.y)), 1.0);
          // mosaic level: coarser with distance, and never finer than one screen pixel
          float k = max(exp2(floor(fd * 3.2)), exp2(ceil(log2(fw))));
          vec2 uvq = (floor(texel / k) + 0.5) * k / uTexRes;
          vec4 texc = texture2D(map, uvq);
          if (texc.a < 0.5) texc = texture2D(map, vMapUv); // mosaic cells straddling the hex rim
          diffuseColor *= texc;
        #endif`,
      )
      .replace(
        "#include <dithering_fragment>",
        `#include <dithering_fragment>
        float f = smoothstep(uInner, uOuter, length(vWorld.xz));
        float lum = dot(gl_FragColor.rgb, vec3(0.299, 0.587, 0.114));
        vec3 muted = mix(gl_FragColor.rgb, vec3(lum), 0.4) * (0.66 + 0.24 * uHover);
        // the night comes in a few hard bands (pixel-art posterisation, no dither to shimmer)
        float band = floor(f * 5.0 + 0.35) / 5.0;
        gl_FragColor.rgb = mix(muted, uFog, clamp(band, 0.0, 0.94));`,
      );
  };
  m.customProgramCacheKey = () => "hexworld-context-fog-2";
  return m;
}

/**
 * Pixel clouds drifting over the surrounding world and across the region's rim, softening the edge
 * between the detailed region and its context. Blocky world-space cells (a few parent pixels wide),
 * posterised alpha, no clouds over the region's middle.
 */
export function CloudVeil({ R, S, P }: { R: number; S: number; P: number }) {
  const mat = useMemo(() => {
    const inner = Math.sqrt(3) * R + 1.2;
    return new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: {
        uTime: SURFACE_TIME,
        uRim: { value: inner },
        uFar: { value: inner + S * 3.2 },
        uCell: { value: (S / (P / 2)) * 3 }, // three parent pixels per cloud pixel
        uScale: { value: 1 / (S * 0.55) }, // cloud size: about half a parent tile
        uLight: { value: new THREE.Color("#c7d0e2") },
        uShade: { value: new THREE.Color("#5b6478") },
      },
      vertexShader: `
        varying vec3 vWorld;
        void main() {
          vec4 w = modelMatrix * vec4(position, 1.0);
          vWorld = w.xyz;
          gl_Position = projectionMatrix * viewMatrix * w;
        }`,
      fragmentShader: `
        varying vec3 vWorld;
        uniform float uTime; uniform float uRim; uniform float uFar; uniform float uCell; uniform float uScale;
        uniform vec3 uLight; uniform vec3 uShade;
        ${NOISE_GLSL}
        void main() {
          // snap to chunky cells, never smaller than a couple of screen pixels (no shimmer when far)
          float cell = max(uCell, max(fwidth(vWorld.x), fwidth(vWorld.z)) * 2.0);
          vec2 c = (floor(vWorld.xz / cell) + 0.5) * cell;
          float d = length(c);
          // thin over the rim, thicker outside, thinning again far away where the night takes over
          float ring = smoothstep(uRim - 2.2, uRim + 1.5, d) * (1.0 - smoothstep(uFar * 0.75, uFar, d));
          vec2 drift = vec2(uTime * 0.18, uTime * 0.07);
          float n = fbm(c * uScale + drift * uScale * 6.0);
          float cover = smoothstep(0.42, 0.72, n) * ring;
          float a = floor(cover * 4.0 + 0.2) / 4.0; // posterised: 0, 1/4, 1/2, 3/4, 1
          if (a <= 0.0) discard;
          // lit tops, shaded undersides: sample the cloud a cell up-light to fake a rim
          float nb = fbm((c + vec2(-cell, -cell)) * uScale + drift * uScale * 6.0);
          vec3 col = mix(uShade, uLight, clamp(0.55 + (n - nb) * 6.0, 0.0, 1.0));
          gl_FragColor = vec4(col, a * 0.72);
        }`,
    });
  }, [R, S, P]);
  useEffect(() => () => mat.dispose(), [mat]);
  const size = (Math.sqrt(3) * R + 1.2 + S * 3.4) * 2;
  return (
    <mesh position={[0, 0.55, 0]} rotation={[-Math.PI / 2, 0, 0]} material={mat} raycast={NO_RAYCAST} renderOrder={6}>
      <planeGeometry args={[size, size]} />
    </mesh>
  );
}
