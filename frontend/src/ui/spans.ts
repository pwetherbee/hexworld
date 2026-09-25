import type { Event as HwEvent } from "../api/types.gen";

export type SpanRow = {
  id: string;
  name: string;
  parent: string | null;
  start: number;
  end: number | null;
  ok: boolean | null;
  q: number | null;
  r: number | null;
  data: Record<string, unknown>;
  depth: number;
};

/** Rebuild the span tree for one run from its flat event log. */
export function buildSpans(events: HwEvent[], runId: string | null): SpanRow[] {
  const byId = new Map<string, SpanRow>();
  for (const ev of events) {
    if (!ev.span_id || ev.run_id !== runId) continue;
    const started = ev.type.endsWith(".started");
    const finished = ev.type.endsWith(".finished");
    if (!started && !finished) continue;
    const name = ev.type.slice(0, ev.type.lastIndexOf("."));
    let row = byId.get(ev.span_id);
    if (!row) {
      row = {
        id: ev.span_id, name, parent: ev.parent_span_id ?? null, start: ev.ts, end: null, ok: null,
        q: ev.q ?? null, r: ev.r ?? null, data: {}, depth: 0,
      };
      byId.set(ev.span_id, row);
    }
    Object.assign(row.data, ev.data ?? {});
    if (started) row.start = ev.ts;
    if (finished) {
      row.end = ev.ts;
      row.ok = (ev.data as { ok?: boolean })?.ok ?? true;
    }
  }
  const rows = [...byId.values()];
  for (const row of rows) {
    let d = 0;
    let p = row.parent;
    while (p && d < 12) {
      d++;
      p = byId.get(p)?.parent ?? null;
    }
    row.depth = d;
  }
  // Depth-first order, children by start time: reads like a trace viewer.
  const children = new Map<string | null, SpanRow[]>();
  for (const r of rows) {
    const k = r.parent && byId.has(r.parent) ? r.parent : null;
    (children.get(k) ?? children.set(k, []).get(k)!).push(r);
  }
  const out: SpanRow[] = [];
  const walk = (k: string | null) => {
    const list = (children.get(k) ?? []).sort((a, b) => a.start - b.start);
    for (const r of list) {
      out.push(r);
      walk(r.id);
    }
  };
  walk(null);
  return out;
}

export function spanLabel(s: SpanRow): string {
  const d = s.data as Record<string, any>;
  switch (s.name) {
    case "run":
      return "run";
    case "super.plan":
      return "super · plan world";
    case "anchor.bootstrap":
      return `super · anchor (${d.candidates ?? "?"} candidates)`;
    case "wave":
      return `wave ${d.index} · ring ${d.ring} · class ${d.color}`;
    case "tile.attempt":
      return `tile ${s.q},${s.r} · attempt ${d.attempt}${d.simplified ? " (simplified)" : ""}`;
    case "tile.design":
      return "tile agent · design";
    case "llm.call":
      return `llm · ${d.role}:${d.task}${d.repair ? " (repair)" : ""}`;
    case "image.generate":
      return `image · ${d.served_by ?? d.backend} · ${d.mode}`;
    case "super.review":
      return `super · review ×${d.candidates}`;
    default:
      return s.name;
  }
}

export function spanColor(s: SpanRow): string {
  if (s.ok === false) return "#ef4444";
  if (s.name === "llm.call") return (s.data as any).role === "super" ? "#a78bfa" : "#60a5fa";
  if (s.name === "image.generate") return "#34d399";
  if (s.name.startsWith("super")) return "#c084fc";
  if (s.name === "tile.attempt") return "#fbbf24";
  if (s.name === "wave") return "#64748b";
  return "#94a3b8";
}
