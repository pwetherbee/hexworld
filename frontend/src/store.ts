import { create } from "zustand";
import { api, type Health } from "./api/client";
import type { Event as HwEvent, MaterialSpec, Run, RunOptions, RunStats, Tile, World } from "./api/types.gen";
import { hexKey } from "./board/hexMath";
import { sfx } from "./sfx";

const MAX_EVENTS = 6000;

export type Tab = "run" | "agents" | "library" | "timeline" | "tile" | "log";

export type LibSprite = { kind: string; asset_id: string; px_w: number; px_h: number; frames: number };

interface State {
  health: Health | null;
  worlds: World[];
  world: World | null;
  tiles: Record<string, Tile>;
  runs: Record<string, Run>;
  activeRunId: string | null;
  focusRunId: string | null;
  events: HwEvent[];
  lastEventId: number;
  /** tiles snapshot already reflects events up to this id */
  snapshotEventId: number;
  streamConnectedAt: number;
  streamState: "idle" | "connecting" | "open" | "closed";

  selected: string | null;
  hover: string | null;
  promptTarget: { q: number; r: number } | null;
  tab: Tab;
  /** inspector drawer: closed unless the user focuses a tile or opens it */
  drawerOpen: boolean;
  muted: boolean;
  /** key -> ms timestamp; drives one-shot animations */
  acceptedAt: Record<string, number>;
  rejectedAt: Record<string, number>;
  plannedAt: Record<string, number>;
  /** grid ripple from where the latest run started */
  ripple: { q: number; r: number; at: number } | null;
  /** session library (agent-designed assets), live-updated from events */
  libSprites: Record<string, LibSprite>;
  libMaterials: Record<string, MaterialSpec>;
  /** asset designs in flight (material/sprite artists) */
  libraryBusy: number;
  /** camera auto-follows the build (rate limited, yields to user input) */
  follow: boolean;
  tileVersion: Record<string, number>;
  error: string | null;

  init: () => Promise<void>;
  openWorld: (id: string) => Promise<void>;
  newWorld: () => Promise<void>;
  refreshWorld: () => Promise<void>;
  startRun: (prompt: string, options: Partial<RunOptions>) => Promise<void>;
  cancelRun: () => Promise<void>;
  applyEvent: (ev: HwEvent) => void;
  select: (key: string | null) => void;
  setHover: (key: string | null) => void;
  setPromptTarget: (t: { q: number; r: number } | null) => void;
  setTab: (t: Tab) => void;
  setFocusRun: (id: string) => void;
  setStreamState: (s: State["streamState"]) => void;
  setError: (e: string | null) => void;
  setFollow: (f: boolean) => void;
  openDrawer: (tab?: Tab) => void;
  closeDrawer: () => void;
  setMuted: (m: boolean) => void;
}

const TERMINAL = new Set(["run.completed", "run.failed", "run.cancelled"]);
let initStarted = false;

export const useStore = create<State>((set, get) => ({
  health: null,
  worlds: [],
  world: null,
  tiles: {},
  runs: {},
  activeRunId: null,
  focusRunId: null,
  events: [],
  lastEventId: 0,
  snapshotEventId: 0,
  streamConnectedAt: 0,
  streamState: "idle",
  selected: null,
  hover: null,
  promptTarget: null,
  tab: "run",
  drawerOpen: false,
  muted: sfx.muted,
  acceptedAt: {},
  rejectedAt: {},
  plannedAt: {},
  ripple: null,
  libSprites: {},
  libMaterials: {},
  libraryBusy: 0,
  follow: localStorageGet("hexworld.follow") !== "0",
  tileVersion: {},
  error: null,

  init: async () => {
    // StrictMode mounts effects twice in dev; without this guard a first visit creates two worlds.
    if (initStarted) return;
    initStarted = true;
    try {
      const [health, worlds] = await Promise.all([api.health(), api.listWorlds()]);
      set({ health, worlds });
      const saved = localStorageGet("hexworld.world");
      const target = worlds.find((w) => w.id === saved) ?? worlds[0];
      if (target) await get().openWorld(target.id);
      else await get().newWorld();
    } catch (e) {
      set({ error: `Backend unreachable: ${(e as Error).message}` });
    }
  },

  openWorld: async (id) => {
    const detail = await api.getWorld(id);
    const tiles: Record<string, Tile> = {};
    for (const t of detail.tiles) tiles[hexKey(t.q, t.r)] = t;
    const runs: Record<string, Run> = {};
    for (const r of detail.runs) runs[r.id] = r;
    localStorageSet("hexworld.world", id);
    set({
      world: detail.world,
      tiles,
      runs,
      activeRunId: detail.active_run_id ?? null,
      focusRunId: detail.active_run_id ?? detail.runs[0]?.id ?? null,
      events: [],
      lastEventId: 0,
      snapshotEventId: detail.last_event_id,
      streamConnectedAt: Date.now(),
      selected: null,
      acceptedAt: {},
      rejectedAt: {},
      plannedAt: {},
      libSprites: libFrom(detail.world),
      libMaterials: detail.world.materials ?? {},
      libraryBusy: 0,
    });
  },

  newWorld: async () => {
    const w = await api.createWorld("New world");
    set({ worlds: [w, ...get().worlds] });
    await get().openWorld(w.id);
  },

  refreshWorld: async () => {
    const w = get().world;
    if (!w) return;
    const detail = await api.getWorld(w.id);
    const runs: Record<string, Run> = {};
    for (const r of detail.runs) runs[r.id] = r;
    set((s) => ({
      world: detail.world,
      runs,
      worlds: s.worlds.map((x) => (x.id === detail.world.id ? detail.world : x)),
      libSprites: { ...s.libSprites, ...libFrom(detail.world) },
      libMaterials: { ...s.libMaterials, ...(detail.world.materials ?? {}) },
    }));
  },

  startRun: async (prompt, options) => {
    const { world, promptTarget } = get();
    if (!world || !promptTarget) return;
    const run = await api.startRun(world.id, promptTarget.q, promptTarget.r, prompt, options);
    set((s) => ({
      runs: { ...s.runs, [run.id]: run },
      activeRunId: run.id,
      focusRunId: run.id,
      promptTarget: null,
      ripple: { q: run.origin.q, r: run.origin.r, at: Date.now() },
    }));
    sfx.play("confirm");
  },

  cancelRun: async () => {
    const id = get().activeRunId;
    if (id) await api.cancelRun(id);
  },

  applyEvent: (ev) => {
    const s = get();
    if (ev.id <= s.lastEventId) return;
    const live = ev.ts * 1000 > s.streamConnectedAt - 1500;
    const patch: Partial<State> = { lastEventId: ev.id };
    const events = s.events.length >= MAX_EVENTS ? s.events.slice(-MAX_EVENTS + 500) : s.events.slice();
    events.push(ev);
    patch.events = events;
    const data = (ev.data ?? {}) as Record<string, unknown>;

    if (ev.type === "tile.updated" && ev.id > s.snapshotEventId) {
      const tile = data.tile as Tile;
      const key = hexKey(tile.q, tile.r);
      const prev = s.tiles[key];
      patch.tiles = { ...s.tiles, [key]: tile };
      patch.tileVersion = { ...s.tileVersion, [key]: (s.tileVersion[key] ?? 0) + 1 };
      if (live && tile.status === "accepted" && prev?.status !== "accepted") {
        patch.acceptedAt = { ...s.acceptedAt, [key]: Date.now() };
        // Copies land at the bottom of their stamp animation, generated tiles at the rise's peak.
        window.setTimeout(() => sfx.play(tile.copy_mode ? "stamp" : "land"), tile.copy_mode ? 240 : 260);
      }
      if (live && tile.status === "planned" && prev?.status !== "planned" && !prev?.attempts) {
        patch.plannedAt = { ...s.plannedAt, [key]: Date.now() };
      }
    } else if (ev.type === "review.verdict" && data.accept === false && ev.q != null && ev.r != null) {
      if (live) {
        patch.rejectedAt = { ...s.rejectedAt, [hexKey(ev.q, ev.r)]: Date.now() };
        sfx.play("reject");
      }
    } else if (ev.type === "validation.result" && data.ok === false && ev.q != null && ev.r != null) {
      if (live) patch.rejectedAt = { ...s.rejectedAt, [hexKey(ev.q, ev.r)]: Date.now() };
    } else if (ev.type === "run.stats" && ev.run_id && s.runs[ev.run_id]) {
      patch.runs = { ...s.runs, [ev.run_id]: { ...s.runs[ev.run_id], stats: data as unknown as RunStats } };
    } else if (ev.type === "run.started" && ev.run_id) {
      patch.activeRunId = ev.run_id;
      if (!s.focusRunId || live) patch.focusRunId = ev.run_id;
      if (!s.runs[ev.run_id] && live) void get().refreshWorld();
      if (live && ev.q != null && ev.r != null) patch.ripple = { q: ev.q, r: ev.r, at: Date.now() };
    } else if (TERMINAL.has(ev.type) && ev.run_id) {
      if (s.activeRunId === ev.run_id) patch.activeRunId = null;
      patch.libraryBusy = 0;
      const run = s.runs[ev.run_id];
      if (run) {
        patch.runs = {
          ...s.runs,
          [ev.run_id]: {
            ...run,
            status: ev.type.split(".")[1] as Run["status"],
            error: (data.error as string | null) ?? null,
            stats: (data.stats as RunStats) ?? run.stats,
            finished_at: ev.ts,
          },
        };
      }
      if (live) {
        void get().refreshWorld();
        if (ev.type === "run.completed") sfx.play("done");
      }
    } else if (ev.type === "library.sprite_added") {
      const k = data.kind as string;
      patch.libSprites = { ...s.libSprites, [k]: data as unknown as LibSprite };
    } else if (ev.type === "library.material_added") {
      patch.libMaterials = { ...s.libMaterials, [data.name as string]: data.spec as MaterialSpec };
    } else if (live && (ev.type === "library.material.started" || ev.type === "library.sprite.started")) {
      patch.libraryBusy = s.libraryBusy + 1;
    } else if (live && (ev.type === "library.material.finished" || ev.type === "library.sprite.finished")) {
      patch.libraryBusy = Math.max(0, s.libraryBusy - 1);
    } else if ((ev.type === "plan.created" || ev.type === "plan.header") && live) {
      void get().refreshWorld();
    }
    set(patch);
  },

  select: (key) =>
    set(key ? { selected: key, tab: "tile", drawerOpen: true } : { selected: null, drawerOpen: false }),
  openDrawer: (tab) => set((s) => ({ drawerOpen: true, tab: tab ?? s.tab })),
  closeDrawer: () => set({ drawerOpen: false, selected: null }),
  setMuted: (muted) => {
    sfx.setMuted(muted);
    set({ muted });
  },
  setHover: (key) => set({ hover: key }),
  setPromptTarget: (t) => set({ promptTarget: t }),
  setTab: (tab) => set({ tab }),
  setFocusRun: (id) => set({ focusRunId: id }),
  setStreamState: (streamState) =>
    set(streamState === "open" ? { streamState, streamConnectedAt: Date.now() } : { streamState }),
  setError: (error) => set({ error }),
  setFollow: (follow) => {
    localStorageSet("hexworld.follow", follow ? "1" : "0");
    set({ follow });
  },
}));

function libFrom(w: World): Record<string, LibSprite> {
  const out: Record<string, LibSprite> = {};
  for (const [k, e] of Object.entries(w.sprites ?? {})) {
    out[k] = { kind: e.kind, asset_id: e.asset_id, px_w: e.px_w, px_h: e.px_h, frames: e.frames };
  }
  return out;
}

function localStorageGet(k: string): string | null {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}
function localStorageSet(k: string, v: string) {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* ignore */
  }
}
