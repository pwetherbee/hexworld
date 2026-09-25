// Tiny Web Audio sound engine for the wooden UI clicks in /public/sfx (imported locally with
// scripts/import-sfx.mjs; the app stays silent if they're missing).
//
// Every sound has a per-name rate limit and random pitch/volume jitter, so a wave of 20 tiles
// landing at once reads as a quick patter instead of a machine gun.

type SoundName = "press" | "confirm" | "land" | "stamp" | "reject" | "done";

const range = (prefix: string, n: number) =>
  Array.from({ length: n }, (_, i) => `${prefix}_${String(i + 1).padStart(2, "0")}.wav`);

const BANK: Record<SoundName, { files: string[]; gain: number; rate: [number, number]; minGapMs: number }> = {
  press: { files: range("wooden_button_click_in", 8), gain: 0.35, rate: [0.96, 1.06], minGapMs: 35 },
  confirm: { files: range("wooden_button", 3), gain: 0.5, rate: [0.98, 1.02], minGapMs: 120 },
  land: { files: range("wooden_button_click_out", 7), gain: 0.22, rate: [0.9, 1.12], minGapMs: 85 },
  stamp: { files: ["wooden_button_click_in_07.wav", "wooden_button_click_in_08.wav"], gain: 0.3, rate: [0.78, 0.86], minGapMs: 90 },
  reject: { files: range("wooden_button_click_out", 7), gain: 0.25, rate: [0.62, 0.7], minGapMs: 150 },
  done: { files: ["wooden_button_02.wav"], gain: 0.45, rate: [0.9, 0.9], minGapMs: 500 },
};

class Sfx {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private buffers = new Map<string, AudioBuffer>();
  private last = new Map<SoundName, number>();
  muted = readMuted();

  /** Audio can only start after a user gesture; call from the first pointerdown. */
  unlock() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.9;
      this.master.connect(this.ctx.destination);
      void this.load();
    }
    if (this.ctx.state === "suspended") void this.ctx.resume();
  }

  private async load() {
    const files = new Set(Object.values(BANK).flatMap((b) => b.files));
    await Promise.all(
      [...files].map(async (f) => {
        try {
          const res = await fetch(`/sfx/${f}`);
          if (!res.ok) return;
          this.buffers.set(f, await this.ctx!.decodeAudioData(await res.arrayBuffer()));
        } catch {
          /* missing or undecodable: stay silent */
        }
      }),
    );
  }

  play(name: SoundName, opts: { gain?: number } = {}) {
    if (this.muted || !this.ctx || !this.master || this.ctx.state !== "running") return;
    const spec = BANK[name];
    const now = performance.now();
    if (now - (this.last.get(name) ?? -Infinity) < spec.minGapMs) return;
    const file = spec.files[Math.floor(Math.random() * spec.files.length)];
    const buf = this.buffers.get(file);
    if (!buf) return;
    this.last.set(name, now);
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = spec.rate[0] + Math.random() * (spec.rate[1] - spec.rate[0]);
    const g = this.ctx.createGain();
    g.gain.value = spec.gain * (opts.gain ?? 1) * (0.85 + Math.random() * 0.3);
    src.connect(g).connect(this.master);
    src.start();
  }

  setMuted(m: boolean) {
    this.muted = m;
    try {
      localStorage.setItem("hexworld.muted", m ? "1" : "0");
    } catch {
      /* ignore */
    }
  }
}

function readMuted() {
  try {
    return localStorage.getItem("hexworld.muted") === "1";
  } catch {
    return false;
  }
}

export const sfx = new Sfx();

/** Unlock audio on the first gesture, and give every button a wooden press. */
export function installUiSounds() {
  const onDown = (e: PointerEvent) => {
    sfx.unlock();
    const el = (e.target as HTMLElement | null)?.closest("button, select, summary, [data-sfx]");
    if (el && !(el as HTMLButtonElement).disabled) sfx.play("press");
  };
  document.addEventListener("pointerdown", onDown, true);
  return () => document.removeEventListener("pointerdown", onDown, true);
}
