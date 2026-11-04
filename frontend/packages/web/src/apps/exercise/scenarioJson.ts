import { CLASS_IDS } from './ships';
import type { Behavior, ClassId, LightPreset, ScenarioConfig, Side, UnitConfig, Waypoint } from './types';
import { validateScenario } from './sim';

const SIDES: Side[] = ['BLUE', 'RED', 'NEUTRAL'];
const LIGHTS: LightPreset[] = ['dawn', 'day', 'dusk', 'night'];

type Obj = Record<string, unknown>;

function obj(v: unknown, what: string): Obj {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new Error(`${what} must be an object.`);
  return v as Obj;
}

function num(v: unknown, what: string): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error(`${what} must be a number.`);
  return v;
}

function str(v: unknown, what: string): string {
  if (typeof v !== 'string' || !v) throw new Error(`${what} must be a non-empty string.`);
  return v;
}

function oneOf<T extends string>(v: unknown, allowed: readonly T[], what: string): T {
  if (typeof v !== 'string' || !allowed.includes(v as T)) throw new Error(`${what} must be one of ${allowed.join(', ')}.`);
  return v as T;
}

function lonLat(v: unknown, what: string) {
  const o = obj(v, what);
  return { lon: num(o.lon, `${what}.lon`), lat: num(o.lat, `${what}.lat`) };
}

function waypoint(v: unknown, what: string): Waypoint {
  const o = obj(v, what);
  const w: Waypoint = lonLat(o, what);
  if (o.speedKt !== undefined) w.speedKt = num(o.speedKt, `${what}.speedKt`);
  return w;
}

function behavior(v: unknown, what: string): Behavior {
  const o = obj(v, what);
  switch (o.type) {
    case 'route': {
      if (!Array.isArray(o.waypoints)) throw new Error(`${what}.waypoints must be a list.`);
      return { type: 'route', waypoints: o.waypoints.map((w, i) => waypoint(w, `${what}.waypoints[${i}]`)), loop: o.loop === true };
    }
    case 'escort':
      return { type: 'escort', leaderId: str(o.leaderId, `${what}.leaderId`), aheadM: num(o.aheadM, `${what}.aheadM`), abeamM: num(o.abeamM, `${what}.abeamM`) };
    case 'pursue':
      return { type: 'pursue', targetId: str(o.targetId, `${what}.targetId`), standoffM: num(o.standoffM, `${what}.standoffM`) };
    case 'hold':
      return { type: 'hold' };
    default:
      throw new Error(`${what}.type must be route, escort, pursue or hold.`);
  }
}

function unit(v: unknown, i: number): UnitConfig {
  const what = `units[${i}]`;
  const o = obj(v, what);
  const u: UnitConfig = {
    id: str(o.id, `${what}.id`),
    name: typeof o.name === 'string' && o.name ? o.name : str(o.id, `${what}.id`),
    classId: oneOf<ClassId>(o.classId, CLASS_IDS, `${what}.classId`),
    side: oneOf(o.side, SIDES, `${what}.side`),
    start: lonLat(o.start, `${what}.start`),
    headingDeg: num(o.headingDeg, `${what}.headingDeg`),
    speedKt: num(o.speedKt, `${what}.speedKt`),
    behavior: behavior(o.behavior, `${what}.behavior`),
  };
  if (o.maxTurnRateDegPerS !== undefined) u.maxTurnRateDegPerS = num(o.maxTurnRateDegPerS, `${what}.maxTurnRateDegPerS`);
  return u;
}

/** Turn untrusted JSON into a scenario, or throw an error that says what is wrong. */
export function parseScenario(json: string): ScenarioConfig {
  let raw: unknown;
  try {
    raw = JSON.parse(json);
  } catch {
    throw new Error('That is not valid JSON.');
  }
  const o = obj(raw, 'The scenario');
  const env = obj(o.environment, 'environment');
  if (!Array.isArray(o.units)) throw new Error('units must be a list.');
  const scenario: ScenarioConfig = {
    id: typeof o.id === 'string' && o.id ? o.id : 'imported',
    name: str(o.name, 'name'),
    description: typeof o.description === 'string' ? o.description : '',
    center: lonLat(o.center, 'center'),
    durationS: num(o.durationS, 'durationS'),
    lightPreset: o.lightPreset === undefined ? 'day' : oneOf(o.lightPreset, LIGHTS, 'lightPreset'),
    environment: {
      windFromDeg: num(env.windFromDeg, 'environment.windFromDeg'),
      windKt: num(env.windKt, 'environment.windKt'),
      currentToDeg: num(env.currentToDeg, 'environment.currentToDeg'),
      currentKt: num(env.currentKt, 'environment.currentKt'),
    },
    units: o.units.map(unit),
  };
  const problems = validateScenario(scenario);
  if (problems.length) throw new Error(problems[0]);
  return scenario;
}

export function exportScenario(s: ScenarioConfig): string {
  return JSON.stringify(s, null, 2);
}
