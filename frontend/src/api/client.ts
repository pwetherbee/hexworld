import type { EnterResult, Run, RunOptions, Scene, SpriteEntry, TileDetail, World, WorldDetail } from "./types.gen";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export type Health = {
  ok: boolean;
  llm: string;
  super_model: string;
  tile_model: string;
  image: string;
  image_healthy: boolean;
};

export const api = {
  health: () => req<Health>("GET", "/health"),
  listWorlds: () => req<World[]>("GET", "/worlds"),
  createWorld: (name?: string, radius?: number) => req<World>("POST", "/worlds", { name, radius }),
  getWorld: (id: string) => req<WorldDetail>("GET", `/worlds/${id}`),
  deleteWorld: (id: string) => req<{ deleted: boolean }>("DELETE", `/worlds/${id}`),
  enterTile: (worldId: string, q: number, r: number, radius?: number) =>
    req<EnterResult>("POST", `/worlds/${worldId}/tiles/${q}/${r}/enter`, { radius }),
  getScene: (worldId: string, q: number, r: number) => req<Scene>("GET", `/worlds/${worldId}/tiles/${q}/${r}/scene`),
  makeScene: (worldId: string, q: number, r: number) => req<Scene>("POST", `/worlds/${worldId}/tiles/${q}/${r}/scene`),
  avatar: (worldId: string) => req<SpriteEntry | null>("POST", `/worlds/${worldId}/avatar`),
  getTile: (worldId: string, q: number, r: number) =>
    req<TileDetail>("GET", `/worlds/${worldId}/tiles/${q}/${r}`),
  startRun: (worldId: string, q: number, r: number, prompt: string, options: Partial<RunOptions>) =>
    req<Run>("POST", `/worlds/${worldId}/runs`, { q, r, prompt, options }),
  cancelRun: (runId: string) => req<{ cancelled: boolean }>("POST", `/runs/${runId}/cancel`),
};

export const assetUrl = (id: string) => `/api/assets/${id}.png`;
