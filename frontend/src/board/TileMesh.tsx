import { useFrame } from "@react-three/fiber";
import { memo, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { TileLayer } from "../api/types.gen";
import { useStore } from "../store";
import { SHARED, hexOutlinePoints, tileFaceGeometry } from "./geometry";
import { Spring, hexDistance, hexToWorld } from "./hexMath";
import { LEVEL_STEP, levelAt, reliefGeometry, useLevels } from "./relief";
import { usePixelTexture } from "./textures";

const FLASH_MS = 900;
const PLAN_STAGGER_MS = 70;
const PLAN_FADE_MS = 420;
const SPRITE_POP_DELAY = 240;
const SPRITE_POP_STAGGER = 70;

const COPY_COLORS = { shallow: "#a78bfa", deep: "#60a5fa" } as const;
const RING_GEO = new THREE.RingGeometry(0.9, 1.0, 6, 1, Math.PI / 6);
const SCAN_GEO = new THREE.BufferGeometry().setFromPoints(hexOutlinePoints(0.8, 0));
const SEL_GEO = new THREE.BufferGeometry().setFromPoints(hexOutlinePoints(1.0, 0));
const NO_RAYCAST = () => undefined;
const SPRITE_GEO = new THREE.PlaneGeometry(1, 1).translate(0, 0.5, 0); // anchored at the bottom

// All accepted tiles share one height: relief lives in the art (painted cliffs + heightmap layer),
// so neighbouring faces meet flush and the ground reads as one continuous surface.
export const TILE_HEIGHT = 0.16;

function biomeTint(biome: string | null | undefined): string {
  if (!biome) return "#94a3b8";
  let h = 0;
  for (const c of biome) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h}, 45%, 55%)`;
}

const phaseOf = (s: string) => {
  let h = 0;
  for (const c of s) h = (h * 33 + c.charCodeAt(0)) % 1000;
  return h / 159;
};

export const TileMesh = memo(function TileMesh({ tileKey }: { tileKey: string }) {
  const tile = useStore((s) => s.tiles[tileKey]);
  const acceptedAt = useStore((s) => s.acceptedAt[tileKey]);
  const rejectedAt = useStore((s) => s.rejectedAt[tileKey]);
  const plannedAt = useStore((s) => s.plannedAt[tileKey]);
  const selected = useStore((s) => s.selected === tileKey);
  const origin = useStore((s) => (s.activeRunId ? s.runs[s.activeRunId]?.origin : undefined));
  const status = tile.status;
  const accepted = status === "accepted";
  const groundLayer = tile.layers?.find((l) => l.kind === "ground");
  const tex = usePixelTexture(accepted ? (groundLayer?.asset_id ?? tile.asset_id) : tile.preview_asset_id);
  const sprites = accepted ? (tile.layers ?? []).filter((l) => l.kind === "sprite") : [];

  const group = useRef<THREE.Group>(null);
  const body = useRef<THREE.Mesh>(null);
  const bodyMat = useRef<THREE.MeshStandardMaterial>(null);
  const ring = useRef<THREE.Mesh>(null);
  const ringMat = useRef<THREE.MeshBasicMaterial>(null);
  const scan = useRef<THREE.LineLoop>(null);
  const sel = useRef<THREE.LineLoop>(null);
  const selMat = useRef<THREE.LineBasicMaterial>(null);
  const shadowMat = useRef<THREE.MeshBasicMaterial>(null);
  const baseEmissive = useRef("#000000");
  const rise = useRef(new Spring(0));
  const lift = useRef(new Spring(0));
  const scale = useRef(new Spring(1));

  const [x, z] = hexToWorld(tile.q, tile.r);
  const height = accepted ? TILE_HEIGHT : 0.08;
  const texW = (tex?.image as { width?: number } | undefined)?.width;
  const faceGeo = useMemo(
    () => (texW && texW > 8 ? tileFaceGeometry(tile.q, tile.r, texW - 3) : SHARED.face),
    [tile.q, tile.r, texW],
  );
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
  const ringColor = useMemo(
    () =>
      tile.copy_mode
        ? new THREE.Color(COPY_COLORS[tile.copy_mode])
        : new THREE.Color(tile.side_color ?? "#ffffff").offsetHSL(0, 0, 0.45),
    [tile.copy_mode, tile.side_color],
  );

  // Landing: generated tiles spring up out of the ground; copies are stamped down from above.
  useEffect(() => {
    if (!accepted || !acceptedAt) return;
    rise.current.snap(isCopy ? 3.4 : -height * 1.9);
    scale.current.snap(isCopy ? 1 : 0.72);
  }, [accepted, acceptedAt, isCopy, height]);

  useFrame(({ clock }, dt) => {
    const g = group.current;
    if (!g) return;
    const now = Date.now();
    const t = clock.elapsedTime;
    const hovered = useStore.getState().hover === tileKey;

    const y = rise.current.step(0, dt, isCopy ? 320 : 150, isCopy ? 13 : 11);
    const l = lift.current.step(selected ? 0.34 : hovered && accepted ? 0.06 : 0, dt, 210, 19);
    const sc = scale.current.step(1, dt, 180, 14);
    let shake = 0;
    if (rejectedAt && now - rejectedAt < FLASH_MS) {
      const k = (now - rejectedAt) / FLASH_MS;
      shake = Math.sin(k * 42) * 0.07 * (1 - k);
    }
    g.position.set(x + shake, y + l, z);
    g.scale.setScalar(sc);
    if (shadowMat.current) shadowMat.current.opacity = Math.min(0.55, l * 1.6);
    if (sel.current && selMat.current) {
      sel.current.visible = selected;
      selMat.current.opacity = 0.6 + 0.4 * Math.sin(t * 4);
    }

    // shockwave ring when the tile lands
    if (ring.current && ringMat.current) {
      const landAt = isCopy ? 170 : 260;
      const rk = acceptedAt ? (now - acceptedAt - landAt) / 1000 : -1;
      const vis = accepted && rk > 0 && rk < 1;
      ring.current.visible = vis;
      if (vis) {
        ring.current.scale.setScalar(1 + rk * 1.2);
        ringMat.current.opacity = 0.9 * (1 - rk) * (1 - rk);
      }
    }
    if (scan.current) {
      scan.current.visible = status === "generating";
      scan.current.rotation.y = t * 1.6;
      scan.current.position.y = 0.25 + 0.12 * Math.sin(t * 3 + tile.q);
    }

    const m = bodyMat.current;
    if (!m) return;
    const flash = rejectedAt && now - rejectedAt < FLASH_MS ? 1 - (now - rejectedAt) / FLASH_MS : 0;
    if (status === "generating") {
      const p = 0.5 + 0.5 * Math.sin(t * 5 + tile.q * 0.7 + tile.r * 1.3);
      m.emissiveIntensity = 0.35 + 0.65 * p;
      m.opacity = 0.35 + 0.3 * p;
      if (body.current) body.current.scale.y = 0.06 + 0.1 * p;
    } else if (status === "reviewing") {
      m.emissiveIntensity = 0.4 + 0.3 * Math.sin(t * 3);
    } else if (status === "planned") {
      const appear = plannedAt ? Math.max(0, Math.min(1, (now - plannedAt - planDelay) / PLAN_FADE_MS)) : 1;
      m.opacity = appear * (0.16 + 0.08 * Math.sin(t * 1.5 + tile.q + tile.r));
    }
    if (flash > 0) {
      m.emissive.set("#ef4444");
      m.emissiveIntensity = flash * 1.4;
    } else {
      m.emissive.set(baseEmissive.current);
      if (accepted || status === "failed" || status === "intentionally_empty") m.emissiveIntensity = 0;
    }
  });

  const onClick = (e: { stopPropagation: () => void; delta: number }) => {
    e.stopPropagation();
    if (e.delta > 5) return;
    const s = useStore.getState();
    s.select(s.selected === tileKey ? null : tileKey);
  };

  if (status === "intentionally_empty" || status === "failed" || status === "planned") {
    const color = status === "failed" ? "#7f1d1d" : status === "planned" ? biomeTint(tile.biome) : "#07080c";
    baseEmissive.current = color;
    return (
      <group ref={group} position={[x, 0, z]}>
        <mesh geometry={SHARED.emptyFace} position={[0, 0.006, 0]}>
          <meshStandardMaterial
            ref={bodyMat}
            color={color}
            transparent
            opacity={status === "failed" ? 0.75 : status === "planned" ? 0 : 0.9}
            emissive={color}
            emissiveIntensity={0}
            depthWrite={false}
          />
        </mesh>
      </group>
    );
  }

  const bodyColor = accepted ? (tile.side_color ?? "#3a3f4b") : status === "reviewing" ? "#f59e0b" : "#22d3ee";
  const translucent = !accepted;
  baseEmissive.current = bodyColor;

  return (
    <>
      <mesh geometry={SHARED.emptyFace} position={[x, 0.003, z]} rotation={[0, 0, 0]} raycast={NO_RAYCAST}>
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
        <mesh ref={body} geometry={SHARED.prism} position={[0, height / 2, 0]} scale={[1, height, 1]}>
          <meshStandardMaterial
            ref={bodyMat}
            color={bodyColor}
            emissive={bodyColor}
            emissiveIntensity={translucent ? 0.5 : 0}
            roughness={0.95}
            transparent={translucent}
            opacity={translucent ? 0.55 : 1}
          />
        </mesh>
        {tex && (
          reliefGeo ? (
            <mesh key="relief" geometry={reliefGeo} position={[0, height + 0.002, 0]}>
              {/* terraces extruded from the heightmap; unlit texture, walls shaded per vertex */}
              <meshBasicMaterial map={tex} vertexColors side={THREE.DoubleSide} />
            </mesh>
          ) : (
            <mesh key="flat" geometry={faceGeo} position={[0, height + 0.002, 0]}>
              {/* unlit: the pixel art shows its exact colours */}
              <meshBasicMaterial map={tex} transparent={!accepted} opacity={accepted ? 1 : 0.85} alphaTest={0.5} />
            </mesh>
          )
        )}
        {sprites.map((layer, i) => (
          <SpriteBillboard
            key={`${layer.asset_id}-${i}`}
            layer={layer}
            top={height + (levels ? levelAt(levels, tile.q, tile.r, layer.x, layer.y) * LEVEL_STEP : 0)}
            tileX={x}
            tileZ={z}
            index={i}
            landedAt={acceptedAt}
          />
        ))}
        <lineLoop ref={sel} geometry={SEL_GEO} position={[0, height + 0.01, 0]} visible={false} raycast={NO_RAYCAST}>
          <lineBasicMaterial ref={selMat} color="#fde68a" transparent depthTest={false} />
        </lineLoop>
        <lineLoop ref={scan} geometry={SCAN_GEO} visible={false} raycast={NO_RAYCAST}>
          <lineBasicMaterial color="#67e8f9" transparent opacity={0.9} />
        </lineLoop>
      </group>
      <mesh ref={ring} geometry={RING_GEO} position={[x, 0.02, z]} rotation={[-Math.PI / 2, 0, 0]} visible={false} raycast={NO_RAYCAST}>
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
    <group ref={grp} position={[layer.x, top, layer.y]}>
      {/* not pickable: a sprite overlaps the tile behind it on screen and would steal its clicks */}
      <mesh ref={mesh} geometry={SPRITE_GEO} scale={[0.001, 0.001, 1]} raycast={NO_RAYCAST}>
        <meshBasicMaterial ref={mat} map={tex} transparent alphaTest={0.5} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}
