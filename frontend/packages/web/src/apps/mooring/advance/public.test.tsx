// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SceneStore } from '../../../scene/store';
vi.mock('../api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling', AGENTS_BASE: 'http://localhost/api/agents',
  modeling: { GET: vi.fn(), POST: vi.fn() }, agents: { GET: vi.fn(), POST: vi.fn() },
  unwrap: <T,>(r: { data: T }) => r.data, awaitJob: vi.fn(), describeError: (e: unknown) => String(e),
}));
import { modeling, awaitJob } from '../api';
import { MooringController } from '../controller';
import { ControllerContext } from '../panels/context';
import { AdvancePanel } from './AdvancePanel';
import { defaultInputs, publicRequest, type ComposedForecast, type ComposeRequest } from './logic';

const NOW = Date.parse('2026-11-05T16:00:00Z');
const HOUR = 3_600_000;
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((r) => { resolve = r; }); return { promise, resolve }; };
function acquisition(request: ComposeRequest, revision = 'sha256:provider-revision'): ComposedForecast {
  return { manifest: { schema_version: 'composed-forecast-v1', revision, request, status: 'complete', components:
    (['wind', 'current', 'water_level'] as const).map((component) => ({ availability: { component, state: 'prediction', basis: 'prediction',
      source: `fixture:${component}`, quality: 'unknown', issued_at_utc: null, retrieved_at_utc: '2026-11-05T15:00:00Z',
      current_depth_ft: component === 'current' ? request.current_depth_ft : null, current_bin: component === 'current' ? request.current_bin : null,
      limitations: ['Offline test fixture; no actual provider data.'] } })) },
    snapshots: Array.from({ length: 1 + (Date.parse(request.horizon_end_utc) - Date.parse(request.horizon_start_utc)) / HOUR }, (_, index) => ({
      valid_at_utc: new Date(Date.parse(request.horizon_start_utc) + index * HOUR).toISOString(), source: 'live', wind_speed_kt: 10,
      wind_gust_kt: 15, wind_from_true_deg: 90, current_speed_kt: 1, current_set_true_deg: 0, water_level_mllw_ft: 1,
      air_density_kgm3: 1.225, water_density_kgm3: 1025, metadata: { basis: 'prediction', source: 'Offline test fixture', quality: 'unknown',
        components: (['wind', 'current', 'water_level'] as const).map((component) => ({ component, basis: 'prediction' as const,
          source: `fixture:${component}`, quality: 'unknown' as const, retrieved_at_utc: '2026-11-05T15:00:00Z' })) },
    })) };
}

let c: MooringController;
let currentAcquisition: ComposedForecast;
beforeEach(() => {
  vi.resetAllMocks();
  c = new MooringController({ store: new SceneStore() });
  c.state.set({ berth: { berth_id: 'B' } as never, berthId: 'B', ship: { class_id: 'DDG', mst_class: 'II' } as never,
    lines: [{ line_number: 1, spec_id: 'L', parts: 1, ship_fitting_id: 'S', pier_fitting_id: 'P' }],
    side: 'starboard', shipXFt: 500, loading: 'full_load', env: { source: 'mock' } as never });
  c.advance.setInputs(defaultInputs(NOW));
  c.advance.setPublicInputs({ currentDepthFt: 21, currentBin: 'fixture-bin' });
  currentAcquisition = acquisition(c.advance.publicBody()!);
  vi.mocked(modeling.POST).mockImplementation((async (path: string, options: { body: Record<string, unknown> }) => {
    const body = options.body;
    if (path === '/api/v1/env/forecast/compose') return { data: currentAcquisition };
    if (path === '/api/v1/mooring/forecast/resolve') return { data: { result_id: 'resolved', validity: { state: 'limited' }, status: 'AMBER', result: {
      berth_id: 'B', series: body.forecast, coverage_complete: true, problems: [], limitations: [], forecast_manifest: {
        ...(body.forecast_binding as object), content_hash: 'planner-content-hash', binding_hash: 'planner-binding-hash',
        as_of_utc: body.as_of_utc, from_utc: body.from_utc, to_utc: body.to_utc, max_gap_min: 60,
      },
    } } };
    if (path === '/api/v1/mooring/forecast-plan') return { data: { job_id: 'job' } };
    if (path === '/api/v1/mooring/forecast-plan/recheck') return { data: { status: 'RED', validity: { state: 'limited' }, result: { state: 'unchanged', reasons: ['Still overloaded.'] } } };
    throw new Error(path);
  }) as never);
  vi.mocked(awaitJob).mockResolvedValue({ result_id: 'old-plan', status: 'RED', backend: 'real', validity: { state: 'limited' },
    result: { windows: [], selected_config: null, evaluations: 1, complete: true, limitations: [], recheck_triggers: [] } });
});
afterEach(() => { cleanup(); c.dispose(); });

describe('explicit public forecast binding', () => {
  it('requires an explicit exact current layer and binds the complete docking/holding horizon', () => {
    expect(publicRequest('B', defaultInputs(NOW), { currentDepthFt: null, currentBin: '' })).toBeNull();
    expect(c.advance.publicBody()).toMatchObject({ source: { mode: 'public' }, current_depth_ft: 21, current_bin: 'fixture-bin',
      as_of_utc: '2026-11-05T16:00:00Z', horizon_start_utc: '2026-11-06T16:00:00Z', horizon_end_utc: '2026-11-07T06:00:00.000Z' });
  });
  it('retains manifest/provenance, resolves canonical content, and pins that hash in planning', async () => {
    await c.advance.fetchPublicSeries();
    expect(c.advance.problems()).toEqual([]);
    const bound = c.advance.state.get().series!;
    expect(bound.manifest).toEqual(currentAcquisition.manifest);
    expect(bound.series).toEqual(currentAcquisition.snapshots);
    currentAcquisition.manifest.components[0].availability.source = 'mutated outside session';
    expect(bound.manifest?.components[0].availability.source).toBe('fixture:wind');
    const request = c.advance.buildRequest()!;
    expect(request.forecast_binding).toMatchObject({ source: 'supplied', revision: 'sha256:provider-revision', expected_content_hash: 'planner-content-hash' });
    expect(request.forecast_binding?.expected_content_hash).not.toBe(request.forecast_binding?.revision);
    await c.advance.run();
    expect(c.advance.state.get().response?.result_id).toBe('old-plan');
  });
  it('preserves partial component reasons without manufacturing snapshots or falling back to training', async () => {
    currentAcquisition.manifest.status = 'partial';
    currentAcquisition.manifest.components[0].availability.state = 'unavailable';
    currentAcquisition.manifest.components[0].availability.reason = 'Issued after the selected cutoff';
    currentAcquisition.snapshots = [];
    await c.advance.fetchPublicSeries();
    expect(c.advance.state.get().series?.series).toEqual([]);
    expect(c.advance.problems().join(' ')).toMatch(/partial.*Issued after/);
    await c.advance.run();
    expect(vi.mocked(modeling.POST).mock.calls.map((call) => call[0])).toEqual(['/api/v1/env/forecast/compose']);
  });
  it.each(['missing', 'gap'])('blocks %s coverage instead of claiming support from endpoint bounds', async (kind) => {
    if (kind === 'missing') currentAcquisition.snapshots = currentAcquisition.snapshots!.slice(0, 1);
    else currentAcquisition.snapshots!.splice(4, 1);
    await c.advance.fetchPublicSeries();
    expect(c.advance.problems().join(' ')).toMatch(kind === 'missing' ? /two usable/ : /120-minute gap/);
  });
  it('discards an old bound series on failed public fetch, without synthetic fallback', async () => {
    await c.advance.fetchPublicSeries();
    vi.mocked(modeling.POST).mockRejectedValueOnce(new Error('provider unavailable'));
    await c.advance.fetchPublicSeries();
    expect(c.advance.state.get()).toMatchObject({ series: null, seriesMode: 'public', seriesState: 'error' });
    expect(c.advance.state.get().seriesError).toMatch(/provider unavailable/);
  });
  it('ignores late public responses after the layer or berth changes', async () => {
    const pending = deferred<unknown>();
    vi.mocked(modeling.POST).mockReturnValueOnce(pending.promise as never);
    const fetching = c.advance.fetchPublicSeries();
    c.advance.setPublicInputs({ currentBin: 'different-layer' });
    c.state.set({ berthId: 'OTHER' });
    pending.resolve({ data: currentAcquisition });
    await fetching;
    expect(c.advance.state.get().series).toBeNull();
    expect(c.advance.state.get().seriesState).toBe('idle');
  });
  it('rejects response metadata for a different current depth', async () => {
    currentAcquisition.manifest.request.current_depth_ft = 99;
    await c.advance.fetchPublicSeries();
    expect(c.advance.state.get().series).toBeNull();
    expect(c.advance.state.get().seriesError).toMatch(/does not match/);
  });
  it('retains an immutable prior result and requires recheck after a new revision', async () => {
    await c.advance.fetchPublicSeries(); await c.advance.run();
    currentAcquisition = acquisition(c.advance.publicBody()!, 'sha256:revision-two');
    await c.advance.fetchPublicSeries();
    expect(c.advance.state.get().response?.result_id).toBe('old-plan');
    expect(c.advance.state.get().recheckReason).toMatch(/Inputs changed/);
    await c.advance.recheck();
    expect(c.advance.state.get().recheck.response?.status).toBe('RED');
  });
  it('ignores a stale revision comparison after its inputs change', async () => {
    await c.advance.fetchPublicSeries(); await c.advance.run();
    const pending = deferred<unknown>();
    vi.mocked(modeling.POST).mockReturnValueOnce(pending.promise as never);
    const rechecking = c.advance.recheck();
    c.advance.setInputs({ holdingHours: 8 });
    pending.resolve({ data: { status: 'RED', result: { state: 'unchanged', reasons: ['old'] } } });
    await rechecking;
    expect(c.advance.state.get().recheck.response).toBeNull();
  });
});

it('shows component unavailability and unknown issuance, and preserves RED for an unchanged recheck', async () => {
  await c.advance.fetchPublicSeries(); await c.advance.run(); await c.advance.recheck();
  render(<ControllerContext.Provider value={c}><AdvancePanel /></ControllerContext.Provider>);
  expect(screen.getByRole('region', { name: 'Public forecast provenance' })).toBeTruthy();
  expect(screen.getAllByText(/Issued unknown; retrieved/)).toHaveLength(3);
  const unchanged = screen.getByText('unchanged');
  expect(unchanged.style.color).toBe('rgb(255, 23, 68)');
  expect(screen.getByText('Still overloaded.')).toBeTruthy();
  await act(async () => {
    currentAcquisition.manifest.status = 'partial'; currentAcquisition.snapshots = [];
    currentAcquisition.manifest.components[0].availability.state = 'unavailable';
    currentAcquisition.manifest.components[0].availability.reason = 'No wind forecast for this cutoff';
    await c.advance.fetchPublicSeries();
  });
  expect(screen.getByText('No wind forecast for this cutoff')).toBeTruthy();
  expect((screen.getByRole('button', { name: 'Assess arrivals' }) as HTMLButtonElement).disabled).toBe(true);
});


it('blocks unknown canonical validity even when the provider reports full coverage', async () => {
  await c.advance.fetchPublicSeries();
  const bound = c.advance.state.get().series!;
  c.advance.state.set({ series: { ...bound, resolved: { ...bound.resolved!, validity: { state: 'unknown' } as never } } });
  expect(c.advance.problems().join(' ')).toMatch(/Canonical forecast binding is unavailable/);
});

it('settles a superseded training request without locking source controls', async () => {
  const pending = deferred<unknown>();
  vi.mocked(modeling.POST).mockReturnValueOnce(pending.promise as never);
  const generating = c.advance.generateTrainingSeries();
  c.advance.setTraining({ seed: 9 });
  expect(c.advance.state.get().seriesState).toBe('idle');
  pending.resolve({ data: { series: [], step_min: 60 } });
  await generating;
  expect(c.advance.state.get().series).toBeNull();
  expect(c.advance.state.get().seriesState).toBe('idle');
});


it('settles a revision comparison when the parent layout changes', async () => {
  await c.advance.fetchPublicSeries(); await c.advance.run();
  const pending = deferred<unknown>();
  vi.mocked(modeling.POST).mockReturnValueOnce(pending.promise as never);
  const rechecking = c.advance.recheck();
  c.state.set({ shipXFt: 650 });
  expect(c.advance.state.get().recheck.state).toBe('idle');
  pending.resolve({ data: { status: 'RED', result: { state: 'unchanged', reasons: ['old'] } } });
  await rechecking;
  expect(c.advance.state.get().recheck.response).toBeNull();
});


it('offers an explicit retrieval cutoff retry without silently moving arrivals or extending coverage (T03)', async () => {
  const initial = structuredClone(c.advance.state.get().inputs);
  currentAcquisition.manifest.status = 'unavailable';
  currentAcquisition.snapshots = [];
  for (const component of currentAcquisition.manifest.components) {
    component.availability.state = 'unavailable';
    component.availability.retrieved_at_utc = '2026-11-05T16:05:00Z';
  }
  await c.advance.fetchPublicSeries();
  expect(c.advance.state.get().inputs.asOfUtc).toBe(initial.asOfUtc);
  render(<ControllerContext.Provider value={c}><AdvancePanel /></ControllerContext.Provider>);
  expect(screen.getByRole('button', { name: 'Use retrieval cutoff and retry' })).toBeTruthy();
  vi.mocked(modeling.POST).mockImplementation((async (_path: string, options: { body: ComposeRequest }) => ({ data: acquisition(options.body) })) as never);
  await act(async () => c.advance.retryAtRetrievalCutoff());
  expect(c.advance.state.get().inputs).toEqual({ ...initial, asOfUtc: '2026-11-05T16:05:00Z' });
  const request = vi.mocked(modeling.POST).mock.calls.filter((entry) => entry[0] === '/api/v1/env/forecast/compose').at(-1)![1] as { body: ComposeRequest };
  expect(request.body).toMatchObject({ as_of_utc: '2026-11-05T16:05:00Z', horizon_start_utc: initial.arrivalFromUtc,
    current_depth_ft: 21, current_bin: 'fixture-bin' });
  expect(c.advance.problems()).toContain('Earliest arrival must be at least 24 h after the as-of time.');
});
