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
import { SHIP_CLASSES, isMine, isMissile } from './ships';
import type { ShipClass } from './ships';
import type { LonLat, ScenarioConfig, UnitConfig, UnitState } from './types';

const DEG = Math.PI / 180;
const MAX_STEPS = 21_600;
const STRIDE = 9;
const LOITER_RADIUS_M = 4000;
/** Missiles aim ahead of a moving target by at most this many seconds of its travel. */
const MAX_LEAD_S = 60;
export const MIN_DURATION_S = 60;
export const MAX_DURATION_S = 24 * 3600;
export const DEFAULT_SEED = 1;

/** Small seeded random number generator (mulberry32). The same seed always gives the same numbers. */
export function makeRng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export type EventType =
  /** A missile was fired or an aircraft launched. `unitId` is the new unit, `otherId` the launcher. */
  | 'launch'
  /** A launch did not happen because the launcher was already destroyed. */
  | 'aborted'
  /** A missile reached its target and did damage. `unitId` is the missile, `otherId` the target. */
  | 'hit'
  /** A missile was shot down. `unitId` is the missile, `otherId` the ship that shot it down. */
  | 'intercept'
  /** A missile was spent without doing damage: it failed to detonate, ran out of fuel or lost its target. */
  | 'miss'
  /** A mine went off on a ship. `unitId` is the mine, `otherId` the ship. */
  | 'mine'
  /** A unit's hit points reached zero. `otherId` is what did it. */
  | 'destroyed';

export interface SimEvent {
  tS: number;
  type: EventType;
  unitId: string;
  otherId?: string;
  lon: number;
  lat: number;
  /** Hit points the unit hit had left. */
  hpAfter?: number;
  detail?: string;
}

/** The whole run, precomputed at a fixed step so playback can scrub, rewind and change rate for free. */
export interface Trajectory {
  dtS: number;
  /** Samples per unit; sample i is at time i * dtS. */
  count: number;
  unitIds: string[];
  /** Packed [lon, lat, headingDeg, speedKt, cogDeg, sogKt, altM, hp, active] per unit per sample. */
  data: Float64Array;
  events: SimEvent[];
}

export interface RunOptions {
  /** Seeds the chance rolls. Defaults to the scenario's `seed`, then to 1. */
  seed?: number;
}

export const unitHp = (u: UnitConfig): number => u.hp ?? SHIP_CLASSES[u.classId].hp;
export const unitDamage = (u: UnitConfig): number => u.damage ?? SHIP_CLASSES[u.classId].weapon?.damage ?? 0;
export const unitPHit = (u: UnitConfig): number => u.pHit ?? SHIP_CLASSES[u.classId].weapon?.pHit ?? 0;
export const unitPKill = (u: UnitConfig): number => u.pKill ?? SHIP_CLASSES[u.classId].defence?.pKill ?? 0;
export const unitMagazine = (u: UnitConfig): number => u.magazine ?? SHIP_CLASSES[u.classId].defence?.magazine ?? 0;
export function unitAltitude(u: UnitConfig): number {
  const cls = SHIP_CLASSES[u.classId];
  if (cls.domain === 'static') return -20;
  if (cls.domain === 'air') return u.altitudeM ?? cls.cruiseAltM ?? 0;
  return 0;
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
    const cls = SHIP_CLASSES[u.classId];
    if (!cls) {
      errors.push(`${label}: unknown unit class "${u.classId}".`);
      continue;
    }
    if (u.maxTurnRateDegPerS !== undefined && !(u.maxTurnRateDegPerS > 0)) {
      errors.push(`${label}: the turn rate limit must be above zero.`);
    }
    if (![u.start.lon, u.start.lat, u.headingDeg, u.speedKt].every(Number.isFinite)) {
      errors.push(`${label}: start position, heading and speed must be numbers.`);
    } else if (Math.abs(u.start.lat) > 85 || Math.abs(u.start.lon) > 180) {
      errors.push(`${label}: start position is out of range (latitude within 85°, longitude within 180°).`);
    }
    if (u.altitudeM !== undefined && !(Number.isFinite(u.altitudeM) && u.altitudeM >= 0)) {
      errors.push(`${label}: altitude must be zero or more.`);
    }
    if (u.hp !== undefined && !(u.hp > 0)) errors.push(`${label}: hit points must be above zero.`);
    if (u.damage !== undefined && !(u.damage >= 0)) errors.push(`${label}: damage cannot be negative.`);
    for (const [name, v] of [['hit chance', u.pHit], ['defence kill chance', u.pKill]] as const) {
      if (v !== undefined && !(v >= 0 && v <= 1)) errors.push(`${label}: ${name} must be between 0 and 1.`);
    }
    if (u.magazine !== undefined && !(u.magazine >= 0)) errors.push(`${label}: magazine cannot be negative.`);
    if (u.launch) {
      if (u.launch.byId === u.id) errors.push(`${label}: cannot launch itself.`);
      else if (!byId.has(u.launch.byId)) errors.push(`${label}: launcher "${u.launch.byId}" does not exist.`);
      if (!(Number.isFinite(u.launch.atS) && u.launch.atS >= 0)) errors.push(`${label}: launch time must be zero or more.`);
    }
    const b = u.behavior;
    if (b.type === 'route') {
      if (b.waypoints.length === 0) errors.push(`${label}: a route needs at least one waypoint.`);
      if (b.waypoints.some((w) => !Number.isFinite(w.lon) || !Number.isFinite(w.lat))) {
        errors.push(`${label}: waypoints must have numeric positions.`);
      }
      if (b.waypoints.some((w) => w.altitudeM !== undefined && !(Number.isFinite(w.altitudeM) && w.altitudeM >= 0))) {
        errors.push(`${label}: waypoint altitudes must be zero or more.`);
      }
    } else if (b.type === 'escort') {
      if (b.leaderId === u.id) errors.push(`${label}: cannot escort itself.`);
      else if (!byId.has(b.leaderId)) errors.push(`${label}: leader "${b.leaderId}" does not exist.`);
      else if (escortCycle(u, byId)) errors.push(`${label}: escort chain loops back on itself.`);
    } else if (b.type === 'pursue') {
      if (b.targetId === u.id) errors.push(`${label}: cannot pursue itself.`);
      else if (!byId.has(b.targetId)) errors.push(`${label}: target "${b.targetId}" does not exist.`);
    } else if (b.type === 'loiter') {
      if (cls.domain !== 'air') errors.push(`${label}: only aircraft can loiter.`);
      if (![b.center.lon, b.center.lat].every(Number.isFinite) || !(b.radiusM > 0)) {
        errors.push(`${label}: a loiter needs a center and a radius above zero.`);
      }
    } else if (b.type === 'strike') {
      if (!isMissile(cls)) errors.push(`${label}: only missiles can strike.`);
      if (b.targetId === u.id) errors.push(`${label}: cannot strike itself.`);
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

interface Point3 {
  lon: number;
  lat: number;
  altM: number;
}

interface Runtime {
  cfg: UnitConfig;
  cls: ShipClass;
  state: UnitState;
  maxHp: number;
  wp: number;
  /** Has been active at some point (so being inactive now means it is spent, not waiting). */
  everActive: boolean;
  cancelled: boolean;
  prev: Point3;
  traveledM: number;
  magazine: number;
  readyAtS: number;
  /** Shots this ship has fired at each missile. */
  attempts: Map<string, number>;
  /** Ships this mine has already been close to. */
  checked: Set<string>;
  /** The last altitude an aircraft was told to head for, held until it is told another. */
  cmdAlt?: number;
  /** Appeared this step: it stays where it was launched until the next one. */
  justSpawned: boolean;
}

export function stepSizeS(durationS: number): number {
  return Math.max(1, Math.ceil(durationS / MAX_STEPS));
}

/** Where two things come closest during a step, each moving in a straight line, in 3D. Returns the distance and how far through the step it was. */
export function closestApproachM(a0: Point3, a1: Point3, b0: Point3, b1: Point3): { dist: number; s: number } {
  const kx = EARTH_RADIUS_M * DEG * Math.cos(a0.lat * DEG);
  const ky = EARTH_RADIUS_M * DEG;
  const rel = (a: Point3, b: Point3): [number, number, number] => [(a.lon - b.lon) * kx, (a.lat - b.lat) * ky, a.altM - b.altM];
  const r0 = rel(a0, b0);
  const r1 = rel(a1, b1);
  const dv: [number, number, number] = [r1[0] - r0[0], r1[1] - r0[1], r1[2] - r0[2]];
  const denom = dv[0] * dv[0] + dv[1] * dv[1] + dv[2] * dv[2];
  const s = denom < 1e-9 ? 0 : Math.min(1, Math.max(0, -(r0[0] * dv[0] + r0[1] * dv[1] + r0[2] * dv[2]) / denom));
  const p: [number, number, number] = [r0[0] + dv[0] * s, r0[1] + dv[1] * s, r0[2] + dv[2] * s];
  return { dist: Math.hypot(p[0], p[1], p[2]), s };
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

interface Guidance {
  heading: number;
  speed: number;
  /** Altitude to head for. Aircraft default to their cruise altitude. */
  alt?: number;
  /** The unit has no reason to go on (a missile whose target is gone). */
  expire?: string;
}

function loiterGuide(s: UnitState, center: LonLat, radiusM: number, speed: number): Guidance {
  const dist = distanceM(s, center);
  if (dist > radiusM * 2.5) return { heading: bearingTo(s, center), speed };
  const fromCenter = bearingTo(center, s);
  const err = dist - radiusM;
  return { heading: normalizeBearing(fromCenter + 90 + clamp((err / radiusM) * 60, -45, 45)), speed };
}

/** Run the scenario to the end. Throws if it does not validate. */
export function runScenario(scenario: ScenarioConfig, options: RunOptions = {}): Trajectory {
  const errors = validateScenario(scenario);
  if (errors.length) throw new Error(errors[0]);

  const rng = makeRng(options.seed ?? scenario.seed ?? DEFAULT_SEED);
  const dtS = stepSizeS(scenario.durationS);
  const count = Math.floor(scenario.durationS / dtS) + 1;
  const n = scenario.units.length;
  const data = new Float64Array(count * n * STRIDE);
  const env = scenario.environment;
  const current = velocityEN(env.currentToDeg, ktToMs(env.currentKt));
  const events: SimEvent[] = [];

  const runtimes: Runtime[] = scenario.units.map((cfg) => {
    const cls = SHIP_CLASSES[cfg.classId];
    const minSpeed = cls.minSpeedKt ?? 0;
    const speedKt = cls.domain === 'static' ? 0 : clamp(cfg.speedKt, minSpeed, cls.maxSpeedKt);
    const waiting = !!cfg.launch;
    const absent = !!cfg.disabled;
    const altM = unitAltitude(cfg);
    return {
      cfg,
      cls,
      maxHp: unitHp(cfg),
      wp: 0,
      everActive: !waiting && !absent,
      cancelled: absent,
      prev: { lon: cfg.start.lon, lat: cfg.start.lat, altM },
      traveledM: 0,
      magazine: unitMagazine(cfg),
      readyAtS: 0,
      attempts: new Map(),
      checked: new Set(),
      justSpawned: false,
      state: {
        lon: cfg.start.lon,
        lat: cfg.start.lat,
        headingDeg: normalizeBearing(cfg.headingDeg),
        speedKt,
        cogDeg: normalizeBearing(cfg.headingDeg),
        sogKt: speedKt,
        altM,
        hp: unitHp(cfg),
        active: !waiting && !absent,
      },
    };
  });
  const byId = new Map(runtimes.map((r) => [r.cfg.id, r]));

  const here = (r: Runtime) => ({ lon: r.state.lon, lat: r.state.lat });
  const emit = (tS: number, type: EventType, unit: Runtime, other: Runtime | undefined, at: LonLat, extra: Partial<SimEvent> = {}) =>
    events.push({ tS, type, unitId: unit.cfg.id, otherId: other?.cfg.id, lon: at.lon, lat: at.lat, ...extra });

  const isGone = (r: Runtime) => r.cancelled || (r.everActive && !r.state.active) || r.state.hp <= 0;

  const spend = (r: Runtime) => {
    r.state.active = false;
    r.state.speedKt = 0;
    r.state.sogKt = 0;
  };

  /** Apply damage, report it, and remove a destroyed aircraft (ships stay where they are, dead in the water). */
  const damage = (tgt: Runtime, dmg: number, by: Runtime, t: number, at: LonLat, type: 'hit' | 'mine') => {
    const before = tgt.state.hp;
    tgt.state.hp = Math.max(0, before - dmg);
    emit(t, type, by, tgt, at, { hpAfter: tgt.state.hp });
    if (before > 0 && tgt.state.hp <= 0) {
      emit(t, 'destroyed', tgt, by, at);
      if (tgt.cls.domain !== 'surface') spend(tgt);
    }
  };

  const spawnDue = (t: number) => {
    for (const r of runtimes) {
      const launch = r.cfg.launch;
      if (!launch || r.everActive || r.cancelled || t < launch.atS) continue;
      const by = byId.get(launch.byId)!;
      if (isGone(by)) {
        r.cancelled = true;
        emit(t, 'aborted', r, by, here(by));
        continue;
      }
      if (!by.state.active) continue; // the launcher has not appeared yet; wait for it
      const target = r.cfg.behavior.type === 'strike' ? byId.get(r.cfg.behavior.targetId) : undefined;
      const s = r.state;
      s.lon = by.state.lon;
      s.lat = by.state.lat;
      s.headingDeg = target ? bearingTo(by.state, target.state) : by.state.headingDeg;
      s.speedKt = r.cls.weapon ? r.cls.maxSpeedKt * 0.5 : clamp(r.cfg.speedKt, r.cls.minSpeedKt ?? 0, r.cls.maxSpeedKt);
      s.sogKt = s.speedKt;
      s.cogDeg = s.headingDeg;
      s.altM = r.cls.weapon ? Math.max(by.state.altM, r.cls.cruiseAltM ?? 20) : unitAltitude(r.cfg);
      s.active = true;
      r.everActive = true;
      r.justSpawned = true;
      emit(t, 'launch', r, by, here(by));
    }
  };

  const guide = (r: Runtime, turnRate: number, cruiseKt: number): Guidance => {
    const { cls, state: s, cfg } = r;
    const air = cls.domain === 'air';
    const b = cfg.behavior;
    switch (b.type) {
      case 'route': {
        const capture = Math.max(air ? 300 : 150, ktToMs(s.speedKt) / Math.max(turnRate * DEG, 1e-6));
        for (let k = 0; k < b.waypoints.length && r.wp < b.waypoints.length && distanceM(s, b.waypoints[r.wp]) < capture; k++) {
          r.wp = b.loop && r.wp === b.waypoints.length - 1 ? 0 : r.wp + 1;
        }
        const target = b.waypoints[r.wp];
        if (target) return { heading: bearingTo(s, target), speed: target.speedKt ?? cruiseKt, alt: target.altitudeM };
        if (air && !cls.canHover) return loiterGuide(s, b.waypoints[b.waypoints.length - 1], LOITER_RADIUS_M, cruiseKt);
        return { heading: s.headingDeg, speed: 0 };
      }
      case 'loiter':
        return loiterGuide(s, b.center, b.radiusM, cruiseKt);
      case 'escort': {
        const leader = byId.get(b.leaderId)!.state;
        const station = stationFrom(leader, leader.headingDeg, b.aheadM, b.abeamM);
        const d = distanceM(s, station);
        const toStation = bearingTo(s, station);
        if (d > 600) return { heading: toStation, speed: cls.maxSpeedKt };
        const lead = angleDiff(toStation, leader.headingDeg);
        const correction = clamp(lead * Math.min(1, d / 250), -75, 75);
        const along = d * Math.cos(lead * DEG);
        return { heading: leader.headingDeg + correction, speed: clamp(leader.speedKt + along * 0.04, 0, cls.maxSpeedKt) };
      }
      case 'pursue': {
        const target = byId.get(b.targetId)!.state;
        if (distanceM(s, target) > b.standoffM) return { heading: bearingTo(s, target), speed: cruiseKt };
        return { heading: target.headingDeg, speed: Math.min(target.speedKt, cls.maxSpeedKt) };
      }
      case 'strike': {
        const target = byId.get(b.targetId)!;
        if (!target.state.active) return { heading: s.headingDeg, speed: 0, expire: 'target lost' };
        const dist = distanceM(s, target.state);
        // Aim where the target will be when the missile gets there.
        const tgo = Math.min(MAX_LEAD_S, dist / Math.max(ktToMs(cls.maxSpeedKt), 1));
        const lead = destination3(target.state, tgo);
        const surfaceTarget = target.cls.domain === 'surface';
        const alt = surfaceTarget ? (dist > 6000 ? cls.cruiseAltM : 8) : target.state.altM;
        return { heading: bearingTo(s, lead), speed: cls.maxSpeedKt, alt };
      }
      case 'hold':
      default:
        if (air && !cls.canHover) return loiterGuide(s, cfg.start, LOITER_RADIUS_M, cruiseKt);
        return { heading: s.headingDeg, speed: 0 };
    }
  };

  const advance = (r: Runtime, t: number, dt: number) => {
    const { cls, state: s, cfg } = r;
    if (cls.domain === 'static') {
      s.speedKt = 0;
      s.sogKt = 0;
      return;
    }
    const air = cls.domain === 'air';
    const dead = s.hp <= 0;
    const crippled = s.hp / r.maxHp < 0.5;
    const cap = dead ? 0 : crippled ? 0.5 : 1;
    const maxSpeed = cls.maxSpeedKt * cap;
    const cruiseKt = Math.min(cfg.speedKt, maxSpeed);
    const turnRate = Math.min(cls.turnRateDegPerS, cfg.maxTurnRateDegPerS ?? Infinity);

    const g: Guidance = dead ? { heading: s.headingDeg, speed: 0 } : guide(r, turnRate, cruiseKt);
    if (g.expire) {
      const target = cfg.behavior.type === 'strike' ? byId.get(cfg.behavior.targetId) : undefined;
      emit(t, 'miss', r, target, here(r), { detail: g.expire });
      spend(r);
      return;
    }

    const minSpeed = air && !dead ? (cls.minSpeedKt ?? 0) : 0;
    const wantSpeed = clamp(g.speed, Math.min(minSpeed, maxSpeed), maxSpeed);
    const accel = (wantSpeed >= s.speedKt ? cls.accelKtPerS : cls.accelKtPerS * 1.5) * dt;
    s.speedKt = clamp(s.speedKt + clamp(wantSpeed - s.speedKt, -accel, accel), 0, cls.maxSpeedKt);

    const turn = turnRate * (0.3 + 0.7 * Math.min(1, s.speedKt / 10)) * dt;
    s.headingDeg = normalizeBearing(s.headingDeg + clamp(angleDiff(g.heading, s.headingDeg), -turn, turn));

    if (air) {
      if (g.alt !== undefined) r.cmdAlt = g.alt;
      const wantAlt = g.alt ?? r.cmdAlt ?? cfg.altitudeM ?? cls.cruiseAltM ?? s.altM;
      const climb = (cls.climbRateMps ?? 10) * dt;
      s.altM += clamp(wantAlt - s.altM, -climb, climb);
    }

    const [ve, vn] = velocityEN(s.headingDeg, ktToMs(s.speedKt));
    const [we, wn] = velocityEN(env.windFromDeg + 180, ktToMs(env.windKt * cls.windage));
    const east = ve + we + (air ? 0 : current[0]);
    const north = vn + wn + (air ? 0 : current[1]);
    s.lat += ((north * dt) / EARTH_RADIUS_M) / DEG;
    s.lon += ((east * dt) / (EARTH_RADIUS_M * Math.cos(s.lat * DEG))) / DEG;
    s.sogKt = msToKt(Math.hypot(east, north));
    s.cogDeg = s.sogKt > 0.01 ? normalizeBearing(Math.atan2(east, north) / DEG) : s.headingDeg;

    r.traveledM += ktToMs(s.speedKt) * dt;
    if (cls.weapon && air && r.traveledM > cls.weapon.rangeM) {
      emit(t, 'miss', r, undefined, here(r), { detail: 'out of range' });
      spend(r);
    }
  };

  /** Ships fire at incoming missiles aimed at their own side. */
  const resolveDefences = (t: number) => {
    for (const d of runtimes) {
      const def = d.cls.defence;
      if (!def || !d.state.active || d.state.hp <= 0 || d.magazine <= 0 || t < d.readyAtS) continue;
      let best: Runtime | null = null;
      let bestDist = Infinity;
      for (const w of runtimes) {
        const b = w.cfg.behavior;
        if (!w.state.active || !isMissile(w.cls) || b.type !== 'strike' || w.cfg.side === d.cfg.side) continue;
        const target = byId.get(b.targetId);
        if (!target || target.cfg.side !== d.cfg.side) continue;
        if ((w.attempts.get(d.cfg.id) ?? 0) >= def.shots) continue;
        const dist = distanceM(d.state, w.state);
        if (dist <= def.rangeM && dist < bestDist) {
          best = w;
          bestDist = dist;
        }
      }
      if (!best) continue;
      d.magazine -= 1;
      d.readyAtS = t + def.reloadS;
      best.attempts.set(d.cfg.id, (best.attempts.get(d.cfg.id) ?? 0) + 1);
      if (rng() < unitPKill(d.cfg)) {
        emit(t, 'intercept', best, d, here(best));
        spend(best);
      }
    }
  };

  const resolveMissiles = (t: number) => {
    for (const w of runtimes) {
      const b = w.cfg.behavior;
      if (!w.state.active || !isMissile(w.cls) || b.type !== 'strike') continue;
      const target = byId.get(b.targetId)!;
      if (!target.state.active) continue;
      const tgtNow: Point3 = { lon: target.state.lon, lat: target.state.lat, altM: target.state.altM };
      const wNow: Point3 = { lon: w.state.lon, lat: w.state.lat, altM: w.state.altM };
      const { dist, s } = closestApproachM(w.prev, wNow, target.prev, tgtNow);
      if (dist > w.cls.weapon!.fuzeM) continue;
      const at = { lon: w.prev.lon + (wNow.lon - w.prev.lon) * s, lat: w.prev.lat + (wNow.lat - w.prev.lat) * s };
      w.state.lon = at.lon;
      w.state.lat = at.lat;
      spend(w);
      if (rng() < unitPHit(w.cfg)) damage(target, unitDamage(w.cfg), w, t, at, 'hit');
      else emit(t, 'miss', w, target, at, { detail: 'did not detonate' });
    }
  };

  const resolveMines = (t: number) => {
    for (const m of runtimes) {
      if (!m.state.active || !isMine(m.cls)) continue;
      const at: Point3 = { lon: m.state.lon, lat: m.state.lat, altM: 0 };
      for (const ship of runtimes) {
        if (!ship.state.active || ship.state.hp <= 0 || ship.cls.domain !== 'surface' || ship.cfg.side === m.cfg.side) continue;
        if (m.checked.has(ship.cfg.id)) continue;
        // Cheap rejection first: most ships are nowhere near most mines.
        if (Math.abs(ship.state.lat - m.state.lat) > 0.05 || Math.abs(ship.state.lon - m.state.lon) > 0.07) continue;
        const { dist } = closestApproachM(
          { ...ship.prev, altM: 0 },
          { lon: ship.state.lon, lat: ship.state.lat, altM: 0 },
          at,
          at,
        );
        if (dist > m.cls.weapon!.fuzeM) continue;
        m.checked.add(ship.cfg.id);
        if (rng() < unitPHit(m.cfg)) {
          damage(ship, unitDamage(m.cfg), m, t, at, 'mine');
          spend(m);
          break;
        }
        emit(t, 'miss', m, ship, at, { detail: 'did not trigger' });
      }
    }
  };

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
      data[o + 6] = s.altM;
      data[o + 7] = s.hp;
      data[o + 8] = s.active ? 1 : 0;
    });
  };

  spawnDue(0);
  record(0);
  for (const r of runtimes) r.justSpawned = false;
  for (let i = 1; i < count; i++) {
    const t = i * dtS;
    spawnDue(t);
    for (const r of runtimes) {
      if (!r.state.active) continue;
      r.prev = { lon: r.state.lon, lat: r.state.lat, altM: r.state.altM };
      if (!r.justSpawned) advance(r, t, dtS);
    }
    resolveDefences(t);
    resolveMissiles(t);
    resolveMines(t);
    record(i);
    for (const r of runtimes) r.justSpawned = false;
  }
  return { dtS, count, unitIds: scenario.units.map((u) => u.id), data, events };
}

/** Where something will be `seconds` from now if it holds its course and speed over the ground. */
function destination3(s: UnitState, seconds: number): LonLat & { altM: number } {
  const [e, nrth] = velocityEN(s.cogDeg, ktToMs(s.sogKt));
  return {
    lat: s.lat + ((nrth * seconds) / EARTH_RADIUS_M) / DEG,
    lon: s.lon + ((e * seconds) / (EARTH_RADIUS_M * Math.cos(s.lat * DEG))) / DEG,
    altM: s.altM,
  };
}

/** The recorded state of one unit at one sample, exactly as stored (no interpolation). */
export function readSample(t: Trajectory, i: number, u: number): UnitState {
  const o = (i * t.unitIds.length + u) * STRIDE;
  const d = t.data;
  return {
    lon: d[o],
    lat: d[o + 1],
    headingDeg: d[o + 2],
    speedKt: d[o + 3],
    cogDeg: d[o + 4],
    sogKt: d[o + 5],
    altM: d[o + 6],
    hp: d[o + 7],
    active: d[o + 8] === 1,
  };
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
  // A unit that is spawning or being spent this step keeps its position from the step where it exists.
  const from = a.active ? a : b;
  const to = b.active ? b : a;
  return {
    lon: lerp(from.lon, to.lon, f),
    lat: lerp(from.lat, to.lat, f),
    headingDeg: lerpAngle(a.headingDeg, b.headingDeg, f),
    speedKt: lerp(a.speedKt, b.speedKt, f),
    cogDeg: lerpAngle(a.cogDeg, b.cogDeg, f),
    sogKt: lerp(a.sogKt, b.sogKt, f),
    altM: lerp(a.altM, b.altM, f),
    hp: a.hp,
    active: a.active,
  };
}

/** Every unit at `timeS`, in scenario order. */
export function statesAt(t: Trajectory, timeS: number): UnitState[] {
  return t.unitIds.map((_, u) => unitStateAt(t, u, timeS));
}

/** Where a unit has been: positions at `timeS` and then every `stepS` back, newest first, stopping at the start or when it did not exist. */
export function trailOf(t: Trajectory, unitIndex: number, timeS: number, lengthS: number, stepS: number): [number, number][] {
  const pts: [number, number][] = [];
  for (let back = 0; back <= lengthS; back += stepS) {
    const at = timeS - back;
    if (at < 0) break;
    const s = unitStateAt(t, unitIndex, at);
    if (!s.active) break;
    pts.push([s.lon, s.lat]);
  }
  return pts;
}
