import { ENV_FIELDS, UNIT_FIELDS } from './montecarlo';
import { CLASS_IDS } from './ships';
import type {
  Behavior,
  ClassId,
  Dist,
  LightPreset,
  OutcomeSpec,
  StoryMoment,
  PerturbTarget,
  Perturbation,
  RedTeamSpec,
  ScenarioConfig,
  Side,
  SweepSpec,
  UnitConfig,
  Waypoint,
} from './types';
import { validateScenario } from './sim';
import { validateStoryboard } from './storyboard';

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

function optNum(o: Obj, key: string, what: string): number | undefined {
  return o[key] === undefined ? undefined : num(o[key], `${what}.${key}`);
}

function str(v: unknown, what: string): string {
  if (typeof v !== 'string' || !v) throw new Error(`${what} must be a non-empty string.`);
  return v;
}

function oneOf<T extends string>(v: unknown, allowed: readonly T[], what: string): T {
  if (typeof v !== 'string' || !allowed.includes(v as T)) throw new Error(`${what} must be one of ${allowed.join(', ')}.`);
  return v as T;
}

function list(v: unknown, what: string): unknown[] {
  if (!Array.isArray(v)) throw new Error(`${what} must be a list.`);
  return v;
}

function lonLat(v: unknown, what: string) {
  const o = obj(v, what);
  return { lon: num(o.lon, `${what}.lon`), lat: num(o.lat, `${what}.lat`) };
}

function waypoint(v: unknown, what: string): Waypoint {
  const o = obj(v, what);
  const w: Waypoint = lonLat(o, what);
  const speedKt = optNum(o, 'speedKt', what);
  const altitudeM = optNum(o, 'altitudeM', what);
  if (speedKt !== undefined) w.speedKt = speedKt;
  if (altitudeM !== undefined) w.altitudeM = altitudeM;
  return w;
}

function behavior(v: unknown, what: string): Behavior {
  const o = obj(v, what);
  switch (o.type) {
    case 'route':
      return { type: 'route', waypoints: list(o.waypoints, `${what}.waypoints`).map((w, i) => waypoint(w, `${what}.waypoints[${i}]`)), ...(o.loop === true ? { loop: true } : {}) };
    case 'escort':
      return { type: 'escort', leaderId: str(o.leaderId, `${what}.leaderId`), aheadM: num(o.aheadM, `${what}.aheadM`), abeamM: num(o.abeamM, `${what}.abeamM`) };
    case 'pursue':
      return { type: 'pursue', targetId: str(o.targetId, `${what}.targetId`), standoffM: num(o.standoffM, `${what}.standoffM`) };
    case 'loiter':
      return { type: 'loiter', center: lonLat(o.center, `${what}.center`), radiusM: num(o.radiusM, `${what}.radiusM`) };
    case 'strike':
      return { type: 'strike', targetId: str(o.targetId, `${what}.targetId`) };
    case 'hold':
      return { type: 'hold' };
    default:
      throw new Error(`${what}.type must be route, escort, pursue, loiter, strike or hold.`);
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
  for (const key of ['maxTurnRateDegPerS', 'altitudeM', 'hp', 'damage', 'pHit', 'pKill', 'magazine', 'signature', 'radarRangeM', 'decoys', 'pDecoy'] as const) {
    const n = optNum(o, key, what);
    if (n !== undefined) u[key] = n;
  }
  if (o.launch !== undefined) {
    const l = obj(o.launch, `${what}.launch`);
    u.launch = { byId: str(l.byId, `${what}.launch.byId`), atS: num(l.atS, `${what}.launch.atS`) };
  }
  if (o.disabled === true) u.disabled = true;
  return u;
}

// ---- red team ----

function dist(v: unknown, what: string): Dist {
  const o = obj(v, what);
  switch (o.type) {
    case 'uniform':
      return { type: 'uniform', min: num(o.min, `${what}.min`), max: num(o.max, `${what}.max`) };
    case 'normal':
      return { type: 'normal', mean: num(o.mean, `${what}.mean`), sd: num(o.sd, `${what}.sd`) };
    case 'triangular':
      return { type: 'triangular', min: num(o.min, `${what}.min`), mode: num(o.mode, `${what}.mode`), max: num(o.max, `${what}.max`) };
    case 'choice': {
      const values = list(o.values, `${what}.values`).map((x, i) => num(x, `${what}.values[${i}]`));
      const weights = o.weights === undefined ? undefined : list(o.weights, `${what}.weights`).map((x, i) => num(x, `${what}.weights[${i}]`));
      return weights ? { type: 'choice', values, weights } : { type: 'choice', values };
    }
    default:
      throw new Error(`${what}.type must be uniform, normal, triangular or choice.`);
  }
}

function target(v: unknown, what: string): PerturbTarget {
  const o = obj(v, what);
  if (o.kind === 'environment') return { kind: 'environment', field: oneOf(o.field, ENV_FIELDS, `${what}.field`) };
  if (o.kind === 'unit') return { kind: 'unit', unitId: str(o.unitId, `${what}.unitId`), field: oneOf(o.field, UNIT_FIELDS, `${what}.field`) };
  throw new Error(`${what}.kind must be environment or unit.`);
}

function perturbation(v: unknown, i: number): Perturbation {
  const what = `redTeam.perturbations[${i}]`;
  const o = obj(v, what);
  const p: Perturbation = {
    id: str(o.id, `${what}.id`),
    target: target(o.target, `${what}.target`),
    mode: oneOf(o.mode, ['set', 'add', 'scale'] as const, `${what}.mode`),
    dist: dist(o.dist, `${what}.dist`),
  };
  if (typeof o.label === 'string' && o.label) p.label = o.label;
  return p;
}

function moment(v: unknown, i: number): StoryMoment {
  const what = `storyboard[${i}]`;
  const o = obj(v, what);
  const m: StoryMoment = {
    id: str(o.id, `${what}.id`),
    atS: num(o.atS, `${what}.atS`),
    holdS: num(o.holdS, `${what}.holdS`),
    title: typeof o.title === 'string' ? o.title : str(o.id, `${what}.id`),
  };
  if (typeof o.unitId === 'string' && o.unitId) m.unitId = o.unitId;
  if (o.at !== undefined) m.at = lonLat(o.at, `${what}.at`);
  if (typeof o.caption === 'string' && o.caption) m.caption = o.caption;
  if (typeof o.image === 'string' && o.image) m.image = o.image;
  return m;
}

function outcome(v: unknown, i: number): OutcomeSpec {
  const what = `redTeam.outcomes[${i}]`;
  const parsed = outcomeCore(v, i);
  const before = obj(v, what).beforeS;
  return before === undefined ? parsed : { ...parsed, beforeS: num(before, `${what}.beforeS`) };
}

function outcomeCore(v: unknown, i: number): OutcomeSpec {
  const what = `redTeam.outcomes[${i}]`;
  const o = obj(v, what);
  const base = { id: str(o.id, `${what}.id`), ...(typeof o.label === 'string' && o.label ? { label: o.label } : {}) };
  switch (o.type) {
    case 'destroyed':
    case 'hit':
      return { ...base, type: o.type, unitId: str(o.unitId, `${what}.unitId`) };
    case 'hp_below':
      return { ...base, type: 'hp_below', unitId: str(o.unitId, `${what}.unitId`), frac: num(o.frac, `${what}.frac`) };
    case 'side_losses':
      return { ...base, type: 'side_losses', side: oneOf(o.side, SIDES, `${what}.side`), atLeast: num(o.atLeast, `${what}.atLeast`) };
    case 'mine_strike':
      return o.unitId === undefined ? { ...base, type: 'mine_strike' } : { ...base, type: 'mine_strike', unitId: str(o.unitId, `${what}.unitId`) };
    case 'intercepts':
      return { ...base, type: 'intercepts', atLeast: num(o.atLeast, `${what}.atLeast`) };
    case 'closest_approach':
      return { ...base, type: 'closest_approach', aId: str(o.aId, `${what}.aId`), bId: str(o.bId, `${what}.bId`), withinM: num(o.withinM, `${what}.withinM`) };
    case 'detected':
      return o.bySide === undefined ? { ...base, type: 'detected', unitId: str(o.unitId, `${what}.unitId`) } : { ...base, type: 'detected', unitId: str(o.unitId, `${what}.unitId`), bySide: oneOf(o.bySide, SIDES, `${what}.bySide`) };
    case 'all':
    case 'any':
      return { ...base, type: o.type, of: list(o.of, `${what}.of`).map((x, k) => str(x, `${what}.of[${k}]`)) };
    case 'not':
      return { ...base, type: 'not', of: str(o.of, `${what}.of`) };
    default:
      throw new Error(`${what}.type must be destroyed, hit, hp_below, side_losses, mine_strike, intercepts, closest_approach, detected, all, any or not.`);
  }
}

function sweep(v: unknown): SweepSpec {
  const o = obj(v, 'redTeam.sweep');
  const t = obj(o.target, 'redTeam.sweep.target');
  const values = list(o.values, 'redTeam.sweep.values').map((x, i) => num(x, `redTeam.sweep.values[${i}]`));
  if (t.kind === 'salvo') return { target: { kind: 'salvo', unitIds: list(t.unitIds, 'redTeam.sweep.target.unitIds').map((x, i) => str(x, `redTeam.sweep.target.unitIds[${i}]`)) }, values };
  return { target: target(t, 'redTeam.sweep.target'), values };
}

export function parseRedTeam(v: unknown): RedTeamSpec {
  const o = obj(v, 'redTeam');
  const spec: RedTeamSpec = {
    runs: num(o.runs, 'redTeam.runs'),
    seed: num(o.seed, 'redTeam.seed'),
    perturbations: list(o.perturbations, 'redTeam.perturbations').map(perturbation),
    outcomes: list(o.outcomes, 'redTeam.outcomes').map(outcome),
  };
  if (o.sweep !== undefined) spec.sweep = sweep(o.sweep);
  if (o.targetHalfWidth !== undefined) spec.targetHalfWidth = num(o.targetHalfWidth, 'redTeam.targetHalfWidth');
  return spec;
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
    units: list(o.units, 'units').map(unit),
  };
  const seed = optNum(o, 'seed', 'The scenario');
  if (seed !== undefined) scenario.seed = seed;
  if (o.storyboard !== undefined) scenario.storyboard = list(o.storyboard, 'storyboard').map(moment);
  if (o.detection === true) scenario.detection = true;
  if (o.seaState === true) scenario.seaState = true;
  if (o.redTeam !== undefined) scenario.redTeam = parseRedTeam(o.redTeam);
  const problems = [...validateScenario(scenario), ...validateStoryboard(scenario, scenario.storyboard ?? [])];
  if (problems.length) throw new Error(problems[0]);
  return scenario;
}

export function exportScenario(s: ScenarioConfig): string {
  return JSON.stringify(s, null, 2);
}
