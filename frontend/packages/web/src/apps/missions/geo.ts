import type { TrackFix, LocateMethod } from './types';

const R_M = 6_371_008.8;
const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

export interface TimedFix {
  tMs: number;
  lat: number;
  lon: number;
  headingDeg: number | null;
  sogKt: number | null;
}

export function haversineM(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function bearingDeg(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const dLon = rad(b.lon - a.lon);
  const y = Math.sin(dLon) * Math.cos(rad(b.lat));
  const x = Math.cos(rad(a.lat)) * Math.sin(rad(b.lat)) - Math.sin(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.cos(dLon);
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

/** Signed shortest difference b - a in degrees, in (-180, 180]. */
export function angleDiff(a: number, b: number): number {
  const d = (((b - a) % 360) + 540) % 360 - 180;
  return d === -180 ? 180 : d;
}

/** Interpolate headings the short way round; result in [0, 360). */
export function lerpAngle(a: number, b: number, f: number): number {
  return (((a + angleDiff(a, b) * f) % 360) + 360) % 360;
}

/** Parse, drop unusable fixes, sort by time and collapse equal timestamps (first wins), as the server does. */
export function prepareTrack(fixes: TrackFix[]): TimedFix[] {
  const parsed = fixes
    .map((f) => ({ tMs: Date.parse(f.t_utc), lat: f.lat, lon: f.lon, headingDeg: f.heading_true_deg ?? f.cog_true_deg ?? null, sogKt: f.sog_kt ?? null }))
    .filter((f) => Number.isFinite(f.tMs) && Number.isFinite(f.lat) && Number.isFinite(f.lon));
  parsed.sort((a, b) => a.tMs - b.tMs);
  return parsed.filter((f, i) => i === 0 || f.tMs !== parsed[i - 1].tMs);
}

export interface TrackPosition {
  method: LocateMethod;
  /** Present only for exact_fix and interpolated. */
  lat?: number;
  lon?: number;
  headingDeg?: number | null;
  sogKt?: number | null;
  gapS?: number;
  /** True when the marker must not be drawn at a position. */
  established: boolean;
}

/**
 * Where was the ship at `tMs`? Interpolates only between two returned fixes closer than `maxGapS`; never beyond
 * either end of the track and never across a longer gap (mirrors the server's methods).
 */
export function locateOnTrack(track: TimedFix[], tMs: number, maxGapS: number): TrackPosition {
  if (track.length === 0) return { method: 'no_track', established: false };
  const first = track[0];
  const last = track[track.length - 1];
  if (tMs < first.tMs) return { method: 'before_track', established: false };
  if (tMs > last.tMs) return { method: 'after_track', established: false };
  if (tMs === last.tMs) return { method: 'exact_fix', lat: last.lat, lon: last.lon, headingDeg: last.headingDeg, sogKt: last.sogKt, gapS: 0, established: true };
  let lo = 0;
  let hi = track.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (track[mid].tMs <= tMs) lo = mid;
    else hi = mid;
  }
  // lo is the last fix at or before tMs.
  const a = track[lo];
  if (a.tMs === tMs) return { method: 'exact_fix', lat: a.lat, lon: a.lon, headingDeg: a.headingDeg, sogKt: a.sogKt, gapS: 0, established: true };
  const b = track[lo + 1];
  const gapS = (b.tMs - a.tMs) / 1000;
  if (gapS > maxGapS) return { method: 'gap', gapS, established: false };
  const f = (tMs - a.tMs) / (b.tMs - a.tMs);
  const dLon = angleDiff(a.lon, b.lon);
  const lon = ((((a.lon + dLon * f) + 540) % 360) + 360) % 360 - 180;
  const heading = a.headingDeg != null && b.headingDeg != null ? lerpAngle(a.headingDeg, b.headingDeg, f) : bearingDeg(a, b);
  const sog = a.sogKt != null && b.sogKt != null ? a.sogKt + (b.sogKt - a.sogKt) * f : null;
  return { method: 'interpolated', lat: a.lat + (b.lat - a.lat) * f, lon, headingDeg: heading, sogKt: sog, gapS, established: true };
}

/** Index of the last event whose time is at or before `tMs` (events with no time are ignored); -1 if none. */
export function currentEventIndex(times: (number | null)[], tMs: number): number {
  let best = -1;
  times.forEach((t, i) => {
    if (t != null && t <= tMs && (best < 0 || t >= (times[best] as number))) best = i;
  });
  return best;
}

/** Keep at most `max` points, always including the first and last (display only). */
export function thin<T>(pts: T[], max: number): T[] {
  if (pts.length <= max || max < 2) return pts;
  const out: T[] = [];
  const step = (pts.length - 1) / (max - 1);
  for (let i = 0; i < max; i++) out.push(pts[Math.round(i * step)]);
  return out;
}
