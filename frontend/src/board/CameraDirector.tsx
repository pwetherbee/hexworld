import { useFrame } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { useStore } from "../store";
import { rig } from "./cameraRig";
import { hexToWorld, parseKey } from "./hexMath";

/** Retarget at most this often: the camera eases toward a goal, it doesn't chase every event. */
const MIN_RETARGET_MS = 1600;
/** After the user touches the camera, auto-follow stays quiet this long. */
const USER_HOLD_MS = 5000;
const MIN_SHIFT = 0.9;
const MIN_ZOOM_CHANGE = 0.15;
const RECENT_MS = 2500;

type Goal = { target: THREE.Vector3; distance: number };

export class RateLimiter {
  private last = -Infinity;
  constructor(private minIntervalMs: number) {}
  ready(now: number) {
    return now - this.last >= this.minIntervalMs;
  }
  fire(now: number) {
    this.last = now;
  }
}

/** Where the action is: tiles being generated/reviewed + tiles that just landed. */
export function activityFrame(keys: string[]): Goal | null {
  if (!keys.length) return null;
  let cx = 0;
  let cz = 0;
  const pts = keys.map((k) => {
    const { q, r } = parseKey(k);
    const [x, z] = hexToWorld(q, r);
    cx += x;
    cz += z;
    return [x, z] as const;
  });
  cx /= pts.length;
  cz /= pts.length;
  let radius = 0;
  for (const [x, z] of pts) radius = Math.max(radius, Math.hypot(x - cx, z - cz));
  return { target: new THREE.Vector3(cx, 0, cz), distance: THREE.MathUtils.clamp(12 + radius * 1.3, 12, 34) };
}

/** Auto-follow: frames the active build, rate limited, yields to the user; also eases toward a
 * newly selected tile. The rig does the actual smoothing. */
export function CameraDirector() {
  const limiter = useRef(new RateLimiter(MIN_RETARGET_MS));
  const wasActive = useRef(false);
  const selected = useStore((s) => s.selected);

  // Selecting a tile: gently bring it toward the centre (without changing zoom much).
  useEffect(() => {
    if (!selected) return;
    const { q, r } = parseKey(selected);
    const [x, z] = hexToWorld(q, r);
    const t = new THREE.Vector3(x, 0, z);
    rig.setGoal(rig.goalTarget.clone().lerp(t, 0.65), Math.min(rig.goalDistance, 10));
    limiter.current.fire(performance.now());
  }, [selected]);

  useFrame(() => {
    const now = performance.now();
    const s = useStore.getState();
    if (!s.follow || rig.dragging || now - rig.userAt < USER_HOLD_MS || !limiter.current.ready(now)) return;
    const wall = Date.now();
    const hot = Object.entries(s.tiles)
      .filter(
        ([k, t]) =>
          t.status === "generating" ||
          t.status === "reviewing" ||
          (s.acceptedAt[k] !== undefined && wall - s.acceptedAt[k] < RECENT_MS),
      )
      .map(([k]) => k);
    let next: Goal | null = null;
    if (hot.length) {
      next = activityFrame(hot);
      wasActive.current = true;
    } else if (wasActive.current && !s.activeRunId) {
      wasActive.current = false; // run finished: one final overview
      next = activityFrame(Object.keys(s.tiles).filter((k) => s.tiles[k].status === "accepted"));
    }
    if (!next) return;
    const moved = next.target.distanceTo(rig.goalTarget) > MIN_SHIFT;
    const zoomed = Math.abs(next.distance - rig.goalDistance) / rig.goalDistance > MIN_ZOOM_CHANGE;
    if (moved || zoomed) {
      rig.setGoal(next.target, next.distance);
      limiter.current.fire(now);
    }
  });

  return null;
}
