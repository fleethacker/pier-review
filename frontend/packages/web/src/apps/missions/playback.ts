import { angleDiff, lerpAngle, wrapLongitude } from './geo';
import type { TransitFrame, TransitVesselState } from './types';

export const SPEEDS = [1, 2, 5, 10, 30, 60] as const;
export const MAX_TRAIL_POINTS = 300;

const lerp = (a: number, b: number, f: number) => a + (b - a) * f;

/** Frame index pair bracketing `tS` and the blend factor. Clamped: never beyond the first or last frame. */
export function bracket(frames: TransitFrame[], tS: number): { i0: number; i1: number; f: number } {
  const n = frames.length;
  if (n === 0) return { i0: 0, i1: 0, f: 0 };
  if (tS <= frames[0].t_s) return { i0: 0, i1: 0, f: 0 };
  if (tS >= frames[n - 1].t_s) return { i0: n - 1, i1: n - 1, f: 0 };
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].t_s <= tS) lo = mid;
    else hi = mid;
  }
  const span = frames[hi].t_s - frames[lo].t_s;
  return { i0: lo, i1: hi, f: span > 0 ? (tS - frames[lo].t_s) / span : 0 };
}

const NUMERIC = [
  'lat', 'x_east_ft', 'y_north_ft', 'sog_kt', 'stw_kt', 'u_kt', 'v_kt', 'r_degps', 'rudder_deg', 'engine_order',
  'thrust_lbf', 'cross_track_ft', 'distance_to_go_nm',
] as const;

export function blendVessel(a: TransitVesselState, b: TransitVesselState, f: number): TransitVesselState {
  if (f <= 0) return a;
  if (f >= 1) return b;
  const out: TransitVesselState = { ...a };
  for (const k of NUMERIC) out[k] = lerp(a[k], b[k], f);
  out.lon = wrapLongitude(a.lon + angleDiff(a.lon, b.lon) * f);
  out.heading_true_deg = lerpAngle(a.heading_true_deg, b.heading_true_deg, f);
  out.cog_true_deg = a.cog_true_deg != null && b.cog_true_deg != null ? lerpAngle(a.cog_true_deg, b.cog_true_deg, f) : a.cog_true_deg;
  // Discrete state (status, leg, tug contacts) comes from the earlier frame; it is not blended.
  return out;
}

/** Vessel states at `tS`, linearly blended between the two bracketing frames. Never extrapolates. */
export function stateAt(frames: TransitFrame[], tS: number): TransitVesselState[] {
  if (frames.length === 0) return [];
  const { i0, i1, f } = bracket(frames, tS);
  const a = frames[i0].vessels;
  if (i0 === i1) return a;
  const bById = new Map(frames[i1].vessels.map((v) => [v.vessel_id, v]));
  return a.map((v) => {
    const w = bById.get(v.vessel_id);
    return w ? blendVessel(v, w, f) : v;
  });
}

export function endTime(frames: TransitFrame[]): number {
  return frames.length ? frames[frames.length - 1].t_s : 0;
}

/** The recent path of one vessel up to `tS`, thinned to at most `cap` points, ending at the current position. */
export function trailPoints(
  frames: TransitFrame[],
  vesselId: string,
  tS: number,
  now: { lat: number; lon: number } | null,
  cap: number = MAX_TRAIL_POINTS,
): { lat: number; lon: number }[] {
  const pts: { lat: number; lon: number }[] = [];
  for (const fr of frames) {
    if (fr.t_s > tS) break;
    const v = fr.vessels.find((x) => x.vessel_id === vesselId);
    if (v) pts.push({ lat: v.lat, lon: v.lon });
  }
  let out = pts;
  if (pts.length > cap - 1) {
    const keep = cap - 1;
    const step = (pts.length - 1) / (keep - 1);
    out = Array.from({ length: keep }, (_, i) => pts[Math.round(i * step)]);
  }
  if (now) out = [...out, now];
  return out;
}

export interface Clock {
  /** Simulation seconds. */
  t: number;
  playing: boolean;
  speed: number;
}

/** Advance the playback clock by `wallDtS` real seconds at `speed`x; stops (and pauses) at the end. */
export function advanceClock(c: Clock, wallDtS: number, endS: number): Clock {
  if (!c.playing) return c;
  const t = Math.min(endS, c.t + Math.max(0, wallDtS) * c.speed);
  return { ...c, t, playing: t < endS };
}

export function clampSpeed(s: number): number {
  return Math.min(60, Math.max(1, s));
}
