import { afterEach, describe, expect, it, vi } from 'vitest';
import { destination } from './geo';
import { resultCsv, resultJson, reportHtml } from './exportResults';
import { compareResults, evaluateOutcomes, runMonteCarlo, simulateChunk, validateRedTeam } from './montecarlo';
import { parseRedTeam } from './scenarioJson';
import { runScenario } from './sim';
import type { Environment, OutcomeSpec, RedTeamSpec, ScenarioConfig, UnitConfig } from './types';

vi.setConfig({ testTimeout: 60_000 });

const C = { lon: -62, lat: 33 };
const still: Environment = { windFromDeg: 0, windKt: 0, currentToDeg: 0, currentKt: 0 };
const unit = (patch: Partial<UnitConfig> & Pick<UnitConfig, 'id'>): UnitConfig => ({
  name: patch.id,
  classId: 'DDG',
  side: 'BLUE',
  start: C,
  headingDeg: 90,
  speedKt: 0,
  behavior: { type: 'hold' },
  magazine: 0,
  ...patch,
});
const scenario = (units: UnitConfig[], durationS = 500): ScenarioConfig => ({ id: 't', name: 'Test <run>', description: '', center: C, durationS, lightPreset: 'day', environment: still, units });
const shooter = () => unit({ id: 'shooter', side: 'RED', start: destination(C, 0, 20_000) });
const asm = (id: string, atS: number, patch: Partial<UnitConfig> = {}): UnitConfig =>
  unit({ id, classId: 'ASM', side: 'RED', speedKt: 300, launch: { byId: 'shooter', atS }, behavior: { type: 'strike', targetId: 'tgt' }, ...patch });
const base = (pHit = 0.5) => scenario([shooter(), unit({ id: 'tgt' }), asm('m', 10, { pHit })]);
const spec = (patch: Partial<RedTeamSpec> = {}): RedTeamSpec => ({
  runs: 200,
  seed: 3,
  perturbations: [],
  outcomes: [{ id: 'hit', type: 'hit', unitId: 'tgt' }],
  ...patch,
});

describe('combined outcomes', () => {
  const outcomes: OutcomeSpec[] = [
    { id: 'hit', type: 'hit', unitId: 'tgt' },
    { id: 'gone', type: 'destroyed', unitId: 'tgt' },
    { id: 'both', type: 'all', of: ['hit', 'gone'] },
    { id: 'either', type: 'any', of: ['hit', 'gone'] },
    { id: 'safe', type: 'not', of: 'hit' },
    { id: 'early', type: 'hit', unitId: 'tgt', beforeS: 1 },
    { id: 'lateOk', type: 'hit', unitId: 'tgt', beforeS: 500 },
  ];

  it('builds all, any and not from the earlier results, and applies time limits', () => {
    const s = base(1);
    const traj = runScenario(s, { seed: 5 });
    const r = Object.fromEntries(outcomes.map((o, i) => [o.id, evaluateOutcomes(s, traj, outcomes)[i]]));
    expect(r.hit.hit).toBe(true);
    expect(r.both.hit).toBe(r.gone.hit);
    expect(r.either.hit).toBe(true);
    expect(r.either.tS).toBe(r.hit.tS);
    expect(r.safe.hit).toBe(false);
    expect(r.early.hit).toBe(false);
    expect(r.lateOk.hit).toBe(true);
  });

  it('a missed shot makes "not hit" true and "any" false', () => {
    const s = base(0);
    const r = evaluateOutcomes(s, runScenario(s, { seed: 5 }), outcomes);
    expect(r[4].hit).toBe(true);
    expect(r[3].hit).toBe(false);
  });

  it('counts a run in a batch as "not hit" exactly when it is not "hit"', async () => {
    const res = await runMonteCarlo(base(0.5), spec({ outcomes }), { workers: 0 });
    const o = Object.fromEntries(res.groups[0].outcomes.map((x) => [x.id, x]));
    expect(o.hit.hits + o.safe.hits).toBe(200);
    expect(o.both.hits).toBeLessThanOrEqual(o.either.hits);
    expect(o.early.hits).toBe(0);
    expect(o.hit.label).toBe('tgt hit');
    expect(o.both.label).toBe('tgt hit and tgt destroyed');
    expect(o.safe.label).toBe('Not: tgt hit');
  });

  it('rejects combinations that point at outcomes listed later, or at nothing', () => {
    const bad = spec({ outcomes: [{ id: 'a', type: 'any', of: ['b'] }, { id: 'b', type: 'hit', unitId: 'tgt' }, { id: 'c', type: 'not', of: 'zzz' }, { id: 'd', type: 'all', of: [] }] });
    const problems = validateRedTeam(base(), bad);
    expect(problems.filter((p) => /not an outcome listed before/.test(p))).toHaveLength(2);
    expect(problems.some((p) => /at least one outcome to combine/.test(p))).toBe(true);
    expect(validateRedTeam(base(), spec({ outcomes: [{ id: 'a', type: 'hit', unitId: 'tgt', beforeS: 0 }] })).some((p) => /time limit/.test(p))).toBe(true);
    expect(validateRedTeam(base(), spec({ targetHalfWidth: 0 })).some((p) => /precision/.test(p))).toBe(true);
  });

  it('survives a round trip through JSON', () => {
    const s = spec({ outcomes, targetHalfWidth: 0.03 });
    expect(parseRedTeam(JSON.parse(JSON.stringify(s)))).toEqual(s);
    expect(() => parseRedTeam({ ...s, outcomes: [{ id: 'x', type: 'not' }] })).toThrow(/outcomes\[0\]\.of/);
  });
});

describe('precision and convergence', () => {
  it('stops early once every interval is narrow enough, and the result is the same as a plain batch of that length', async () => {
    const s = base(0.5);
    const early = await runMonteCarlo(s, spec({ runs: 600, targetHalfWidth: 0.08 }), { workers: 0 });
    expect(early.converged).toBe(true);
    expect(early.totalRuns).toBeLessThan(600);
    expect(early.totalRuns).toBeGreaterThanOrEqual(40);
    expect(early.groups[0].outcomes[0].halfWidth).toBeLessThanOrEqual(0.08);
    const plain = await runMonteCarlo(s, spec({ runs: early.totalRuns }), { workers: 0 });
    expect(plain.groups[0].outcomes[0].hits).toBe(early.groups[0].outcomes[0].hits);
  });

  it('runs to the end when it never gets there', async () => {
    const res = await runMonteCarlo(base(0.5), spec({ runs: 60, targetHalfWidth: 0.001 }), { workers: 0 });
    expect(res.converged).toBe(false);
    expect(res.totalRuns).toBe(60);
  });

  it('records how the chance settled, ending on the final answer, and how many runs would be enough', async () => {
    const res = await runMonteCarlo(base(0.5), spec({ runs: 120 }), { workers: 0 });
    const g = res.groups[0];
    const trace = g.trace.hit;
    expect(trace.length).toBeGreaterThan(5);
    expect(trace[trace.length - 1].n).toBe(120);
    expect(trace[trace.length - 1].p).toBeCloseTo(g.outcomes[0].p, 10);
    expect(trace[trace.length - 1].hi - trace[trace.length - 1].lo).toBeLessThan(trace[0].hi - trace[0].lo);
    expect(g.outcomes[0].runsNeeded).toBeGreaterThan(1000);
  });
});

describe('workers', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('gives the same numbers whether chunks run in pieces or all at once', () => {
    const s = base();
    const sp = spec({ runs: 24 });
    const whole = simulateChunk(s, sp, 0, 24);
    const pieces = [0, 8, 16].flatMap((k) => simulateChunk(s, sp, k, k + 8));
    expect(pieces).toEqual(whole);
  });

  it('falls back to the calling thread when the workers cannot run, with the same result', async () => {
    const s = base();
    const sp = spec({ runs: 40, perturbations: [{ id: 'w', target: { kind: 'environment', field: 'windKt' }, mode: 'add', dist: { type: 'uniform', min: 0, max: 10 } }] });
    const reference = await runMonteCarlo(s, sp, { workers: 0 });
    class BrokenWorker {
      onerror: ((e: { message: string }) => void) | null = null;
      onmessage: unknown = null;
      postMessage() {
        queueMicrotask(() => this.onerror?.({ message: 'blocked' }));
      }
      terminate() {}
    }
    vi.stubGlobal('Worker', BrokenWorker);
    const res = await runMonteCarlo(s, sp, { workers: 3 });
    expect(res.totalRuns).toBe(40);
    expect(res.groups[0].outcomes[0].hits).toBe(reference.groups[0].outcomes[0].hits);
    expect(res.groups[0].sensitivity).toEqual(reference.groups[0].sensitivity);
  });

  it('uses workers when they work, and gets the same answer', async () => {
    const s = base();
    const sp = spec({ runs: 40 });
    const reference = await runMonteCarlo(s, sp, { workers: 0 });
    const created: FakeWorker[] = [];
    class FakeWorker {
      onmessage: ((e: { data: unknown }) => void) | null = null;
      onerror: unknown = null;
      terminated = false;
      private cfg: { base: ScenarioConfig; spec: RedTeamSpec } | null = null;
      constructor() {
        created.push(this);
      }
      postMessage(m: { type: string; base?: ScenarioConfig; spec?: RedTeamSpec; k0?: number; k1?: number }) {
        if (m.type === 'init') this.cfg = { base: m.base!, spec: m.spec! };
        else setTimeout(() => this.onmessage?.({ data: { records: simulateChunk(this.cfg!.base, this.cfg!.spec, m.k0!, m.k1!) } }), 0);
      }
      terminate() {
        this.terminated = true;
      }
    }
    vi.stubGlobal('Worker', FakeWorker);
    const res = await runMonteCarlo(s, sp, { workers: 3 });
    expect(created).toHaveLength(3);
    expect(created.every((w) => w.terminated)).toBe(true);
    expect(res.groups[0].outcomes[0].hits).toBe(reference.groups[0].outcomes[0].hits);
  });

  it('can be stopped, and the stopped batch keeps only whole chunks in order', async () => {
    let calls = 0;
    const res = await runMonteCarlo(base(), spec({ runs: 400 }), { workers: 0, shouldStop: () => ++calls >= 3 });
    expect(res.stopped).toBe(true);
    expect(res.totalRuns).toBeLessThan(400);
    expect(res.totalRuns % 8).toBe(0);
  });
});

describe('comparing batches', () => {
  it('shows no real change between identical batches and a real one when the odds change', async () => {
    const a = await runMonteCarlo(base(0.3), spec({ runs: 300 }), { workers: 0 });
    const same = await runMonteCarlo(base(0.3), spec({ runs: 300 }), { workers: 0 });
    const better = await runMonteCarlo(base(0.9), spec({ runs: 300 }), { workers: 0 });
    const noChange = compareResults(a, same)[0].rows[0];
    expect(noChange.delta).toBe(0);
    expect(noChange.significant).toBe(false);
    const change = compareResults(a, better)[0].rows[0];
    expect(change.delta).toBeGreaterThan(0.4);
    expect(change.lo).toBeGreaterThan(0);
    expect(change.significant).toBe(true);
    expect(change.before).toBeCloseTo(a.groups[0].outcomes[0].p, 10);
  });

  it('matches sweep groups by value and skips what has no counterpart', async () => {
    const sweep = (values: number[]): RedTeamSpec => spec({ runs: 20, sweep: { target: { kind: 'environment', field: 'windKt' }, values } });
    const a = await runMonteCarlo(base(), sweep([0, 10, 20]), { workers: 0 });
    const b = await runMonteCarlo(base(), sweep([10, 30]), { workers: 0 });
    const deltas = compareResults(a, b);
    expect(deltas).toHaveLength(1);
    expect(deltas[0].label).toBe('windKt = 10');
  });
});

describe('exporting results', () => {
  it('writes a CSV a spreadsheet can read, quoting what needs it', async () => {
    const res = await runMonteCarlo(base(), spec({ runs: 30, outcomes: [{ id: 'q', label: 'Hit, "badly"', type: 'hit', unitId: 'tgt' }] }), { workers: 0 });
    const lines = resultCsv(res).trim().split('\n');
    expect(lines[0]).toBe('group,outcome,runs_with_outcome,runs,probability,ci95_low,ci95_high,half_width,mean_time_s');
    expect(lines).toHaveLength(2);
    expect(lines[1].startsWith('All runs,"Hit, ""badly""",')).toBe(true);
  });

  it('writes JSON that holds the scenario, the settings and the results', async () => {
    const s = base();
    const sp = spec({ runs: 20 });
    const res = await runMonteCarlo(s, sp, { workers: 0 });
    const parsed = JSON.parse(resultJson(s, sp, res));
    expect(parsed.redTeam.runs).toBe(20);
    expect(parsed.scenario.units).toHaveLength(3);
    expect(parsed.result.groups[0].runs).toBe(20);
  });

  it('writes a printable report that escapes names and shows the change against a baseline', async () => {
    const s = base();
    const a = await runMonteCarlo(s, spec({ runs: 100 }), { workers: 0 });
    const b = await runMonteCarlo(base(0.95), spec({ runs: 100 }), { workers: 0 });
    const html = reportHtml(s, spec(), b, a);
    expect(html).toContain('Test &lt;run&gt;');
    expect(html).not.toContain('Test <run>');
    expect(html).toContain('Change vs baseline');
    expect(html).toContain('(significant)');
    expect(reportHtml(s, spec(), b)).not.toContain('Change vs baseline');
  });
});
