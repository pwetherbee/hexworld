import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";

const EXAMPLES = [
  "A pirate archipelago with hidden coves and a volcano",
  "A long river valley winding from glacier to delta",
  "A dense neon megacity block with markets and alleys",
  "The inside of a dwarven fortress: forges, halls and mines",
];

const RESOLUTIONS = [32, 48, 64, 96, 128]; // ground texture pixels per tile (backend TILE_PX_CHOICES)

export function PromptModal() {
  const target = useStore((s) => s.promptTarget);
  const world = useStore((s) => s.world);
  const [shown, setShown] = useState(target);
  const [prompt, setPrompt] = useState("");
  const [maxTiles, setMaxTiles] = useState(40);
  const [resIdx, setResIdx] = useState(2); // index into RESOLUTIONS

  const [maxAttempts, setMaxAttempts] = useState(3);
  const [maxCost, setMaxCost] = useState(2);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const extending = !!world?.spec;
  const worldPx = world?.style?.tile_px;
  const tilePx = extending && worldPx ? worldPx : RESOLUTIONS[resIdx];

  // Keep content mounted while the exit animation plays.
  useEffect(() => {
    if (target) {
      setShown(target);
      setErr(null);
      setTimeout(() => ref.current?.focus(), 30);
      return;
    }
    const t = setTimeout(() => setShown(null), 220);
    return () => clearTimeout(t);
  }, [target]);

  if (!shown) return null;
  const close = () => useStore.getState().setPromptTarget(null);
  const submit = async () => {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await useStore.getState().startRun(prompt, { max_tiles: maxTiles, tile_px: tilePx, max_attempts: maxAttempts, max_cost_usd: maxCost });
      setPrompt("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`scrim ${target ? "in" : "out"}`} onMouseDown={close}>
      <div className="prompt-card" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Describe a world">
        <textarea
          ref={ref}
          rows={3}
          value={prompt}
          placeholder={extending ? `Extend “${world?.spec?.title}” here…` : "Describe a world or a board game…"}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
            if (e.key === "Escape") close();
          }}
        />
        <div className={`examples ${prompt || extending ? "collapsed" : ""}`}>
          <div className="examples-inner">
            {EXAMPLES.map((ex) => (
              <button key={ex} className="example" onClick={() => setPrompt(ex)}>
                {ex}
              </button>
            ))}
          </div>
        </div>
        <details className="prompt-options">
          <summary>
            <span className="mono muted">
              ({shown.q}, {shown.r}) · up to {maxTiles} tiles · {tilePx}px terrain · {maxAttempts} tries · ${maxCost.toFixed(2)} cap
            </span>
          </summary>
          <div className="options">
            <label>
              Max tiles <b>{maxTiles}</b>
              <input
                type="range" min={5} max={200} step={5} value={maxTiles}
                onChange={(e) => setMaxTiles(+e.target.value)}
              />
            </label>
            <label title={extending ? "Set when the world was created: every tile shares one pixel grid" : undefined}>
              Terrain detail <b>{tilePx}px</b>
              <input
                type="range" min={0} max={RESOLUTIONS.length - 1} step={1}
                value={extending && worldPx ? RESOLUTIONS.indexOf(worldPx) : resIdx}
                disabled={extending}
                onChange={(e) => setResIdx(+e.target.value)}
              />
            </label>
            <label>
              Attempts <b>{maxAttempts}</b>
              <input type="range" min={1} max={5} value={maxAttempts} onChange={(e) => setMaxAttempts(+e.target.value)} />
            </label>
            <label>
              Cost cap <b>${maxCost.toFixed(2)}</b>
              <input
                type="range" min={0.25} max={10} step={0.25} value={maxCost}
                onChange={(e) => setMaxCost(+e.target.value)}
              />
            </label>
          </div>
        </details>
        {err && <div className="error">{err}</div>}
        <div className="prompt-actions">
          <span className="muted small">Enter to create · Esc to close</span>
          <button className="go" disabled={busy || !prompt.trim()} onClick={() => void submit()}>
            {busy ? "…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
