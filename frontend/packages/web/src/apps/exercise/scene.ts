import { bearingTo, circleRing, destination, distanceM, stationFrom } from './geo';
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
  foam: FeatureCollection<Poly>;
  /** Tiny emissive pillars: navigation and deck lights. */
  lights: FeatureCollection<Poly>;
  /** The same lights as points, for a soft glow around them. */
  glows: FeatureCollection<Pt>;
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
  const foam: Feature<Poly>[] = [];
  const lights: Feature<Poly>[] = [];
  const glows: Feature<Pt>[] = [];
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

    for (const slice of shape.slices) {
      hulls.push({
        type: 'Feature',
        properties: { id: unit.id, base: slice.base * s, height: slice.top * s, color: slice.color },
        geometry: { type: 'Polygon', coordinates: [ring(here, st.headingDeg, shape.hull.map(([x, y]): [number, number] => [x * slice.stretch, y * slice.beamScale]), s)] },
      });
    }
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
    foam.push({
      type: 'Feature',
      properties: { id: unit.id, foam: Math.min(1, st.speedKt / 18) },
      geometry: { type: 'Polygon', coordinates: [ring(here, st.headingDeg, shape.hull, s, 1.16)] },
    });
    for (const light of shape.lights) {
      const half = (light.size * s) / 2;
      const at = shipPoint(here, st.headingDeg, light.x * s, light.y * s);
      const corner = (dx: number, dy: number) => shipPoint(here, st.headingDeg, light.x * s + dx, light.y * s + dy);
      lights.push({
        type: 'Feature',
        properties: { id: unit.id, color: light.color, base: (light.height - light.size / 2) * s, height: (light.height + light.size / 2) * s },
        geometry: { type: 'Polygon', coordinates: [[corner(-half, -half), corner(half, -half), corner(half, half), corner(-half, half), corner(-half, -half)]] },
      });
      glows.push({ type: 'Feature', properties: { id: unit.id, color: light.color, sizeM: light.size * s }, geometry: { type: 'Point', coordinates: at } });
    }
    markers.push({
      type: 'Feature',
      properties: {
        id: unit.id,
        name: unit.name,
        info: `${Math.round(st.speedKt)} kt  ${Math.round(st.headingDeg).toString().padStart(3, '0')}°`,
        color: sideColor,
        selected,
        speedKt: Math.round(st.speedKt),
      },
      geometry: { type: 'Point', coordinates: [st.lon, st.lat] },
    });

    if (view.trailS > 0 && st.sogKt > 0.5) {
      const stepS = Math.max(trajectory.dtS, view.trailS / 40);
      const back = trailOf(trajectory, i, timeS, view.trailS, stepS);
      const stern = shipPoint(here, st.headingDeg, (-cls.loaM / 2) * s, 0);
      const line = [stern, ...back.slice(1)];
      if (line.length >= 2) {
        const beam = cls.beamM * s;
        trails.push({
          type: 'Feature',
          properties: { id: unit.id, widthPx0: widthPxAtZoom0(beam * 0.9, st.lat) },
          geometry: { type: 'LineString', coordinates: line },
        });
        // The V of the wake: two arms that open at about 19 degrees and fade like the trail does.
        const arms: [number, number][][] = [[], []];
        let behind = 0;
        line.forEach((pt, k) => {
          if (k > 0) behind += distanceM({ lon: line[k - 1][0], lat: line[k - 1][1] }, { lon: pt[0], lat: pt[1] });
          const next = line[Math.min(k + 1, line.length - 1)];
          const prev = line[Math.max(k - 1, 0)];
          const along = bearingTo({ lon: prev[0], lat: prev[1] }, { lon: next[0], lat: next[1] });
          const spread = beam * 0.45 + behind * 0.28;
          [90, -90].forEach((turn, arm) => {
            const p = destination({ lon: pt[0], lat: pt[1] }, along + turn, spread);
            arms[arm].push([p.lon, p.lat]);
          });
        });
        for (const arm of arms) {
          trails.push({
            type: 'Feature',
            properties: { id: unit.id, widthPx0: widthPxAtZoom0(beam * 0.16, st.lat) },
            geometry: { type: 'LineString', coordinates: arm },
          });
        }
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
    foam: collection(foam),
    lights: collection(lights),
    glows: collection(glows),
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

/** The units within `radiusM` of the one at `anchor` (counting it): the main group, for the opening camera shot. */
export function groupStates(states: UnitState[], anchor = 0, radiusM = 8000): UnitState[] {
  const a = states[anchor];
  if (!a) return [];
  return states.filter((st) => distanceM(a, st) <= radiusM);
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
