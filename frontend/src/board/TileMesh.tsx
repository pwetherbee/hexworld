import { useFrame } from "@react-three/fiber";
import { memo, useMemo, useRef } from "react";
import * as THREE from "three";
import type { Tile } from "../api/types.gen";
import { useStore } from "../store";
import { SHARED, hexOutlinePoints } from "./geometry";
import { hexDistance, hexToWorld } from "./hexMath";
import { usePixelTexture } from "./textures";

const RISE_MS = 800;
const STAMP_MS = 650;
const RING_MS = 1000;
const FLASH_MS = 900;
const PLAN_STAGGER_MS = 90;
const PLAN_FADE_MS = 400;

const COPY_COLORS = { shallow: "#a78bfa", deep: "#60a5fa" } as const;

export function tileHeight(t: Tile): number {
  const biome = t.biome ?? "";
  if (/water|ocean|sea|lava|lake/.test(biome)) return 0.12;
  const elev = typeof t.attributes?.elevation === "number" ? (t.attributes.elevation as number) : 1.5;
  return 0.18 + Math.max(0, Math.min(6, elev)) * 0.07;
}

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

function easeOutBack(t: number) {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
}

function easeOutBounce(t: number) {
  const n1 = 7.5625;
  const d1 = 2.75;
  if (t < 1 / d1) return n1 * t * t;
  if (t < 2 / d1) return n1 * (t -= 1.5 / d1) * t + 0.75;
  if (t < 2.5 / d1) return n1 * (t -= 2.25 / d1) * t + 0.9375;
  return n1 * (t -= 2.625 / d1) * t + 0.984375;
}

function biomeTint(biome: string | null | undefined): string {
  if (!biome) return "#94a3b8";
  let h = 0;
  for (const c of biome) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h}, 45%, 55%)`;
}

const RING_GEO = new THREE.RingGeometry(0.9, 1.0, 6, 1, Math.PI / 6);
const SCAN_GEO = new THREE.BufferGeometry().setFromPoints(hexOutlinePoints(0.8, 0));

export const TileMesh = memo(function TileMesh({ tileKey }: { tileKey: string }) {
  const tile = useStore((s) => s.tiles[tileKey]);
  const acceptedAt = useStore((s) => s.acceptedAt[tileKey]);
  const rejectedAt = useStore((s) => s.rejectedAt[tileKey]);
  const plannedAt = useStore((s) => s.plannedAt[tileKey]);
  const origin = useStore((s) => (s.activeRunId ? s.runs[s.activeRunId]?.origin : undefined));
  const status = tile.status;
  const tex = usePixelTexture(status === "accepted" ? tile.asset_id : tile.preview_asset_id);

  const group = useRef<THREE.Group>(null);
  const body = useRef<THREE.Mesh>(null);
  const bodyMat = useRef<THREE.MeshStandardMaterial>(null);
  const ring = useRef<THREE.Mesh>(null);
  const ringMat = useRef<THREE.MeshBasicMaterial>(null);
  const scan = useRef<THREE.LineLoop>(null);
  const baseEmissive = useRef("#000000");
  const [x, z] = hexToWorld(tile.q, tile.r);
  const height = status === "accepted" ? tileHeight(tile) : 0.08;
  const isCopy = status === "accepted" && !!tile.copy_mode;
  const planDelay = origin ? hexDistance(origin, tile) * PLAN_STAGGER_MS : 0;
  const ringColor = useMemo(
    () => (tile.copy_mode ? COPY_COLORS[tile.copy_mode] : new THREE.Color(tile.side_color ?? "#ffffff").offsetHSL(0, 0, 0.45)),
    [tile.copy_mode, tile.side_color],
  );

  useFrame(({ clock }) => {
    const g = group.current;
    if (!g) return;
    const now = Date.now();
    const t = clock.elapsedTime;
    let yOff = 0;
    let shake = 0;
    let scale = 1;

    if (status === "accepted" && acceptedAt) {
      const age = now - acceptedAt;
      if (isCopy) {
        // Copies are "stamped": dropped from above with a bounce.
        const k = clamp01(age / STAMP_MS);
        yOff = 3.2 * (1 - easeOutBounce(k));
      } else {
        // Generated tiles grow out of the ground with a little overshoot.
        const k = clamp01(age / RISE_MS);
        yOff = -height * 1.4 * (1 - easeOutBack(k));
        scale = 0.82 + 0.18 * clamp01(k * 1.6);
      }
      // Shockwave ring when the tile lands.
      const landAt = isCopy ? STAMP_MS * 0.36 : RISE_MS * 0.35;
      const rk = (age - landAt) / RING_MS;
      if (ring.current && ringMat.current) {
        const vis = rk > 0 && rk < 1;
        ring.current.visible = vis;
        if (vis) {
          ring.current.scale.setScalar(1 + rk * 1.1);
          ringMat.current.opacity = 0.85 * (1 - rk) * (1 - rk);
        }
      }
    } else if (ring.current) {
      ring.current.visible = false;
    }

    if (rejectedAt && now - rejectedAt < FLASH_MS) {
      const k = (now - rejectedAt) / FLASH_MS;
      shake = Math.sin(k * 42) * 0.07 * (1 - k);
    }
    g.position.set(x + shake, yOff, z);
    g.scale.setScalar(scale);

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
      const appear = plannedAt ? clamp01((now - plannedAt - planDelay) / PLAN_FADE_MS) : 1;
      m.opacity = appear * (0.16 + 0.08 * Math.sin(t * 1.5 + tile.q + tile.r));
    }
    if (flash > 0) {
      m.emissive.set("#ef4444");
      m.emissiveIntensity = flash * 1.4;
    } else {
      m.emissive.set(baseEmissive.current);
      if (status === "accepted" || status === "failed" || status === "intentionally_empty") m.emissiveIntensity = 0;
    }
  });

  const onClick = (e: { stopPropagation: () => void; delta: number }) => {
    e.stopPropagation();
    if (e.delta > 5) return;
    useStore.getState().select(tileKey);
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

  const bodyColor =
    status === "accepted" ? tile.side_color ?? "#3a3f4b" : status === "reviewing" ? "#f59e0b" : "#22d3ee";
  const translucent = status !== "accepted";
  baseEmissive.current = bodyColor;

  return (
    <>
      <group ref={group} position={[x, 0, z]} onClick={onClick}>
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
          <mesh geometry={SHARED.face} position={[0, height + 0.002, 0]}>
            <meshStandardMaterial
              map={tex}
              roughness={1}
              metalness={0}
              transparent={status !== "accepted"}
              opacity={status === "accepted" ? 1 : 0.85}
              alphaTest={0.5}
            />
          </mesh>
        )}
        <lineLoop ref={scan} geometry={SCAN_GEO} visible={false}>
          <lineBasicMaterial color="#67e8f9" transparent opacity={0.9} />
        </lineLoop>
      </group>
      <mesh ref={ring} geometry={RING_GEO} position={[x, 0.02, z]} rotation={[-Math.PI / 2, 0, 0]} visible={false}>
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
