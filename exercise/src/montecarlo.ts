import { formatClock, offsetM } from './geo';
import { SENSORS, SHIP_CLASSES, isMine, isMissile, isPlatform } from './ships';
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
  'signature',
  'radarRangeM',
  'decoys',
  'pDecoy',
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
    case 'signature':
      return u.signature ?? 1;
    case 'radarRangeM':
      return u.radarRangeM ?? SENSORS[u.classId]?.radarRangeM ?? 0;
    case 'decoys':
      return u.decoys ?? 0;
    case 'pDecoy':
      return u.pDecoy ?? 0.3;
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
    case 'signature':
      return (u.signature = Math.max(0.001, v));
    case 'radarRangeM':
      return (u.radarRangeM = Math.max(0, v));
    case 'decoys':
      return (u.decoys = Math.max(0, Math.round(v)));
    case 'pDecoy':
      return (u.pDecoy = clamp(v, 0, 1));
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
    case 'detected': {
      const sideOf = (id?: string) => (id ? units.get(id)?.side : undefined);
      return first((e) => e.type === 'detected' && e.unitId === o.unitId && (o.bySide === undefined || sideOf(e.otherId) === o.bySide));
    }
    case 'all':
    case 'any':
    case 'not':
      // Built from other outcomes, so it needs their results: see evaluateOutcomes.
      return { hit: false };
  }
}

/** Every outcome of a run, in order. Combinations (all, any, not) read the results of the outcomes listed before them. */
export function evaluateOutcomes(scenario: ScenarioConfig, traj: Trajectory, outcomes: OutcomeSpec[]): OutcomeResult[] {
  const byId = new Map<string, OutcomeResult>();
  return outcomes.map((o) => {
    let r: OutcomeResult;
    if (o.type === 'all' || o.type === 'any') {
      const parts = o.of.map((id) => byId.get(id) ?? { hit: false });
      const hits = parts.filter((p) => p.hit);
      const times = hits.map((p) => p.tS).filter((t): t is number => t !== undefined);
      if (o.type === 'all') r = parts.length > 0 && hits.length === parts.length ? { hit: true, tS: times.length ? Math.max(...times) : undefined } : { hit: false };
      else r = hits.length > 0 ? { hit: true, tS: times.length ? Math.min(...times) : undefined } : { hit: false };
    } else if (o.type === 'not') {
      r = byId.get(o.of)?.hit ? { hit: false } : { hit: true };
    } else {
      r = evaluateOutcome(scenario, traj, o);
    }
    if (o.beforeS !== undefined && r.hit && (r.tS ?? 0) > o.beforeS) r = { hit: false };
    byId.set(o.id, r);
    return r;
  });
}

export function describeOutcome(o: OutcomeSpec, name: (id: string) => string, outcomeName: (id: string) => string = (id) => id): string {
  if (o.label) return o.label;
  const when = o.beforeS !== undefined ? ` before T+${formatClock(o.beforeS)}` : '';
  switch (o.type) {
    case 'destroyed':
      return `${name(o.unitId)} destroyed${when}`;
    case 'hit':
      return `${name(o.unitId)} hit${when}`;
    case 'hp_below':
      return `${name(o.unitId)} below ${Math.round(o.frac * 100)}% strength${when}`;
    case 'side_losses':
      return `${o.atLeast}+ ${o.side.toLowerCase()} losses${when}`;
    case 'mine_strike':
      return `${o.unitId ? `${name(o.unitId)} strikes a mine` : 'A mine goes off'}${when}`;
    case 'intercepts':
      return `${o.atLeast}+ missiles shot down${when}`;
    case 'closest_approach':
      return `${name(o.aId)} within ${o.withinM} m of ${name(o.bId)}${when}`;
    case 'detected':
      return `${name(o.unitId)} detected${o.bySide ? ` by ${o.bySide.toLowerCase()}` : ''}${when}`;
    case 'all':
      return `${o.of.map(outcomeName).join(' and ')}${when}`;
    case 'any':
      return `${o.of.map(outcomeName).join(' or ')}${when}`;
    case 'not':
      return `Not: ${outcomeName(o.of)}${when}`;
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
  /** Half the width of the 95% interval: the "±" on the chance. */
  halfWidth: number;
  /** Runs in all this outcome needs for the interval to be as narrow as the target (the spec's, or ±2 points), at the chance seen so far. */
  runsNeeded: number;
}

/** The chance of an outcome as the batch went on, so it can be seen settling. */
export interface TracePoint {
  n: number;
  p: number;
  lo: number;
  hi: number;
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
  /** How each outcome's chance settled as runs accumulated, by outcome id. */
  trace: Record<string, TracePoint[]>;
}

export interface McResult {
  groups: McGroup[];
  stopped: boolean;
  /** The batch ended early because every interval reached the target precision. */
  converged: boolean;
  elapsedMs: number;
  totalRuns: number;
}

export interface McOptions {
  onProgress?: (done: number, total: number) => void;
  shouldStop?: () => boolean;
  /** Worker threads to use. 0 keeps everything on the calling thread. Default: as many as the machine has to spare. */
  workers?: number;
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
  if (spec.targetHalfWidth !== undefined && !(spec.targetHalfWidth > 0 && spec.targetHalfWidth <= 0.5)) errors.push('The target precision must be above 0 and at most 50 points.');
  const outcomeIds = new Set<string>();
  for (const o of spec.outcomes) {
    const earlier = new Set(outcomeIds);
    if (outcomeIds.has(o.id)) errors.push(`Two outcomes share the id "${o.id}".`);
    outcomeIds.add(o.id);
    const what = `Outcome "${o.label ?? o.id}"`;
    if (o.beforeS !== undefined && !(o.beforeS > 0)) errors.push(`${what}: the time limit must be above zero.`);
    if (o.type === 'detected' && o.bySide !== undefined && !SIDES.includes(o.bySide)) errors.push(`${what}: unknown side.`);
    if (o.type === 'detected' && !base.detection) errors.push(`${what}: turn on "Sensors and detection" for the scenario, or nothing is ever detected.`);
    if (o.type === 'all' || o.type === 'any' || o.type === 'not') {
      const refs = o.type === 'not' ? [o.of] : o.of;
      if (refs.length === 0) errors.push(`${what}: pick at least one outcome to combine.`);
      for (const r of refs) if (!earlier.has(r)) errors.push(`${what}: "${r}" is not an outcome listed before it.`);
    }
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

export const METRICS = ['Hits on ships per run', 'Missiles shot down per run', 'Blue losses per run', 'Red losses per run', 'Mines triggered per run'];

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

/** What one run contributes to a batch. Plain data, so a worker can send it back. */
export interface RunRecord {
  k: number;
  /** Which sweep value (index) it was run at. */
  g: number;
  /** 1 where each outcome happened. */
  flags: number[];
  /** When each outcome happened, or -1. */
  times: number[];
  values: number[];
  metrics: number[];
}

export function simulateRun(base: ScenarioConfig, spec: RedTeamSpec, k: number, g: number, sweepValue?: number): RunRecord {
  const run = prepareRun(base, spec, k, sweepValue);
  const traj = runScenario(run.scenario, { seed: run.seed });
  const results = evaluateOutcomes(run.scenario, traj, spec.outcomes);
  return {
    k,
    g,
    flags: results.map((r) => (r.hit ? 1 : 0)),
    times: results.map((r) => (r.hit && r.tS !== undefined ? r.tS : -1)),
    values: spec.perturbations.map((p) => run.values[p.id]),
    metrics: metricsOf(run.scenario, traj),
  };
}

/** Run `k0` up to (not including) `k1` at every sweep value. This is the unit of work handed to a worker. */
export function simulateChunk(base: ScenarioConfig, spec: RedTeamSpec, k0: number, k1: number): RunRecord[] {
  const sweepValues = spec.sweep ? spec.sweep.values : [undefined];
  const out: RunRecord[] = [];
  for (let k = k0; k < k1; k++) sweepValues.forEach((sv, g) => out.push(simulateRun(base, spec, k, g, sv)));
  return out;
}

// ---- running a batch ----

/** Somewhere to run chunks: the calling thread, or a pool of workers. */
interface Backend {
  slots: number;
  run(slot: number, k0: number, k1: number): Promise<RunRecord[]>;
  close(): void;
}

function mainBackend(base: ScenarioConfig, spec: RedTeamSpec): Backend {
  return {
    slots: 1,
    run: async (_slot, k0, k1) => {
      await yieldToUi();
      return simulateChunk(base, spec, k0, k1);
    },
    close: () => undefined,
  };
}

function workerCount(requested?: number): number {
  if (requested !== undefined) return Math.max(0, Math.floor(requested));
  if (typeof Worker === 'undefined') return 0;
  const cores = typeof navigator !== 'undefined' && navigator.hardwareConcurrency ? navigator.hardwareConcurrency : 4;
  return Math.max(1, Math.min(8, cores - 1));
}

function poolBackend(size: number, base: ScenarioConfig, spec: RedTeamSpec): Backend | null {
  if (size < 1 || typeof Worker === 'undefined') return null;
  try {
    type Pending = { resolve: (r: RunRecord[]) => void; reject: (e: Error) => void };
    const workers: Worker[] = [];
    const pending: (Pending | null)[] = [];
    for (let i = 0; i < size; i++) {
      const w = new Worker(new URL('./mcWorker.ts', import.meta.url), { type: 'module' });
      const slot = i;
      pending.push(null);
      w.onmessage = (e: MessageEvent<{ records?: RunRecord[]; error?: string }>) => {
        const p = pending[slot];
        pending[slot] = null;
        if (!p) return;
        if (e.data.error) p.reject(new Error(e.data.error));
        else p.resolve(e.data.records ?? []);
      };
      w.onerror = (e) => {
        const p = pending[slot];
        pending[slot] = null;
        p?.reject(new Error(e.message || 'A worker failed.'));
      };
      w.postMessage({ type: 'init', base, spec });
      workers.push(w);
    }
    return {
      slots: size,
      run: (slot, k0, k1) =>
        new Promise<RunRecord[]>((resolve, reject) => {
          pending[slot] = { resolve, reject };
          workers[slot].postMessage({ type: 'chunk', k0, k1 });
        }),
      close: () => workers.forEach((w) => w.terminate()),
    };
  } catch {
    return null;
  }
}

interface Acc {
  hits: number[];
  times: number[][];
  values: number[][];
  flags: number[][];
  hitRuns: number[][];
  missRuns: number[][];
  metricSums: number[];
  trace: { n: number; hits: number[] }[];
  n: number;
}

const halfWidthOf = (hits: number, n: number) => {
  const { lo, hi } = wilson(hits, n);
  return (hi - lo) / 2;
};

/** Runs in all needed for a 95% half-width of `target` when the chance is `p` (normal approximation, with p kept off 0 and 1). */
export function runsNeeded(p: number, target: number): number {
  const q = Math.min(0.95, Math.max(0.05, p));
  return Math.ceil((1.96 * 1.96 * q * (1 - q)) / (target * target));
}

const MIN_RUNS_TO_CONVERGE = 40;
const CHUNK_TASKS = 8;

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
    trace: [],
    n: 0,
  }));
  const traceEvery = Math.max(1, Math.floor(spec.runs / 24));

  const kPer = Math.max(1, Math.ceil(CHUNK_TASKS / sweepValues.length));
  const nChunks = Math.ceil(spec.runs / kPer);
  let backend: Backend = poolBackend(workerCount(options.workers), base, spec) ?? mainBackend(base, spec);

  let done = 0;
  let stopped = false;
  let converged = false;
  let finished = false;

  const accumulate = (r: RunRecord) => {
    const acc = accs[r.g];
    r.flags.forEach((f, i) => {
      acc.flags[i].push(f);
      if (f) {
        acc.hits[i]++;
        if (r.times[i] >= 0) acc.times[i].push(r.times[i]);
        if (acc.hitRuns[i].length < 8) acc.hitRuns[i].push(r.k);
      } else if (acc.missRuns[i].length < 8) acc.missRuns[i].push(r.k);
    });
    r.values.forEach((v, i) => acc.values[i].push(v));
    r.metrics.forEach((v, i) => (acc.metricSums[i] += v));
    acc.n++;
    if (acc.n % traceEvery === 0) acc.trace.push({ n: acc.n, hits: [...acc.hits] });
    done++;
  };

  const isConverged = () =>
    spec.targetHalfWidth !== undefined &&
    accs.every((a) => a.n >= MIN_RUNS_TO_CONVERGE && a.hits.every((h) => halfWidthOf(h, a.n) <= spec.targetHalfWidth!));

  await new Promise<void>((resolve) => {
    const results = new Map<number, RunRecord[]>();
    const free = Array.from({ length: backend.slots }, (_, i) => i);
    let nextLaunch = 0;
    let nextApply = 0;

    const finish = () => {
      if (finished) return;
      finished = true;
      backend.close();
      resolve();
    };

    const apply = () => {
      while (!finished && results.has(nextApply)) {
        for (const r of results.get(nextApply)!) accumulate(r);
        results.delete(nextApply);
        nextApply++;
        options.onProgress?.(done, total);
        if (options.shouldStop?.()) {
          stopped = true;
          return finish();
        }
        if (nextApply < nChunks && isConverged()) {
          converged = true;
          return finish();
        }
      }
      if (nextApply >= nChunks) finish();
    };

    const pump = () => {
      while (!finished && free.length && nextLaunch < nChunks) {
        const slot = free.pop()!;
        const c = nextLaunch++;
        const launchedOn = backend;
        const k0 = c * kPer;
        const k1 = Math.min(spec.runs, k0 + kPer);
        launchedOn.run(slot, k0, k1).then(
          (recs) => {
            if (launchedOn !== backend) return; // from workers that have since been abandoned
            free.push(slot);
            results.set(c, recs);
            apply();
            pump();
          },
          () => {
            if (launchedOn !== backend) return;
            // The workers could not run (blocked, or crashed). Carry on from the first chunk not yet received, on the calling thread.
            launchedOn.close();
            backend = mainBackend(base, spec);
            free.length = 0;
            free.push(0);
            nextLaunch = nextApply;
            for (let i = nextApply; i < nChunks; i++) results.delete(i);
            pump();
          },
        );
      }
    };
    pump();
  });
  options.onProgress?.(done, total);

  const groups: McGroup[] = accs.map((acc, g) => {
    const target = spec.targetHalfWidth ?? 0.02;
    const outcomes: OutcomeStat[] = spec.outcomes.map((o, i) => {
      const { lo, hi } = wilson(acc.hits[i], acc.n);
      const times = acc.times[i];
      const hist = new Array<number>(HIST_BINS).fill(0);
      for (const t of times) hist[Math.min(HIST_BINS - 1, Math.floor((t / base.durationS) * HIST_BINS))]++;
      const p = acc.n ? acc.hits[i] / acc.n : 0;
      return {
        id: o.id,
        label: describeOutcome(o, nameOf, (id) => {
          const ref = spec.outcomes.find((x) => x.id === id);
          return ref ? describeOutcome(ref, nameOf) : id;
        }),
        hits: acc.hits[i],
        n: acc.n,
        p,
        lo,
        hi,
        meanTimeS: times.length ? times.reduce((a, v) => a + v, 0) / times.length : null,
        timeHist: hist,
        halfWidth: (hi - lo) / 2,
        runsNeeded: runsNeeded(p, target),
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
    const trace: Record<string, TracePoint[]> = {};
    spec.outcomes.forEach((o, i) => {
      const pts = acc.trace.map((t) => ({ n: t.n, p: t.hits[i] / t.n, ...wilson(t.hits[i], t.n) }));
      const last = acc.trace[acc.trace.length - 1];
      if (acc.n > 0 && (!last || last.n !== acc.n)) pts.push({ n: acc.n, p: acc.hits[i] / acc.n, ...wilson(acc.hits[i], acc.n) });
      trace[o.id] = pts;
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
      trace,
    };
  });
  return { groups, stopped, converged, elapsedMs: performance.now() - started, totalRuns: done };
}

// ---- comparing two batches ----

export interface OutcomeDelta {
  id: string;
  label: string;
  /** Chance in the baseline and in the new batch. */
  before: number;
  after: number;
  delta: number;
  /** 95% interval on the difference (Newcombe's method on the two Wilson intervals). */
  lo: number;
  hi: number;
  /** The interval on the difference excludes zero. */
  significant: boolean;
}

export interface GroupDelta {
  label: string;
  rows: OutcomeDelta[];
}

/** How each outcome's chance moved between a baseline batch and a new one. Outcomes and sweep values are matched up by id and value. */
export function compareResults(before: McResult, after: McResult): GroupDelta[] {
  return after.groups.flatMap((g, gi) => {
    const other = before.groups.find((x) => x.sweepValue !== undefined && x.sweepValue === g.sweepValue) ?? (g.sweepValue === undefined ? before.groups[gi] : undefined);
    if (!other) return [];
    const rows: OutcomeDelta[] = [];
    for (const o of g.outcomes) {
      const b = other.outcomes.find((x) => x.id === o.id);
      if (!b) continue;
      const delta = o.p - b.p;
      const lo = delta - Math.sqrt((o.p - o.lo) ** 2 + (b.hi - b.p) ** 2);
      const hi = delta + Math.sqrt((o.hi - o.p) ** 2 + (b.p - b.lo) ** 2);
      rows.push({ id: o.id, label: o.label, before: b.p, after: o.p, delta, lo, hi, significant: lo > 0 || hi < 0 });
    }
    return [{ label: g.label, rows }];
  });
}
