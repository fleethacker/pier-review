import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SceneStore } from '../../../scene/store';

vi.mock('../api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling', AGENTS_BASE: 'http://localhost/api/agents',
  modeling: { GET: vi.fn(), POST: vi.fn() }, agents: { POST: vi.fn() }, awaitJob: vi.fn(),
  unwrap: <T,>(r: { data: T }) => r.data,
  describeError: (e: unknown) => String(e),
}));

import { agents, awaitJob } from '../api';
import { MooringController } from '../controller';
import type { IntakeReport } from './logic';

let c: MooringController;
const report = { report_id: 'intake-selected' } as IntakeReport;
const accepted = { job_id: 'job-1', status_url: '/api/v1/jobs/job-1' };

beforeEach(() => {
  vi.resetAllMocks();
  c = new MooringController({ store: new SceneStore() });
  vi.spyOn(c, 'ensureScenario').mockResolvedValue('selected-scenario');
  vi.mocked(agents.POST).mockResolvedValue({ data: accepted } as never);
  vi.mocked(awaitJob).mockResolvedValue(report);
});
afterEach(() => { c.dispose(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('assesses the selected scenario and passes that report to Planner', async () => {
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} });
  await c.intake.run();
  expect(agents.POST).toHaveBeenCalledWith('/api/v1/intake/reports', expect.objectContaining({
    body: { scenario_id: 'selected-scenario', horizon_hours: 24 }, signal: expect.any(AbortSignal),
  }));
  expect(c.intake.reportId()).toBe(report.report_id);
  vi.mocked(agents.POST).mockResolvedValue({ data: { plan_id: 'p1', events_url: '/api/v1/agent/plans/p1/events' } } as never);
  await c.agent.run();
  expect(agents.POST).toHaveBeenLastCalledWith('/api/v1/agent/plans', expect.objectContaining({
    body: expect.objectContaining({ scenario_id: 'selected-scenario', intake_report_id: report.report_id }),
  }));
});

it.each(['environment', 'loading', 'geometry', 'lines', 'tugs'])('clears assessment after changing %s', async (change) => {
  await c.intake.run();
  if (change === 'environment') c.state.set({ env: { wind_gust_kt: 64 } as never });
  if (change === 'loading') c.state.set({ loading: 'light' });
  if (change === 'geometry') c.state.set({ shipXFt: 100 });
  if (change === 'lines') c.state.set({ lines: [{ line_number: 7 }] as never });
  if (change === 'tugs') c.state.set({ tugAssignments: [{ tug_id: 'T1' }] as never });
  expect(c.intake.reportId()).toBeNull();
  expect(c.intake.state.get().report).toBeNull();
});

it.each(['resolve', 'reject'])('ignores an old submission that %s after a new assessment starts', async (outcome) => {
  let resolve!: (r: unknown) => void;
  let reject!: (e: Error) => void;
  vi.mocked(agents.POST).mockReturnValueOnce(new Promise((ok, fail) => { resolve = ok; reject = fail; }) as never);
  const old = c.intake.run();
  await Promise.resolve();
  const oldSignal = (vi.mocked(agents.POST).mock.calls[0][1] as { signal: AbortSignal }).signal;
  c.state.set({ side: 'port' });
  await c.intake.run();
  if (outcome === 'resolve') resolve({ data: accepted });
  else reject(new Error('obsolete request failed'));
  await old;
  expect(oldSignal.aborted).toBe(true);
  expect(awaitJob).toHaveBeenCalledTimes(1);
  expect(c.intake.state.get()).toMatchObject({ phase: 'done', report, error: null });
});

it('ignores a completed poll and progress callback after inputs change', async () => {
  let resolve!: (r: IntakeReport) => void;
  vi.mocked(awaitJob).mockReturnValue(new Promise((ok) => { resolve = ok; }));
  const run = c.intake.run();
  await Promise.resolve();
  await Promise.resolve();
  const progress = vi.mocked(awaitJob).mock.calls[0][2]!;
  c.state.set({ berthId: 'another-berth' });
  progress(0.9);
  resolve(report);
  await run;
  expect(c.intake.state.get()).toEqual({ phase: 'idle', progress: 0, error: null, report: null });
});

it('does not submit after inputs change during scenario saving', async () => {
  let resolve!: (id: string) => void;
  vi.mocked(c.ensureScenario).mockReturnValue(new Promise((ok) => { resolve = ok; }));
  const run = c.intake.run();
  c.state.set({ shipClassId: 'another-ship' });
  resolve('obsolete-scenario');
  await run;
  expect(agents.POST).not.toHaveBeenCalled();
  expect(c.intake.state.get().phase).toBe('idle');
});


it('carries the immutable selected arrival and fractional holding interval into Intake then Planner (F02)', async () => {
  const forecast = { berth_id: 'B', as_of_utc: '2026-11-05T12:00:00Z', from_utc: '2026-11-06T15:00:00Z',
    to_utc: '2026-11-06T17:30:00Z', forecast: [{ wind_gust_kt: 64 }, { wind_gust_kt: 50 }],
    forecast_binding: { source: 'supplied', source_id: 'selected-source', revision: 'r7', expected_content_hash: `sha256:${'a'.repeat(64)}` } } as never;
  c.setForecastSelection(forecast);
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} });
  await c.intake.run();
  expect(agents.POST).toHaveBeenCalledWith('/api/v1/intake/reports', expect.objectContaining({
    body: { scenario_id: 'selected-scenario', horizon_hours: 2.5, forecast_request: forecast },
  }));
  vi.mocked(agents.POST).mockResolvedValue({ data: { plan_id: 'p1', events_url: '/events' } } as never);
  await c.agent.run();
  expect(agents.POST).toHaveBeenLastCalledWith('/api/v1/agent/plans', expect.objectContaining({ body: expect.objectContaining({ intake_report_id: report.report_id }) }));
  c.advance.setInputs({ holdingHours: 8 });
  expect(c.forecastSelection).toBeNull();
  expect(c.intake.reportId()).toBeNull();
  expect(c.agent.state.get().planId).toBeNull();
});


it('direct Planner action assesses an applied forecast first instead of silently using steady conditions', async () => {
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} });
  c.setForecastSelection({ berth_id: 'B', as_of_utc: '2026-11-05T12:00:00Z', from_utc: '2026-11-06T15:00:00Z',
    to_utc: '2026-11-06T17:30:00Z', forecast: [{ wind_gust_kt: 64 }, { wind_gust_kt: 50 }],
    forecast_binding: { source: 'supplied', source_id: 'selected-source', revision: 'r7' } } as never);
  vi.mocked(agents.POST).mockImplementation((async (path: string) => ({ data: path === '/api/v1/intake/reports' ? accepted : { plan_id: 'p1', events_url: '/events' } })) as never);
  await c.agent.run();
  expect(vi.mocked(agents.POST).mock.calls.map((call) => call[0])).toEqual(['/api/v1/intake/reports', '/api/v1/agent/plans']);
  expect(agents.POST).toHaveBeenLastCalledWith('/api/v1/agent/plans', expect.objectContaining({ body: expect.objectContaining({ intake_report_id: report.report_id }) }));
});

it('does not submit a steady-condition plan after its selected-forecast Intake fails', async () => {
  c.setForecastSelection({ from_utc: '2026-11-06T15:00:00Z', to_utc: '2026-11-06T17:30:00Z' } as never);
  vi.mocked(awaitJob).mockRejectedValue(new Error('Selected forecast has a gap'));
  await c.agent.run();
  expect(vi.mocked(agents.POST).mock.calls.map((call) => call[0])).toEqual(['/api/v1/intake/reports']);
  expect(c.agent.state.get()).toMatchObject({ phase: 'error', planId: null });
  expect(c.agent.state.get().error).toContain('Selected forecast has a gap');
});
