import { type ReactNode, useEffect, useMemo, useState } from "react";
import { api, assetUrl } from "../api/client";
import type { Attempt, Run, TileDetail } from "../api/types.gen";
import { DIRECTION_NAMES, parseKey } from "../board/hexMath";
import { useStore, type Tab } from "../store";
import { IconClose } from "./icons";
import { buildSpans, spanColor, spanLabel } from "./spans";

const TABS: { id: Tab; label: string }[] = [
  { id: "run", label: "Run" },
  { id: "timeline", label: "Timeline" },
  { id: "tile", label: "Tile" },
  { id: "log", label: "Log" },
];

/** Slide-in drawer: hidden until the user focuses a tile or opens it (I). */
export function Inspector() {
  const tab = useStore((s) => s.tab);
  const open = useStore((s) => s.drawerOpen);
  return (
    <aside className={`drawer ${open ? "open" : ""}`} aria-hidden={!open}>
      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => useStore.getState().setTab(t.id)}>
            {t.label}
          </button>
        ))}
        <button className="drawer-close" onClick={() => useStore.getState().closeDrawer()} aria-label="Close">
          <IconClose />
        </button>
      </nav>
      <div className="tab-body">
        {open && tab === "run" && <RunPanel />}
        {open && tab === "timeline" && <Timeline />}
        {open && tab === "tile" && <TilePanel />}
        {open && tab === "log" && <EventLog />}
      </div>
    </aside>
  );
}

// ------------------------------------------------------------------ run

function RunPanel() {
  const { world, runs, focusRunId } = useStore();
  const run = focusRunId ? runs[focusRunId] : undefined;
  const sorted = Object.values(runs).sort((a, b) => b.created_at - a.created_at);
  if (!world) return null;
  return (
    <div className="stack">
      {!world.spec && (
        <div className="hint">
          Click any empty hex on the board and describe a world or a board game to start. The <b>super agent</b>{" "}
          plans the region, <b>tile agents</b> paint each hex in parallel waves, and the super reviews them with vision.
        </div>
      )}
      {run && <RunCard run={run} />}
      {world.spec && (
        <Disclosure title={world.spec.title}>
          <p className="muted small">
            {world.spec.genre} · {world.spec.theme}
          </p>
          <p className="small">{world.spec.lore}</p>
          <p className="small muted">{world.spec.directional_notes}</p>
          <div className="kv">
            <span>terrains</span>
            <span className="tags">
              {world.spec.terrain_vocabulary.map((t) => (
                <i key={t}>{t}</i>
              ))}
            </span>
            <span>connectors</span>
            <span className="tags">
              {world.spec.connector_vocabulary.map((t) => (
                <i key={t}>{t}</i>
              ))}
            </span>
          </div>
        </Disclosure>
      )}
      {world.style && (
        <Disclosure title="Style guide">
          <div className="palette">
            {world.style.palette.map((c) => (
              <span key={c} style={{ background: c }} title={c} />
            ))}
          </div>
          <p className="small muted">
            {world.style.tile_px}px · {world.style.view} · light {world.style.light_direction} · {world.style.outline}
          </p>
          <p className="small">{world.style.style_keywords}</p>
          {world.anchor_asset_ids?.[0] && (
            <div className="anchor">
              <img className="pixel" src={assetUrl(world.anchor_asset_ids[0])} alt="anchor tile" />
              <span className="small muted">Style anchor, picked by the super from candidate renders</span>
            </div>
          )}
        </Disclosure>
      )}
      {world.tile_attributes && world.tile_attributes.length > 0 && (
        <Disclosure title="Tile schema">
          <table className="table small">
            <tbody>
              {world.tile_attributes.map((a) => (
                <tr key={a.name}>
                  <td className="mono">{a.name}</td>
                  <td className="muted">
                    {a.type}
                    {a.enum_values.length ? `: ${a.enum_values.join(" | ")}` : ""}
                    {a.minimum != null || a.maximum != null ? ` [${a.minimum ?? ""}..${a.maximum ?? ""}]` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Disclosure>
      )}
      {sorted.length > 0 && (
        <Disclosure title={`Runs (${sorted.length})`}>
          <ul className="runs">
            {sorted.map((r) => (
              <li
                key={r.id}
                className={r.id === focusRunId ? "active" : ""}
                onClick={() => useStore.getState().setFocusRun(r.id)}
              >
                <span className={`badge ${r.status}`}>{r.status}</span>
                <span className="ellipsis">{r.prompt}</span>
                <span className="mono muted">
                  {r.stats.tiles_accepted}/{r.stats.tiles_planned}
                </span>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
    </div>
  );
}

function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="disclosure">
      <summary>{title}</summary>
      <div className="disclosure-body">{children}</div>
    </details>
  );
}

function RunCard({ run }: { run: Run }) {
  const st = run.stats;
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (run.finished_at) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [run.finished_at]);
  const wall = ((run.finished_at ?? now / 1000) - run.created_at).toFixed(1);
  const cells: [string, string][] = [
    ["tiles", `${st.tiles_accepted} / ${st.tiles_planned}${st.tiles_failed ? ` (${st.tiles_failed} failed)` : ""}`],
    ["copies", `${st.tiles_copied ?? 0}`],
    ["attempts", `${st.attempts} (${(st.attempts / Math.max(1, st.tiles_planned - (st.tiles_copied ?? 0))).toFixed(2)}/tile)`],
    ["rejected", `${st.rejections_validation} checks · ${st.rejections_review} review`],
    ["llm calls", `${st.llm_calls}`],
    ["tokens", `${fmt(st.input_tokens)} in (${fmt(st.cached_input_tokens)} cached) · ${fmt(st.output_tokens)} out`],
    ["cost", `$${st.cost_usd.toFixed(4)}`],
    ["images", `${st.images}`],
    ["wall", `${wall}s`],
  ];
  return (
    <section className="card">
      <div className="row">
        <span className={`badge ${run.status}`}>{run.status}</span>
        <span className="mono muted small">
          {run.id} · origin ({run.origin.q},{run.origin.r})
        </span>
      </div>
      <p className="prompt">“{run.prompt}”</p>
      {run.error && <div className="error small">{run.error}</div>}
      <div className="stats">
        {cells.map(([k, v]) => (
          <div key={k}>
            <span>{k}</span>
            <b>{v}</b>
          </div>
        ))}
      </div>
      <div className="progress">
        <div style={{ width: `${(100 * st.tiles_accepted) / Math.max(1, st.tiles_planned)}%` }} />
      </div>
    </section>
  );
}

const fmt = (n: number) => (n >= 10000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);

// ------------------------------------------------------------------ timeline

function Timeline() {
  const { events, focusRunId, runs } = useStore();
  const [showLlm, setShowLlm] = useState(true);
  const [showImg, setShowImg] = useState(true);
  const [now, setNow] = useState(Date.now() / 1000);
  const running = focusRunId ? !runs[focusRunId]?.finished_at : false;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 400);
    return () => clearInterval(t);
  }, [running]);
  const spans = useMemo(() => buildSpans(events, focusRunId), [events, focusRunId]);
  if (!spans.length) return <div className="hint">No trace yet for this run.</div>;
  const t0 = Math.min(...spans.map((s) => s.start));
  const t1 = Math.max(...spans.map((s) => s.end ?? now), t0 + 0.001);
  const rows = spans
    .filter((s) => (showLlm || s.name !== "llm.call") && (showImg || s.name !== "image.generate"))
    .slice(0, 800);
  return (
    <div className="timeline">
      <div className="row small">
        <label>
          <input type="checkbox" checked={showLlm} onChange={(e) => setShowLlm(e.target.checked)} /> llm calls
        </label>
        <label>
          <input type="checkbox" checked={showImg} onChange={(e) => setShowImg(e.target.checked)} /> images
        </label>
        <span className="muted">{(t1 - t0).toFixed(1)}s · {spans.length} spans</span>
      </div>
      <div className="rows">
        {rows.map((s) => {
          const left = ((s.start - t0) / (t1 - t0)) * 100;
          const width = Math.max(0.4, (((s.end ?? now) - s.start) / (t1 - t0)) * 100);
          const d = s.data as Record<string, any>;
          const tip = [
            spanLabel(s),
            s.end ? `${((s.end - s.start) * 1000).toFixed(0)} ms` : "running…",
            d.model ? `model ${d.model}` : "",
            d.input_tokens != null ? `tokens ${d.input_tokens} in / ${d.output_tokens} out` : "",
            d.cost_usd ? `$${d.cost_usd}` : "",
            d.error ? `error: ${d.error}` : "",
            d.invalid ? `invalid: ${d.invalid}` : "",
          ]
            .filter(Boolean)
            .join("\n");
          return (
            <div
              key={s.id}
              className="trow"
              title={tip}
              onClick={() => s.q != null && s.r != null && useStore.getState().select(`${s.q},${s.r}`)}
            >
              <span className="tlabel" style={{ paddingLeft: s.depth * 10 }}>
                {spanLabel(s)}
              </span>
              <span className="tbar-wrap">
                <span
                  className={`tbar ${s.end ? "" : "live"}`}
                  style={{ left: `${left}%`, width: `${width}%`, background: spanColor(s) }}
                />
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ tile

function TilePanel() {
  const { selected, world, tileVersion } = useStore();
  const version = selected ? tileVersion[selected] : 0;
  const [detail, setDetail] = useState<TileDetail | null>(null);
  useEffect(() => {
    if (!selected || !world) return;
    const { q, r } = parseKey(selected);
    let alive = true;
    api.getTile(world.id, q, r).then((d) => alive && setDetail(d));
    return () => {
      alive = false;
    };
  }, [selected, world, version]);
  if (!selected) return <div className="hint">Click a tile on the board to inspect it.</div>;
  if (!detail) return <div className="hint">Loading…</div>;
  const t = detail.tile;
  const img = t.asset_id ?? t.preview_asset_id;
  return (
    <div className="stack">
      <section className="tile-head">
        {img ? <img className="pixel big" src={assetUrl(img)} alt="" /> : <div className="pixel big empty" />}
        <div>
          <div className="row">
            <span className={`badge ${t.status}`}>{t.status}</span>
            <span className="mono">
              ({t.q}, {t.r})
            </span>
          </div>
          {t.copy_of && (
            <p className="small">
              <span className={`badge ${t.copy_mode}`}>{t.copy_mode} copy</span> of{" "}
              <a className="link" onClick={() => useStore.getState().select(`${t.copy_of!.q},${t.copy_of!.r}`)}>
                ({t.copy_of.q}, {t.copy_of.r})
              </a>
            </p>
          )}
          <p className="small">{t.summary ?? t.directive?.intent ?? ""}</p>
          {t.biome && <p className="small muted">biome: {t.biome}</p>}
        </div>
      </section>
      {t.attributes && Object.keys(t.attributes).length > 0 && (
        <section>
          <h4>Attributes</h4>
          <div className="kv small">
            {Object.entries(t.attributes).map(([k, v]) => (
              <FragmentKV key={k} k={k} v={Array.isArray(v) ? v.join(", ") : String(v)} />
            ))}
          </div>
        </section>
      )}
      {t.edges && (
        <section>
          <h4>Edge contract</h4>
          <div className="edges small">
            {t.edges.map((e, i) => (
              <div key={i}>
                <b>{DIRECTION_NAMES[i]}</b> {e.terrain}
                {e.connectors.length > 0 && <i> +{e.connectors.join("/")}</i>}
              </div>
            ))}
          </div>
        </section>
      )}
      {t.directive && (
        <section>
          <h4>Directive from super{t.directive.simplified ? " (simplified fallback)" : ""}</h4>
          <p className="small">{t.directive.intent}</p>
          {t.directive.features.length > 0 && <p className="small muted">features: {t.directive.features.join(", ")}</p>}
        </section>
      )}
      <section>
        <h4>Attempts ({detail.attempts.length})</h4>
        {detail.attempts.length === 0 && <p className="small muted">No generation attempts (copies need none).</p>}
        {detail.attempts
          .slice()
          .reverse()
          .map((a) => (
            <AttemptCard key={`${a.run_id}-${a.attempt}`} a={a} />
          ))}
      </section>
    </div>
  );
}

function FragmentKV({ k, v }: { k: string; v: string }) {
  return (
    <>
      <span className="mono muted">{k}</span>
      <span>{v}</span>
    </>
  );
}

function AttemptCard({ a }: { a: Attempt }) {
  const v = a.validation as Record<string, any>;
  const seams = (v?.seam_delta ?? {}) as Record<string, number>;
  return (
    <div className={`attempt ${a.outcome}`}>
      <div className="row">
        {a.asset_id ? <img className="pixel" src={assetUrl(a.asset_id)} alt="" /> : <div className="pixel empty" />}
        <div className="grow">
          <div className="row">
            <b>#{a.attempt}</b>
            <span className={`badge ${a.outcome}`}>{a.outcome}</span>
          </div>
          {a.design && <p className="small">{a.design.art_prompt}</p>}
          {Object.keys(seams).length > 0 && (
            <p className="small mono muted">
              seams:{" "}
              {Object.entries(seams)
                .map(([e, d]) => `${DIRECTION_NAMES[+e]} ${d.toFixed(2)}`)
                .join(" · ")}
            </p>
          )}
          {v?.failures?.length > 0 && <p className="small error-text">{v.failures.join("; ")}</p>}
          {v?.normalization?.repaired_edges?.length > 0 && (
            <p className="small muted">auto-repaired edges: {v.normalization.repaired_edges.join(", ")}</p>
          )}
          {a.verdict && (
            <p className="small">
              <span className="muted">
                review: style {a.verdict.scores.style} · fidelity {a.verdict.scores.fidelity} · edges{" "}
                {a.verdict.scores.edge_continuity} · fit {a.verdict.scores.directive_fit}
              </span>
              {a.verdict.feedback && <span className="error-text"> — {a.verdict.feedback}</span>}
            </p>
          )}
          {a.error && <p className="small error-text">{a.error}</p>}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ log

function EventLog() {
  const events = useStore((s) => s.events);
  const [filter, setFilter] = useState("");
  const [hideNoise, setHideNoise] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  const list = useMemo(() => {
    const f = filter.toLowerCase();
    const out = [];
    for (let i = events.length - 1; i >= 0 && out.length < 400; i--) {
      const e = events[i];
      if (hideNoise && (e.type === "tile.updated" || e.type.endsWith(".started"))) continue;
      if (f && !`${e.type} ${e.q},${e.r} ${JSON.stringify(e.data)}`.toLowerCase().includes(f)) continue;
      out.push(e);
    }
    return out;
  }, [events, filter, hideNoise]);
  return (
    <div className="log">
      <div className="row">
        <input placeholder="filter events…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <label className="small">
          <input type="checkbox" checked={hideNoise} onChange={(e) => setHideNoise(e.target.checked)} /> quiet
        </label>
      </div>
      {list.map((e) => (
        <div key={e.id} className="ev" onClick={() => setOpen(open === e.id ? null : e.id)}>
          <span className="mono muted">{new Date(e.ts * 1000).toLocaleTimeString()}</span>
          <span className={`etype ${e.type.split(".")[0]}`}>{e.type}</span>
          {e.q != null && <span className="mono muted">({e.q},{e.r})</span>}
          {open === e.id && <pre>{JSON.stringify(e.data, null, 2)}</pre>}
        </div>
      ))}
    </div>
  );
}
