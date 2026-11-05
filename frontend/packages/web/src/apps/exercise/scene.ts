import { bearingTo, circleRing, destination, distanceM, stationFrom } from './geo';
import { SHIP_CLASSES, SIDE_COLORS, isMine, isMissile, mix, shipShape } from './ships';
import { statesAt, trailOf, unitHp as unitMaxHp } from './sim';
import type { EventType, Trajectory } from './sim';
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
  /** Flashes where things were hit, shot down or launched, and fires on wrecks. */
  bursts: FeatureCollection<Pt>;
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

/** How long each kind of event flashes for, in simulated seconds, and how big the flash gets, meters. */
const BURST: Partial<Record<EventType, { seconds: number; radiusM: number; color: string }>> = {
  hit: { seconds: 25, radiusM: 260, color: '#ff7a1a' },
  mine: { seconds: 25, radiusM: 300, color: '#ff8a2a' },
  destroyed: { seconds: 60, radiusM: 520, color: '#ff3b1a' },
  intercept: { seconds: 15, radiusM: 170, color: '#bfe6ff' },
  launch: { seconds: 12, radiusM: 90, color: '#ffd24a' },
  miss: { seconds: 12, radiusM: 110, color: '#9aa7b3' },
};

const WRECK = '#101214';

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
  const bursts: Feature<Pt>[] = [];
  const markers: Feature<Pt>[] = [];
  const trails: Feature<Line>[] = [];
  const overlays: Feature<Line>[] = [];
  const byId = new Map(scenario.units.map((u, i) => [u.id, i]));

  scenario.units.forEach((unit, i) => {
    const st = states[i];
    if (!st.active) return;
    const cls = SHIP_CLASSES[unit.classId];
    const weapon = !!cls.weapon;
    const air = cls.domain === 'air';
    const dead = st.hp <= 0;
    const s = view.shipScale * cls.visualBoost;
    const alt = air ? Math.max(0, st.altM) : 0;
    const shape = shipShape(unit.classId);
    const selected = unit.id === selectedId;
    const sideColor = SIDE_COLORS[unit.side];
    const here = { lon: st.lon, lat: st.lat };
    const shade = (c: string) => (dead ? mix(c, WRECK, 0.7) : c);

    for (const slice of shape.slices) {
      hulls.push({
        type: 'Feature',
        properties: { id: unit.id, base: alt + slice.base * s, height: alt + slice.top * s, color: shade(slice.color) },
        geometry: { type: 'Polygon', coordinates: [ring(here, st.headingDeg, shape.hull.map(([x, y]): [number, number] => [x * slice.stretch, y * slice.beamScale]), s)] },
      });
    }
    for (const part of shape.parts) {
      parts.push({
        type: 'Feature',
        properties: { id: unit.id, base: alt + part.base * s, height: alt + part.height * s, color: shade(part.color) },
        geometry: { type: 'Polygon', coordinates: [ring(here, st.headingDeg, part.points, s)] },
      });
    }
    halos.push({
      type: 'Feature',
      properties: { id: unit.id, color: dead ? '#6b7178' : sideColor, selected },
      geometry: { type: 'Polygon', coordinates: [ring(here, st.headingDeg, shape.hull, s, 1.35)] },
    });
    if (cls.domain === 'surface' && !dead) {
      foam.push({
        type: 'Feature',
        properties: { id: unit.id, foam: Math.min(1, st.speedKt / 18) },
        geometry: { type: 'Polygon', coordinates: [ring(here, st.headingDeg, shape.hull, s, 1.16)] },
      });
    }
    if (!dead) {
      for (const light of shape.lights) {
        const half = (light.size * s) / 2;
        const at = shipPoint(here, st.headingDeg, light.x * s, light.y * s);
        const corner = (dx: number, dy: number) => shipPoint(here, st.headingDeg, light.x * s + dx, light.y * s + dy);
        lights.push({
          type: 'Feature',
          properties: { id: unit.id, color: light.color, base: alt + (light.height - light.size / 2) * s, height: alt + (light.height + light.size / 2) * s },
          geometry: { type: 'Polygon', coordinates: [[corner(-half, -half), corner(half, -half), corner(half, half), corner(-half, half), corner(-half, -half)]] },
        });
        glows.push({
          type: 'Feature',
          properties: { id: unit.id, color: light.color, sizeM: light.size * s, minGlow: light.alwaysGlow ? 0.9 : 0 },
          geometry: { type: 'Point', coordinates: at },
        });
      }
    } else {
      // A burning wreck: a flickering fire where it floats.
      const flicker = 0.55 + 0.25 * Math.sin(timeS * 0.9 + i * 1.7);
      bursts.push({
        type: 'Feature',
        properties: { color: '#ff6a1a', sizeM: Math.max(14, cls.loaM * 0.12 * view.shipScale), opacity: flicker },
        geometry: { type: 'Point', coordinates: [st.lon, st.lat] },
      });
    }

    const hpPct = Math.round((st.hp / unitMaxHp(unit)) * 100);
    const infoParts = dead
      ? ['DESTROYED']
      : [
          `${Math.round(st.speedKt)} kt  ${Math.round(st.headingDeg).toString().padStart(3, '0')}°`,
          ...(air && !weapon ? [`${Math.round(st.altM).toLocaleString('en-US')} m`] : []),
          ...(hpPct < 100 ? [`${hpPct}%`] : []),
        ];
    markers.push({
      type: 'Feature',
      properties: {
        id: unit.id,
        // Missiles and mines are numerous and short-lived: they are named only when selected.
        name: weapon && !selected ? '' : unit.name,
        info: weapon && !selected ? '' : infoParts.join('  '),
        color: dead ? '#8a9199' : sideColor,
        selected,
        r: weapon ? 3.5 : 6,
        speedKt: Math.round(st.speedKt),
      },
      geometry: { type: 'Point', coordinates: [st.lon, st.lat] },
    });

    if (view.trailS > 0 && cls.trailScale > 0 && st.sogKt > 0.5) {
      const trailS = weapon ? Math.min(view.trailS, 30) : air ? Math.min(view.trailS, 90) : view.trailS;
      const stepS = Math.max(trajectory.dtS, trailS / 40);
      const back = trailOf(trajectory, i, timeS, trailS, stepS);
      const stern = shipPoint(here, st.headingDeg, (-cls.loaM / 2) * s, 0);
      const line = [stern, ...back.slice(1)];
      if (line.length >= 2) {
        const beam = cls.beamM * s * cls.trailScale;
        trails.push({
          type: 'Feature',
          properties: { id: unit.id, widthPx0: widthPxAtZoom0(beam * 0.9, st.lat) },
          geometry: { type: 'LineString', coordinates: line },
        });
        if (cls.domain === 'surface') {
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
    }

    if (isMissile(cls) && view.showRoutes && unit.behavior.type === 'strike') {
      const ti = byId.get(unit.behavior.targetId);
      const tgt = ti === undefined ? undefined : states[ti];
      if (tgt?.active) {
        overlays.push({
          type: 'Feature',
          properties: { kind: 'strike', color: sideColor },
          geometry: { type: 'LineString', coordinates: [[st.lon, st.lat], [tgt.lon, tgt.lat]] },
        });
      }
    }
    if (isMine(cls) && view.showRoutes) {
      overlays.push({
        type: 'Feature',
        properties: { kind: 'danger', color: sideColor },
        geometry: { type: 'LineString', coordinates: circleRing(here, cls.weapon!.fuzeM, 24) },
      });
    }

    if (selected) {
      overlays.push({
        type: 'Feature',
        properties: { kind: 'selection', color: '#ffffff' },
        geometry: { type: 'LineString', coordinates: circleRing(here, Math.max(cls.loaM * s * 0.8, 120), 64) },
      });
      if (view.showRange && cls.sensorRangeNm > 0) {
        overlays.push({
          type: 'Feature',
          properties: { kind: 'range', color: sideColor },
          geometry: { type: 'LineString', coordinates: circleRing(here, cls.sensorRangeNm * 1852, 128) },
        });
      }
      if (cls.defence && view.showRange) {
        overlays.push({
          type: 'Feature',
          properties: { kind: 'defence', color: '#7ad7ff' },
          geometry: { type: 'LineString', coordinates: circleRing(here, cls.defence.rangeM, 96) },
        });
      }
    }
  });

  // Flashes from events that have just happened.
  const flashScale = Math.max(1, view.shipScale / 3);
  for (const e of trajectory.events) {
    const spec = BURST[e.type];
    if (!spec || e.tS > timeS) continue;
    const age = timeS - e.tS;
    if (age >= spec.seconds) continue;
    const p = age / spec.seconds;
    bursts.push({
      type: 'Feature',
      properties: { color: spec.color, sizeM: (spec.radiusM * flashScale * (0.3 + 2.2 * p)) / 4, opacity: 0.9 * (1 - p) ** 1.5 },
      geometry: { type: 'Point', coordinates: [e.lon, e.lat] },
    });
  }

  return {
    hulls: collection(hulls),
    parts: collection(parts),
    halos: collection(halos),
    foam: collection(foam),
    lights: collection(lights),
    glows: collection(glows),
    bursts: collection(bursts),
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
  if (!a?.active) return [];
  return states.filter((st) => st.active && distanceM(a, st) <= radiusM);
}

/** Everything the camera needs to frame all units at one instant. */
export function boundsOf(all: UnitState[]): [[number, number], [number, number]] | null {
  const states = all.filter((st) => st.active);
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
