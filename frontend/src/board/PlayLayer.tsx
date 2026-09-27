import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { HOP_MS, usePlay } from "../play";
import { useStore } from "../store";
import { hexOutlinePoints } from "./geometry";
import { DIRECTIONS, hexKey, hexToWorld } from "./hexMath";
import { rig } from "./cameraRig";
import { LEVEL_STEP, levelAt, useLevels } from "./relief";
import { usePixelTexture } from "./textures";
import { TILE_HEIGHT } from "./TileMesh";

const NO_RAYCAST = () => undefined;
const SPRITE_GEO = new THREE.PlaneGeometry(1, 1).translate(0, 0.5, 0);
const SHADOW_GEO = new THREE.CircleGeometry(0.5, 20);
const RING_GEO = new THREE.BufferGeometry().setFromPoints(hexOutlinePoints(0.9, 0));
const MARK_GEO = new THREE.OctahedronGeometry(0.12, 0);
const HOP_HEIGHT = 0.45;
const AVATAR_WIDTH = 0.55; // world units: a traveller reads clearly at both layers
const STAND_Z = 0.34; // where the traveller stands on a tile: in front of its landmark
const FOOT_SAMPLES: ReadonlyArray<[number, number]> = [
  [0, STAND_Z], [0.1, STAND_Z], [-0.1, STAND_Z], [0, STAND_Z - 0.1], [0, STAND_Z + 0.08],
];

/** Everything play mode adds to the 3D board: the traveller, where they can step, the camera. */
export function PlayLayer() {
  const active = usePlay((s) => s.active);
  if (!active) return null;
  return (
    <>
      <Avatar />
      <Reach />
      <PlayCamera />
    </>
  );
}

function useHere() {
  return usePlay((s) => s.stack[s.stack.length - 1]);
}

/** Height of the ground at the middle of a tile (relief levels -> world units). */
function useGroundY(q: number, r: number) {
  const tile = useStore((s) => s.tiles[hexKey(q, r)]);
  const heightId = tile?.status === "accepted" ? tile.layers?.find((l) => l.kind === "height")?.asset_id : undefined;
  const levels = useLevels(heightId);
  // stand on the highest ground around the feet, so the traveller never sinks into a rock or roof
  const top = levels ? Math.max(...FOOT_SAMPLES.map(([x, z]) => levelAt(levels, q, r, x, z))) : 0;
  return TILE_HEIGHT + top * LEVEL_STEP;
}

function Avatar() {
  const here = useHere();
  const from = usePlay((s) => s.from);
  const hopAt = usePlay((s) => s.hopAt);
  const avatar = usePlay((s) => s.avatar);
  const tex = usePixelTexture(avatar?.asset_id);
  const y = useGroundY(here.q, here.r);
  const fromY = useGroundY(from?.q ?? here.q, from?.r ?? here.r);
  const grp = useRef<THREE.Group>(null);
  const body = useRef<THREE.Group>(null);
  const [tx, tz] = hexToWorld(here.q, here.r);
  const [fx, fz] = from ? hexToWorld(from.q, from.r) : [tx, tz];
  const w = AVATAR_WIDTH;
  const h = avatar ? w * (avatar.px_h / Math.max(1, avatar.px_w)) : 0.5;

  useFrame(({ camera, clock }) => {
    const g = grp.current;
    const b = body.current;
    if (!g || !b) return;
    const k = Math.min(1, (performance.now() - hopAt) / HOP_MS);
    const e = k < 1 ? 1 - (1 - k) ** 2 : 1;
    const x = fx + (tx - fx) * e;
    const z = fz + (tz - fz) * e + STAND_Z;
    const arc = k < 1 ? Math.sin(Math.PI * k) * HOP_HEIGHT : 0;
    g.position.set(x, fromY + (y - fromY) * e + arc, z);
    // squash on landing, gentle breathing at rest
    const land = k < 1 ? 0 : Math.max(0, 1 - (performance.now() - hopAt - HOP_MS) / 160);
    const breathe = Math.sin(clock.elapsedTime * 2.1) * 0.02;
    b.scale.set(w * (1 + 0.18 * land), h * (1 - 0.2 * land + breathe), 1);
    // face the camera, leaning back toward a high camera like the world's sprites
    const dx = camera.position.x - x;
    const dz = camera.position.z - z;
    g.rotation.order = "YXZ";
    g.rotation.y = Math.atan2(dx, dz);
    const pitch = Math.atan2(camera.position.y - g.position.y, Math.hypot(dx, dz));
    g.rotation.x = -Math.min(1.0, Math.max(0, pitch - 0.25) * 0.85);
  });

  return (
    <>
      <mesh geometry={SHADOW_GEO} position={[tx, y + 0.005, tz + STAND_Z]} rotation={[-Math.PI / 2, 0, 0]} scale={[w * 0.7, w * 0.35, 1]} raycast={NO_RAYCAST} renderOrder={1}>
        <meshBasicMaterial color="#000000" transparent opacity={0.35} depthWrite={false} />
      </mesh>
      <group ref={grp}>
        <group ref={body}>
          {tex ? (
            <>
              <mesh key="sprite" geometry={SPRITE_GEO} raycast={NO_RAYCAST} renderOrder={3}>
                <meshBasicMaterial key="sprite-mat" map={tex} color="#ffffff" transparent alphaTest={0.5} side={THREE.DoubleSide} />
              </mesh>
              {/* x-ray: where terrain hides the traveller, a pale silhouette shows through */}
              <mesh key="xray" geometry={SPRITE_GEO} raycast={NO_RAYCAST} renderOrder={4}>
                <meshBasicMaterial
                  map={tex}
                  color="#fde68a"
                  transparent
                  opacity={0.45}
                  alphaTest={0.5}
                  depthFunc={THREE.GreaterDepth}
                  depthWrite={false}
                  side={THREE.DoubleSide}
                />
              </mesh>
            </>
          ) : (
            // no painted traveller yet (or no image model): a plain marker
            <mesh key="marker" geometry={MARK_GEO} position={[0, 0.5, 0]} scale={[1 / w, 1 / h, 1]} raycast={NO_RAYCAST}>
              <meshBasicMaterial color="#fde68a" />
            </mesh>
          )}
        </group>
      </group>
    </>
  );
}

/** Soft rings on the tiles one hop away. */
function Reach() {
  const here = useHere();
  const tiles = useStore((s) => s.tiles);
  const moving = usePlay((s) => s.queue.length > 0);
  const ring = useRef<THREE.Group>(null);
  const spots = useMemo(
    () =>
      DIRECTIONS.map(([dq, dr]) => [here.q + dq, here.r + dr] as const).filter(
        ([q, r]) => tiles[hexKey(q, r)]?.status === "accepted",
      ),
    [here.q, here.r, tiles],
  );
  useFrame(({ clock }) => {
    if (ring.current) ring.current.visible = !moving;
    ring.current?.children.forEach((c, i) => {
      const m = (c as THREE.LineLoop).material as THREE.LineBasicMaterial;
      m.opacity = 0.25 + 0.15 * Math.sin(clock.elapsedTime * 2.4 + i);
    });
  });
  return (
    <group ref={ring}>
      {spots.map(([q, r]) => {
        const [x, z] = hexToWorld(q, r);
        return (
          <lineLoop key={`${q},${r}`} geometry={RING_GEO} position={[x, TILE_HEIGHT + 0.02, z]} raycast={NO_RAYCAST}>
            <lineBasicMaterial color="#fde68a" transparent opacity={0.3} depthWrite={false} />
          </lineLoop>
        );
      })}
    </group>
  );
}

/** Keeps the traveller in view: eases toward them at a walking distance. */
function PlayCamera() {
  const here = useHere();
  const depth = useStore((s) => s.world?.depth ?? 0);
  useEffect(() => {
    const [x, z] = hexToWorld(here.q, here.r);
    rig.setGoal(new THREE.Vector3(x, 0, z), depth > 0 ? 7.5 : 9);
  }, [here.q, here.r, here.worldId, depth]);
  return null;
}
