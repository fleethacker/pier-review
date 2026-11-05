import { offsetM } from './geo';
import { SHIP_CLASSES, isMine, isMissile, isPlatform } from './ships';
import { closestApproachM, makeRng, readSample, runScenario, unitHp, validateScenario } from './sim';
import type { Trajectory } from './sim';
import type {
  Dist,
  EnvField,
  OutcomeSpec,
  PerturbTarget,
  Perturbation,
  RedTeamSpec,
  ScenarioConfig,
  Side,
  UnitConfig,
  UnitField,
} from './types';

export const ENV_FIELDS: EnvField[] = ['windKt', 'windFromDeg', 'currentKt', 'currentToDeg'];
export const UNIT_FIELDS: UnitField[] = [
  'speedKt',
  'headingDeg',
  'startEastM',
  'startNorthM',
  'routeEastM',
  'routeNorthM',
  'launchAtS',
  'altitudeM',
  'hp',
  'damage',
  'pHit',
  'pKill',
  'magazine',
  'disabled',
];
const OFFSET_FIELDS = new Set<UnitField>(['startEastM', 'startNorthM', 'routeEastM', 'routeNorthM']);
const SIDES: Side[] = ['BLUE', 'RED', 'NEUTRAL'];
export const MAX_RUNS = 20_000;
const HIST_BINS = 12;

// ---- drawing from distributions ----

const TWO_PI = Math.PI * 2;

export function sampleDist(dist: Dist, rng: () => number): number {
  switch (dist.type) {
    case 'uniform':
      return dist.min + rng() * (dist.max - dist.min);
    case 'normal': {
      const u1 = Math.max(rng(), 1e-12);
      const u2 = rng();
      return dist.mean + dist.sd * Math.sqrt(-2 * Math.log(u1)) * Math.cos(TWO_PI * u2);
    }
    case 'triangular': {
      const u = rng();
      const { min, mode, max } = dist;
      if (max === min) return min;
      const cut = (mode - min) / (max - min);
      return u < cut ? min + Math.sqrt(u * (max - min) * (mode - min)) : max - Math.sqrt((1 - u) * (max - min) * (max - mode));
    }
    case 'choice': {
      const weights = dist.weights ?? dist.values.map(() => 1);
      const total = weights.reduce((a, w) => a + w, 0);
      let pick = rng() * total;
      for (let i = 0; i < dist.values.length; i++) {
        pick -= weights[i];
        if (pick < 0) return dist.values[i];
      }
      return dist.values[dist.values.length - 1];
    }
  }
}

const norm360 = (v: number) => ((v % 360) + 360) % 360;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

function combine(mode: Perturbation['mode'], base: number, draw: number): number {
  return mode === 'set' ? draw : mode === 'add' ? base + draw : base * draw;
}

/** The value a unit field has in the scenario now, falling back to the class default. Offsets start from zero. */
export function unitFieldValue(u: UnitConfig, field: UnitField): number | undefined {
  const cls = SHIP_CLASSES[u.classId];
  switch (field) {
    case 'speedKt':
      return u.speedKt;
    case 'headingDeg':
      return u.headingDeg;
    case 'launchAtS':
      return u.launch?.atS;
    case 'altitudeM':
      return u.altitudeM ?? cls.cruiseAltM ?? 0;
    case 'hp':
      return unitHp(u);
    case 'damage':
      return u.damage ?? cls.weapon?.damage ?? 0;
    case 'pHit':
      return u.pHit ?? cls.weapon?.pHit ?? 0;
    case 'pKill':
      return u.pKill ?? cls.defence?.pKill ?? 0;
    case 'magazine':
      return u.magazine ?? cls.defence?.magazine ?? 0;
    case 'disabled':
      return u.disabled ? 1 : 0;
    default:
      return 0;
  }
}

/** Set a unit field in a scenario copy, clamped to something that runs. Returns what was actually set, or NaN if the unit cannot take it. */
function setUnitField(u: UnitConfig, field: UnitField, v: number): number {
  switch (field) {
    case 'speedKt':
      return (u.speedKt = Math.max(0, v));
    case 'headingDeg':
      return (u.headingDeg = norm360(v));
    case 'startEastM':
      u.start = offsetM(u.start, v, 0);
      return v;
    case 'startNorthM':
      u.start = offsetM(u.start, 0, v);
      return v;
    case 'routeEastM':
    case 'routeNorthM': {
      const e = field === 'routeEastM' ? v : 0;
      const n = field === 'routeNorthM' ? v : 0;
      const b = u.behavior;
      if (b.type === 'route') b.waypoints = b.waypoints.map((w) => ({ ...w, ...offsetM(w, e, n) }));
      else if (b.type === 'loiter') b.center = offsetM(b.center, e, n);
      return v;
    }
    case 'launchAtS':
      if (!u.launch) return NaN;
      return (u.launch.atS = Math.max(0, v));
    case 'altitudeM':
      return (u.altitudeM = Math.max(0, v));
    case 'hp':
      return (u.hp = Math.max(1, v));
    case 'damage':
      return (u.damage = Math.max(0, v));
    case 'pHit':
      return (u.pHit = clamp(v, 0, 1));
    case 'pKill':
      return (u.pKill = clamp(v, 0, 1));
    case 'magazine':
      return (u.magazine = Math.max(0, Math.round(v)));
    case 'disabled':
      u.disabled = v >= 0.5;
      return u.disabled ? 1 : 0;
  }
}

function setEnvField(s: ScenarioConfig, field: EnvField, v: number): number {
  switch (field) {
    case 'windKt':
    case 'currentKt':
      return (s.environment[field] = Math.max(0, v));
    case 'windFromDeg':
    case 'currentToDeg':
      return (s.environment[field] = norm360(v));
  }
}

function apply(s: ScenarioConfig, target: PerturbTarget, mode: Perturbation['mode'], draw: number): number {
  if (target.kind === 'environment') return setEnvField(s, target.field, combine(mode, s.environment[target.field], draw));
  const u = s.units.find((x) => x.id === target.unitId);
  if (!u) return NaN;
  const base = unitFieldValue(u, target.field) ?? 0;
  return setUnitField(u, target.field, OFFSET_FIELDS.has(target.field) ? draw : combine(mode, base, draw));
}

/** What one run of a red-team batch looks like: the scenario with its random draws applied, and the seed for its chance rolls. */
export interface PreparedRun {
  scenario: ScenarioConfig;
  seed: number;
  /** The value each perturbation took, by perturbation id (NaN where it did not apply). */
  values: Record<string, number>;
}

export function sweepLabel(sweep: NonNullable<RedTeamSpec['sweep']>, value: number): string {
  const t = sweep.target;
  if (t.kind === 'salvo') return `${value} of ${t.unitIds.length} enabled`;
  return t.kind === 'environment' ? `${t.field} = ${value}` : `${t.unitId} ${t.field} = ${value}`;
}

/** Build run number `k` of a batch. The same spec, base scenario and `k` always give the same run, which is what makes any run replayable. */
export function prepareRun(base: ScenarioConfig, spec: RedTeamSpec, k: number, sweepValue?: number): PreparedRun {
  const scenario = JSON.parse(JSON.stringify({ ...base, redTeam: undefined })) as ScenarioConfig;
  if (spec.sweep && sweepValue !== undefined) {
    const t = spec.sweep.target;
    if (t.kind === 'salvo') {
      t.unitIds.forEach((id, i) => {
        const u = scenario.units.find((x) => x.id === id);
        if (u) u.disabled = i >= sweepValue;
      });
    } else {
      apply(scenario, t, 'set', sweepValue);
    }
  }
  const rng = makeRng((Math.imul(spec.seed, 2_654_435_761) + Math.imul(k, 40_503) + 3) >>> 0);
  const values: Record<string, number> = {};
  for (const p of spec.perturbations) values[p.id] = apply(scenario, p.target, p.mode, sampleDist(p.dist, rng));
  return { scenario, seed: (Math.imul(spec.seed, 1_000_003) + Math.imul(k, 7_919) + 17) >>> 0, values };
}

// ---- asking questions of a run ----

export interface OutcomeResult {
  hit: boolean;
  /** When it happened: the first time, or the time the threshold was reached. */
  tS?: number;
}

function closestApproachTime(traj: Trajectory, aIdx: number, bIdx: number, withinM: number): number | undefined {
  for (let i = 0; i < traj.count - 1; i++) {
    const a0 = readSample(traj, i, aIdx);
    const b0 = readSample(traj, i, bIdx);
    if (!a0.active || !b0.active) continue;
    const a1 = readSample(traj, i + 1, aIdx);
    const b1 = readSample(traj, i + 1, bIdx);
    // Horizontal distance only: a raider overhead has still reached the ship.
    const { dist, s } = closestApproachM(
      { lon: a0.lon, lat: a0.lat, altM: 0 },
      { lon: a1.lon, lat: a1.lat, altM: 0 },
      { lon: b0.lon, lat: b0.lat, altM: 0 },
      { lon: b1.lon, lat: b1.lat, altM: 0 },
    );
    if (dist <= withinM) return (i + s) * traj.dtS;
  }
  return undefined;
}

export function evaluateOutcome(scenario: ScenarioConfig, traj: Trajectory, o: OutcomeSpec): OutcomeResult {
  const units = new Map(scenario.units.map((u) => [u.id, u]));
  const ev = traj.events;
  const first = (pred: (e: (typeof ev)[number]) => boolean): OutcomeResult => {
    const e = ev.find(pred);
    return e ? { hit: true, tS: e.tS } : { hit: false };
  };
  const nth = (pred: (e: (typeof ev)[number]) => boolean, n: number): OutcomeResult => {
    let seen = 0;
    for (const e of ev) if (pred(e) && ++seen >= n) return { hit: true, tS: e.tS };
    return { hit: false };
  };
  switch (o.type) {
    case 'destroyed':
      return first((e) => e.type === 'destroyed' && e.unitId === o.unitId);
    case 'hit':
      return first((e) => (e.type === 'hit' || e.type === 'mine') && e.otherId === o.unitId);
    case 'hp_below': {
      const u = units.get(o.unitId);
      const max = u ? unitHp(u) : 1;
      return first((e) => (e.type === 'hit' || e.type === 'mine') && e.otherId === o.unitId && (e.hpAfter ?? max) / max < o.frac);
    }
    case 'side_losses':
      return nth((e) => {
        if (e.type !== 'destroyed') return false;
        const u = units.get(e.unitId);
        return !!u && u.side === o.side && isPlatform(SHIP_CLASSES[u.classId]);
      }, o.atLeast);
    case 'mine_strike':
      return first((e) => e.type === 'mine' && (o.unitId === undefined || e.otherId === o.unitId));
    case 'intercepts':
      return nth((e) => e.type === 'intercept', o.atLeast);
    case 'closest_approach': {
      const a = traj.unitIds.indexOf(o.aId);
      const b = traj.unitIds.indexOf(o.bId);
      if (a < 0 || b < 0) return { hit: false };
      const tS = closestApproachTime(traj, a, b, o.withinM);
      return tS === undefined ? { hit: false } : { hit: true, tS };
    }
  }
}

export function describeOutcome(o: OutcomeSpec, name: (id: string) => string): string {
  if (o.label) return o.label;
  switch (o.type) {
    case 'destroyed':
      return `${name(o.unitId)} destroyed`;
    case 'hit':
      return `${name(o.unitId)} hit`;
    case 'hp_below':
      return `${name(o.unitId)} below ${Math.round(o.frac * 100)}% strength`;
    case 'side_losses':
      return `${o.atLeast}+ ${o.side.toLowerCase()} losses`;
    case 'mine_strike':
      return o.unitId ? `${name(o.unitId)} strikes a mine` : 'A mine goes off';
    case 'intercepts':
      return `${o.atLeast}+ missiles shot down`;
    case 'closest_approach':
      return `${name(o.aId)} within ${o.withinM} m of ${name(o.bId)}`;
  }
}

// ---- statistics ----

/** 95% Wilson score interval for a proportion. Well behaved at 0 and 1 and with few runs. */
export function wilson(hits: number, n: number): { lo: number; hi: number } {
  if (n === 0) return { lo: 0, hi: 1 };
  const z = 1.96;
  const p = hits / n;
  const denom = 1 + (z * z) / n;
  const center = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  return { lo: Math.max(0, center - half), hi: Math.min(1, center + half) };
}

function pearson(xs: number[], ys: number[]): number {
  const n = xs.length;
  if (n < 3) return 0;
  const mx = xs.reduce((a, v) => a + v, 0) / n;
  const my = ys.reduce((a, v) => a + v, 0) / n;
  let sxy = 0;
  let sxx = 0;
  let syy = 0;
  for (let i = 0; i < n; i++) {
    sxy += (xs[i] - mx) * (ys[i] - my);
    sxx += (xs[i] - mx) ** 2;
    syy += (ys[i] - my) ** 2;
  }
  return sxx === 0 || syy === 0 ? 0 : sxy / Math.sqrt(sxx * syy);
}

export interface OutcomeStat {
  id: string;
  label: string;
  hits: number;
  n: number;
  p: number;
  lo: number;
  hi: number;
  meanTimeS: number | null;
  /** How many runs had the outcome happen in each twelfth of the scenario. */
  timeHist: number[];
}

export interface SensitivityRow {
  perturbationId: string;
  label: string;
  outcomeId: string;
  /** Correlation between the draw and the outcome happening: positive means higher values make it more likely. */
  corr: number;
  meanWhenHit: number | null;
  meanWhenNot: number | null;
}

export interface McGroup {
  label: string;
  sweepValue?: number;
  runs: number;
  outcomes: OutcomeStat[];
  sensitivity: SensitivityRow[];
  /** Run numbers where each outcome happened and where it did not, for replaying. */
  hitRuns: Record<string, number[]>;
  missRuns: Record<string, number[]>;
  metrics: { label: string; mean: number }[];
}

export interface McResult {
  groups: McGroup[];
  stopped: boolean;
  elapsedMs: number;
  totalRuns: number;
}

export interface McOptions {
  onProgress?: (done: number, total: number) => void;
  shouldStop?: () => boolean;
}

export function validateRedTeam(base: ScenarioConfig, spec: RedTeamSpec): string[] {
  const errors: string[] = [];
  const unit = (id: string) => base.units.find((u) => u.id === id);
  const needUnit = (id: string, what: string) => {
    if (!unit(id)) errors.push(`${what} refers to a unit that does not exist: "${id}".`);
  };
  if (!Number.isInteger(spec.runs) || spec.runs < 1 || spec.runs > MAX_RUNS) errors.push(`Runs must be a whole number from 1 to ${MAX_RUNS}.`);
  if (!Number.isFinite(spec.seed)) errors.push('The seed must be a number.');
  if (spec.outcomes.length === 0) errors.push('Add at least one outcome to measure.');
  const outcomeIds = new Set<string>();
  for (const o of spec.outcomes) {
    if (outcomeIds.has(o.id)) errors.push(`Two outcomes share the id "${o.id}".`);
    outcomeIds.add(o.id);
    const what = `Outcome "${o.label ?? o.id}"`;
    if ('unitId' in o && o.unitId !== undefined) needUnit(o.unitId, what);
    if (o.type === 'hp_below' && !(o.frac > 0 && o.frac <= 1)) errors.push(`${what}: the fraction must be above 0 and at most 1.`);
    if ((o.type === 'side_losses' || o.type === 'intercepts') && !(Number.isInteger(o.atLeast) && o.atLeast >= 1)) errors.push(`${what}: "at least" must be a whole number, 1 or more.`);
    if (o.type === 'side_losses' && !SIDES.includes(o.side)) errors.push(`${what}: unknown side.`);
    if (o.type === 'closest_approach') {
      needUnit(o.aId, what);
      needUnit(o.bId, what);
      if (!(o.withinM > 0)) errors.push(`${what}: the distance must be above zero.`);
    }
  }
  const pertIds = new Set<string>();
  for (const p of spec.perturbations) {
    if (pertIds.has(p.id)) errors.push(`Two variations share the id "${p.id}".`);
    pertIds.add(p.id);
    const what = `Variation "${p.label ?? p.id}"`;
    if (p.target.kind === 'unit') needUnit(p.target.unitId, what);
    const d = p.dist;
    if (d.type === 'uniform' && !(d.min <= d.max)) errors.push(`${what}: the minimum is above the maximum.`);
    if (d.type === 'normal' && !(d.sd >= 0)) errors.push(`${what}: the standard deviation cannot be negative.`);
    if (d.type === 'triangular' && !(d.min <= d.mode && d.mode <= d.max)) errors.push(`${what}: it needs min ≤ mode ≤ max.`);
    if (d.type === 'choice') {
      if (d.values.length === 0) errors.push(`${what}: the list of values is empty.`);
      if (d.weights && (d.weights.length !== d.values.length || d.weights.some((w) => !(w >= 0)) || d.weights.every((w) => w === 0))) {
        errors.push(`${what}: weights must match the values, not be negative, and not all be zero.`);
      }
    }
  }
  const sw = spec.sweep;
  if (sw) {
    if (sw.values.length === 0 || sw.values.length > 30 || sw.values.some((v) => !Number.isFinite(v))) errors.push('A sweep needs between 1 and 30 numeric values.');
    if (sw.target.kind === 'salvo') {
      if (sw.target.unitIds.length === 0) errors.push('A salvo sweep needs at least one unit.');
      for (const id of sw.target.unitIds) needUnit(id, 'The sweep');
    } else if (sw.target.kind === 'unit') needUnit(sw.target.unitId, 'The sweep');
  }
  return errors;
}

/** A sensible first red-team setup for any scenario: lose-the-ship outcomes and a little variation in the obvious places. */
export function defaultRedTeam(s: ScenarioConfig): RedTeamSpec {
  const platforms = s.units.filter((u) => isPlatform(SHIP_CLASSES[u.classId]) && SHIP_CLASSES[u.classId].domain === 'surface');
  const blue = platforms.filter((u) => u.side === 'BLUE');
  const focus = (blue.length ? blue : platforms).slice(0, 3);
  const outcomes: OutcomeSpec[] = [
    ...focus.map((u): OutcomeSpec => ({ id: `${u.id}-hit`, label: `${u.name} is hit`, type: 'hit', unitId: u.id })),
    ...focus.map((u): OutcomeSpec => ({ id: `${u.id}-lost`, label: `${u.name} is destroyed`, type: 'destroyed', unitId: u.id })),
  ];
  if (s.units.some((u) => isMissile(SHIP_CLASSES[u.classId]))) outcomes.push({ id: 'intercepts', label: 'At least 3 missiles shot down', type: 'intercepts', atLeast: 3 });
  if (s.units.some((u) => isMine(SHIP_CLASSES[u.classId]))) outcomes.push({ id: 'mine', label: 'A mine goes off', type: 'mine_strike' });
  if (outcomes.length === 0) outcomes.push({ id: 'losses', label: 'Any blue loss', type: 'side_losses', side: 'BLUE', atLeast: 1 });

  const perturbations: Perturbation[] = [
    { id: 'wind', label: 'Wind speed', target: { kind: 'environment', field: 'windKt' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 4 } },
  ];
  for (const u of s.units.filter((x) => x.launch && isMissile(SHIP_CLASSES[x.classId])).slice(0, 4)) {
    perturbations.push({ id: `${u.id}-time`, label: `${u.name} launch time`, target: { kind: 'unit', unitId: u.id, field: 'launchAtS' }, mode: 'add', dist: { type: 'uniform', min: -15, max: 15 } });
  }
  for (const u of s.units.filter((x) => isMissile(SHIP_CLASSES[x.classId])).slice(0, 2)) {
    perturbations.push({ id: `${u.id}-phit`, label: `${u.name} hit chance`, target: { kind: 'unit', unitId: u.id, field: 'pHit' }, mode: 'set', dist: { type: 'uniform', min: 0.6, max: 0.95 } });
  }
  for (const u of platforms.slice(0, 3)) {
    perturbations.push({ id: `${u.id}-e`, label: `${u.name} start east`, target: { kind: 'unit', unitId: u.id, field: 'startEastM' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 500 } });
  }
  return { runs: 100, seed: 1, perturbations, outcomes };
}

const yieldToUi = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

interface Acc {
  hits: number[];
  times: number[][];
  values: number[][];
  flags: number[][];
  hitRuns: number[][];
  missRuns: number[][];
  metricSums: number[];
  n: number;
}

const METRICS = ['Hits on ships per run', 'Missiles shot down per run', 'Blue losses per run', 'Red losses per run', 'Mines triggered per run'];

function metricsOf(s: ScenarioConfig, traj: Trajectory): number[] {
  const units = new Map(s.units.map((u) => [u.id, u]));
  let hits = 0;
  let intercepts = 0;
  let blue = 0;
  let red = 0;
  let mines = 0;
  for (const e of traj.events) {
    if (e.type === 'hit') hits++;
    else if (e.type === 'mine') {
      hits++;
      mines++;
    } else if (e.type === 'intercept') intercepts++;
    else if (e.type === 'destroyed') {
      const u = units.get(e.unitId);
      if (u && isPlatform(SHIP_CLASSES[u.classId])) {
        if (u.side === 'BLUE') blue++;
        if (u.side === 'RED') red++;
      }
    }
  }
  return [hits, intercepts, blue, red, mines];
}

export async function runMonteCarlo(base: ScenarioConfig, spec: RedTeamSpec, options: McOptions = {}): Promise<McResult> {
  const problems = [...validateScenario(base), ...validateRedTeam(base, spec)];
  if (problems.length) throw new Error(problems[0]);
  const started = performance.now();
  const sweepValues = spec.sweep ? spec.sweep.values : [undefined];
  const total = spec.runs * sweepValues.length;
  const nameOf = (id: string) => base.units.find((u) => u.id === id)?.name ?? id;
  const accs: Acc[] = sweepValues.map(() => ({
    hits: spec.outcomes.map(() => 0),
    times: spec.outcomes.map(() => []),
    values: spec.perturbations.map(() => []),
    flags: spec.outcomes.map(() => []),
    hitRuns: spec.outcomes.map(() => []),
    missRuns: spec.outcomes.map(() => []),
    metricSums: METRICS.map(() => 0),
    n: 0,
  }));

  let done = 0;
  let stopped = false;
  let lastYield = performance.now();
  // Interleave the sweep values run by run, so stopping early leaves every group with about the same number of runs.
  outer: for (let k = 0; k < spec.runs; k++) {
    for (let g = 0; g < sweepValues.length; g++) {
      const run = prepareRun(base, spec, k, sweepValues[g]);
      const traj = runScenario(run.scenario, { seed: run.seed });
      const acc = accs[g];
      spec.outcomes.forEach((o, i) => {
        const r = evaluateOutcome(run.scenario, traj, o);
        acc.flags[i].push(r.hit ? 1 : 0);
        if (r.hit) {
          acc.hits[i]++;
          if (r.tS !== undefined) acc.times[i].push(r.tS);
          if (acc.hitRuns[i].length < 8) acc.hitRuns[i].push(k);
        } else if (acc.missRuns[i].length < 8) acc.missRuns[i].push(k);
      });
      spec.perturbations.forEach((p, i) => acc.values[i].push(run.values[p.id]));
      metricsOf(run.scenario, traj).forEach((v, i) => (acc.metricSums[i] += v));
      acc.n++;
      done++;
      if (performance.now() - lastYield > 30) {
        options.onProgress?.(done, total);
        await yieldToUi();
        lastYield = performance.now();
        if (options.shouldStop?.()) {
          stopped = true;
          break outer;
        }
      }
    }
  }
  options.onProgress?.(done, total);

  const groups: McGroup[] = accs.map((acc, g) => {
    const outcomes: OutcomeStat[] = spec.outcomes.map((o, i) => {
      const { lo, hi } = wilson(acc.hits[i], acc.n);
      const times = acc.times[i];
      const hist = new Array<number>(HIST_BINS).fill(0);
      for (const t of times) hist[Math.min(HIST_BINS - 1, Math.floor((t / base.durationS) * HIST_BINS))]++;
      return {
        id: o.id,
        label: describeOutcome(o, nameOf),
        hits: acc.hits[i],
        n: acc.n,
        p: acc.n ? acc.hits[i] / acc.n : 0,
        lo,
        hi,
        meanTimeS: times.length ? times.reduce((a, v) => a + v, 0) / times.length : null,
        timeHist: hist,
      };
    });
    const sensitivity: SensitivityRow[] = [];
    spec.perturbations.forEach((p, pi) => {
      const xs = acc.values[pi];
      if (xs.some((v) => Number.isNaN(v))) return;
      spec.outcomes.forEach((o, oi) => {
        const flags = acc.flags[oi];
        const hit = xs.filter((_, r) => flags[r] === 1);
        const not = xs.filter((_, r) => flags[r] === 0);
        const mean = (a: number[]) => (a.length ? a.reduce((s, v) => s + v, 0) / a.length : null);
        sensitivity.push({
          perturbationId: p.id,
          label: p.label ?? p.id,
          outcomeId: o.id,
          corr: hit.length && not.length ? pearson(xs, flags) : 0,
          meanWhenHit: mean(hit),
          meanWhenNot: mean(not),
        });
      });
    });
    const sv = sweepValues[g];
    return {
      label: spec.sweep && sv !== undefined ? sweepLabel(spec.sweep, sv) : 'All runs',
      sweepValue: sv,
      runs: acc.n,
      outcomes,
      sensitivity,
      hitRuns: Object.fromEntries(spec.outcomes.map((o, i) => [o.id, acc.hitRuns[i]])),
      missRuns: Object.fromEntries(spec.outcomes.map((o, i) => [o.id, acc.missRuns[i]])),
      metrics: METRICS.map((label, i) => ({ label, mean: acc.n ? acc.metricSums[i] / acc.n : 0 })),
    };
  });
  return { groups, stopped, elapsedMs: performance.now() - started, totalRuns: done };
}
