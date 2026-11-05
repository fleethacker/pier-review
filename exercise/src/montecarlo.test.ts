import { describe, expect, it, vi } from 'vitest';
import { destination, distanceM } from './geo';
import {
  defaultRedTeam,
  describeOutcome,
  evaluateOutcome,
  prepareRun,
  runMonteCarlo,
  sampleDist,
  sweepLabel,
  validateRedTeam,
  wilson,
} from './montecarlo';
import { parseRedTeam, parseScenario } from './scenarioJson';
import { PRESET_SCENARIOS, blankScenario } from './scenarios';
import { makeRng, runScenario, unitStateAt } from './sim';
import type { Dist, Environment, OutcomeSpec, Perturbation, RedTeamSpec, ScenarioConfig, UnitConfig } from './types';

// Batches of many runs are slow when the whole suite runs at once.
vi.setConfig({ testTimeout: 60_000 });

const C = { lon: -62, lat: 33 };
const still: Environment = { windFromDeg: 0, windKt: 0, currentToDeg: 0, currentKt: 0 };

function unit(patch: Partial<UnitConfig> & Pick<UnitConfig, 'id'>): UnitConfig {
  return { name: patch.id, classId: 'DDG', side: 'BLUE', start: C, headingDeg: 90, speedKt: 0, behavior: { type: 'hold' }, magazine: 0, ...patch };
}

function scenario(units: UnitConfig[], durationS = 500): ScenarioConfig {
  return { id: 't', name: 't', description: '', center: C, durationS, lightPreset: 'day', environment: still, units };
}

const shooter = () => unit({ id: 'shooter', side: 'RED', start: destination(C, 0, 20_000) });
const asm = (id: string, atS: number, patch: Partial<UnitConfig> = {}): UnitConfig =>
  unit({ id, classId: 'ASM', side: 'RED', speedKt: 300, launch: { byId: 'shooter', atS }, behavior: { type: 'strike', targetId: 'tgt' }, ...patch });
const target = (patch: Partial<UnitConfig> = {}) => unit({ id: 'tgt', ...patch });

const hitOutcome: OutcomeSpec = { id: 'hit', type: 'hit', unitId: 'tgt' };
const pHitVar = (min = 0, max = 1): Perturbation => ({ id: 'p', target: { kind: 'unit', unitId: 'm', field: 'pHit' }, mode: 'set', dist: { type: 'uniform', min, max } });

function spec(patch: Partial<RedTeamSpec> = {}): RedTeamSpec {
  return { runs: 50, seed: 1, perturbations: [], outcomes: [hitOutcome], ...patch };
}

describe('sampleDist', () => {
  const draw = (d: Dist, n = 4000, seed = 1) => {
    const rng = makeRng(seed);
    return Array.from({ length: n }, () => sampleDist(d, rng));
  };
  const mean = (xs: number[]) => xs.reduce((a, v) => a + v, 0) / xs.length;
  const sd = (xs: number[]) => Math.sqrt(mean(xs.map((v) => (v - mean(xs)) ** 2)));

  it('draws uniformly between the limits', () => {
    const xs = draw({ type: 'uniform', min: 10, max: 20 });
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(10);
    expect(Math.max(...xs)).toBeLessThan(20);
    expect(mean(xs)).toBeCloseTo(15, 0);
  });
  it('draws normally around a mean with a spread', () => {
    const xs = draw({ type: 'normal', mean: 5, sd: 2 });
    expect(mean(xs)).toBeCloseTo(5, 0);
    expect(sd(xs)).toBeCloseTo(2, 0);
    expect(draw({ type: 'normal', mean: 5, sd: 0 }, 5).every((v) => v === 5)).toBe(true);
  });
  it('draws triangularly, between the limits and leaning to the mode', () => {
    const xs = draw({ type: 'triangular', min: 0, mode: 2, max: 10 });
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...xs)).toBeLessThanOrEqual(10);
    expect(mean(xs)).toBeCloseTo(4, 0);
    expect(draw({ type: 'triangular', min: 3, mode: 3, max: 3 }, 3)).toEqual([3, 3, 3]);
  });
  it('picks from a list, evenly or by weight', () => {
    const even = draw({ type: 'choice', values: [1, 2, 3, 4] });
    for (const v of [1, 2, 3, 4]) expect(even.filter((x) => x === v).length / even.length).toBeCloseTo(0.25, 1);
    const weighted = draw({ type: 'choice', values: [0, 1], weights: [9, 1] });
    expect(mean(weighted)).toBeCloseTo(0.1, 1);
    expect(draw({ type: 'choice', values: [7] }, 3)).toEqual([7, 7, 7]);
  });
  it('gives the same draws for the same seed', () => {
    const d: Dist = { type: 'normal', mean: 0, sd: 1 };
    expect(draw(d, 10, 9)).toEqual(draw(d, 10, 9));
    expect(draw(d, 10, 9)).not.toEqual(draw(d, 10, 10));
  });
});

describe('wilson interval', () => {
  it('matches known values and behaves at the ends', () => {
    const a = wilson(0, 10);
    expect(a.lo).toBe(0);
    expect(a.hi).toBeCloseTo(0.278, 2);
    const b = wilson(5, 10);
    expect(b.lo).toBeCloseTo(0.237, 2);
    expect(b.hi).toBeCloseTo(0.763, 2);
    const c = wilson(10, 10);
    expect(c.lo).toBeCloseTo(0.722, 2);
    expect(c.hi).toBe(1);
    expect(wilson(0, 0)).toEqual({ lo: 0, hi: 1 });
  });
  it('narrows as runs increase', () => {
    const w = (n: number) => wilson(n / 2, n);
    expect(w(1000).hi - w(1000).lo).toBeLessThan((w(100).hi - w(100).lo) / 2);
  });
});

describe('prepareRun', () => {
  const base = scenario([shooter(), target(), asm('m', 0)]);
  const withP = (p: Perturbation) => prepareRun(base, spec({ perturbations: [p] }), 0);
  const unitOf = (r: ReturnType<typeof prepareRun>, id: string) => r.scenario.units.find((u) => u.id === id)!;

  it('is the same every time for the same batch and run number, and different for other runs', () => {
    const s = spec({ perturbations: [pHitVar()] });
    const a = prepareRun(base, s, 3);
    const b = prepareRun(base, s, 3);
    expect(a).toEqual(b);
    expect(prepareRun(base, s, 4).values.p).not.toBe(a.values.p);
    expect(prepareRun(base, { ...s, seed: 2 }, 3).values.p).not.toBe(a.values.p);
    expect(prepareRun(base, s, 3).seed).not.toBe(prepareRun(base, s, 4).seed);
  });

  it('does not change the scenario it starts from, and leaves the red-team settings out of the copy', () => {
    const before = JSON.stringify(base);
    const withSpec = { ...base, redTeam: spec() };
    const r = prepareRun(withSpec, spec({ perturbations: [pHitVar()] }), 0);
    expect(JSON.stringify(base)).toBe(before);
    expect(r.scenario.redTeam).toBeUndefined();
    expect(unitOf(r, 'm')).not.toBe(base.units[2]);
  });

  it('sets, adds to, or scales a value', () => {
    const mk = (mode: Perturbation['mode'], v: number) => withP({ id: 'p', target: { kind: 'unit', unitId: 'tgt', field: 'speedKt' }, mode, dist: { type: 'choice', values: [v] } });
    const s = scenario([shooter(), target({ speedKt: 10 }), asm('m', 0)]);
    const run = (mode: Perturbation['mode'], v: number) => prepareRun(s, spec({ perturbations: [{ id: 'p', target: { kind: 'unit', unitId: 'tgt', field: 'speedKt' }, mode, dist: { type: 'choice', values: [v] } }] }), 0).scenario.units[1].speedKt;
    expect(run('set', 4)).toBe(4);
    expect(run('add', 4)).toBe(14);
    expect(run('scale', 3)).toBe(30);
    expect(mk('set', 1).values.p).toBe(1);
  });

  it('starts from the class default for things the unit does not set', () => {
    const run = (mode: Perturbation['mode'], v: number) =>
      prepareRun(base, spec({ perturbations: [{ id: 'p', target: { kind: 'unit', unitId: 'm', field: 'pHit' }, mode, dist: { type: 'choice', values: [v] } }] }), 0).scenario.units[2].pHit;
    expect(run('scale', 0.5)).toBeCloseTo(0.425, 6);
    expect(run('add', -0.05)).toBeCloseTo(0.8, 6);
  });

  it('keeps values where the scenario can run', () => {
    const pick = (field: Perturbation['target'] & { kind: 'unit' }, v: number, id = 'tgt') =>
      prepareRun(scenario([shooter(), target(), asm('m', 0)]), spec({ perturbations: [{ id: 'p', target: { ...field, unitId: id }, mode: 'set', dist: { type: 'choice', values: [v] } }] }), 0).scenario.units;
    expect(pick({ kind: 'unit', unitId: 'm', field: 'pHit' }, 1.7, 'm')[2].pHit).toBe(1);
    expect(pick({ kind: 'unit', unitId: 'm', field: 'pHit' }, -1, 'm')[2].pHit).toBe(0);
    expect(pick({ kind: 'unit', unitId: 'tgt', field: 'hp' }, -5)[1].hp).toBe(1);
    expect(pick({ kind: 'unit', unitId: 'tgt', field: 'headingDeg' }, -90)[1].headingDeg).toBe(270);
    expect(pick({ kind: 'unit', unitId: 'tgt', field: 'magazine' }, 2.6)[1].magazine).toBe(3);
    expect(pick({ kind: 'unit', unitId: 'tgt', field: 'speedKt' }, -4)[1].speedKt).toBe(0);
    expect(pick({ kind: 'unit', unitId: 'tgt', field: 'disabled' }, 1)[1].disabled).toBe(true);
    expect(pick({ kind: 'unit', unitId: 'tgt', field: 'disabled' }, 0.2)[1].disabled).toBe(false);
  });

  it('shifts positions and routes by an offset in meters, whatever the mode', () => {
    const s = scenario([unit({ id: 'tgt', speedKt: 10, behavior: { type: 'route', waypoints: [destination(C, 90, 10_000), destination(C, 90, 20_000)] } }), shooter(), asm('m', 0)]);
    const r = prepareRun(
      s,
      spec({
        perturbations: [
          { id: 'e', target: { kind: 'unit', unitId: 'tgt', field: 'startEastM' }, mode: 'scale', dist: { type: 'choice', values: [300] } },
          { id: 'n', target: { kind: 'unit', unitId: 'tgt', field: 'routeNorthM' }, mode: 'set', dist: { type: 'choice', values: [500] } },
        ],
      }),
      0,
    );
    const moved = r.scenario.units[0];
    expect(distanceM(moved.start, C)).toBeCloseTo(300, -1);
    expect(moved.start.lon).toBeGreaterThan(C.lon);
    const wp = moved.behavior.type === 'route' ? moved.behavior.waypoints : [];
    expect(distanceM(wp[0], destination(C, 90, 10_000))).toBeCloseTo(500, -1);
    expect(wp[1].lat).toBeGreaterThan(s.units[0].behavior.type === 'route' ? s.units[0].behavior.waypoints[1].lat : 0);
  });

  it('changes the environment and clamps it', () => {
    const run = (field: 'windKt' | 'windFromDeg', mode: Perturbation['mode'], v: number) =>
      prepareRun(base, spec({ perturbations: [{ id: 'p', target: { kind: 'environment', field }, mode, dist: { type: 'choice', values: [v] } }] }), 0).scenario.environment[field];
    expect(run('windKt', 'add', 12)).toBe(12);
    expect(run('windKt', 'add', -5)).toBe(0);
    expect(run('windFromDeg', 'add', -30)).toBe(330);
  });

  it('moves a launch time only for units that are launched, and marks the rest as not applying', () => {
    const r = prepareRun(
      base,
      spec({
        perturbations: [
          { id: 'a', target: { kind: 'unit', unitId: 'm', field: 'launchAtS' }, mode: 'add', dist: { type: 'choice', values: [40] } },
          { id: 'b', target: { kind: 'unit', unitId: 'tgt', field: 'launchAtS' }, mode: 'add', dist: { type: 'choice', values: [40] } },
          { id: 'c', target: { kind: 'unit', unitId: 'ghost', field: 'pHit' }, mode: 'set', dist: { type: 'choice', values: [1] } },
        ],
      }),
      0,
    );
    expect(r.scenario.units[2].launch?.atS).toBe(40);
    expect(r.scenario.units[1].launch).toBeUndefined();
    expect(Number.isNaN(r.values.b)).toBe(true);
    expect(Number.isNaN(r.values.c)).toBe(true);
  });

  it('applies a sweep before the random draws: a salvo enables only the first few, a value sets a field', () => {
    const s = scenario([shooter(), target(), asm('a', 0), asm('b', 5), asm('c', 10)]);
    const salvo = { ...spec(), sweep: { target: { kind: 'salvo' as const, unitIds: ['a', 'b', 'c'] }, values: [2] } };
    const r = prepareRun(s, salvo, 0, 2);
    expect(r.scenario.units.slice(2).map((u) => !!u.disabled)).toEqual([false, false, true]);
    const field = { ...spec(), sweep: { target: { kind: 'unit' as const, unitId: 'a', field: 'pHit' as const }, values: [0.3] } };
    expect(prepareRun(s, field, 0, 0.3).scenario.units[2].pHit).toBe(0.3);
    expect(sweepLabel(salvo.sweep, 2)).toBe('2 of 3 enabled');
    expect(sweepLabel(field.sweep, 0.3)).toBe('a pHit = 0.3');
    expect(sweepLabel({ target: { kind: 'environment', field: 'windKt' }, values: [] }, 20)).toBe('windKt = 20');
  });
});

describe('evaluateOutcome', () => {
  const sure = (p: Partial<UnitConfig> = {}) => asm('m', 10, { pHit: 1, ...p });
  const result = (units: UnitConfig[]) => {
    const s = scenario(units, 600);
    return { s, t: runScenario(s, { seed: 1 }) };
  };
  const ask = (units: UnitConfig[], o: OutcomeSpec) => {
    const { s, t } = result(units);
    return evaluateOutcome(s, t, o);
  };

  it('sees a hit, and when it happened', () => {
    const r = ask([shooter(), target(), sure()], hitOutcome);
    expect(r.hit).toBe(true);
    expect(r.tS).toBeGreaterThan(70);
    expect(ask([shooter(), target(), sure({ pHit: 0 })], hitOutcome).hit).toBe(false);
    expect(ask([shooter(), target()], hitOutcome).hit).toBe(false);
  });

  it('sees destruction, and losses by side, counting only ships and aircraft', () => {
    const units = [shooter(), target({ hp: 50 }), sure({ damage: 100 })];
    expect(ask(units, { id: 'd', type: 'destroyed', unitId: 'tgt' }).hit).toBe(true);
    expect(ask([shooter(), target(), sure()], { id: 'd', type: 'destroyed', unitId: 'tgt' }).hit).toBe(false);
    expect(ask(units, { id: 'l', type: 'side_losses', side: 'BLUE', atLeast: 1 }).hit).toBe(true);
    expect(ask(units, { id: 'l', type: 'side_losses', side: 'BLUE', atLeast: 2 }).hit).toBe(false);
    expect(ask(units, { id: 'l', type: 'side_losses', side: 'RED', atLeast: 1 }).hit).toBe(false);
  });

  it('sees a loss of strength once it falls below the fraction', () => {
    const units = [shooter(), target(), sure()];
    expect(ask(units, { id: 'h', type: 'hp_below', unitId: 'tgt', frac: 0.5 }).hit).toBe(true);
    expect(ask(units, { id: 'h', type: 'hp_below', unitId: 'tgt', frac: 0.3 }).hit).toBe(false);
  });

  it('sees mine strikes, for any ship or a particular one', () => {
    const mine = unit({ id: 'mine', classId: 'MINE', side: 'RED', start: destination(C, 90, 3000), pHit: 1 });
    const ship = unit({ id: 'tgt', speedKt: 15, behavior: { type: 'route', waypoints: [destination(C, 90, 8000)] } });
    const other = unit({ id: 'other', start: destination(C, 0, 5000) });
    expect(ask([ship, mine, other], { id: 'm', type: 'mine_strike' }).hit).toBe(true);
    expect(ask([ship, mine, other], { id: 'm', type: 'mine_strike', unitId: 'tgt' }).hit).toBe(true);
    expect(ask([ship, mine, other], { id: 'm', type: 'mine_strike', unitId: 'other' }).hit).toBe(false);
    expect(ask([ship, mine, other], hitOutcome).hit).toBe(true);
  });

  it('counts missiles shot down, reaching the count at the right time', () => {
    const defended = [shooter(), target({ pKill: 1, magazine: 9 }), asm('a', 0), asm('b', 0)];
    expect(ask(defended, { id: 'i', type: 'intercepts', atLeast: 1 }).hit).toBe(true);
    expect(ask(defended, { id: 'i', type: 'intercepts', atLeast: 3 }).hit).toBe(false);
    const one = ask(defended, { id: 'i', type: 'intercepts', atLeast: 1 }).tS!;
    const two = ask(defended, { id: 'i', type: 'intercepts', atLeast: 2 }).tS;
    expect(two === undefined || two >= one).toBe(true);
  });

  it('sees two units pass close, horizontally, even between steps', () => {
    const a = unit({ id: 'a', speedKt: 30, behavior: { type: 'route', waypoints: [destination(C, 90, 20_000)] } });
    const b = unit({ id: 'b', start: destination(destination(C, 90, 9000), 0, 300), speedKt: 0 });
    expect(ask([a, b], { id: 'c', type: 'closest_approach', aId: 'a', bId: 'b', withinM: 500 }).hit).toBe(true);
    const when = ask([a, b], { id: 'c', type: 'closest_approach', aId: 'a', bId: 'b', withinM: 400 }).tS!;
    expect(when).toBeGreaterThan(500);
    expect(when).toBeLessThan(700);
    expect(ask([a, b], { id: 'c', type: 'closest_approach', aId: 'a', bId: 'b', withinM: 100 }).hit).toBe(false);
    expect(ask([a, b], { id: 'c', type: 'closest_approach', aId: 'a', bId: 'ghost', withinM: 5000 }).hit).toBe(false);
  });

  it('describes outcomes in words', () => {
    const name = (id: string) => `<${id}>`;
    expect(describeOutcome({ id: 'x', label: 'Mine label', type: 'hit', unitId: 'a' }, name)).toBe('Mine label');
    expect(describeOutcome({ id: 'x', type: 'destroyed', unitId: 'a' }, name)).toBe('<a> destroyed');
    expect(describeOutcome({ id: 'x', type: 'hp_below', unitId: 'a', frac: 0.5 }, name)).toBe('<a> below 50% strength');
    expect(describeOutcome({ id: 'x', type: 'side_losses', side: 'BLUE', atLeast: 2 }, name)).toBe('2+ blue losses');
    expect(describeOutcome({ id: 'x', type: 'closest_approach', aId: 'a', bId: 'b', withinM: 500 }, name)).toBe('<a> within 500 m of <b>');
  });
});

describe('validateRedTeam', () => {
  const base = scenario([shooter(), target(), asm('m', 0)]);
  const errs = (patch: Partial<RedTeamSpec>) => validateRedTeam(base, spec(patch)).join('\n');

  it('accepts a sound setup', () => {
    expect(errs({ perturbations: [pHitVar()] })).toBe('');
  });
  it('rejects bad run counts, seeds and missing outcomes', () => {
    expect(errs({ runs: 0 })).toContain('Runs');
    expect(errs({ runs: 1.5 })).toContain('Runs');
    expect(errs({ runs: 50_000 })).toContain('Runs');
    expect(errs({ seed: NaN })).toContain('seed');
    expect(errs({ outcomes: [] })).toContain('at least one outcome');
  });
  it('rejects references to units that are not there, and repeated ids', () => {
    expect(errs({ outcomes: [{ id: 'a', type: 'destroyed', unitId: 'ghost' }] })).toContain('"ghost"');
    expect(errs({ outcomes: [hitOutcome, hitOutcome] })).toContain('share the id');
    expect(errs({ perturbations: [pHitVar(), pHitVar()] })).toContain('share the id');
    expect(errs({ perturbations: [{ ...pHitVar(), target: { kind: 'unit', unitId: 'ghost', field: 'pHit' } }] })).toContain('"ghost"');
    expect(errs({ outcomes: [{ id: 'c', type: 'closest_approach', aId: 'tgt', bId: 'ghost', withinM: 5 }] })).toContain('"ghost"');
  });
  it('rejects nonsense in outcomes', () => {
    expect(errs({ outcomes: [{ id: 'a', type: 'hp_below', unitId: 'tgt', frac: 0 }] })).toContain('fraction');
    expect(errs({ outcomes: [{ id: 'a', type: 'hp_below', unitId: 'tgt', frac: 1.2 }] })).toContain('fraction');
    expect(errs({ outcomes: [{ id: 'a', type: 'side_losses', side: 'BLUE', atLeast: 0 }] })).toContain('at least');
    expect(errs({ outcomes: [{ id: 'a', type: 'intercepts', atLeast: 1.5 }] })).toContain('at least');
    expect(errs({ outcomes: [{ id: 'a', type: 'closest_approach', aId: 'tgt', bId: 'm', withinM: 0 }] })).toContain('distance');
  });
  it('rejects distributions that cannot be drawn from', () => {
    const d = (dist: Dist) => errs({ perturbations: [{ ...pHitVar(), dist }] });
    expect(d({ type: 'uniform', min: 2, max: 1 })).toContain('minimum');
    expect(d({ type: 'normal', mean: 0, sd: -1 })).toContain('deviation');
    expect(d({ type: 'triangular', min: 0, mode: 5, max: 1 })).toContain('min ≤ mode ≤ max');
    expect(d({ type: 'choice', values: [] })).toContain('empty');
    expect(d({ type: 'choice', values: [1, 2], weights: [1] })).toContain('weights');
    expect(d({ type: 'choice', values: [1, 2], weights: [0, 0] })).toContain('weights');
  });
  it('rejects bad sweeps', () => {
    const sw = (sweep: RedTeamSpec['sweep']) => errs({ sweep });
    expect(sw({ target: { kind: 'salvo', unitIds: ['m'] }, values: [] })).toContain('sweep needs');
    expect(sw({ target: { kind: 'salvo', unitIds: ['m'] }, values: Array.from({ length: 31 }, (_, i) => i) })).toContain('sweep needs');
    expect(sw({ target: { kind: 'salvo', unitIds: [] }, values: [1] })).toContain('at least one unit');
    expect(sw({ target: { kind: 'salvo', unitIds: ['ghost'] }, values: [1] })).toContain('"ghost"');
    expect(sw({ target: { kind: 'unit', unitId: 'ghost', field: 'pHit' }, values: [1] })).toContain('"ghost"');
  });
});

describe('runMonteCarlo', () => {
  const single = () => scenario([shooter(), target(), asm('m', 0)]);

  it('finds the probability it was built to have, with an interval that contains it', async () => {
    const r = await runMonteCarlo(single(), spec({ runs: 300, perturbations: [{ ...pHitVar(), dist: { type: 'choice', values: [0.6] } }] }));
    const [o] = r.groups[0].outcomes;
    expect(o.n).toBe(300);
    expect(o.p).toBeGreaterThan(0.5);
    expect(o.p).toBeLessThan(0.7);
    expect(o.lo).toBeLessThan(0.6);
    expect(o.hi).toBeGreaterThan(0.6);
    expect(o.hits).toBe(Math.round(o.p * 300));
    expect(o.meanTimeS).toBeGreaterThan(60);
    expect(o.timeHist.reduce((a, v) => a + v, 0)).toBe(o.hits);
    expect(r.stopped).toBe(false);
    expect(r.totalRuns).toBe(300);
  });

  it('is exactly repeatable', async () => {
    const s = spec({ runs: 40, perturbations: [pHitVar()] });
    const a = await runMonteCarlo(single(), s);
    const b = await runMonteCarlo(single(), s);
    expect(a.groups[0].outcomes).toEqual(b.groups[0].outcomes);
    expect(a.groups[0].sensitivity).toEqual(b.groups[0].sensitivity);
    const c = await runMonteCarlo(single(), { ...s, seed: 99 });
    expect(c.groups[0].outcomes[0].hits).not.toBe(a.groups[0].outcomes[0].hits);
  });

  it('ranks the thing that matters: hit chance drives a hit, an irrelevant variation does not', async () => {
    const wind: Perturbation = { id: 'w', target: { kind: 'environment', field: 'windKt' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 3 } };
    const r = await runMonteCarlo(single(), spec({ runs: 300, perturbations: [pHitVar(), wind] }));
    const rows = r.groups[0].sensitivity;
    const p = rows.find((x) => x.perturbationId === 'p')!;
    const w = rows.find((x) => x.perturbationId === 'w')!;
    expect(p.corr).toBeGreaterThan(0.4);
    expect(p.meanWhenHit!).toBeGreaterThan(p.meanWhenNot!);
    expect(Math.abs(w.corr)).toBeLessThan(0.2);
  });

  it('leaves out variations that did not apply, rather than reporting nonsense', async () => {
    const odd: Perturbation = { id: 'x', target: { kind: 'unit', unitId: 'tgt', field: 'launchAtS' }, mode: 'add', dist: { type: 'uniform', min: 0, max: 1 } };
    const r = await runMonteCarlo(single(), spec({ runs: 10, perturbations: [odd] }));
    expect(r.groups[0].sensitivity).toEqual([]);
  });

  it('sweeps a salvo size and the chance of a hit rises with it', async () => {
    const s = scenario([shooter(), target(), ...Array.from({ length: 6 }, (_, i) => asm(`m${i}`, i * 3, { pHit: 0.5 }))]);
    const r = await runMonteCarlo(
      s,
      spec({ runs: 120, sweep: { target: { kind: 'salvo', unitIds: ['m0', 'm1', 'm2', 'm3', 'm4', 'm5'] }, values: [1, 3, 6] } }),
    );
    expect(r.groups.map((g) => g.label)).toEqual(['1 of 6 enabled', '3 of 6 enabled', '6 of 6 enabled']);
    const p = r.groups.map((g) => g.outcomes[0].p);
    expect(p[0]).toBeGreaterThan(0.3);
    expect(p[0]).toBeLessThan(0.7);
    expect(p[1]).toBeGreaterThan(p[0]);
    expect(p[2]).toBeGreaterThan(p[1]);
    expect(p[2]).toBeGreaterThan(0.9);
    expect(r.groups.map((g) => g.sweepValue)).toEqual([1, 3, 6]);
  });

  it('uses the same draws at every sweep value, so the curve is not noise', () => {
    const s = scenario([shooter(), target(), ...Array.from({ length: 4 }, (_, i) => asm(`m${i}`, i * 3, { pHit: 0.5 }))]);
    const sp = spec({ sweep: { target: { kind: 'salvo', unitIds: ['m0', 'm1', 'm2', 'm3'] }, values: [2, 4] } });
    const hit = (k: number, size: number) => {
      const run = prepareRun(s, sp, k, size);
      return evaluateOutcome(run.scenario, runScenario(run.scenario, { seed: run.seed }), hitOutcome).hit;
    };
    let fewer = 0;
    for (let k = 0; k < 40; k++) {
      // Anything that hit with two missiles also hit with four: the first two behave the same way in both.
      if (hit(k, 2)) expect(hit(k, 4)).toBe(true);
      fewer += hit(k, 2) ? 1 : 0;
    }
    expect(fewer).toBeGreaterThan(10);
    expect(fewer).toBeLessThan(40);
  });

  it('reports progress and stops when asked, keeping what it has', async () => {
    const progress = vi.fn();
    let calls = 0;
    const r = await runMonteCarlo(single(), spec({ runs: 5000 }), {
      onProgress: progress,
      shouldStop: () => ++calls >= 2,
    });
    expect(r.stopped).toBe(true);
    expect(r.totalRuns).toBeGreaterThan(0);
    expect(r.totalRuns).toBeLessThan(5000);
    expect(r.groups[0].runs).toBe(r.totalRuns);
    expect(progress).toHaveBeenCalled();
    const last = progress.mock.calls.at(-1)!;
    expect(last[0]).toBe(r.totalRuns);
    expect(last[1]).toBe(5000);
  });

  it('refuses a scenario or setup that cannot run, with the first problem', async () => {
    await expect(runMonteCarlo(single(), spec({ outcomes: [] }))).rejects.toThrow(/at least one outcome/);
    await expect(runMonteCarlo({ ...single(), durationS: 5 }, spec())).rejects.toThrow(/Duration/);
  });

  it('lists runs to replay, and replaying one reproduces what the batch saw', async () => {
    const s = spec({ runs: 40, perturbations: [pHitVar()] });
    const base = single();
    const r = await runMonteCarlo(base, s);
    const g = r.groups[0];
    expect(g.hitRuns.hit.length).toBeGreaterThan(0);
    expect(g.missRuns.hit.length).toBeGreaterThan(0);
    const check = (k: number) => {
      const run = prepareRun(base, s, k);
      return evaluateOutcome(run.scenario, runScenario(run.scenario, { seed: run.seed }), hitOutcome).hit;
    };
    for (const k of g.hitRuns.hit) expect(check(k)).toBe(true);
    for (const k of g.missRuns.hit) expect(check(k)).toBe(false);
  });

  it('gives averages that match what happened in the runs', async () => {
    const sure = scenario([shooter(), target(), asm('m', 0, { pHit: 1 })]);
    const r = await runMonteCarlo(sure, spec({ runs: 5 }));
    const m = Object.fromEntries(r.groups[0].metrics.map((x) => [x.label, x.mean]));
    expect(m['Hits on ships per run']).toBe(1);
    expect(m['Missiles shot down per run']).toBe(0);
    expect(m['Blue losses per run']).toBe(0);
    const killed = scenario([shooter(), target({ hp: 10 }), asm('m', 0, { pHit: 1 })]);
    const k = await runMonteCarlo(killed, spec({ runs: 5 }));
    expect(Object.fromEntries(k.groups[0].metrics.map((x) => [x.label, x.mean]))['Blue losses per run']).toBe(1);
  });

  it('measures the effect of defences: a ship with shots left is hit far less often', async () => {
    const hitChance = (magazine: number, pKill: number) => {
      // Three missiles well apart, so a ship with a 12 second reload can answer each one.
      const s = scenario([shooter(), target({ magazine, pKill }), ...Array.from({ length: 3 }, (_, i) => asm(`m${i}`, i * 40, { pHit: 1 }))]);
      return runMonteCarlo(s, spec({ runs: 100 })).then((r) => r.groups[0].outcomes[0].p);
    };
    expect(await hitChance(0, 0.9)).toBe(1);
    const strong = await hitChance(40, 0.9);
    const weak = await hitChance(40, 0.2);
    expect(strong).toBeLessThan(0.25);
    expect(weak).toBeGreaterThan(strong + 0.4);
  });
});

describe('default setup and presets', () => {
  it('is valid for every preset and for a blank scenario, and asks about the ships on the blue side', () => {
    for (const s of [...PRESET_SCENARIOS, blankScenario()]) {
      const d = defaultRedTeam(s);
      expect(validateRedTeam(s, d), s.id).toEqual([]);
      expect(d.outcomes.length).toBeGreaterThan(0);
    }
    const spec = defaultRedTeam(PRESET_SCENARIOS[0]);
    expect(spec.outcomes.map((o) => o.type)).toContain('destroyed');
    expect(spec.perturbations.some((p) => p.target.kind === 'environment')).toBe(true);
  });

  it('knows about missiles and mines when the scenario has them', () => {
    const salvo = defaultRedTeam(PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!);
    expect(salvo.outcomes.map((o) => o.type)).toContain('intercepts');
    expect(salvo.perturbations.some((p) => p.target.kind === 'unit' && p.target.field === 'launchAtS')).toBe(true);
    const mines = defaultRedTeam(PRESET_SCENARIOS.find((p) => p.id === 'minefield-transit')!);
    expect(mines.outcomes.map((o) => o.type)).toContain('mine_strike');
  });

  it('ships ready-made red-team setups that are valid and run', async () => {
    for (const id of ['salvo-defense', 'minefield-transit', 'air-raid']) {
      const s = PRESET_SCENARIOS.find((p) => p.id === id)!;
      expect(s.redTeam, id).toBeDefined();
      expect(validateRedTeam(s, s.redTeam!), id).toEqual([]);
      const r = await runMonteCarlo(s, { ...s.redTeam!, runs: 3 });
      for (const g of r.groups) for (const o of g.outcomes) expect(o.p).toBeGreaterThanOrEqual(0);
    }
  }, 60_000);

  it('shows a salvo curve for the salvo preset: more missiles, more chance the carrier is hit', async () => {
    const s = PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!;
    const r = await runMonteCarlo(s, { ...s.redTeam!, runs: 60, sweep: { target: s.redTeam!.sweep!.target, values: [1, 8] } });
    expect(r.groups[1].outcomes[0].p).toBeGreaterThanOrEqual(r.groups[0].outcomes[0].p);
  }, 60_000);

  it('has a showcase run in each scenario that does something worth watching', () => {
    const seen = (id: string) => {
      const s = PRESET_SCENARIOS.find((p) => p.id === id)!;
      const types = new Set(runScenario(s).events.map((e) => e.type));
      return types;
    };
    expect(seen('salvo-defense')).toEqual(expect.objectContaining({}));
    expect(seen('salvo-defense').has('intercept')).toBe(true);
    expect(seen('salvo-defense').has('hit')).toBe(true);
    expect(seen('minefield-transit').has('mine')).toBe(true);
    expect(seen('air-raid').has('destroyed')).toBe(true);
    expect(unitStateAt(runScenario(PRESET_SCENARIOS[0]), 0, 0).active).toBe(true);
  });
});

describe('red-team settings in scenario JSON', () => {
  it('survive a round trip', () => {
    for (const id of ['salvo-defense', 'minefield-transit', 'air-raid']) {
      const s = PRESET_SCENARIOS.find((p) => p.id === id)!;
      const parsed = parseScenario(JSON.stringify(s));
      expect(parsed.redTeam).toEqual(s.redTeam);
      expect(parsed.seed).toBe(s.seed);
      expect(parsed.units).toEqual(s.units);
    }
  });

  it('say what is wrong when they are malformed', () => {
    const good = PRESET_SCENARIOS.find((p) => p.id === 'air-raid')!.redTeam!;
    const bad = (patch: Record<string, unknown>) => () => parseRedTeam({ ...good, ...patch });
    expect(bad({ runs: 'many' })).toThrow(/redTeam.runs/);
    expect(bad({ perturbations: [{ id: 'a', target: { kind: 'unit', unitId: 'x', field: 'colour' }, mode: 'set', dist: { type: 'normal', mean: 0, sd: 1 } }] })).toThrow(/field/);
    expect(bad({ perturbations: [{ id: 'a', target: { kind: 'environment', field: 'windKt' }, mode: 'wobble', dist: { type: 'normal', mean: 0, sd: 1 } }] })).toThrow(/mode/);
    expect(bad({ perturbations: [{ id: 'a', target: { kind: 'environment', field: 'windKt' }, mode: 'set', dist: { type: 'cauchy' } }] })).toThrow(/dist.type/);
    expect(bad({ outcomes: [{ id: 'a', type: 'vibes' }] })).toThrow(/outcomes\[0\].type/);
    expect(bad({ sweep: { target: { kind: 'salvo', unitIds: 'm1' }, values: [1] } })).toThrow(/unitIds/);
    expect(() => parseRedTeam([])).toThrow(/must be an object/);
  });

  it('accepts weighted choices, optional fields and a sweep over one setting', () => {
    const spec = parseRedTeam({
      runs: 10,
      seed: 1,
      perturbations: [{ id: 'a', label: 'Wind', target: { kind: 'environment', field: 'windKt' }, mode: 'set', dist: { type: 'choice', values: [0, 20], weights: [3, 1] } }],
      outcomes: [{ id: 'o', type: 'mine_strike' }, { id: 'p', type: 'mine_strike', unitId: 'x' }],
      sweep: { target: { kind: 'unit', unitId: 'x', field: 'pHit' }, values: [0.1, 0.9] },
    });
    expect(spec.perturbations[0].dist).toEqual({ type: 'choice', values: [0, 20], weights: [3, 1] });
    expect(spec.perturbations[0].label).toBe('Wind');
    expect(spec.outcomes[0]).toEqual({ id: 'o', type: 'mine_strike' });
    expect(spec.sweep?.target).toEqual({ kind: 'unit', unitId: 'x', field: 'pHit' });
  });
});
