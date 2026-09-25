import { type ThreeEvent, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useStore } from "../store";
import { rig } from "./cameraRig";
import { hexKey, hexToWorld, parseKey, worldToHex } from "./hexMath";

/**
 * A "virtual" infinite hex grid: one large plane whose fragment shader draws pointy-top hex cells
 * (matching hexMath), fading with distance from the focus point. The hovered hex glows, and a
 * ripple sweeps outward from where a run starts. Picking uses the plane hit point -> worldToHex.
 */
const vert = /* glsl */ `
  varying vec2 vW;
  void main() {
    vec4 w = modelMatrix * vec4(position, 1.0);
    vW = w.xz;
    gl_Position = projectionMatrix * viewMatrix * w;
  }
`;

const frag = /* glsl */ `
  varying vec2 vW;
  uniform vec2 uFocus;
  uniform vec2 uHover;
  uniform float uHoverOn;
  uniform float uHoverFree;
  uniform vec2 uRipple;
  uniform float uRippleT;
  uniform float uTime;
  uniform float uFade;
  const float S3 = 1.7320508;

  vec2 hexCenter(vec2 p) {
    float qf = (S3 / 3.0 * p.x - p.y / 3.0);
    float rf = (2.0 / 3.0 * p.y);
    float sf = -qf - rf;
    float q = floor(qf + 0.5), r = floor(rf + 0.5), s = floor(sf + 0.5);
    float dq = abs(q - qf), dr = abs(r - rf), ds = abs(s - sf);
    if (dq > dr && dq > ds) q = -r - s; else if (dr > ds) r = -q - s;
    return vec2(S3 * (q + r * 0.5), 1.5 * r);
  }
  // 0 at the centre, 1 on the edge (pointy-top, circumradius 1)
  float hexDist(vec2 d) {
    d = abs(d);
    float a = S3 * 0.5;
    return max(d.x, 0.5 * d.x + a * d.y) / a;
  }

  void main() {
    vec2 c = hexCenter(vW);
    float h = hexDist(vW - c);
    float fw = fwidth(h) * 1.2;
    float line = smoothstep(1.0 - fw * 2.2, 1.0 - fw * 0.4, h);

    float dist = length(vW - uFocus);
    float fade = exp(-dist * dist / (uFade * uFade));

    vec3 base = vec3(0.043, 0.051, 0.075);
    vec3 cell = vec3(0.070, 0.082, 0.115);
    vec3 lineC = vec3(0.165, 0.190, 0.255);
    vec3 col = mix(base, cell, fade * 0.9);
    col = mix(col, lineC, line * (0.25 + 0.75 * fade));

    // hover glow
    float hov = uHoverOn * step(length(c - uHover), 0.1);
    vec3 glow = mix(vec3(0.95, 0.85, 0.55), vec3(0.49, 0.83, 0.99), uHoverFree);
    col += glow * hov * (0.07 + 0.35 * line + 0.05 * sin(uTime * 4.0));

    // ripple from a run's origin
    if (uRippleT >= 0.0 && uRippleT < 2.5) {
      float rd = length(c - uRipple);
      float ring = exp(-pow((rd - uRippleT * 14.0) / 1.6, 2.0)) * (1.0 - uRippleT / 2.5);
      col += vec3(0.35, 0.65, 0.95) * ring * (0.25 + 0.6 * line);
    }
    gl_FragColor = vec4(col, 1.0);
  }
`;

const FREE = new Set(["empty", "intentionally_empty", "failed"]);

export function HexGrid() {
  const mat = useRef<THREE.ShaderMaterial>(null);
  const uniforms = useMemo(
    () => ({
      uFocus: { value: new THREE.Vector2() },
      uHover: { value: new THREE.Vector2() },
      uHoverOn: { value: 0 },
      uHoverFree: { value: 1 },
      uRipple: { value: new THREE.Vector2() },
      uRippleT: { value: -1 },
      uTime: { value: 0 },
      uFade: { value: 40 },
    }),
    [],
  );

  useFrame(({ clock }) => {
    const s = useStore.getState();
    uniforms.uTime.value = clock.elapsedTime;
    uniforms.uFocus.value.set(rig.target.x, rig.target.z);
    uniforms.uFade.value = 18 + rig.distance * 1.6;
    if (s.hover) {
      const { q, r } = parseKey(s.hover);
      const [x, z] = hexToWorld(q, r);
      uniforms.uHover.value.set(x, z);
      uniforms.uHoverOn.value = 1;
      const t = s.tiles[s.hover];
      uniforms.uHoverFree.value = (!t || FREE.has(t.status)) && !s.activeRunId ? 1 : 0;
    } else {
      uniforms.uHoverOn.value = 0;
    }
    if (s.ripple) {
      const [x, z] = hexToWorld(s.ripple.q, s.ripple.r);
      uniforms.uRipple.value.set(x, z);
      uniforms.uRippleT.value = (Date.now() - s.ripple.at) / 1000;
    }
  });

  const keyOf = (e: ThreeEvent<PointerEvent | MouseEvent>) => {
    const h = worldToHex(e.point.x, e.point.z);
    return hexKey(h.q, h.r);
  };

  return (
    <mesh
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, -0.01, 0]}
      onPointerMove={(e) => {
        const k = keyOf(e);
        if (k !== useStore.getState().hover) useStore.getState().setHover(k);
      }}
      onPointerOut={() => useStore.getState().setHover(null)}
      onClick={(e) => {
        if (e.delta > 5) return; // that was a drag
        const k = keyOf(e);
        const s = useStore.getState();
        const tile = s.tiles[k];
        if ((!tile || FREE.has(tile.status)) && !s.activeRunId) s.setPromptTarget(parseKey(k));
        else if (tile && !FREE.has(tile.status)) s.select(k);
        else s.select(null);
      }}
      onPointerMissed={() => undefined}
    >
      <planeGeometry args={[3000, 3000]} />
      <shaderMaterial ref={mat} vertexShader={vert} fragmentShader={frag} uniforms={uniforms} />
    </mesh>
  );
}
