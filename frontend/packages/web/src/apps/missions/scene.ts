import type { LocalFrame, SceneEntity, SceneLink, SceneVector } from '../../scene/types';
import { haversineM, thin } from './geo';
import { KIND_COLOR, DISCREPANCY_WARN_M, hasMarker, locateStyle } from './styling';
import type { Storyboard, StoryboardEvent, TransitTugState, TransitVesselState } from './types';

const M_PER_DEG_LAT = 111_132;
const FT = 0.3048;
export const MAX_TRACK_SEGMENTS = 400;
/** Used for a vessel whose class length is unknown: a fixed, labeled glyph (not to scale). */
export const FALLBACK_HULL_M = 120;

/**
 * Local frame for the shell: +x east (bearing 90), so +y is north. Equirectangular about the origin; fine for a
 * port transit and adequate for display of a sortie.
 */
export interface Projector {
  frame: LocalFrame;
  toXY(lat: number, lon: number): { x: number; y: number };
}

export function makeProjector(lat0: number, lon0: number): Projector {
  const kLon = M_PER_DEG_LAT * Math.cos((lat0 * Math.PI) / 180);
  return {
    frame: { latDeg: lat0, lonDeg: lon0, xBearingTrueDeg: 90 },
    toXY: (lat, lon) => ({ x: (((lon - lon0 + 540) % 360) - 180) * kLon, y: (lat - lat0) * M_PER_DEG_LAT }),
  };
}

/** Heading in the scene (degrees CCW from +x = east) from a true bearing. */
export const sceneHeading = (trueDeg: number): number => 90 - trueDeg;

export function centroid(points: { lat: number; lon: number }[]): { lat: number; lon: number } {
  if (points.length === 0) return { lat: 0, lon: 0 };
  const lat = points.reduce((s, p) => s + p.lat, 0) / points.length;
  const lon = points.reduce((s, p) => s + p.lon, 0) / points.length;
  return { lat, lon };
}

function polyline(id: string, kind: string, pts: { lat: number; lon: number }[], p: Projector, color: string, widthPx: number, opts: Partial<SceneLink> = {}): SceneLink[] {
  const out: SceneLink[] = [];
  for (let i = 1; i < pts.length; i++) {
    const a = p.toXY(pts[i - 1].lat, pts[i - 1].lon);
    const b = p.toXY(pts[i].lat, pts[i].lon);
    out.push({ id: `${id}:${i}`, kind, from: { ...a, z: 0 }, to: { ...b, z: 0 }, color, widthPx, ...opts });
  }
  return out;
}

export function eventEntityId(eventId: string): string {
  return `event:${eventId}`;
}

export function eventIdFromEntity(entityId: string): string | null {
  return entityId.startsWith('event:') ? entityId.slice('event:'.length) : null;
}

export function eventEntity(e: StoryboardEvent, p: Projector, selected: boolean): SceneEntity | null {
  if (!hasMarker(e)) return null;
  const st = locateStyle(e.located.method);
  const { x, y } = p.toXY(e.located.lat as number, e.located.lon as number);
  const bigDiscrepancy = (e.located.discrepancy_m ?? 0) > DISCREPANCY_WARN_M;
  return {
    id: eventEntityId(e.event_id),
    kind: `event-${e.kind}`,
    label: `${e.kind === 'image' ? 'Image' : 'Report'}: ${e.title}`,
    labelAlways: selected,
    pose: { x, y, z: 0, headingDeg: 0 },
    geometry: { type: 'point', sizePx: selected ? st.sizePx + 5 : st.sizePx },
    color: KIND_COLOR[e.kind],
    opacity: st.opacity,
    status: bigDiscrepancy ? 'AMBER' : undefined,
    selectable: true,
    props: [
      { label: 'Located', value: st.label },
      ...(e.t_utc ? [{ label: 'Time (UTC)', value: e.t_utc }] : []),
      ...(e.located.discrepancy_m != null ? [{ label: 'Stated vs track', value: `${Math.round(e.located.discrepancy_m)} m` }] : []),
    ],
  };
}

const FIT_PAD_FRACTION = 0.2;
const FIT_MIN_PAD_M = 300;
/** Transit frames the start (the shell cannot show a whole route) with room for a hull and tug arrows. */
export const TRANSIT_FIT_PAD_M = 800;
export const FIT_ANCHOR_KIND = 'fit-anchor';

/**
 * The shell fits the camera to entities only, not to links or vectors. Two invisible points at the opposite corners
 * of the data's bounding box make the track or the transit route frame correctly, even before the first marker exists.
 */
export function fitAnchors(points: { lat: number; lon: number }[], p: Projector, minPadM = FIT_MIN_PAD_M): SceneEntity[] {
  if (points.length === 0) return [];
  const xy = points.map((q) => p.toXY(q.lat, q.lon));
  const xs = xy.map((q) => q.x);
  const ys = xy.map((q) => q.y);
  // The shell fits tightly (a vessel at the end of a route sat on the canvas edge), so pad the box.
  const pad = Math.max(minPadM, FIT_PAD_FRACTION * Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)));
  const corners = [
    [Math.min(...xs) - pad, Math.min(...ys) - pad],
    [Math.max(...xs) + pad, Math.max(...ys) + pad],
  ];
  return corners.map(([x, y], i) => ({
    id: `fit-anchor:${i}`,
    kind: FIT_ANCHOR_KIND,
    pose: { x, y, z: 0, headingDeg: 0 },
    geometry: { type: 'point' as const, sizePx: 1 },
    opacity: 0,
    noOutline: true,
    selectable: false,
  }));
}

export const SHIP_ID = 'mission-ship';

/** Storyboard map content: the track polyline, event markers (never for unlocated events). */
export function storyboardContent(sb: Storyboard, p: Projector, selectedEventId: string | null): { entities: SceneEntity[]; links: SceneLink[] } {
  const pts = thin(sb.track, MAX_TRACK_SEGMENTS + 1);
  // Break the polyline across gaps so the line does not imply a position where none is established.
  const links: SceneLink[] = [];
  let run: { lat: number; lon: number }[] = [];
  let seg = 0;
  const flush = () => {
    links.push(...polyline(`track${seg++}`, 'track', run, p, '#4fc3f7', 3));
    run = [];
  };
  let prevT = 0;
  for (const f of pts) {
    const t = Date.parse(f.t_utc);
    if (run.length && (t - prevT) / 1000 > sb.max_interp_gap_s) {
      // Dashed look is not available on links; draw the gap as a thin dim line so it reads as "not recorded".
      const last = run[run.length - 1];
      links.push(...polyline(`gap${seg}`, 'track-gap', [last, f], p, '#6b7f99', 1));
      flush();
    }
    run.push(f);
    prevT = t;
  }
  flush();
  const entities = sb.events.map((e) => eventEntity(e, p, e.event_id === selectedEventId)).filter((x): x is SceneEntity => x !== null);
  return { entities, links };
}

export function shipMarker(lat: number, lon: number, headingTrue: number | null, p: Projector, label: string): SceneEntity {
  const { x, y } = p.toXY(lat, lon);
  return {
    id: SHIP_ID,
    kind: 'ship-marker',
    label,
    labelAlways: true,
    pose: { x, y, z: 0, headingDeg: sceneHeading(headingTrue ?? 90) },
    geometry: { type: 'point', sizePx: 14 },
    color: '#ffffff',
    selectable: false,
  };
}

/** Pointed-bow hull outline in entity-local meters (+x forward). */
export function hullOutline(lengthM: number): [number, number][] {
  const L = lengthM / 2;
  const B = lengthM / 14;
  return [[-L, -B], [L * 0.6, -B], [L, 0], [L * 0.6, B], [-L, B]];
}

export interface VesselLook {
  lengthM: number | null;
  color: string;
}

export const VESSEL_COLORS = ['#4fc3f7', '#ffb74d', '#81c784', '#ba68c8', '#e57373', '#fff176', '#90a4ae', '#f06292'];

export function vesselEntities(states: TransitVesselState[], p: Projector, looks: Map<string, VesselLook>): SceneEntity[] {
  const out: SceneEntity[] = [];
  for (const v of states) {
    const look = looks.get(v.vessel_id) ?? { lengthM: null, color: '#ffffff' };
    const { x, y } = p.toXY(v.lat, v.lon);
    const known = look.lengthM != null;
    const len = look.lengthM ?? FALLBACK_HULL_M;
    const pose = { x, y, z: 0, headingDeg: sceneHeading(v.heading_true_deg) };
    out.push({
      id: `vessel:${v.vessel_id}`,
      kind: 'vessel',
      label: known ? v.vessel_id : `${v.vessel_id} (fixed glyph, not to scale)`,
      pose,
      geometry: { type: 'polygon', points: hullOutline(len), heightM: 2 },
      color: look.color,
      status: v.status === 'invalid' || v.status === 'stopped_short' ? 'AMBER' : undefined,
      selectable: true,
      props: [
        { label: 'SOG', value: `${v.sog_kt.toFixed(1)} kt` },
        { label: 'Heading', value: `${v.heading_true_deg.toFixed(0)} T` },
        { label: 'Status', value: v.status },
        { label: 'Hull', value: known ? `${len.toFixed(0)} m from ship class` : 'fixed glyph, length unknown' },
      ],
    });
    out.push({
      id: `vessel-dot:${v.vessel_id}`,
      kind: 'vessel-marker',
      label: v.vessel_id,
      labelAlways: true,
      pose,
      geometry: { type: 'point', sizePx: 8 },
      color: look.color,
      selectable: false,
    });
  }
  return out;
}

/** Arrow from the contact point in the direction the tug pushes or pulls the hull. */
export function tugVector(t: TransitTugState, vessel: TransitVesselState, p: Projector): SceneVector {
  const { x, y } = p.toXY(t.lat, t.lon);
  const bearing = (vessel.heading_true_deg + t.direction_rel_deg) % 360;
  return {
    id: `tug:${vessel.vessel_id}:${t.tug_id}`,
    kind: 'tug-force',
    origin: { x, y, z: 1 },
    angleDeg: sceneHeading(bearing),
    lengthM: Math.min(150, Math.max(20, t.force_lbf / 500)),
    label: `${t.tug_id} ${(t.force_lbf / 1000).toFixed(0)} klbf`,
    color: '#ff9800',
  };
}

export function trailLinks(vesselId: string, pts: { lat: number; lon: number }[], p: Projector, color: string): SceneLink[] {
  return polyline(`trail:${vesselId}`, 'trail', pts, p, color, 2, {});
}

/** Great-circle length of a fix list, nautical miles. */
export function pathNm(pts: { lat: number; lon: number }[]): number {
  let m = 0;
  for (let i = 1; i < pts.length; i++) m += haversineM(pts[i - 1], pts[i]);
  return m / 1852;
}

export const feetToMeters = (ft: number) => ft * FT;
