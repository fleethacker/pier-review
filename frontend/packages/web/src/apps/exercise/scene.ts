import { circleRing, stationFrom } from './geo';
import { SHIP_CLASSES, SIDE_COLORS, shipShape } from './ships';
import { statesAt, trailOf } from './sim';
import type { Trajectory } from './sim';
import type { LonLat, ScenarioConfig, UnitConfig, UnitState } from './types';

export interface Feature<G> {
  type: 'Feature';
  properties: Record<string, string | number | boolean>;
  geometry: G;
}
export interface FeatureCollection<G> {
  type: 'FeatureCollection';
  features: Feature<G>[];
}
type Pt = { type: 'Point'; coordinates: [number, number] };
type Line = { type: 'LineString'; coordinates: [number, number][] };
type Poly = { type: 'Polygon'; coordinates: [number, number][][] };

const DEG = Math.PI / 180;
/** Width in screen pixels at map zoom 0 of something `meters` wide at `latDeg`; doubles with every zoom level. */
export function widthPxAtZoom0(meters: number, latDeg: number): number {
  return (meters * 512) / (40_075_016.686 * Math.cos(latDeg * DEG));
}

const collection = <G>(features: Feature<G>[]): FeatureCollection<G> => ({ type: 'FeatureCollection', features });

export interface ViewOptions {
  /** Draws ships this many times their size, so they read at overview zoom. */
  shipScale: number;
  /** How far back the wake trail reaches, seconds. 0 turns it off. */
  trailS: number;
  showLabels: boolean;
  showRoutes: boolean;
  /** Sensor ring around the selected unit. */
  showRange: boolean;
}

export const DEFAULT_VIEW: ViewOptions = { shipScale: 3, trailS: 240, showLabels: true, showRoutes: true, showRange: false };

/** Layers that change every frame. */
export interface FrameData {
  hulls: FeatureCollection<Poly>;
  parts: FeatureCollection<Poly>;
  halos: FeatureCollection<Poly>;
  markers: FeatureCollection<Pt>;
  trails: FeatureCollection<Line>;
  overlays: FeatureCollection<Line>;
}

/** Layers that only change when the scenario or the selection does. */
export interface StaticData {
  routes: FeatureCollection<Line>;
  waypoints: FeatureCollection<Pt>;
}

/** A point in a ship's own frame (+x forward, +y to port, meters) to [lon, lat]. */
export function shipPoint(at: LonLat, headingDeg: number, x: number, y: number): [number, number] {
  const p = stationFrom(at, headingDeg, x, -y);
  return [p.lon, p.lat];
}

function ring(at: LonLat, headingDeg: number, pts: [number, number][], scale: number, stretch = 1): [number, number][] {
  const out = pts.map(([x, y]) => shipPoint(at, headingDeg, x * scale * stretch, y * scale * stretch));
  out.push(out[0]);
  return out;
}

export function buildFrameData(
  scenario: ScenarioConfig,
  trajectory: Trajectory,
  timeS: number,
  view: ViewOptions,
  selectedId: string | null,
): FrameData {
  const states = statesAt(trajectory, timeS);
  const hulls: Feature<Poly>[] = [];
  const parts: Feature<Poly>[] = [];
  const halos: Feature<Poly>[] = [];
  const markers: Feature<Pt>[] = [];
  const trails: Feature<Line>[] = [];
  const overlays: Feature<Line>[] = [];
  const s = view.shipScale;

  scenario.units.forEach((unit, i) => {
    const st = states[i];
    const cls = SHIP_CLASSES[unit.classId];
    const shape = shipShape(unit.classId);
    const selected = unit.id === selectedId;
    const sideColor = SIDE_COLORS[unit.side];
    const here = { lon: st.lon, lat: st.lat };

    hulls.push({
      type: 'Feature',
      properties: { id: unit.id, height: cls.freeboardM * s, color: cls.hullColor },
      geometry: { type: 'Polygon', coordinates: [ring(here, st.headingDeg, shape.hull, s)] },
    });
    for (const part of shape.parts) {
      parts.push({
        type: 'Feature',
        properties: { id: unit.id, base: part.base * s, height: part.height * s, color: part.color },
        geometry: { type: 'Polygon', coordinates: [ring(here, st.headingDeg, part.points, s)] },
      });
    }
    halos.push({
      type: 'Feature',
      properties: { id: unit.id, color: sideColor, selected },
      geometry: { type: 'Polygon', coordinates: [ring(here, st.headingDeg, shape.hull, s, 1.35)] },
    });
    markers.push({
      type: 'Feature',
      properties: { id: unit.id, name: unit.name, color: sideColor, selected, speedKt: Math.round(st.speedKt) },
      geometry: { type: 'Point', coordinates: [st.lon, st.lat] },
    });

    if (view.trailS > 0 && st.sogKt > 0.5) {
      const stepS = Math.max(trajectory.dtS, view.trailS / 40);
      const back = trailOf(trajectory, i, timeS, view.trailS, stepS);
      const stern = shipPoint(here, st.headingDeg, (-cls.loaM / 2) * s, 0);
      const line = [stern, ...back.slice(1)];
      if (line.length >= 2) {
        trails.push({
          type: 'Feature',
          properties: { id: unit.id, widthPx0: widthPxAtZoom0(cls.beamM * 0.9 * s, st.lat) },
          geometry: { type: 'LineString', coordinates: line },
        });
      }
    }

    if (selected) {
      overlays.push({
        type: 'Feature',
        properties: { kind: 'selection', color: '#ffffff' },
        geometry: { type: 'LineString', coordinates: circleRing(here, Math.max(cls.loaM * s * 0.8, 120), 64) },
      });
      if (view.showRange) {
        overlays.push({
          type: 'Feature',
          properties: { kind: 'range', color: sideColor },
          geometry: { type: 'LineString', coordinates: circleRing(here, cls.sensorRangeNm * 1852, 128) },
        });
      }
    }
  });

  return {
    hulls: collection(hulls),
    parts: collection(parts),
    halos: collection(halos),
    markers: collection(markers),
    trails: collection(trails),
    overlays: collection(overlays),
  };
}

function routeOf(unit: UnitConfig): { points: LonLat[]; loop: boolean } | null {
  if (unit.behavior.type !== 'route') return null;
  return { points: unit.behavior.waypoints, loop: !!unit.behavior.loop };
}

export function buildStaticData(scenario: ScenarioConfig, view: ViewOptions, selectedId: string | null): StaticData {
  const routes: Feature<Line>[] = [];
  const waypoints: Feature<Pt>[] = [];
  if (view.showRoutes) {
    for (const unit of scenario.units) {
      const route = routeOf(unit);
      if (!route) continue;
      const color = SIDE_COLORS[unit.side];
      const selected = unit.id === selectedId;
      const coords = [[unit.start.lon, unit.start.lat], ...route.points.map((p): [number, number] => [p.lon, p.lat])] as [number, number][];
      if (route.loop && route.points.length > 1) coords.push([route.points[0].lon, route.points[0].lat]);
      routes.push({
        type: 'Feature',
        properties: { id: unit.id, color, selected },
        geometry: { type: 'LineString', coordinates: coords },
      });
      route.points.forEach((p, n) => {
        waypoints.push({
          type: 'Feature',
          properties: { id: unit.id, index: n + 1, color, selected },
          geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
        });
      });
    }
  }
  return { routes: collection(routes), waypoints: collection(waypoints) };
}

/** Everything the camera needs to frame all units at one instant. */
export function boundsOf(states: UnitState[]): [[number, number], [number, number]] | null {
  if (!states.length) return null;
  let w = Infinity;
  let s = Infinity;
  let e = -Infinity;
  let n = -Infinity;
  for (const st of states) {
    w = Math.min(w, st.lon);
    e = Math.max(e, st.lon);
    s = Math.min(s, st.lat);
    n = Math.max(n, st.lat);
  }
  return [
    [w, s],
    [e, n],
  ];
}
