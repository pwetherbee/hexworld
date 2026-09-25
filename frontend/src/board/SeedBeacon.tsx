import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useStore } from "../store";
import { rig } from "./cameraRig";
import { tilePalette } from "./forming";
import { SHARED, hexOutlinePoints } from "./geometry";
import { SQRT3, Spring, hexKey, hexToWorld } from "./hexMath";

/**
 * The seed of a build, shown the moment a run is requested (and, softly, while the prompt card
 * is open on an empty hex): a glowing plinth with a hexagonal beam of light, pixel motes spiralling
 * up it, and survey rings sweeping out to the edge of the planned area while the super plans.
 * It takes on the origin's palette as soon as the plan header names its biome, and hands over to
 * the tile's own forming animation once the origin tile starts building.
 */

const MOTES = 28;
const RING_COUNT = 3;
const RING_PERIOD = 1.6;
const CYAN = new THREE.Color("#67e8f9");
const HEX_RING = new THREE.BufferGeometry().setFromPoints(hexOutlinePoints(1.0, 0));
const NO_RAYCAST = () => undefined;

const beamVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
const beamFragment = /* glsl */ `
uniform float uTime, uIntensity;
uniform vec3 uColor;
varying vec2 vUv;
void main() {
  float fade = pow(1.0 - vUv.y, 2.2);
  // stepped bands streaming upwards (pixel-ish, not smooth)
  float bands = step(0.72, fract(vUv.y * 18.0 - uTime * 1.6));
  float a = uIntensity * fade * (0.22 + 0.35 * bands);
  gl_FragColor = vec4(uColor * (1.0 + 0.6 * bands), a);
  #include <colorspace_fragment>
}
`;

export function SeedBeacon() {
  const run = useStore((s) => (s.activeRunId ? s.runs[s.activeRunId] : undefined));
  const promptTarget = useStore((s) => s.promptTarget);
  const target = useMemo(() => {
    if (run) return { q: run.origin.q, r: run.origin.r, radius: run.options?.radius ?? 3, armed: false };
    if (promptTarget) return { ...promptTarget, radius: 0, armed: true };
    return null;
  }, [run, promptTarget]);
  const key = target ? hexKey(target.q, target.r) : null;

  // while the prompt card is open, ease the chosen hex up above the card so it stays in view
  useEffect(() => {
    if (!promptTarget) return;
    const [x, z] = hexToWorld(promptTarget.q, promptTarget.r);
    rig.setGoal(new THREE.Vector3(x, 0, z + 3.4), Math.min(rig.goalDistance, 16));
  }, [promptTarget]);

  // a run starts: centre on the seed and frame the area the survey rings will sweep
  const runId = run?.id;
  useEffect(() => {
    if (!runId || !run) return;
    const [x, z] = hexToWorld(run.origin.q, run.origin.r);
    rig.setGoal(new THREE.Vector3(x, 0, z), 10 + (run.options?.radius ?? 3) * 2.4);
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps
  const originTile = useStore((s) => (key ? s.tiles[key] : undefined));
  const biome = originTile?.biome ?? originTile?.directive?.biome ?? null;
  const mat = useStore((s) => (biome ? s.libMaterials[biome] : undefined));
  const color = useMemo(() => (biome ? tilePalette(biome, mat)[4] : CYAN), [biome, mat]);
  // planning = the run exists but the origin hasn't started building yet
  const planning =
    !!target && !target.armed && (!originTile || originTile.status === "empty" || originTile.status === "planned");
  const active = !!target && (target.armed || planning);

  const group = useRef<THREE.Group>(null);
  const plinth = useRef<THREE.Mesh>(null);
  const plinthMat = useRef<THREE.MeshStandardMaterial>(null);
  const beam = useRef<THREE.Mesh>(null);
  const rings = useRef<(THREE.LineLoop | null)[]>([]);
  const ringMats = useRef<(THREE.LineBasicMaterial | null)[]>([]);
  const intensity = useRef(new Spring(0));
  const lastPos = useRef<[number, number]>([0, 0]);
  const currentColor = useRef(CYAN.clone());

  const beamMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms: { uTime: { value: 0 }, uIntensity: { value: 0 }, uColor: { value: CYAN.clone() } },
        vertexShader: beamVertex,
        fragmentShader: beamFragment,
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
      }),
    [],
  );
  const beamGeo = useMemo(() => new THREE.CylinderGeometry(0.8, 0.92, 3.2, 6, 1, true).translate(0, 1.6, 0), []);
  const motes = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(MOTES * 3), 3));
    return g;
  }, []);
  const moteMat = useMemo(
    () =>
      new THREE.PointsMaterial({
        size: 0.07,
        color: CYAN.clone(),
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    [],
  );
  const seeds = useMemo(() => Array.from({ length: MOTES }, (_, i) => ({ a: i * 2.39996, s: 0.35 + (i % 7) * 0.09 })), []);

  useFrame(({ clock }, dt) => {
    const g = group.current;
    if (!g) return;
    const t = clock.elapsedTime;
    const goal = active ? (target?.armed ? 0.45 : 1) : 0;
    const k = intensity.current.step(goal, dt, 90, 14);
    const vis = k > 0.01;
    g.visible = vis;
    if (!vis) return;
    if (target) lastPos.current = hexToWorld(target.q, target.r);
    const [x, z] = lastPos.current;
    g.position.set(x, 0, z);
    currentColor.current.lerp(color, 1 - Math.exp(-3 * dt));
    const c = currentColor.current;

    // plinth: rises a little and breathes
    if (plinth.current && plinthMat.current) {
      const h = 0.03 + 0.04 * k;
      plinth.current.scale.set(1, h, 1);
      plinth.current.position.y = h / 2;
      plinthMat.current.color.copy(c).multiplyScalar(0.25);
      plinthMat.current.emissive.copy(c);
      plinthMat.current.emissiveIntensity = (0.35 + 0.25 * Math.sin(t * 4)) * k;
      plinthMat.current.opacity = 0.85 * Math.min(1, k * 1.5);
    }
    // beam (only once the run is real)
    const beamK = target?.armed ? 0 : k;
    beamMat.uniforms.uTime.value = t;
    beamMat.uniforms.uIntensity.value = beamK * (0.85 + 0.15 * Math.sin(t * 6));
    beamMat.uniforms.uColor.value.copy(c);
    if (beam.current) {
      beam.current.visible = beamK > 0.01;
      beam.current.rotation.y = t * 0.4;
      beam.current.scale.y = 0.2 + 0.8 * beamK;
    }
    // motes spiralling up the beam
    const pos = motes.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < MOTES; i++) {
      const sd = seeds[i];
      const u = (t * sd.s + i / MOTES) % 1;
      const r = 0.75 * (1 - u * 0.6);
      const a = sd.a + t * (1.2 + sd.s);
      pos.setXYZ(i, Math.cos(a) * r, 0.1 + u * 2.6 * beamK, Math.sin(a) * r);
    }
    pos.needsUpdate = true;
    moteMat.color.copy(c);
    moteMat.opacity = beamK * 0.9;

    // survey rings sweeping out to the edge of the planned area
    const reach = Math.max(1.2, (target?.radius ?? 1) * SQRT3 + 1);
    for (let i = 0; i < RING_COUNT; i++) {
      const ringLine = rings.current[i];
      const ringMat = ringMats.current[i];
      if (!ringLine || !ringMat) continue;
      const p = ((t / RING_PERIOD + i / RING_COUNT) % 1 + 1) % 1;
      const armed = !!target?.armed;
      const radius = armed ? 1 + 0.25 * p : 1 + p * (reach - 1);
      ringLine.scale.setScalar(radius);
      ringLine.position.y = 0.02;
      ringMat.color.copy(c);
      ringMat.opacity = k * (armed ? 0.5 : 0.7) * (1 - p) ** 1.5;
    }
  });

  return (
    <group ref={group} visible={false}>
      <mesh ref={plinth} geometry={SHARED.prism} raycast={NO_RAYCAST}>
        <meshStandardMaterial ref={plinthMat} transparent roughness={0.6} />
      </mesh>
      <mesh ref={beam} geometry={beamGeo} material={beamMat} raycast={NO_RAYCAST} renderOrder={3} />
      <points geometry={motes} material={moteMat} raycast={NO_RAYCAST} renderOrder={4} />
      {Array.from({ length: RING_COUNT }, (_, i) => (
        <lineLoop
          key={i}
          ref={(el) => {
            rings.current[i] = el;
          }}
          geometry={HEX_RING}
          raycast={NO_RAYCAST}
        >
          <lineBasicMaterial
            ref={(el) => {
              ringMats.current[i] = el;
            }}
            transparent
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </lineLoop>
      ))}
    </group>
  );
}
