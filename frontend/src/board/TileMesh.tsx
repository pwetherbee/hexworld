import { useFrame } from "@react-three/fiber";
import { memo, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { TileLayer } from "../api/types.gen";
import { useStore } from "../store";
import { type FormingUniforms, makeFormingMaterial, tilePalette } from "./forming";
import { SHARED, hexOutlinePoints, tileFaceGeometry } from "./geometry";
import { DIRECTIONS, Spring, hexDistance, hexKey, hexToWorld } from "./hexMath";
import {
  LEVEL_STEP,
  SURFACE_CELLS,
  levelAt,
  reliefGeometry,
  reliefShader,
  reliefShaderKey,
  useLevels,
} from "./relief";
import { usePixelTexture } from "./textures";

const FLASH_MS = 900;
const PLAN_STAGGER_MS = 70;
const PLAN_FADE_MS = 520;
const REVEAL_MS = 950;
const SPRITE_POP_DELAY = 380;
const SPRITE_POP_STAGGER = 80;
const GROW_DELAY_MS = 90;

const COPY_COLORS = { shallow: "#a78bfa", deep: "#60a5fa" } as const;
const RING_GEO = new THREE.RingGeometry(0.9, 1.0, 6, 1, Math.PI / 6);
const SEL_GEO = new THREE.BufferGeometry().setFromPoints(hexOutlinePoints(1.0, 0));
const RIM_GEO = new THREE.BufferGeometry().setFromPoints(hexOutlinePoints(0.995, 0));
const NO_RAYCAST = () => undefined;
const SHADOW_GEO = new THREE.CircleGeometry(0.5, 20);
const SPRITE_GEO = new THREE.PlaneGeometry(1, 1).translate(0, 0.5, 0); // anchored at the bottom

// All accepted tiles share one height: relief lives in the art (heightmap layer), so neighbouring
// faces meet flush and the ground reads as one continuous surface.
export const TILE_HEIGHT = 0.16;
const FORMING_HEIGHT = 0.07;

const phaseOf = (s: string) => {
  let h = 0;
  for (const c of s) h = (h * 33 + c.charCodeAt(0)) % 1000;
  return h / 159;
};
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const easeOut = (v: number) => 1 - (1 - v) ** 3;

export const TileMesh = memo(function TileMesh({ tileKey }: { tileKey: string }) {
  const tile = useStore((s) => s.tiles[tileKey]);
  const acceptedAt = useStore((s) => s.acceptedAt[tileKey]);
  const rejectedAt = useStore((s) => s.rejectedAt[tileKey]);
  const plannedAt = useStore((s) => s.plannedAt[tileKey]);
  const selected = useStore((s) => s.selected === tileKey);
  const origin = useStore((s) => (s.activeRunId ? s.runs[s.activeRunId]?.origin : undefined));
  const biome = tile.biome ?? tile.directive?.biome ?? null;
  const biomeMat = useStore((s) => (biome ? s.libMaterials[biome] : undefined));
  const status = tile.status;
  const accepted = status === "accepted";
  const forming = status === "planned" || status === "generating" || status === "reviewing";
  const groundLayer = tile.layers?.find((l) => l.kind === "ground");
  const tex = usePixelTexture(accepted ? (groundLayer?.asset_id ?? tile.asset_id) : tile.preview_asset_id);
  const sprites = accepted ? (tile.layers ?? []).filter((l) => l.kind === "sprite") : [];

  const group = useRef<THREE.Group>(null);
  const body = useRef<THREE.Mesh>(null);
  const bodyMat = useRef<THREE.MeshStandardMaterial>(null);
  const reliefMesh = useRef<THREE.Mesh>(null);
  const face = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.Mesh>(null);
  const ringMat = useRef<THREE.MeshBasicMaterial>(null);
  const rim = useRef<THREE.LineLoop>(null);
  const rimMat = useRef<THREE.LineBasicMaterial>(null);
  const sel = useRef<THREE.LineLoop>(null);
  const selMat = useRef<THREE.LineBasicMaterial>(null);
  const shadowMat = useRef<THREE.MeshBasicMaterial>(null);
  const rise = useRef(new Spring(0));
  const lift = useRef(new Spring(0));
  const scale = useRef(new Spring(1));
  const plinth = useRef(new Spring(accepted ? TILE_HEIGHT : 0));
  const grow = useRef(new Spring(1));
  const fill = useRef(0);
  const lastTex = useRef<THREE.Texture | null>(null);
  const texReadyAt = useRef(0);

  const [x, z] = hexToWorld(tile.q, tile.r);
  const texW = (tex?.image as { width?: number } | undefined)?.width;
  const P = texW && texW > 8 ? texW - 3 : 64;
  const faceGeo = useMemo(() => tileFaceGeometry(tile.q, tile.r, P), [tile.q, tile.r, P]);
  const heightLayer = accepted ? tile.layers?.find((l) => l.kind === "height") : undefined;
  const levels = useLevels(heightLayer?.asset_id);
  const reliefGeo = useMemo(
    () =>
      levels && heightLayer && texW && levels.C === texW
        ? reliefGeometry(tile.q, tile.r, heightLayer.asset_id, levels)
        : null,
    [levels, heightLayer, texW, tile.q, tile.r],
  );
  const isCopy = accepted && !!tile.copy_mode;
  const planDelay = origin ? hexDistance(origin, tile) * PLAN_STAGGER_MS : 0;
  const neighbourKeys = useMemo(() => DIRECTIONS.map(([dq, dr]) => hexKey(tile.q + dq, tile.r + dr)), [tile.q, tile.r]);
  const ringColor = useMemo(
    () =>
      tile.copy_mode
        ? new THREE.Color(COPY_COLORS[tile.copy_mode])
        : new THREE.Color(tile.side_color ?? "#ffffff").offsetHSL(0, 0, 0.45),
    [tile.copy_mode, tile.side_color],
  );

  // the tile's palette (its biome material's ramp once designed); colours ease to new targets
  const formingMat = useMemo(() => makeFormingMaterial(phaseOf(tileKey) * 13.7), [tileKey]);
  useEffect(() => () => formingMat.dispose(), [formingMat]);
  const palette = useMemo(() => tilePalette(biome, biomeMat), [biome, biomeMat]);
  const paletteSnapped = useRef(false);
  const U = formingMat.uniforms as unknown as FormingUniforms;

  useEffect(() => {
    if (tex && !accepted) {
      lastTex.current = tex;
      texReadyAt.current = Date.now();
    }
  }, [tex, accepted]);

  // Landing: generated tiles grow their relief out of the surface; copies are stamped from above.
  useEffect(() => {
    if (!accepted || !acceptedAt) return;
    if (isCopy) {
      rise.current.snap(3.4);
      grow.current.snap(1);
    } else {
      grow.current.snap(0.02);
      scale.current.snap(0.94);
    }
  }, [accepted, acceptedAt, isCopy]);

  useFrame(({ clock }, dt) => {
    const g = group.current;
    if (!g) return;
    const now = Date.now();
    const t = clock.elapsedTime;
    const st = useStore.getState();
    const hovered = st.hover === tileKey;

    // --- transforms
    const y = rise.current.step(0, dt, isCopy ? 320 : 150, isCopy ? 13 : 11);
    const l = lift.current.step(selected ? 0.34 : hovered && !forming ? 0.06 : 0, dt, 210, 19);
    const sc = scale.current.step(1, dt, 240, 12);
    const plinthTarget = accepted ? TILE_HEIGHT : status === "planned" && !tile.attempts ? 0 : FORMING_HEIGHT;
    const ph = plinth.current.step(plinthTarget, dt, 140, 16);
    let shake = 0;
    if (rejectedAt && now - rejectedAt < FLASH_MS) {
      const k = (now - rejectedAt) / FLASH_MS;
      shake = Math.sin(k * 42) * 0.05 * (1 - k);
    }
    g.position.set(x + shake, y + l, z);
    g.scale.setScalar(sc);
    if (body.current) {
      body.current.visible = ph > 0.004;
      body.current.scale.y = Math.max(0.001, ph);
      body.current.position.y = ph / 2;
    }
    if (face.current) face.current.position.y = ph + 0.003;
    if (reliefMesh.current) {
      reliefMesh.current.position.y = ph + 0.002;
      const growing = !acceptedAt || now - acceptedAt > GROW_DELAY_MS;
      reliefMesh.current.scale.y = Math.max(0.02, grow.current.step(growing ? 1 : 0.02, dt, 120, 9));
    }
    if (shadowMat.current) shadowMat.current.opacity = Math.min(0.55, l * 1.6);
    if (sel.current && selMat.current) {
      sel.current.visible = selected;
      sel.current.position.y = ph + 0.01;
      selMat.current.opacity = 0.6 + 0.4 * Math.sin(t * 4);
    }

    // --- shockwave ring when the tile lands
    if (ring.current && ringMat.current) {
      const landAt = isCopy ? 170 : 120;
      const rk = acceptedAt ? (now - acceptedAt - landAt) / 1000 : -1;
      const vis = accepted && rk > 0 && rk < 1;
      ring.current.visible = vis;
      if (vis) {
        ring.current.scale.setScalar(1 + rk * 1.2);
        ringMat.current.opacity = 0.9 * (1 - rk) * (1 - rk);
      }
    }

    U.uCells.value = P + 3;
    if (accepted && texW) SURFACE_CELLS.value = texW; // all tiles of a world share one resolution

    // --- palette (eases when the material artist delivers the real ramp)
    const k = paletteSnapped.current ? 1 - Math.exp(-3 * dt) : 1;
    paletteSnapped.current = true;
    U.uPal.value.forEach((c, i) => c.lerp(palette[i], k));

    // --- body colour
    const m = bodyMat.current;
    if (m) {
      if (accepted) {
        m.color.set(tile.side_color ?? "#3a3f4b");
        m.emissiveIntensity = 0;
        m.opacity = 1;
        m.transparent = false;
      } else {
        m.color.copy(U.uPal.value[0]).multiplyScalar(0.8);
        m.emissive.copy(U.uPal.value[3]);
        m.emissiveIntensity = 0.12 + 0.08 * Math.sin(t * 2.4 + phaseOf(tileKey));
        m.transparent = true;
        m.opacity = 0.92;
      }
      if (rejectedAt && now - rejectedAt < FLASH_MS) {
        m.emissive.set("#ef4444");
        m.emissiveIntensity = (1 - (now - rejectedAt) / FLASH_MS) * 1.2;
      }
    }
    if (!forming) return;

    // --- forming surface
    const since = st.statusAt[tileKey] ? now - st.statusAt[tileKey] : 0;
    U.uTime.value = t;
    const retry = status === "planned" && !!tile.attempts;
    U.uState.value = status === "planned" && !retry ? 0 : 1;
    U.uAppear.value = plannedAt ? clamp01((now - plannedAt - planDelay) / PLAN_FADE_MS) : 1;
    let pulse = 0;
    for (const nk of neighbourKeys) {
      const at = st.acceptedAt[nk];
      if (at && now > at) pulse = Math.max(pulse, Math.exp(-(now - at) / 650));
    }
    U.uPulse.value = pulse;
    const fillTarget =
      status === "reviewing" ? 1 : status === "generating" ? 0.12 + 0.86 * (1 - Math.exp(-since / 7000)) : fill.current;
    fill.current += (fillTarget - fill.current) * (1 - Math.exp(-4 * dt));
    U.uFill.value = fill.current;
    const recentlyRejected = !!rejectedAt && now - rejectedAt < FLASH_MS;
    const map = tex ?? (recentlyRejected ? lastTex.current : null);
    U.uMap.value = map;
    U.uHasMap.value = map ? 1 : 0;
    const reveal = tex ? easeOut(clamp01((now - texReadyAt.current) / REVEAL_MS)) : 0;
    U.uReveal.value = recentlyRejected ? Math.max(0, 1 - (now - rejectedAt) / 700) : reveal;
    U.uScan.value = status === "reviewing" && tex ? clamp01((now - texReadyAt.current - REVEAL_MS) / 400) : 0;
    U.uGlitch.value = recentlyRejected ? 1 - (now - rejectedAt) / FLASH_MS : 0;
    formingMat.depthWrite = U.uState.value > 0.5;

    // rim: traces the hex in the palette (light while forming, a slow highlight breath under review)
    if (rim.current && rimMat.current) {
      rim.current.visible = U.uState.value > 0.5;
      rim.current.position.y = ph + 0.006;
      const reviewing = status === "reviewing";
      rimMat.current.color.copy(U.uPal.value[reviewing ? 4 : 3]);
      rimMat.current.opacity = (reviewing ? 0.55 : 0.45) + 0.2 * Math.sin(t * (reviewing ? 1.6 : 5.0));
    }
  });

  const onClick = (e: { stopPropagation: () => void; delta: number }) => {
    e.stopPropagation();
    if (e.delta > 5) return;
    const s = useStore.getState();
    s.select(s.selected === tileKey ? null : tileKey);
  };

  if (status === "intentionally_empty" || status === "failed") {
    const color = status === "failed" ? "#7f1d1d" : "#07080c";
    return (
      <group position={[x, 0, z]}>
        <mesh geometry={SHARED.emptyFace} position={[0, 0.006, 0]}>
          <meshStandardMaterial color={color} transparent opacity={status === "failed" ? 0.75 : 0.9} depthWrite={false} />
        </mesh>
      </group>
    );
  }

  return (
    <>
      <mesh geometry={SHARED.emptyFace} position={[x, 0.003, z]} raycast={NO_RAYCAST}>
        <meshBasicMaterial ref={shadowMat} color="#000000" transparent opacity={0} depthWrite={false} />
      </mesh>
      <group
        ref={group}
        position={[x, 0, z]}
        onClick={onClick}
        onPointerMove={(e) => {
          e.stopPropagation(); // the ground-plane grid underneath must not steal hover
          if (useStore.getState().hover !== tileKey) useStore.getState().setHover(tileKey);
        }}
      >
        <mesh ref={body} geometry={SHARED.prism} visible={false}>
          <meshStandardMaterial ref={bodyMat} roughness={0.95} />
        </mesh>
        {forming && <mesh ref={face} geometry={faceGeo} material={formingMat} renderOrder={2} />}
        {accepted &&
          tex &&
          (reliefGeo ? (
            <mesh key="relief" ref={reliefMesh} geometry={reliefGeo}>
              {/* terraces extruded from the heightmap; unlit texture, walls shaded per vertex */}
              <meshBasicMaterial
                map={tex}
                vertexColors
                side={THREE.DoubleSide}
                onBeforeCompile={reliefShader}
                customProgramCacheKey={reliefShaderKey}
              />
            </mesh>
          ) : (
            <mesh key="flat" geometry={faceGeo} position={[0, TILE_HEIGHT + 0.002, 0]}>
              {/* unlit: the pixel art shows its exact colours */}
              <meshBasicMaterial map={tex} alphaTest={0.5} />
            </mesh>
          ))}
        {sprites.map((layer, i) => (
          <SpriteBillboard
            key={`${layer.asset_id}-${i}`}
            layer={layer}
            top={TILE_HEIGHT + (levels ? levelAt(levels, tile.q, tile.r, layer.x, layer.y) * LEVEL_STEP : 0)}
            tileX={x}
            tileZ={z}
            index={i}
            landedAt={acceptedAt}
          />
        ))}
        <lineLoop ref={rim} geometry={RIM_GEO} visible={false} raycast={NO_RAYCAST}>
          <lineBasicMaterial ref={rimMat} transparent depthWrite={false} />
        </lineLoop>
        <lineLoop ref={sel} geometry={SEL_GEO} visible={false} raycast={NO_RAYCAST}>
          <lineBasicMaterial ref={selMat} color="#fde68a" transparent depthTest={false} />
        </lineLoop>
      </group>
      <mesh
        ref={ring}
        geometry={RING_GEO}
        position={[x, 0.02, z]}
        rotation={[-Math.PI / 2, 0, 0]}
        visible={false}
        raycast={NO_RAYCAST}
      >
        <meshBasicMaterial
          ref={ringMat}
          color={ringColor}
          transparent
          opacity={0}
          depthWrite={false}
          side={THREE.DoubleSide}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </>
  );
});

/** Upright sprite layer: cylindrical billboard, frame animation, procedural motion, pop-in. */
function SpriteBillboard({
  layer,
  top,
  tileX,
  tileZ,
  index,
  landedAt,
}: {
  layer: TileLayer;
  top: number;
  tileX: number;
  tileZ: number;
  index: number;
  landedAt: number | undefined;
}) {
  const base = usePixelTexture(layer.asset_id);
  const tex = useMemo(() => {
    if (!base || layer.frames <= 1) return base;
    const t = base.clone();
    t.repeat.set(1 / layer.frames, 1);
    t.needsUpdate = true;
    return t;
  }, [base, layer.frames]);
  const grp = useRef<THREE.Group>(null);
  const mesh = useRef<THREE.Mesh>(null);
  const mat = useRef<THREE.MeshBasicMaterial>(null);
  const pop = useRef(new Spring(landedAt ? 0 : 1));
  const phase = useMemo(() => phaseOf(`${layer.asset_id}${index}${tileX}`), [layer.asset_id, index, tileX]);
  const w = layer.width;
  const h = w * (layer.px_h / Math.max(1, layer.px_w));

  useEffect(() => {
    if (landedAt) pop.current.snap(0);
  }, [landedAt]);

  useFrame(({ camera, clock }, dt) => {
    const g = grp.current;
    const m = mesh.current;
    if (!g || !m) return;
    const t = clock.elapsedTime + phase;
    // cylindrical billboard: rotate around Y to face the camera
    g.rotation.y = Math.atan2(camera.position.x - (tileX + layer.x), camera.position.z - (tileZ + layer.y));
    const started = !landedAt || Date.now() - landedAt > SPRITE_POP_DELAY + index * SPRITE_POP_STAGGER;
    const s = pop.current.step(started ? 1 : 0, dt, 260, 15);
    let sx = s;
    let sy = s;
    m.rotation.z = 0;
    m.position.y = 0;
    if (layer.motion === "sway") m.rotation.z = Math.sin(t * 1.4) * 0.05;
    if (layer.motion === "bob") m.position.y = Math.sin(t * 2.2) * 0.03;
    if (layer.motion === "flicker") sy *= 1 + 0.06 * Math.sin(t * 17) + 0.03 * Math.sin(t * 31);
    if (mat.current) {
      const glow = layer.motion === "pulse" ? 1 + 0.3 * (0.5 + 0.5 * Math.sin(t * 2.6)) : 1;
      mat.current.color.setScalar(glow);
    }
    m.scale.set(w * Math.max(0.001, sx), h * Math.max(0.001, sy), 1);
    if (tex && layer.frames > 1 && layer.fps > 0) {
      tex.offset.x = (Math.floor(t * layer.fps) % layer.frames) / layer.frames;
    }
  });

  if (!tex) return null;
  return (
    <>
      {/* soft contact shadow: grounds the upright billboard on the terrain */}
      <mesh
        geometry={SHADOW_GEO}
        position={[layer.x, top + 0.004, layer.y + 0.01]}
        rotation={[-Math.PI / 2, 0, 0]}
        scale={[w * 0.62, w * 0.3, 1]}
        raycast={NO_RAYCAST}
        renderOrder={1}
      >
        <meshBasicMaterial color="#000000" transparent opacity={0.28} depthWrite={false} />
      </mesh>
      <group ref={grp} position={[layer.x, top, layer.y]}>
        {/* not pickable: a sprite overlaps the tile behind it on screen and would steal its clicks */}
        <mesh ref={mesh} geometry={SPRITE_GEO} scale={[0.001, 0.001, 1]} raycast={NO_RAYCAST}>
          <meshBasicMaterial ref={mat} map={tex} transparent alphaTest={0.5} side={THREE.DoubleSide} />
        </mesh>
      </group>
    </>
  );
}
