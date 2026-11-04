import {
  EARTH_RADIUS_M,
  angleDiff,
  bearingTo,
  distanceM,
  ktToMs,
  msToKt,
  normalizeBearing,
  stationFrom,
  velocityEN,
} from './geo';
import { SHIP_CLASSES } from './ships';
import type { ScenarioConfig, UnitConfig, UnitState } from './types';

const DEG = Math.PI / 180;
const MAX_STEPS = 21_600;
const STRIDE = 6;
export const MIN_DURATION_S = 60;
export const MAX_DURATION_S = 24 * 3600;

/** The whole run, precomputed at a fixed step so playback can scrub, rewind and change rate for free. */
export interface Trajectory {
  dtS: number;
  /** Samples per unit; sample i is at time i * dtS. */
  count: number;
  unitIds: string[];
  /** Packed [lon, lat, headingDeg, speedKt, cogDeg, sogKt] per unit per sample. */
  data: Float64Array;
}

/** Everything wrong with a scenario that would make it impossible to run. Empty means it runs. */
export function validateScenario(s: ScenarioConfig): string[] {
  const errors: string[] = [];
  if (!Number.isFinite(s.durationS) || s.durationS < MIN_DURATION_S || s.durationS > MAX_DURATION_S) {
    errors.push(`Duration must be between ${MIN_DURATION_S} s and 24 h.`);
  }
  const ids = new Set<string>();
  for (const u of s.units) {
    if (ids.has(u.id)) errors.push(`Two units share the id "${u.id}".`);
    ids.add(u.id);
  }
  const byId = new Map(s.units.map((u) => [u.id, u]));
  for (const u of s.units) {
    const label = u.name || u.id;
    if (!SHIP_CLASSES[u.classId]) errors.push(`${label}: unknown ship class "${u.classId}".`);
    if (u.maxTurnRateDegPerS !== undefined && !(u.maxTurnRateDegPerS > 0)) {
      errors.push(`${label}: the turn rate limit must be above zero.`);
    }
    if (![u.start.lon, u.start.lat, u.headingDeg, u.speedKt].every(Number.isFinite)) {
      errors.push(`${label}: start position, heading and speed must be numbers.`);
    } else if (Math.abs(u.start.lat) > 85 || Math.abs(u.start.lon) > 180) {
      errors.push(`${label}: start position is out of range (latitude within 85°, longitude within 180°).`);
    }
    const b = u.behavior;
    if (b.type === 'route') {
      if (b.waypoints.length === 0) errors.push(`${label}: a route needs at least one waypoint.`);
      if (b.waypoints.some((w) => !Number.isFinite(w.lon) || !Number.isFinite(w.lat))) {
        errors.push(`${label}: waypoints must have numeric positions.`);
      }
    } else if (b.type === 'escort') {
      if (b.leaderId === u.id) errors.push(`${label}: cannot escort itself.`);
      else if (!byId.has(b.leaderId)) errors.push(`${label}: leader "${b.leaderId}" does not exist.`);
      else if (escortCycle(u, byId)) errors.push(`${label}: escort chain loops back on itself.`);
    } else if (b.type === 'pursue') {
      if (b.targetId === u.id) errors.push(`${label}: cannot pursue itself.`);
      else if (!byId.has(b.targetId)) errors.push(`${label}: target "${b.targetId}" does not exist.`);
    }
  }
  return errors;
}

function escortCycle(start: UnitConfig, byId: Map<string, UnitConfig>): boolean {
  const seen = new Set<string>([start.id]);
  let cur: UnitConfig | undefined = start;
  while (cur && cur.behavior.type === 'escort') {
    cur = byId.get(cur.behavior.leaderId);
    if (!cur) return false;
    if (seen.has(cur.id)) return true;
    seen.add(cur.id);
  }
  return false;
}

interface Runtime {
  cfg: UnitConfig;
  state: UnitState;
  wp: number;
}

export function stepSizeS(durationS: number): number {
  return Math.max(1, Math.ceil(durationS / MAX_STEPS));
}

/** Run the scenario to the end. Throws if it does not validate. */
export function runScenario(scenario: ScenarioConfig): Trajectory {
  const errors = validateScenario(scenario);
  if (errors.length) throw new Error(errors[0]);

  const dtS = stepSizeS(scenario.durationS);
  const count = Math.floor(scenario.durationS / dtS) + 1;
  const n = scenario.units.length;
  const data = new Float64Array(count * n * STRIDE);
  const env = scenario.environment;
  const current = velocityEN(env.currentToDeg, ktToMs(env.currentKt));

  const runtimes: Runtime[] = scenario.units.map((cfg) => {
    const cls = SHIP_CLASSES[cfg.classId];
    const speedKt = Math.min(Math.max(cfg.speedKt, 0), cls.maxSpeedKt);
    return {
      cfg,
      wp: 0,
      state: {
        lon: cfg.start.lon,
        lat: cfg.start.lat,
        headingDeg: normalizeBearing(cfg.headingDeg),
        speedKt,
        cogDeg: normalizeBearing(cfg.headingDeg),
        sogKt: speedKt,
      },
    };
  });
  const byId = new Map(runtimes.map((r) => [r.cfg.id, r]));

  const record = (i: number) => {
    runtimes.forEach((r, u) => {
      const o = (i * n + u) * STRIDE;
      const s = r.state;
      data[o] = s.lon;
      data[o + 1] = s.lat;
      data[o + 2] = s.headingDeg;
      data[o + 3] = s.speedKt;
      data[o + 4] = s.cogDeg;
      data[o + 5] = s.sogKt;
    });
  };

  record(0);
  for (let i = 1; i < count; i++) {
    for (const r of runtimes) advance(r, byId, dtS, env.windFromDeg, env.windKt, current);
    record(i);
  }
  return { dtS, count, unitIds: scenario.units.map((u) => u.id), data };
}

function advance(
  r: Runtime,
  byId: Map<string, Runtime>,
  dt: number,
  windFromDeg: number,
  windKt: number,
  current: [number, number],
): void {
  const cls = SHIP_CLASSES[r.cfg.classId];
  const s = r.state;
  const cruiseKt = Math.min(r.cfg.speedKt, cls.maxSpeedKt);
  const turnRateDegPerS = Math.min(cls.turnRateDegPerS, r.cfg.maxTurnRateDegPerS ?? Infinity);
  let wantHeading = s.headingDeg;
  let wantSpeed = 0;

  const b = r.cfg.behavior;
  if (b.type === 'route') {
    const turnRadius = ktToMs(s.speedKt) / Math.max(turnRateDegPerS * DEG, 1e-6);
    const capture = Math.max(150, turnRadius);
    for (let n = 0; n < b.waypoints.length && r.wp < b.waypoints.length && distanceM(s, b.waypoints[r.wp]) < capture; n++) {
      r.wp = b.loop && r.wp === b.waypoints.length - 1 ? 0 : r.wp + 1;
    }
    const target = b.waypoints[r.wp];
    if (target) {
      wantHeading = bearingTo(s, target);
      wantSpeed = Math.min(target.speedKt ?? cruiseKt, cls.maxSpeedKt);
    }
  } else if (b.type === 'escort') {
    const leader = byId.get(b.leaderId)!.state;
    const station = stationFrom(leader, leader.headingDeg, b.aheadM, b.abeamM);
    const d = distanceM(s, station);
    const toStation = bearingTo(s, station);
    if (d > 600) {
      wantHeading = toStation;
      wantSpeed = cls.maxSpeedKt;
    } else {
      const lead = angleDiff(toStation, leader.headingDeg);
      const correction = Math.max(-75, Math.min(75, lead * Math.min(1, d / 250)));
      wantHeading = leader.headingDeg + correction;
      const along = d * Math.cos(lead * DEG);
      wantSpeed = Math.max(0, Math.min(cls.maxSpeedKt, leader.speedKt + along * 0.04));
    }
  } else if (b.type === 'pursue') {
    const target = byId.get(b.targetId)!.state;
    if (distanceM(s, target) > b.standoffM) {
      wantHeading = bearingTo(s, target);
      wantSpeed = cruiseKt;
    } else {
      wantHeading = target.headingDeg;
      wantSpeed = Math.min(target.speedKt, cls.maxSpeedKt);
    }
  }

  const accel = (wantSpeed >= s.speedKt ? cls.accelKtPerS : cls.accelKtPerS * 1.5) * dt;
  s.speedKt = Math.min(cls.maxSpeedKt, Math.max(0, s.speedKt + Math.max(-accel, Math.min(accel, wantSpeed - s.speedKt))));

  const turn = turnRateDegPerS * (0.3 + 0.7 * Math.min(1, s.speedKt / 10)) * dt;
  s.headingDeg = normalizeBearing(s.headingDeg + Math.max(-turn, Math.min(turn, angleDiff(wantHeading, s.headingDeg))));

  const [ve, vn] = velocityEN(s.headingDeg, ktToMs(s.speedKt));
  const [le, ln] = velocityEN(windFromDeg + 180, ktToMs(windKt * cls.windage));
  const east = ve + current[0] + le;
  const north = vn + current[1] + ln;
  s.lat += ((north * dt) / EARTH_RADIUS_M) / DEG;
  s.lon += ((east * dt) / (EARTH_RADIUS_M * Math.cos(s.lat * DEG))) / DEG;
  s.sogKt = msToKt(Math.hypot(east, north));
  s.cogDeg = s.sogKt > 0.01 ? normalizeBearing(Math.atan2(east, north) / DEG) : s.headingDeg;
}

function readSample(t: Trajectory, i: number, u: number): UnitState {
  const o = (i * t.unitIds.length + u) * STRIDE;
  const d = t.data;
  return { lon: d[o], lat: d[o + 1], headingDeg: d[o + 2], speedKt: d[o + 3], cogDeg: d[o + 4], sogKt: d[o + 5] };
}

function lerp(a: number, b: number, f: number): number {
  return a + (b - a) * f;
}

function lerpAngle(a: number, b: number, f: number): number {
  return normalizeBearing(a + angleDiff(b, a) * f);
}

export function unitStateAt(t: Trajectory, unitIndex: number, timeS: number): UnitState {
  const x = Math.min(Math.max(timeS / t.dtS, 0), t.count - 1);
  const i0 = Math.floor(x);
  const i1 = Math.min(i0 + 1, t.count - 1);
  const f = x - i0;
  const a = readSample(t, i0, unitIndex);
  if (f === 0 || i0 === i1) return a;
  const b = readSample(t, i1, unitIndex);
  return {
    lon: lerp(a.lon, b.lon, f),
    lat: lerp(a.lat, b.lat, f),
    headingDeg: lerpAngle(a.headingDeg, b.headingDeg, f),
    speedKt: lerp(a.speedKt, b.speedKt, f),
    cogDeg: lerpAngle(a.cogDeg, b.cogDeg, f),
    sogKt: lerp(a.sogKt, b.sogKt, f),
  };
}

/** Every unit at `timeS`, in scenario order. */
export function statesAt(t: Trajectory, timeS: number): UnitState[] {
  return t.unitIds.map((_, u) => unitStateAt(t, u, timeS));
}

/** Where a unit has been: positions at `timeS` and then every `stepS` back, newest first, stopping at the start. */
export function trailOf(t: Trajectory, unitIndex: number, timeS: number, lengthS: number, stepS: number): [number, number][] {
  const pts: [number, number][] = [];
  for (let back = 0; back <= lengthS; back += stepS) {
    const at = timeS - back;
    if (at < 0) break;
    const s = unitStateAt(t, unitIndex, at);
    pts.push([s.lon, s.lat]);
  }
  return pts;
}
