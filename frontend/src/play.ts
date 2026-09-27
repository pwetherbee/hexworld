import { create } from "zustand";
import { api } from "./api/client";
import type { Scene, SpriteEntry } from "./api/types.gen";
import { DIRECTIONS, hexKey, parseKey } from "./board/hexMath";
import { sfx } from "./sfx";
import { localStorageGet, localStorageSet, useStore } from "./store";

/** Play mode: walk the world as a traveller, enter tiles (their region is built on first entry) and
 * look around (a painted scene). Separate from the build store; it drives it by opening worlds. */

export type Pos = { worldId: string; q: number; r: number };

export const HOP_MS = 230;
/** radius of a tile's region grid (entering an overworld tile) */
export const REGION_RADIUS = 5;
/** deepest layer you can enter; below it tiles are looked at (scenes) */
export const MAX_ENTER_DEPTH = 0;

type SceneView = { worldId: string; q: number; r: number; data: Scene | null; error: string | null };

interface PlayState {
  active: boolean;
  rootId: string | null;
  /** stack[0] is the overworld position; the last entry is where the traveller is now */
  stack: Pos[];
  /** tiles still to hop through (keys in the current world) */
  queue: string[];
  /** where the current hop started (world coordinates are derived by the avatar) */
  from: { q: number; r: number } | null;
  hopAt: number;
  busy: null | "entering" | "leaving";
  avatar: SpriteEntry | null;
  scene: SceneView | null;

  start: () => Promise<void>;
  stop: () => Promise<void>;
  click: (key: string) => void;
  step: (dir: number) => void;
  enter: () => Promise<void>;
  back: () => Promise<void>;
  look: () => Promise<void>;
  closeScene: () => void;
}

const here = (s: PlayState) => s.stack[s.stack.length - 1];
const walkable = (key: string) => useStore.getState().tiles[key]?.status === "accepted";

function saveKey(rootId: string) {
  return `hexworld.play.${rootId}`;
}

function persist(s: Pick<PlayState, "rootId" | "stack">) {
  if (s.rootId) localStorageSet(saveKey(s.rootId), JSON.stringify(s.stack));
}

/** Shortest walk over built tiles (BFS on the hex grid). */
export function findPath(from: string, to: string, ok: (k: string) => boolean): string[] | null {
  if (from === to) return [];
  const prev = new Map<string, string | null>([[from, null]]);
  const q = [from];
  while (q.length) {
    const cur = q.shift()!;
    const { q: cq, r: cr } = parseKey(cur);
    for (const [dq, dr] of DIRECTIONS) {
      const n = hexKey(cq + dq, cr + dr);
      if (prev.has(n) || !ok(n)) continue;
      prev.set(n, cur);
      if (n === to) {
        const path = [n];
        let p = cur;
        while (p !== from) {
          path.unshift(p);
          p = prev.get(p)!;
        }
        return path;
      }
      if (prev.size > 4000) return null;
      q.push(n);
    }
  }
  return null;
}

let hopTimer: number | undefined;
let prefetchTimer: number | undefined;
/** a traveller who stops on a tile will likely look around: start painting its scene */
const PREFETCH_MS = 1200;

export const usePlay = create<PlayState>((set, get) => {
  const hopNext = () => {
    const s = get();
    const [next, ...rest] = s.queue;
    if (!next || !s.active) {
      hopTimer = undefined;
      schedulePrefetch();
      return;
    }
    const cur = here(s);
    const { q, r } = parseKey(next);
    const stack = [...s.stack.slice(0, -1), { ...cur, q, r }];
    set({ stack, queue: rest, from: { q: cur.q, r: cur.r }, hopAt: performance.now() });
    persist({ rootId: s.rootId, stack });
    sfx.play("press");
    hopTimer = window.setTimeout(hopNext, HOP_MS);
  };
  const schedulePrefetch = () => {
    window.clearTimeout(prefetchTimer);
    prefetchTimer = window.setTimeout(() => {
      const s = get();
      const world = useStore.getState().world;
      if (!s.active || s.queue.length || !world || world.depth <= MAX_ENTER_DEPTH) return;
      const cur = here(s);
      if (cur.worldId !== world.id || !walkable(hexKey(cur.q, cur.r))) return;
      api.getScene(cur.worldId, cur.q, cur.r).catch(() => api.makeScene(cur.worldId, cur.q, cur.r).catch(() => undefined));
    }, PREFETCH_MS);
  };
  const walk = (path: string[]) => {
    set({ queue: path });
    if (hopTimer === undefined) hopNext();
  };

  return {
    active: false,
    rootId: null,
    stack: [],
    queue: [],
    from: null,
    hopAt: 0,
    busy: null,
    avatar: null,
    scene: null,

    start: async () => {
      const b = useStore.getState();
      const world = b.world;
      if (!world || world.depth !== 0) return;
      let stack: Pos[] = [];
      try {
        stack = JSON.parse(localStorageGet(saveKey(world.id)) ?? "[]") as Pos[];
      } catch {
        stack = [];
      }
      if (!stack.length || stack[0].worldId !== world.id) {
        const built = Object.values(b.tiles).filter((t) => t.status === "accepted");
        const origin =
          built.find((t) => t.q === 0 && t.r === 0) ??
          built.sort((a, z) => Math.abs(a.q) + Math.abs(a.r) - (Math.abs(z.q) + Math.abs(z.r)))[0];
        if (!origin) return;
        stack = [{ worldId: world.id, q: origin.q, r: origin.r }];
      }
      b.closeDrawer();
      set({ active: true, rootId: world.id, stack, queue: [], from: null, busy: null, scene: null });
      sfx.play("confirm");
      const cur = stack[stack.length - 1];
      if (cur.worldId !== world.id) await b.openWorld(cur.worldId, { remember: false });
      api
        .avatar(world.id)
        .then((avatar) => set({ avatar }))
        .catch(() => undefined);
    },

    stop: async () => {
      const s = get();
      window.clearTimeout(hopTimer);
      hopTimer = undefined;
      persist(s);
      set({ active: false, queue: [], scene: null, busy: null });
      if (s.rootId && useStore.getState().world?.id !== s.rootId) await useStore.getState().openWorld(s.rootId);
    },

    click: (key) => {
      const s = get();
      if (!s.active || s.busy || s.scene) return;
      const cur = here(s);
      const path = findPath(hexKey(cur.q, cur.r), key, walkable);
      if (path === null) {
        sfx.play("reject");
        return;
      }
      if (!path.length) {
        // clicking where you stand: go in (overworld) or look around (deeper)
        if ((useStore.getState().world?.depth ?? 0) <= MAX_ENTER_DEPTH) void get().enter();
        else void get().look();
        return;
      }
      walk(path);
    },

    step: (dir) => {
      const s = get();
      if (!s.active || s.busy || s.scene || s.queue.length) return;
      const cur = here(s);
      const [dq, dr] = DIRECTIONS[dir];
      const key = hexKey(cur.q + dq, cur.r + dr);
      if (walkable(key)) walk([key]);
      else sfx.play("reject");
    },

    enter: async () => {
      const s = get();
      const world = useStore.getState().world;
      if (!s.active || s.busy || !world || world.depth > MAX_ENTER_DEPTH) return;
      const cur = here(s);
      set({ busy: "entering", queue: [] });
      sfx.play("confirm");
      try {
        const res = await api.enterTile(world.id, cur.q, cur.r, REGION_RADIUS);
        const stack = [...get().stack, { worldId: res.world.id, q: 0, r: 0 }];
        set({ stack, from: null });
        persist({ rootId: s.rootId, stack });
        await useStore.getState().openWorld(res.world.id, { remember: false });
        schedulePrefetch();
      } catch (e) {
        useStore.getState().setError(`Couldn't enter: ${(e as Error).message}`);
      } finally {
        set({ busy: null });
      }
    },

    back: async () => {
      const s = get();
      if (!s.active || s.busy) return;
      if (s.scene) {
        get().closeScene();
        return;
      }
      if (s.stack.length < 2) return;
      set({ busy: "leaving", queue: [] });
      const stack = s.stack.slice(0, -1);
      set({ stack, from: null });
      persist({ rootId: s.rootId, stack });
      try {
        await useStore.getState().openWorld(stack[stack.length - 1].worldId, {
          remember: stack.length === 1,
        });
      } finally {
        set({ busy: null });
      }
    },

    look: async () => {
      const s = get();
      if (!s.active || s.busy || s.scene) return;
      const cur = here(s);
      const view: SceneView = { worldId: cur.worldId, q: cur.q, r: cur.r, data: null, error: null };
      set({ scene: view, queue: [] });
      sfx.play("confirm");
      try {
        let data: Scene;
        try {
          data = await api.getScene(cur.worldId, cur.q, cur.r);
        } catch {
          data = await api.makeScene(cur.worldId, cur.q, cur.r);
        }
        const now = get().scene;
        if (now && now.worldId === view.worldId && now.q === view.q && now.r === view.r) {
          set({ scene: { ...now, data } });
        }
      } catch (e) {
        const now = get().scene;
        if (now) set({ scene: { ...now, error: (e as Error).message } });
      }
    },

    closeScene: () => set({ scene: null }),
  };
});
