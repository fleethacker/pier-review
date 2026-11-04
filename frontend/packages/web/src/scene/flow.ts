/** A rectangle in scene-frame meters that particles stay inside. */
export interface FlowRegion {
  cx: number;
  cy: number;
  halfW: number;
  halfH: number;
}

export interface Streak {
  x: number;
  y: number;
}

/**
 * Particles drifting along one direction inside a region. A particle that leaves is put back on the upwind edge, so
 * the field looks endless. Pure: no rendering, and the random source can be replaced in tests.
 */
export class FlowField {
  readonly streaks: Streak[];

  constructor(
    count: number,
    public region: FlowRegion,
    private rng: () => number = Math.random,
  ) {
    this.streaks = Array.from({ length: count }, () => this.randomPoint());
  }

  private randomPoint(): Streak {
    const r = this.region;
    return { x: r.cx + (this.rng() * 2 - 1) * r.halfW, y: r.cy + (this.rng() * 2 - 1) * r.halfH };
  }

  private inside(p: Streak): boolean {
    const r = this.region;
    return Math.abs(p.x - r.cx) <= r.halfW && Math.abs(p.y - r.cy) <= r.halfH;
  }

  /** A random point slid back against the flow until it sits on the upwind edge of the region. */
  private upwindPoint(dirX: number, dirY: number): Streak {
    const r = this.region;
    const q = this.randomPoint();
    const room = (pos: number, center: number, half: number, d: number) =>
      d > 1e-9 ? (pos - (center - half)) / d : d < -1e-9 ? (center + half - pos) / -d : Infinity;
    const t = Math.min(room(q.x, r.cx, r.halfW, dirX), room(q.y, r.cy, r.halfH, dirY));
    return Number.isFinite(t) ? { x: q.x - dirX * t, y: q.y - dirY * t } : q;
  }

  /** Move every particle `speed * dt` meters along the unit direction (dirX, dirY). */
  step(dt: number, dirX: number, dirY: number, speed: number): void {
    const d = speed * dt;
    for (const s of this.streaks) {
      s.x += dirX * d;
      s.y += dirY * d;
      if (!this.inside(s)) {
        const p = this.upwindPoint(dirX, dirY);
        s.x = p.x;
        s.y = p.y;
      }
    }
  }
}

/** Visual speed of a streak in m/s: steady speed with a slow swell, so gusty wind visibly surges. */
export function flowSpeed(baseMps: number, gustiness: number | undefined, timeS: number): number {
  const g = gustiness ?? 0;
  return baseMps * (1 + g * 0.5 * (Math.sin(timeS * 0.9) + 0.5 * Math.sin(timeS * 2.3 + 1)));
}
