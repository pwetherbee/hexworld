import { useFrame, useThree } from "@react-three/fiber";
import { useEffect } from "react";
import * as THREE from "three";

/**
 * Hand-rolled camera rig tuned for feel:
 * - left drag pans 1:1 with the ground under the cursor, and keeps gliding (momentum) on release
 * - wheel zooms smoothly toward the point under the cursor
 * - right drag (or shift+drag) orbits: yaw + pitch, damped
 * Everything eases toward "goal" values each frame; the director (auto-follow) sets goals too.
 */
export const rig = {
  target: new THREE.Vector3(0, 0, 0),
  goalTarget: new THREE.Vector3(0, 0, 0),
  distance: 24,
  goalDistance: 24,
  yaw: 0,
  goalYaw: 0,
  pitch: 0.78, // radians from vertical
  goalPitch: 0.78,
  vel: new THREE.Vector3(),
  dragging: false,
  userAt: -Infinity,
  setGoal(target: THREE.Vector3, distance?: number) {
    this.goalTarget.copy(target);
    if (distance !== undefined) this.goalDistance = distance;
    this.vel.set(0, 0, 0);
  },
};

const MIN_DIST = 5;
const MAX_DIST = 140;
const PLANE = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

export function CameraRig() {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const gl = useThree((s) => s.gl);

  useEffect(() => {
    const el = gl.domElement;
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    const groundAt = (clientX: number, clientY: number, out: THREE.Vector3) => {
      const r = el.getBoundingClientRect();
      ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      return ray.ray.intersectPlane(PLANE, out);
    };

    let mode: "pan" | "orbit" | null = null;
    let lastX = 0;
    let lastY = 0;
    let lastT = 0;
    const cur = new THREE.Vector3();

    const down = (e: PointerEvent) => {
      mode = e.button === 2 || e.button === 1 || e.shiftKey ? "orbit" : e.button === 0 ? "pan" : null;
      if (!mode) return;
      lastX = e.clientX;
      lastY = e.clientY;
      lastT = performance.now();
      rig.vel.set(0, 0, 0);
      rig.dragging = true;
      rig.userAt = performance.now();
    };
    const move = (e: PointerEvent) => {
      if (!mode) return;
      const now = performance.now();
      const dt = Math.max(1, now - lastT) / 1000;
      if (mode === "pan") {
        // world units per pixel at the focus distance; vertical motion is foreshortened by the tilt
        const h = el.getBoundingClientRect().height || 1;
        const wpp = (2 * rig.distance * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) / h;
        const dx = (e.clientX - lastX) * wpp;
        const dz = ((e.clientY - lastY) * wpp) / Math.max(0.35, Math.cos(rig.pitch));
        const right = new THREE.Vector3(Math.cos(rig.yaw), 0, -Math.sin(rig.yaw));
        const fwd = new THREE.Vector3(-Math.sin(rig.yaw), 0, -Math.cos(rig.yaw));
        const delta = right.multiplyScalar(-dx).addScaledVector(fwd, dz);
        rig.target.add(delta);
        rig.goalTarget.add(delta);
        rig.vel.lerp(delta.clone().divideScalar(dt), 0.4);
      } else {
        rig.goalYaw -= (e.clientX - lastX) * 0.006;
        rig.goalPitch = THREE.MathUtils.clamp(rig.goalPitch - (e.clientY - lastY) * 0.004, 0.25, 1.25);
      }
      lastX = e.clientX;
      lastY = e.clientY;
      lastT = now;
      rig.userAt = now;
    };
    const up = () => {
      if (performance.now() - lastT > 90) rig.vel.set(0, 0, 0); // paused before release: no fling
      mode = null;
      rig.dragging = false;
      rig.userAt = performance.now();
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const factor = Math.exp(e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
      const next = THREE.MathUtils.clamp(rig.goalDistance * factor, MIN_DIST, MAX_DIST);
      const applied = next / rig.goalDistance;
      if (groundAt(e.clientX, e.clientY, cur)) {
        // zoom toward the cursor: the point under it stays (roughly) put
        rig.goalTarget.lerp(cur, 1 - applied);
        rig.goalTarget.y = 0;
      }
      rig.goalDistance = next;
      rig.vel.set(0, 0, 0);
      rig.userAt = performance.now();
    };
    const ctx = (e: Event) => e.preventDefault();
    const keys = new Set<string>();
    const kd = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      keys.add(e.key.toLowerCase());
    };
    const ku = (e: KeyboardEvent) => keys.delete(e.key.toLowerCase());
    (rig as unknown as { keys: Set<string> }).keys = keys;

    el.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    el.addEventListener("wheel", wheel, { passive: false });
    el.addEventListener("contextmenu", ctx);
    window.addEventListener("keydown", kd);
    window.addEventListener("keyup", ku);
    return () => {
      el.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      el.removeEventListener("wheel", wheel);
      el.removeEventListener("contextmenu", ctx);
      window.removeEventListener("keydown", kd);
      window.removeEventListener("keyup", ku);
    };
  }, [camera, gl]);

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 1 / 20);
    // keyboard pan (WASD / arrows), relative to the view direction
    const keys = (rig as unknown as { keys?: Set<string> }).keys;
    if (keys && keys.size) {
      const f = new THREE.Vector3(Math.sin(rig.yaw), 0, Math.cos(rig.yaw)).multiplyScalar(-1);
      const r = new THREE.Vector3(f.z, 0, -f.x).multiplyScalar(-1);
      const speed = rig.distance * 1.1 * dt;
      const d = new THREE.Vector3();
      if (keys.has("w") || keys.has("arrowup")) d.add(f);
      if (keys.has("s") || keys.has("arrowdown")) d.sub(f);
      if (keys.has("a") || keys.has("arrowleft")) d.sub(r);
      if (keys.has("d") || keys.has("arrowright")) d.add(r);
      if (d.lengthSq()) {
        rig.goalTarget.addScaledVector(d.normalize(), speed);
        rig.userAt = performance.now();
      }
    }
    // momentum
    if (!rig.dragging && rig.vel.lengthSq() > 1e-4) {
      rig.goalTarget.addScaledVector(rig.vel, dt);
      rig.target.addScaledVector(rig.vel, dt);
      rig.vel.multiplyScalar(Math.exp(-3.2 * dt));
    }
    const kPan = 1 - Math.exp(-10 * dt);
    const kZoom = 1 - Math.exp(-7 * dt);
    const kRot = 1 - Math.exp(-9 * dt);
    rig.target.lerp(rig.goalTarget, kPan);
    rig.distance += (rig.goalDistance - rig.distance) * kZoom;
    rig.yaw += (rig.goalYaw - rig.yaw) * kRot;
    rig.pitch += (rig.goalPitch - rig.pitch) * kRot;
    const sp = Math.sin(rig.pitch);
    camera.position.set(
      rig.target.x + rig.distance * sp * Math.sin(rig.yaw),
      rig.target.y + rig.distance * Math.cos(rig.pitch),
      rig.target.z + rig.distance * sp * Math.cos(rig.yaw),
    );
    camera.lookAt(rig.target);
  });

  return null;
}
