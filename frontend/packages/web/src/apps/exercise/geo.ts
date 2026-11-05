import type { LonLat } from './types';

const DEG = Math.PI / 180;
export const EARTH_RADIUS_M = 6_371_008.8;
export const M_PER_NM = 1852;
export const KT_TO_MS = M_PER_NM / 3600;

export const ktToMs = (kt: number) => kt * KT_TO_MS;
export const msToKt = (ms: number) => ms / KT_TO_MS;
export const nmToM = (nm: number) => nm * M_PER_NM;
export const mToNm = (m: number) => m / M_PER_NM;

/** Compass bearing in [0, 360). */
export function normalizeBearing(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

/** Signed smallest rotation from `from` to `to`, in (-180, 180]. Positive turns clockwise (to starboard). */
export function angleDiff(to: number, from: number): number {
  const d = normalizeBearing(to - from);
  return d > 180 ? d - 360 : d;
}

/** Great-circle distance in meters. */
export function distanceM(a: LonLat, b: LonLat): number {
  const p1 = a.lat * DEG;
  const p2 = b.lat * DEG;
  const dp = p2 - p1;
  const dl = (b.lon - a.lon) * DEG;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Initial true bearing from a to b. */
export function bearingTo(a: LonLat, b: LonLat): number {
  const p1 = a.lat * DEG;
  const p2 = b.lat * DEG;
  const dl = (b.lon - a.lon) * DEG;
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return normalizeBearing(Math.atan2(y, x) / DEG);
}

/** Point reached from `from` after `distM` along a great circle with initial true bearing `bearingDeg`. */
export function destination(from: LonLat, bearingDeg: number, distM: number): LonLat {
  const d = distM / EARTH_RADIUS_M;
  const b = bearingDeg * DEG;
  const p1 = from.lat * DEG;
  const l1 = from.lon * DEG;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return { lon: ((l2 / DEG + 540) % 360) - 180, lat: p2 / DEG };
}

/** Meters east and north of `origin`, flat-earth. Fine below a few kilometers. */
export function offsetM(origin: LonLat, eastM: number, northM: number): LonLat {
  const lat = origin.lat + (northM / EARTH_RADIUS_M) / DEG;
  const lon = origin.lon + eastM / (EARTH_RADIUS_M * Math.cos(origin.lat * DEG)) / DEG;
  return { lon, lat };
}

/**
 * A station relative to a ship: `forwardM` along its heading, `starboardM` to its right.
 * Used for formation positions and to place things in the ship's frame.
 */
export function stationFrom(origin: LonLat, headingDeg: number, forwardM: number, starboardM: number): LonLat {
  const h = headingDeg * DEG;
  const east = forwardM * Math.sin(h) + starboardM * Math.cos(h);
  const north = forwardM * Math.cos(h) - starboardM * Math.sin(h);
  return offsetM(origin, east, north);
}

/** Heading and speed to meters east/north per second. Heading is a compass bearing. */
export function velocityEN(headingDeg: number, speedMs: number): [number, number] {
  const h = headingDeg * DEG;
  return [speedMs * Math.sin(h), speedMs * Math.cos(h)];
}

/** Closed ring of `steps` points around `center`, `radiusM` away, as [lon, lat]. */
export function circleRing(center: LonLat, radiusM: number, steps = 96): [number, number][] {
  const ring: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const p = destination(center, (i / steps) * 360, radiusM);
    ring.push([p.lon, p.lat]);
  }
  return ring;
}

export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

/** Latitude and longitude in degrees and decimal minutes, the way a bridge reads them. */
export function formatLatLon(p: LonLat): string {
  const part = (v: number, pos: string, neg: string, width: number) => {
    const a = Math.abs(v);
    const deg = Math.floor(a);
    const min = (a - deg) * 60;
    return `${String(deg).padStart(width, '0')}°${min.toFixed(2).padStart(5, '0')}'${v >= 0 ? pos : neg}`;
  };
  return `${part(p.lat, 'N', 'S', 2)} ${part(p.lon, 'E', 'W', 3)}`;
}
