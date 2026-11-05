/** A berth with the position it sits at, for placing it on the world map. */
export interface BerthSite {
  berthId: string;
  name: string;
  lat: number;
  lon: number;
}

/** Berths close together (the two faces of one pier, or one base) share a port marker. */
export interface Port {
  id: string;
  label: string;
  lat: number;
  lon: number;
  berths: BerthSite[];
}

const PORT_RADIUS_DEG = 0.5;
/** The map shows the middle band of the Web Mercator square: y from 0.25 to 0.75, about 66 N to 66 S. */
const Y_MIN = 0.25;
const Y_MAX = 0.75;

/** Web Mercator, as 0..1 fractions of the world square (x from the west edge, y from the north edge). */
export function mercator(lat: number, lon: number): { x: number; y: number } {
  const clamped = Math.max(-85, Math.min(85, lat));
  const rad = (clamped * Math.PI) / 180;
  return { x: (lon + 180) / 360, y: 0.5 - Math.log(Math.tan(Math.PI / 4 + rad / 2)) / (2 * Math.PI) };
}

/** Position inside the cropped map box, as 0..1 fractions of its width and height. */
export function mapPosition(lat: number, lon: number): { x: number; y: number } {
  const m = mercator(lat, lon);
  return { x: m.x, y: (m.y - Y_MIN) / (Y_MAX - Y_MIN) };
}

/** "Mock Pier 12 North face (NAVSTA Norfolk)" -> "NAVSTA Norfolk"; falls back to the whole name. */
export function portLabel(name: string): string {
  return /\(([^)]+)\)/.exec(name)?.[1] ?? name;
}

export function groupPorts(sites: BerthSite[]): Port[] {
  const ports: Port[] = [];
  for (const s of sites) {
    const home = ports.find((p) => Math.abs(p.lat - s.lat) < PORT_RADIUS_DEG && Math.abs(p.lon - s.lon) < PORT_RADIUS_DEG);
    if (home) {
      home.berths.push(s);
      continue;
    }
    ports.push({ id: s.berthId, label: portLabel(s.name), lat: s.lat, lon: s.lon, berths: [s] });
  }
  return ports;
}

/** Which marker a pointer is over: the nearest one within `radius` pixels of its centre, or null. */
export function portAt(x: number, y: number, centres: { id: string; x: number; y: number }[], radius = 18): string | null {
  let best: { id: string; d: number } | null = null;
  for (const c of centres) {
    const d = Math.hypot(c.x - x, c.y - y);
    if (d <= radius && (!best || d < best.d)) best = { id: c.id, d };
  }
  return best?.id ?? null;
}
