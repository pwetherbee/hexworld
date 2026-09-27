import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import { api } from "../api/client";
import type { Tile } from "../api/types.gen";
import { usePlay } from "../play";
import { useStore } from "../store";
import { tileFaceGeometry } from "./geometry";
import { hexDistance, hexToWorld } from "./hexMath";
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
      scale={[S, 1, S]}
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
  uPix: { value: number };
  uFog: { value: THREE.Color };
  uHover: { value: number };
};

/** Unlit tile art, dimmed and desaturated, dissolving into fog through a 4x4 ordered dither on the
 * parent's pixel grid: chunky, pixelated fog rather than a smooth blur. */
function makeFogMaterial(R: number, S: number, P: number): THREE.MeshBasicMaterial {
  const inner = Math.sqrt(3) * R + 1.2; // the region's rim
  const uniforms: FogUniforms = {
    uInner: { value: inner + S * 0.2 }, // a clear band of the entered tile around the region
    uOuter: { value: inner + S * 2.8 },
    uPix: { value: (S / (P / 2)) * 2 }, // two parent pixels per fog cell
    uFog: { value: FOG },
    uHover: { value: 0 },
  };
  const m = new THREE.MeshBasicMaterial({ transparent: false });
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
        uniform float uInner; uniform float uOuter; uniform float uPix; uniform vec3 uFog; uniform float uHover;
        float bayer4(vec2 c) {
          vec2 m = mod(c, 4.0);
          float i = m.x + 4.0 * m.y;
          // 4x4 Bayer matrix, row-major
          float b[16] = float[16](0., 8., 2., 10., 12., 4., 14., 6., 3., 11., 1., 9., 15., 7., 13., 5.);
          for (int k = 0; k < 16; k++) if (float(k) == i) return (b[k] + 0.5) / 16.0;
          return 0.5;
        }`,
      )
      .replace(
        "#include <dithering_fragment>",
        `#include <dithering_fragment>
        float d = length(vWorld.xz);
        float f = smoothstep(uInner, uOuter, d);
        vec2 cell = floor(vWorld.xz / uPix);
        float lum = dot(gl_FragColor.rgb, vec3(0.299, 0.587, 0.114));
        vec3 muted = mix(gl_FragColor.rgb, vec3(lum), 0.45) * (0.62 + 0.25 * uHover);
        // ordered-dither fog: a pixel is either the (muted) world or the night, never a blur
        gl_FragColor.rgb = f * 1.15 > bayer4(cell) ? mix(muted, uFog, 0.9) : muted;`,
      );
  };
  m.customProgramCacheKey = () => "hexworld-context-fog";
  return m;
}
