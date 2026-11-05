import type { SimFrame } from './frames';

/** What the motion view says about time: simulation vs wall clock, and when the forcing applies. */
export interface SimClockView {
  simS: number;
  /** Wall seconds this run has spent running, as observed by this browser (paused time excluded). */
  wallRunningS: number;
  /** Simulated seconds per wall second over the last few seconds; null until measurable. */
  effectiveSpeed: number | null;
  /** Simulation time the frame's environment values apply to; null when the simulator does not say. */
  forcingTS: number | null;
  /** Forcing series revision when the simulator publishes one; null otherwise. */
  forcingRevision: string | null;
  /** True when the forcing is synthetic or training data, so the view keeps a standing label. */
  training: boolean;
}

const WINDOW_MS = 5000;

/** Tracks simulation time against this browser's wall clock for one live session. */
export class SimClock {
  private runId: string | null = null;
  private samples: { wall: number; sim: number }[] = [];
  private wallRunningMs = 0;
  private lastWall: number | null = null;

  reset(): void {
    this.runId = null;
    this.samples = [];
    this.wallRunningMs = 0;
    this.lastWall = null;
  }

  /** Record a displayed frame. `running` is the session lifecycle state at the time. */
  observe(frame: SimFrame, wallMs: number, running: boolean): SimClockView {
    const runId = frame.run_id ?? null;
    const last = this.samples[this.samples.length - 1];
    if (runId !== this.runId || (last && frame.t_s < last.sim)) {
      // New run or reset: time starts again.
      this.runId = runId;
      this.samples = [];
      this.wallRunningMs = 0;
      this.lastWall = null;
    }
    if (running) {
      if (this.lastWall !== null) this.wallRunningMs += Math.max(0, wallMs - this.lastWall);
      this.lastWall = wallMs;
      this.samples.push({ wall: wallMs, sim: frame.t_s });
      while (this.samples.length > 2 && wallMs - this.samples[0].wall > WINDOW_MS) this.samples.shift();
    } else {
      // Paused time is not running time, and a speed measured across a pause would be wrong.
      this.lastWall = null;
      this.samples = [];
    }
    const first = this.samples[0];
    const span = first ? (wallMs - first.wall) / 1000 : 0;
    const effectiveSpeed = first && span >= 1 ? (frame.t_s - first.sim) / span : null;
    return { simS: frame.t_s, wallRunningS: this.wallRunningMs / 1000, effectiveSpeed, ...forcingOf(frame) };
  }
}

/** Forcing time, revision and training status from the frame, read only from what it supplies. */
export function forcingOf(frame: SimFrame): Pick<SimClockView, 'forcingTS' | 'forcingRevision' | 'training'> {
  const env = (frame.environment ?? null) as (Record<string, unknown> & { t_s?: number | null }) | null;
  // S2 publishes the revision on the frame; retain older environment-local metadata compatibility.
  const rev = frame.forcing_revision ?? env?.['forcing_revision'] ?? env?.['revision'];
  const kinds = [
    ...(['wind', 'current', 'water'] as const).map((k) => (env?.[k] as { provenance?: { kind?: string } } | null | undefined)?.provenance?.kind),
  ];
  return {
    forcingTS: typeof env?.t_s === 'number' ? env.t_s : frame.forcing_revision ? frame.t_s : null,
    forcingRevision: typeof rev === 'string' ? rev : null,
    training: kinds.some((k) => k === 'mock'),
  };
}

/** "1:02:03" or "4:05" for seconds. */
export function clockText(s: number): string {
  const t = Math.max(0, Math.floor(s));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = String(t % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}
