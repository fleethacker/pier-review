import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SceneStore } from '../../../scene/store';

vi.mock('../api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling',
  AGENTS_BASE: 'http://localhost/api/agents',
  modeling: { GET: vi.fn(), POST: vi.fn() },
  agents: { GET: vi.fn(), POST: vi.fn() },
  unwrap: <T,>(r: { data: T }) => r.data,
  awaitJob: vi.fn(),
  describeError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

import { awaitJob, modeling } from '../api';
import { MooringController } from '../controller';
import { coverage, defaultInputs, inputProblems, isoMinute, outcomeStatus } from './logic';

const NOW = Date.parse('2026-11-05T16:42:00Z');
const H = 3_600_000;
const snap = (t: number) => ({ valid_at_utc: isoMinute(t), source: 'scenario', wind_speed_kt: 10 }) as never;
const series = (fromMs: number, hours: number) => Array.from({ length: hours + 1 }, (_, k) => snap(fromMs + k * H));

describe('logic', () => {
  it('defaults to an arrival window 24 to 30 h after an hourly as-of', () => {
    const i = defaultInputs(NOW);
    expect(i.asOfUtc).toBe('2026-11-05T16:00:00Z');
    expect(i.arrivalFromUtc).toBe('2026-11-06T16:00:00Z');
    expect(i.arrivalToUtc).toBe('2026-11-06T22:00:00Z');
    expect(inputProblems(i)).toEqual([]);
  });

  it('rejects an arrival less than 24 h ahead and an inverted window', () => {
    const i = defaultInputs(NOW);
    expect(inputProblems({ ...i, arrivalFromUtc: '2026-11-06T10:00:00Z' })[0]).toMatch(/24 h/);
    expect(inputProblems({ ...i, arrivalToUtc: '2026-11-06T10:00:00Z' })).toContain('The latest arrival is before the earliest arrival.');
    expect(inputProblems({ ...i, asOfUtc: 'nonsense' })[0]).toMatch(/UTC/);
  });

  it('requires coverage through docking and holding after the latest arrival', () => {
    const i = defaultInputs(NOW); // needs 16:00 day+1 to 22:00 + 8 h = 06:00 day+2
    const asOf = Date.parse(i.asOfUtc);
    expect(coverage(series(asOf, 38), i)).toMatchObject({ covered: true, neededToUtc: '2026-11-07T06:00:00Z', maxGapMin: 60, count: 39 });
    expect(coverage(series(asOf, 37), i)?.covered).toBe(false);
    expect(coverage([snap(asOf)], i)).toBeNull();
  });

  it('ignores snapshots without a time instead of assuming they fill a gap', () => {
    const i = defaultInputs(NOW);
    const asOf = Date.parse(i.asOfUtc);
    const s = series(asOf, 38);
    s[20] = { ...(s[20] as object), valid_at_utc: undefined } as never;
    expect(coverage(s, i)).toMatchObject({ count: 38, maxGapMin: 120 });
  });

  it('never shows a forecast arrival as unconditionally green', () => {
    expect(outcomeStatus('within_target')).toBe('AMBER');
    expect(outcomeStatus('overloaded')).toBe('RED');
    expect(outcomeStatus('unavailable')).toBe('NONE');
  });
});

describe('advance session', () => {
  let c: MooringController;
  const line = { line_number: 1, spec_id: 'S', parts: 1, ship_fitting_id: 'B1', pier_fitting_id: 'P1' };
  const env = { valid_at_utc: '2026-11-05T16:00:00Z', source: 'mock', wind_speed_kt: 10 };
  const response = (selected: boolean) => ({
    result_id: 'fp-1', status: 'AMBER', backend: 'real', validity: { state: 'limited' },
    result: {
      selected_arrival_utc: selected ? '2026-11-06T17:00:00Z' : null,
      selected_config: selected
        ? { side_to: 'starboard', ship_x_ft: 650, lines: [{ ...line, paid_out_unstretched_length_ft: 123.4, condition: 'wet' }] }
        : null,
      installed_at_water_level_mllw_ft: selected ? 1.2 : null,
      windows: [], evaluations: 10, complete: true, limitations: [], recheck_triggers: [],
    },
  });

  beforeEach(() => {
    vi.resetAllMocks();
    c = new MooringController({ store: new SceneStore() });
    c.state.set({
      berth: { berth_id: 'B' } as never, ship: { class_id: 'DDG', mst_class: 'II' } as never, env: env as never,
      lines: [line as never], side: 'starboard', shipXFt: 650, loading: 'full_load',
    });
    c.advance.setInputs(defaultInputs(NOW));
    vi.mocked(modeling.POST).mockImplementation((async (path: string) => {
      if (path === '/api/v1/data-simulation/forecast') {
        return { data: { berth_id: 'B', step_min: 60, series: series(Date.parse(c.advance.state.get().inputs.asOfUtc), 48) } };
      }
      if (path === '/api/v1/mooring/forecast-plan') return { data: { job_id: 'j', status_url: '/api/v1/jobs/j' } };
      if (path === '/api/v1/mooring/forecast-plan/recheck') return { data: { result: { state: 'recheck_required', reasons: ['changed'] } } };
      throw new Error(path);
    }) as never);
    vi.mocked(awaitJob).mockResolvedValue(response(true));
  });
  afterEach(() => c.dispose());

  it('binds a labeled training series starting at the as-of time', async () => {
    await c.advance.generateTrainingSeries();
    expect(modeling.POST).toHaveBeenCalledWith('/api/v1/data-simulation/forecast', {
      body: expect.objectContaining({ berth_id: 'B', start_utc: '2026-11-05T16:00:00Z', seed: 7, baseline: env, duration_hours: 48 }),
    });
    const s = c.advance.state.get().series!;
    expect(s.label).toMatch(/synthetic, not a weather forecast/);
    expect(c.advance.problems()).toEqual([]);
  });

  it('submits the layout, times and series with a supplied binding', async () => {
    await c.advance.generateTrainingSeries();
    await c.advance.run();
    const body = vi.mocked(modeling.POST).mock.calls.find((k) => k[0] === '/api/v1/mooring/forecast-plan')![1] as { body: Record<string, unknown> };
    expect(body.body).toMatchObject({
      ship_class_id: 'DDG', berth_id: 'B', mst: 'II', as_of_utc: '2026-11-05T16:00:00Z',
      arrival_from_utc: '2026-11-06T16:00:00Z', holding_hours: 6, operation_hours: 2, target_pct_wll: 80,
      config: { side_to: 'starboard', ship_x_ft: 650, lines: [line] },
      forecast_binding: { source: 'supplied', revision: expect.stringContaining('seed7') },
    });
    expect(c.advance.state.get()).toMatchObject({ phase: 'done', recheckReason: null });
  });

  it('does not submit without a series', async () => {
    await c.advance.run();
    expect(modeling.POST).not.toHaveBeenCalled();
    expect(c.advance.state.get().error).toMatch(/series/);
  });

  it('applies the selected configuration with its paid-out lengths and stays current', async () => {
    await c.advance.generateTrainingSeries();
    await c.advance.run();
    expect(c.advance.applySelected()).toBe(true);
    expect(c.state.get().lines[0]).toMatchObject({ paid_out_unstretched_length_ft: 123.4, condition: 'wet' });
    expect(c.advance.state.get()).toMatchObject({ applied: { arrivalUtc: '2026-11-06T17:00:00Z', installedAtFt: 1.2 }, recheckReason: null });
  });

  it.each([
    ['layout', () => c.state.set({ shipXFt: 700 })],
    ['environment', () => c.state.set({ env: { ...env, wind_speed_kt: 40 } as never })],
    ['holding time', () => c.advance.setInputs({ holdingHours: 12 })],
  ])('marks the result recheck-required when the %s changes and refuses to apply it', async (_name, change) => {
    await c.advance.generateTrainingSeries();
    await c.advance.run();
    change();
    expect(c.advance.state.get().recheckReason).toMatch(/Inputs changed/);
    expect(c.advance.applySelected()).toBe(false);
    expect(c.state.get().lines[0]).not.toHaveProperty('paid_out_unstretched_length_ft');
  });

  it('marks the result stale when the series is regenerated, and compares it without changing the plan', async () => {
    await c.advance.generateTrainingSeries();
    await c.advance.run();
    c.advance.setTraining({ seed: 8 });
    await c.advance.generateTrainingSeries();
    expect(c.advance.state.get().recheckReason).toMatch(/forecast series/);
    await c.advance.recheck();
    expect(modeling.POST).toHaveBeenLastCalledWith('/api/v1/mooring/forecast-plan/recheck', {
      body: expect.objectContaining({ prior_result_id: 'fp-1', forecast_binding: expect.objectContaining({ revision: expect.stringContaining('seed8') }) }),
    });
    expect(c.advance.state.get().recheck.response?.result.state).toBe('recheck_required');
    expect(c.advance.state.get().response?.result_id).toBe('fp-1');
  });

  it('publishes no apply when no arrival is supported', async () => {
    vi.mocked(awaitJob).mockResolvedValue(response(false));
    await c.advance.generateTrainingSeries();
    await c.advance.run();
    expect(c.advance.applySelected()).toBe(false);
  });
});
