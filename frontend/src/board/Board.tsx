import { MapControls } from "@react-three/drei";
import { Canvas, type ThreeEvent } from "@react-three/fiber";
import { memo, useMemo, useRef } from "react";
import * as THREE from "three";
import { useStore } from "../store";
import { CameraDirector } from "./CameraDirector";
import { SHARED, hexOutlinePoints } from "./geometry";
import { hexKey, hexToWorld, hexesWithin, parseKey } from "./hexMath";
import { TileMesh } from "./TileMesh";

const FREE = new Set(["empty", "intentionally_empty", "failed"]);

export function Board() {
  const world = useStore((s) => s.world);
  return (
    <Canvas
      className="board"
      dpr={[1, 2]}
      camera={{ position: [0, 17, 15], fov: 40, near: 0.1, far: 400 }}
      gl={{ antialias: true }}
      onPointerMissed={() => useStore.getState().select(null)}
    >
      <color attach="background" args={["#0b0d13"]} />
      <fog attach="fog" args={["#0b0d13", 40, 110]} />
      <ambientLight intensity={1.1} />
      <hemisphereLight args={["#dfe8ff", "#2a2233", 0.6]} />
      <directionalLight position={[-8, 16, -6]} intensity={1.6} />
      <MapControls
        makeDefault
        enableDamping
        dampingFactor={0.12}
        maxPolarAngle={1.25}
        minDistance={4}
        maxDistance={80}
        screenSpacePanning={false}
      />
      {world && (
        <>
          <EmptyField radius={world.radius} />
          <Tiles />
          <HoverMarker />
          <SelectedMarker />
          <CameraDirector />
        </>
      )}
    </Canvas>
  );
}

/** One instanced mesh for every slot in the world + one merged outline geometry. */
const EmptyField = memo(function EmptyField({ radius }: { radius: number }) {
  const hexes = useMemo(() => hexesWithin(radius), [radius]);
  const meshRef = useRef<THREE.InstancedMesh>(null);

  const matrices = useMemo(() => {
    const m = new THREE.Matrix4();
    return hexes.map(({ q, r }) => {
      const [x, z] = hexToWorld(q, r);
      return m.makeTranslation(x, 0, z).clone();
    });
  }, [hexes]);

  const outline = useMemo(() => {
    const pts: number[] = [];
    const ring = hexOutlinePoints(0.97, 0.003);
    for (const { q, r } of hexes) {
      const [x, z] = hexToWorld(q, r);
      for (let i = 0; i < 6; i++) {
        pts.push(ring[i].x + x, ring[i].y, ring[i].z + z, ring[i + 1].x + x, ring[i + 1].y, ring[i + 1].z + z);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return g;
  }, [hexes]);

  const setMesh = (mesh: THREE.InstancedMesh | null) => {
    meshRef.current = mesh;
    if (!mesh) return;
    matrices.forEach((m, i) => mesh.setMatrixAt(i, m));
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  };

  const keyOf = (e: ThreeEvent<PointerEvent | MouseEvent>) => {
    if (e.instanceId == null) return null;
    const h = hexes[e.instanceId];
    return hexKey(h.q, h.r);
  };

  return (
    <group>
      <instancedMesh
        ref={setMesh}
        args={[SHARED.emptyFace, undefined, hexes.length]}
        onPointerMove={(e) => {
          e.stopPropagation();
          const k = keyOf(e);
          if (k !== useStore.getState().hover) useStore.getState().setHover(k);
        }}
        onPointerOut={() => useStore.getState().setHover(null)}
        onClick={(e) => {
          e.stopPropagation();
          if (e.delta > 5) return; // it was a drag
          const k = keyOf(e);
          if (!k) return;
          const s = useStore.getState();
          const tile = s.tiles[k];
          if ((!tile || FREE.has(tile.status ?? "empty")) && !s.activeRunId) {
            s.setPromptTarget(parseKey(k));
          } else {
            s.select(k);
          }
        }}
      >
        <meshStandardMaterial color="#161a24" roughness={1} />
      </instancedMesh>
      <lineSegments geometry={outline}>
        <lineBasicMaterial color="#262c3b" />
      </lineSegments>
    </group>
  );
});

function Tiles() {
  const tiles = useStore((s) => s.tiles);
  return (
    <>
      {Object.entries(tiles).map(([key, t]) =>
        t.status === "empty" ? null : <TileMesh key={key} tileKey={key} />,
      )}
    </>
  );
}

function MarkerAt({ tileKey, color, y = 0.01 }: { tileKey: string; color: string; y?: number }) {
  const { q, r } = parseKey(tileKey);
  const [x, z] = hexToWorld(q, r);
  const geo = useMemo(() => new THREE.BufferGeometry().setFromPoints(hexOutlinePoints(0.99, 0)), []);
  return (
    <lineLoop geometry={geo} position={[x, y, z]}>
      <lineBasicMaterial color={color} transparent opacity={0.95} depthTest={false} />
    </lineLoop>
  );
}

function HoverMarker() {
  const hover = useStore((s) => s.hover);
  const tile = useStore((s) => (s.hover ? s.tiles[s.hover] : undefined));
  const busy = useStore((s) => !!s.activeRunId);
  if (!hover) return null;
  const free = !tile || FREE.has(tile.status ?? "empty");
  const h = tile?.status === "accepted" ? 0.6 : 0.02;
  return <MarkerAt tileKey={hover} color={free ? (busy ? "#6b7280" : "#7dd3fc") : "#e5e7eb"} y={h} />;
}

function SelectedMarker() {
  const sel = useStore((s) => s.selected);
  if (!sel) return null;
  return <MarkerAt tileKey={sel} color="#fde047" y={0.62} />;
}
