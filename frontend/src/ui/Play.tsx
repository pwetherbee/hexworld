import { useEffect, useMemo, useRef, useState } from "react";
import { assetUrl } from "../api/client";
import type { Scene } from "../api/types.gen";
import { hexKey } from "../board/hexMath";
import { MAX_ENTER_DEPTH, usePlay } from "../play";
import { useStore } from "../store";

const NO_COLORS: string[] = [];
const pretty = (s?: string | null) => (s ?? "").replace(/_/g, " ");
const title = (s?: string | null) => pretty(s).replace(/\b\w/g, (c) => c.toUpperCase());

/** Top middle: the game pill. Build mode: Play. Play mode: where you are, and Exit. */
export function GamePill() {
  const active = usePlay((s) => s.active);
  const world = useStore((s) => s.world);
  const built = useStore((s) => Object.values(s.tiles).some((t) => t.status === "accepted"));
  const building = useStore((s) => !!s.activeRunId);
  const stack = usePlay((s) => s.stack);
  const scene = usePlay((s) => !!s.scene);
  const worlds = useStore((s) => s.worlds);
  if (!world) return null;
  if (!active) {
    if (world.depth !== 0 || !built) return null;
    return (
      <div className="game-pill">
        <button
          className="game-play"
          disabled={building}
          onClick={() => void usePlay.getState().start()}
          title={building ? "Wait for the build to finish" : "Walk this world"}
        >
          ▶ Play
        </button>
      </div>
    );
  }
  const root = worlds.find((w) => w.id === stack[0]?.worldId);
  return (
    <div className="game-pill playing">
      <span className="crumbs">
        <span>{root?.spec?.title ?? root?.name ?? "World"}</span>
        {stack.length > 1 && <span>› {title(world.parent?.context?.biome as string) || world.name}</span>}
        {scene && <span>› up close</span>}
      </span>
      <button className="game-exit" onClick={() => void usePlay.getState().stop()} title="Back to the editor">
        ⏏ Exit
      </button>
    </div>
  );
}

/** Bottom: the place you're standing on and what you can do there. */
export function PlayHud() {
  const active = usePlay((s) => s.active);
  const here = usePlay((s) => s.stack[s.stack.length - 1]);
  const busy = usePlay((s) => s.busy);
  const scene = usePlay((s) => s.scene);
  const tile = useStore((s) => (here ? s.tiles[hexKey(here.q, here.r)] : undefined));
  const depth = useStore((s) => s.world?.depth ?? 0);
  const drilled = useStore((s) => (here ? !!s.drills[hexKey(here.q, here.r)] : false));
  const forming = useStore((s) => {
    const run = s.activeRunId ? s.runs[s.activeRunId] : undefined;
    return run ? `${run.stats.tiles_accepted}/${run.stats.tiles_planned || "…"}` : null;
  });
  useKeys(active);
  if (!active || !here || scene) return null;
  const canEnter = depth <= MAX_ENTER_DEPTH;
  return (
    <div className="play-hud">
      <div className="place">
        <div className="place-name">{title(tile?.biome) || "…"}</div>
        <div className="place-line">{tile?.summary ?? "The ground here is still forming."}</div>
      </div>
      <div className="play-actions">
        {canEnter ? (
          <button className="primary" disabled={!!busy || tile?.status !== "accepted"} onClick={() => void usePlay.getState().enter()}>
            {busy === "entering" ? "Opening…" : drilled ? "Enter ⏎" : "Enter · explore up close ⏎"}
          </button>
        ) : (
          <button className="primary" disabled={!!busy || tile?.status !== "accepted"} onClick={() => void usePlay.getState().look()}>
            Look around ⏎
          </button>
        )}
        {depth > 0 && (
          <button disabled={!!busy} onClick={() => void usePlay.getState().back()}>
            Back ⎋
          </button>
        )}
      </div>
      <div className="play-hint">
        {forming && depth > 0
          ? `This place is still taking shape around you (${forming}): walk on the finished tiles.`
          : "Click a tile to walk there · W E / A D / Z X to hop · Enter · Esc"}
      </div>
    </div>
  );
}

const KEY_DIRS: Record<string, number> = { d: 0, e: 1, w: 2, a: 3, z: 4, x: 5 };

function useKeys(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.target instanceof HTMLTextAreaElement || ev.target instanceof HTMLInputElement) return;
      const p = usePlay.getState();
      const k = ev.key.toLowerCase();
      if (k in KEY_DIRS) {
        p.step(KEY_DIRS[k]);
        ev.preventDefault();
      } else if (k === "enter" || k === " ") {
        if (p.scene) return;
        if ((useStore.getState().world?.depth ?? 0) <= MAX_ENTER_DEPTH) void p.enter();
        else void p.look();
        ev.preventDefault();
      } else if (k === "escape" || k === "backspace") {
        void p.back();
        ev.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);
}

/** A tile up close: the painted scene, animated. */
export function SceneView() {
  const scene = usePlay((s) => s.scene);
  const palette = useStore((s) => s.world?.style?.palette ?? NO_COLORS);
  if (!scene) return null;
  return (
    <div className="scene-overlay" onClick={(e) => e.target === e.currentTarget && usePlay.getState().closeScene()}>
      {scene.data ? (
        <SceneCanvas data={scene.data} />
      ) : (
        <ScenePainting palette={palette} error={scene.error} />
      )}
      <button className="scene-back" onClick={() => usePlay.getState().closeScene()}>
        ⎋ Back
      </button>
    </div>
  );
}

function ScenePainting({ palette, error }: { palette: string[]; error: string | null }) {
  const cells = useMemo(() => Array.from({ length: 96 }, (_, i) => palette[(i * 7) % Math.max(1, palette.length)] ?? "#333"), [palette]);
  return (
    <div className="scene-frame painting">
      <div className="paint-grid">
        {cells.map((c, i) => (
          <span key={i} style={{ background: c, animationDelay: `${(i % 12) * 70 + Math.floor(i / 12) * 45}ms` }} />
        ))}
      </div>
      <div className="paint-label">{error ? `Couldn't paint this place: ${error}` : "Painting this place…"}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------- the scene canvas

const VIEW_W = 368; // a window into the 384x256 painting: integer-pixel parallax without rescaling
const VIEW_H = 244;
const SLACK_X = 16;
const SLACK_Y = 12;

type Particle = { x: number; y: number; vx: number; vy: number; c: string; life: number; phase: number; kind: string };

function loadImage(id: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = rej;
    img.src = assetUrl(id);
  });
}

function hex(r: number, g: number, b: number) {
  return `rgb(${r | 0},${g | 0},${b | 0})`;
}

function SceneCanvas({ data }: { data: Scene }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const mouse = useRef({ x: 0, y: 0 });
  const [shown, setShown] = useState(false);

  useEffect(() => {
    let raf = 0;
    let alive = true;
    const bgLayer = data.layers.find((l) => l.role === "backdrop");
    const fgLayer = data.layers.find((l) => l.role === "foreground");
    void Promise.all([
      bgLayer ? loadImage(bgLayer.asset_id) : Promise.resolve(null),
      fgLayer ? loadImage(fgLayer.asset_id).catch(() => null) : Promise.resolve(null),
    ]).then(([bg, fg]) => {
      if (!alive || !bg || !ref.current) return;
      const ctx = ref.current.getContext("2d")!;
      ctx.imageSmoothingEnabled = false;
      // read the painting once: water for glints, colours for leaves and dust
      const probe = document.createElement("canvas");
      probe.width = bg.width;
      probe.height = bg.height;
      const pctx = probe.getContext("2d")!;
      pctx.drawImage(bg, 0, 0);
      const px = pctx.getImageData(0, 0, bg.width, bg.height).data;
      const at = (x: number, y: number) => {
        const i = (y * bg.width + x) * 4;
        return [px[i], px[i + 1], px[i + 2]] as const;
      };
      const water: [number, number][] = [];
      const greens: string[] = [];
      const grounds: string[] = [];
      for (let n = 0; n < 6000; n++) {
        const x = (Math.random() * bg.width) | 0;
        const y = (Math.random() * bg.height) | 0;
        const [r, g, b] = at(x, y);
        if (y > bg.height * 0.35 && b > r + 25 && b >= g - 5 && water.length < 70) water.push([x, y]);
        if (g > r + 12 && g > b + 8 && greens.length < 24) greens.push(hex(r, g, b));
        if (y > bg.height * 0.7 && r > b + 15 && grounds.length < 16) grounds.push(hex(r * 1.2, g * 1.2, b * 1.1));
      }
      const fx = new Set(data.fx);
      const parts: Particle[] = [];
      const spawn = (kind: string): Particle => {
        const r = Math.random;
        switch (kind) {
          case "leaves":
            return { kind, x: r() * VIEW_W, y: -4, vx: 4 + r() * 6, vy: 7 + r() * 6, c: greens[(r() * greens.length) | 0] ?? "#6a9a3a", life: 1, phase: r() * 6 };
          case "snow":
            return { kind, x: r() * VIEW_W, y: -2, vx: -2 + r() * 4, vy: 8 + r() * 8, c: "#f4f7fb", life: 1, phase: r() * 6 };
          case "embers":
            return { kind, x: r() * VIEW_W, y: VIEW_H + 2, vx: -2 + r() * 4, vy: -(10 + r() * 14), c: r() < 0.5 ? "#ffb347" : "#ff6a2a", life: 1, phase: r() * 6 };
          case "dust":
            return { kind, x: -2, y: VIEW_H * (0.45 + r() * 0.5), vx: 8 + r() * 10, vy: -1 + r() * 2, c: grounds[(r() * grounds.length) | 0] ?? "#e7d3a8", life: 1, phase: r() * 6 };
          case "fireflies":
            return { kind, x: r() * VIEW_W, y: VIEW_H * (0.4 + r() * 0.5), vx: 0, vy: 0, c: "#e9ff8a", life: 1, phase: r() * 6 };
          case "gulls":
            return { kind, x: -6, y: 12 + r() * VIEW_H * 0.3, vx: 14 + r() * 10, vy: 0, c: "#f2f2f2", life: 1, phase: r() * 6 };
          case "steam":
            return { kind, x: r() * VIEW_W, y: VIEW_H * (0.5 + r() * 0.3), vx: 1, vy: -6, c: "rgba(235,235,240,0.55)", life: 1, phase: r() * 6 };
          default: // motes: every place has a little air moving
            return { kind: "motes", x: r() * VIEW_W, y: r() * VIEW_H * 0.8, vx: 1 + r() * 2, vy: -0.5 + r(), c: "rgba(255,255,240,0.55)", life: 1, phase: r() * 6 };
        }
      };
      const target: Record<string, number> = { motes: 10, leaves: 14, snow: 60, embers: 26, dust: 18, fireflies: 16, gulls: 2, steam: 10 };
      const kinds = ["motes", ...[...fx].filter((k) => k !== "water")];
      let last = performance.now();
      setShown(true);

      const frame = (now: number) => {
        if (!alive) return;
        const dt = Math.min(0.05, (now - last) / 1000);
        last = now;
        const t = now / 1000;
        // a slow drift plus the mouse: the far layer moves half as much as the near one
        const driftX = Math.sin(t * 0.09) * 0.5 + mouse.current.x * 0.5;
        const driftY = Math.sin(t * 0.07 + 1) * 0.3 + mouse.current.y * 0.4;
        const bx = Math.round(SLACK_X / 2 + driftX * (SLACK_X / 4));
        const by = Math.round(SLACK_Y / 2 + driftY * (SLACK_Y / 4));
        const fxo = Math.max(0, Math.min(SLACK_X, Math.round(SLACK_X / 2 + driftX * (SLACK_X / 2))));
        const fyo = Math.max(0, Math.min(SLACK_Y, Math.round(SLACK_Y / 2 + driftY * (SLACK_Y / 2))));
        ctx.drawImage(bg, bx, by, VIEW_W, VIEW_H, 0, 0, VIEW_W, VIEW_H);
        // glints on water, found in the painting itself
        if (fx.has("water")) {
          for (let i = 0; i < water.length; i++) {
            const [wx, wy] = water[i];
            const s = Math.sin(t * 2.2 + i * 1.7);
            if (s > 0.82) {
              ctx.fillStyle = s > 0.95 ? "#ffffff" : "rgba(220,240,255,0.8)";
              ctx.fillRect(wx - bx, wy - by, s > 0.95 ? 2 : 1, 1);
            }
          }
        }
        // ambient particles
        for (const k of kinds) {
          const have = parts.filter((p) => p.kind === k).length;
          if (have < (target[k] ?? 8) && Math.random() < 0.08) parts.push(spawn(k));
        }
        for (let i = parts.length - 1; i >= 0; i--) {
          const p = parts[i];
          if (p.kind === "fireflies") {
            p.x += Math.sin(t * 0.8 + p.phase) * 6 * dt;
            p.y += Math.cos(t * 0.6 + p.phase * 1.3) * 4 * dt;
          } else {
            p.x += (p.vx + (p.kind === "leaves" ? Math.sin(t * 2 + p.phase) * 8 : 0)) * dt;
            p.y += p.vy * dt;
          }
          if (p.x < -8 || p.x > VIEW_W + 8 || p.y < -8 || p.y > VIEW_H + 8) {
            parts.splice(i, 1);
            continue;
          }
          const x = Math.round(p.x);
          const y = Math.round(p.y);
          if (p.kind === "fireflies") {
            if (Math.sin(t * 3 + p.phase * 5) > 0.2) {
              ctx.fillStyle = p.c;
              ctx.fillRect(x, y, 1, 1);
              ctx.fillStyle = "rgba(233,255,138,0.25)";
              ctx.fillRect(x - 1, y, 3, 1);
              ctx.fillRect(x, y - 1, 1, 3);
            }
          } else if (p.kind === "gulls") {
            const flap = Math.sin(t * 9 + p.phase) > 0 ? 1 : 0;
            ctx.fillStyle = p.c;
            ctx.fillRect(x, y, 1, 1);
            ctx.fillRect(x - 1, y - flap, 1, 1);
            ctx.fillRect(x + 1, y - flap, 1, 1);
            ctx.fillRect(x - 2, y - 1 + flap, 1, 1);
            ctx.fillRect(x + 2, y - 1 + flap, 1, 1);
          } else if (p.kind === "steam") {
            ctx.fillStyle = p.c;
            ctx.fillRect(x, y, 3, 2);
          } else {
            ctx.fillStyle = p.c;
            ctx.fillRect(x, y, p.kind === "leaves" ? 2 : 1, 1);
          }
        }
        if (fg) ctx.drawImage(fg, fxo, fyo, VIEW_W, VIEW_H, 0, 0, VIEW_W, VIEW_H);
        raf = requestAnimationFrame(frame);
      };
      raf = requestAnimationFrame(frame);
    });
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
    };
  }, [data]);

  return (
    <div
      className={`scene-frame ${shown ? "shown" : ""}`}
      onPointerMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        mouse.current = { x: ((e.clientX - r.left) / r.width) * 2 - 1, y: ((e.clientY - r.top) / r.height) * 2 - 1 };
      }}
    >
      <canvas ref={ref} width={VIEW_W} height={VIEW_H} className="scene-canvas" />
      <div className="scene-card">
        <div className="scene-title">{data.title}</div>
        {data.caption && <div className="scene-caption">{data.caption}</div>}
      </div>
    </div>
  );
}
