import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { useStore } from "../store";
import { hexToWorld, parseKey } from "./hexMath";

/** Retarget at most this often: the camera eases toward a goal, it doesn't chase every event. */
const MIN_RETARGET_MS = 1600;
/** After the user grabs the camera, auto-follow stays quiet this long. */
const USER_HOLD_MS = 5000;
/** Ignore goal changes smaller than this (world units / relative zoom). */
const MIN_SHIFT = 0.9;
const MIN_ZOOM_CHANGE = 0.15;
/** Exponential smoothing rate (1/s): higher = snappier. */
const DAMP = 2.0;
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

/** Compute where the action is: tiles being generated/reviewed + tiles that just landed. */
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
  return {
    target: new THREE.Vector3(cx, 0, cz),
    distance: THREE.MathUtils.clamp(9 + radius * 2.1, 9, 55),
  };
}

export function CameraDirector() {
  const controls = useThree((s) => s.controls) as unknown as
    | (THREE.EventDispatcher<{ start: object; end: object }> & { target: THREE.Vector3; update: () => void })
    | null;
  const camera = useThree((s) => s.camera);
  const dom = useThree((s) => s.gl.domElement);
  const goal = useRef<Goal | null>(null);
  const limiter = useRef(new RateLimiter(MIN_RETARGET_MS));
  const userAt = useRef(-Infinity);
  const dragging = useRef(false);
  const wasActive = useRef(false);

  useEffect(() => {
    if (!controls) return;
    const onStart = () => {
      dragging.current = true;
      userAt.current = performance.now();
      goal.current = null; // the user wins immediately
    };
    const onEnd = () => {
      dragging.current = false;
      userAt.current = performance.now();
    };
    controls.addEventListener("start", onStart);
    controls.addEventListener("end", onEnd);
    const onWheel = () => {
      userAt.current = performance.now();
      goal.current = null;
    };
    dom.addEventListener("wheel", onWheel, { passive: true });
    return () => {
      controls.removeEventListener("start", onStart);
      controls.removeEventListener("end", onEnd);
      dom.removeEventListener("wheel", onWheel);
    };
  }, [controls, dom]);

  useFrame((_, dt) => {
    if (!controls) return;
    const now = performance.now();
    const s = useStore.getState();

    // 1) choose a new goal (rate limited, only while following and not overridden by the user)
    const userHolding = dragging.current || now - userAt.current < USER_HOLD_MS;
    if (s.follow && !userHolding && limiter.current.ready(now)) {
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
        // Run finished: one final overview of everything built so far.
        wasActive.current = false;
        next = activityFrame(Object.keys(s.tiles).filter((k) => s.tiles[k].status === "accepted"));
      }
      if (next) {
        const cur = goal.current ?? { target: controls.target.clone(), distance: camera.position.distanceTo(controls.target) };
        const moved = next.target.distanceTo(cur.target) > MIN_SHIFT;
        const zoomed = Math.abs(next.distance - cur.distance) / cur.distance > MIN_ZOOM_CHANGE;
        if (moved || zoomed) {
          goal.current = next;
          limiter.current.fire(now);
        }
      }
    }

    // 2) ease toward the goal, preserving the user's current viewing angle
    const g = goal.current;
    if (!g || userHolding) return;
    const k = 1 - Math.exp(-DAMP * Math.min(dt, 0.1));
    const offset = camera.position.clone().sub(controls.target);
    const dist = offset.length();
    const newTarget = controls.target.clone().lerp(g.target, k);
    const newDist = THREE.MathUtils.lerp(dist, g.distance, k);
    offset.setLength(newDist);
    controls.target.copy(newTarget);
    camera.position.copy(newTarget).add(offset);
    controls.update();
    if (newTarget.distanceTo(g.target) < 0.02 && Math.abs(newDist - g.distance) < 0.02) goal.current = null;
  });

  return null;
}
