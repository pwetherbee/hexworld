import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { HexLogo, IconChevron, IconFollow, IconPanel, IconPlus, IconSound } from "./icons";

/** Top-left: world name; expands into the world switcher. */
export function WorldPill() {
  const world = useStore((s) => s.world);
  const worlds = useStore((s) => s.worlds);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [open]);
  return (
    <div className={`pill world-pill ${open ? "open" : ""}`} ref={ref}>
      <button className="pill-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="logo">
          <HexLogo />
        </span>
        <span className="ellipsis">{world?.spec?.title ?? world?.name ?? "HexWorld"}</span>
        <IconChevron />
      </button>
      <div className="pill-body">
        <div className="pill-body-inner">
          {worlds.map((w) => (
            <button
              key={w.id}
              className={`menu-item ${w.id === world?.id ? "active" : ""}`}
              onClick={() => {
                setOpen(false);
                void useStore.getState().openWorld(w.id);
              }}
            >
              {w.spec?.title ?? w.name}
            </button>
          ))}
          <button
            className="menu-item accent"
            onClick={() => {
              setOpen(false);
              void useStore.getState().newWorld();
            }}
          >
            <IconPlus /> New world
          </button>
        </div>
      </div>
    </div>
  );
}

/** Top-right: icon-only toggles. */
export function Controls() {
  const follow = useStore((s) => s.follow);
  const muted = useStore((s) => s.muted);
  const drawerOpen = useStore((s) => s.drawerOpen);
  const health = useStore((s) => s.health);
  const stream = useStore((s) => s.streamState);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      const s = useStore.getState();
      if (e.key === "f") s.setFollow(!s.follow);
      if (e.key === "m") s.setMuted(!s.muted);
      if (e.key === "i") (s.drawerOpen ? s.closeDrawer() : s.openDrawer("run"));
      if (e.key === "Escape") s.closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const s = useStore.getState();
  const sys = health
    ? `llm ${health.llm} (${health.super_model} / ${health.tile_model}) · images ${health.image}${health.image_healthy ? "" : " (down)"} · stream ${stream}`
    : "connecting…";
  return (
    <div className={`controls ${drawerOpen ? "shifted" : ""}`}>
      <span className={`status-dot ${stream === "open" && health?.image_healthy !== false ? "ok" : "bad"}`} data-tip={sys} />
      <button className={`icon-btn ${follow ? "on" : ""}`} onClick={() => s.setFollow(!follow)} data-tip="Follow the build (F)">
        <IconFollow on={follow} />
      </button>
      <button className={`icon-btn ${muted ? "" : "on"}`} onClick={() => s.setMuted(!muted)} data-tip="Sound (M)">
        <IconSound muted={muted} />
      </button>
      <button
        className={`icon-btn ${drawerOpen ? "on" : ""}`}
        onClick={() => (drawerOpen ? s.closeDrawer() : s.openDrawer("run"))}
        data-tip="Inspector (I)"
      >
        <IconPanel />
      </button>
    </div>
  );
}

/** Bottom-center: slim progress capsule while a run is active; hover to expand details. */
export function RunCapsule() {
  const run = useStore((s) => (s.activeRunId ? s.runs[s.activeRunId] : null));
  useStore((s) => s.libraryBusy); // re-render when artists start/finish
  const [lingering, setLingering] = useState<typeof run>(null);
  useEffect(() => {
    if (run) {
      setLingering(run);
      return;
    }
    const t = setTimeout(() => setLingering(null), 2200); // let "done" breathe, then fade out
    return () => clearTimeout(t);
  }, [run]);
  const shown = run ?? lingering;
  const latest = useStore((s) => (shown ? s.runs[shown.id] : null));
  if (!latest) return <div className="capsule hidden" />;
  const st = latest.stats;
  const pct = st.tiles_planned ? st.tiles_accepted / st.tiles_planned : 0;
  const active = latest.status === "running" || latest.status === "pending";
  const busy = useStore.getState().libraryBusy;
  const phase = !st.tiles_planned
    ? "super is planning"
    : busy > 0
      ? `artists designing ${busy} asset${busy > 1 ? "s" : ""}`
      : active
        ? "building"
        : latest.status;
  return (
    <div className={`capsule ${run ? "" : "leaving"}`} onClick={() => useStore.getState().openDrawer("run")}>
      <div className="capsule-row">
        <span className={`dot ${active ? "pulse" : "done"}`} />
        <span className="capsule-phase">{phase}</span>
        <span className="mono">
          {st.tiles_accepted}/{st.tiles_planned || "–"}
        </span>
        {active && (
          <button
            className="capsule-cancel"
            onClick={(e) => {
              e.stopPropagation();
              void useStore.getState().cancelRun();
            }}
          >
            stop
          </button>
        )}
      </div>
      <div className="capsule-bar">
        <div style={{ transform: `scaleX(${pct})` }} />
      </div>
      <div className="capsule-more">
        <div className="capsule-more-inner mono">
          <span>{st.attempts} attempts</span>
          <span>{st.tiles_copied} copies</span>
          <span>{st.rejections_review + st.rejections_validation} rejected</span>
          <span>{st.llm_calls} llm calls</span>
          <span>${st.cost_usd.toFixed(3)}</span>
        </div>
      </div>
    </div>
  );
}

export function EmptyHint() {
  const world = useStore((s) => s.world);
  const busy = useStore((s) => !!s.activeRunId || s.promptTarget !== null);
  const show = !!world && !world.spec && !busy;
  return <div className={`empty-hint ${show ? "" : "hidden"}`}>click any hex to begin</div>;
}

export function Toast() {
  const error = useStore((s) => s.error);
  return (
    <div className={`toast ${error ? "" : "hidden"}`} onClick={() => useStore.getState().setError(null)}>
      {error}
    </div>
  );
}
