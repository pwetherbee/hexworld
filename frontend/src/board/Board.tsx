import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect } from "react";
import * as THREE from "three";
import { useStore } from "../store";
import { usePlay } from "../play";
import { CameraDirector } from "./CameraDirector";
import { PlayLayer } from "./PlayLayer";
import { CameraRig, rig } from "./cameraRig";
import { hexToWorld, parseKey } from "./hexMath";
import { HexGrid } from "./HexGrid";
import { SeedBeacon } from "./SeedBeacon";
import { SURFACE_TIME } from "./relief";
import { TileMesh } from "./TileMesh";

export function Board() {
  const world = useStore((s) => s.world);
  const playing = usePlay((s) => s.active);
  return (
    <Canvas className="board" dpr={[1, 2]} camera={{ position: [0, 18, 16], fov: 38, near: 0.1, far: 600 }} gl={{ antialias: true }}>
      <color attach="background" args={["#090a0f"]} />
      <fog attach="fog" args={["#090a0f", 60, 190]} />
      <ambientLight intensity={1.0} />
      <hemisphereLight args={["#dfe8ff", "#2a2233", 0.7]} />
      <directionalLight position={[-8, 16, -6]} intensity={1.5} />
      <CameraRig />
      <SurfaceClock />
      <WorldFramer />
      {import.meta.env.DEV && <DevProbe />}
      <HexGrid />
      <SeedBeacon />
      {world && (
        <>
          <Tiles />
          {playing ? <PlayLayer /> : <CameraDirector />}
        </>
      )}
    </Canvas>
  );
}

/** On opening a world, glide to frame what has been built so far. */
function WorldFramer() {
  const worldId = useStore((s) => s.world?.id);
  useEffect(() => {
    if (!worldId || usePlay.getState().active) return; // in play the camera follows the traveller
    const keys = Object.keys(useStore.getState().tiles).filter((k) => useStore.getState().tiles[k].status === "accepted");
    if (!keys.length) {
      rig.setGoal(new THREE.Vector3(0, 0, 0), 14);
      return;
    }
    const pts = keys.map((k) => hexToWorld(parseKey(k).q, parseKey(k).r));
    const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length;
    const cz = pts.reduce((a, p) => a + p[1], 0) / pts.length;
    const rad = Math.max(...pts.map((p) => Math.hypot(p[0] - cx, p[1] - cz)));
    rig.setGoal(new THREE.Vector3(cx, 0, cz), THREE.MathUtils.clamp(8 + rad * 1.5, 8, 40));
  }, [worldId]);
  return null;
}

function Tiles() {
  const tiles = useStore((s) => s.tiles);
  return (
    <>
      {Object.entries(tiles).map(([key, t]) => (t.status === "empty" ? null : <TileMesh key={key} tileKey={key} />))}
    </>
  );
}

/** Dev only: expose the scene for debugging from the browser console (window.__hexScene). */
function DevProbe() {
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera);
  useEffect(() => {
    const w = window as unknown as {
      __hexScene?: unknown;
      __hexStore?: unknown;
      __hexCamera?: unknown;
      __hexPlay?: unknown;
    };
    w.__hexScene = scene;
    w.__hexStore = useStore;
    w.__hexPlay = usePlay;
    w.__hexCamera = camera;
  }, [scene, camera]);
  return null;
}

/** Advances the shared clock used by animated surfaces (water shimmer). */
function SurfaceClock() {
  useFrame(({ clock }) => {
    SURFACE_TIME.value = clock.elapsedTime;
  });
  return null;
}
