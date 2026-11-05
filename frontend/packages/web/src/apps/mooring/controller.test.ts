import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SceneStore } from '../../scene/store';

const post = vi.fn();
vi.mock('./api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling',
  modeling: { GET: vi.fn(), POST: (...args: unknown[]) => post(...args) },
  unwrap: <T,>(r: { data: T }) => r.data,
  awaitJob: vi.fn(),
  describeError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

import { MooringController, type Candidate } from './controller';
import { modeling } from './api';
import type { Berth, Environment, ShipClass, TugAssignment } from './types';

const berth = {
  berth_id: 'B1',
  name: 'Pier',
  face_bearing_true_deg: 90,
  origin_lat: 36.9,
  origin_lon: -76.3,
  face_length_ft: 1000,
  deck_height_mllw_ft: 11,
  structure: 'open_pile',
  provenance: { source: 't', confidence: 'mock' },
  fittings: [
    { fitting_id: 'P1', kind: 'bollard_special_b', x_ft: 100, y_ft: -6, capacity_nominal_lbf: 1, condition: 'good' },
    { fitting_id: 'P2', kind: 'bollard_special_b', x_ft: 200, y_ft: -6, capacity_nominal_lbf: 1, condition: 'good' },
  ],
  fenders: [{ fender_id: 'F', kind: 'camel', x_ft: 300, length_ft: 40, standoff_ft: 12, stiffness_lbf_per_ft: 1, rated_energy_ftlbf: 1 }],
} as unknown as Berth;

const ship = {
  class_id: 'S1',
  name: 'Ship',
  hull_type: 'DDG',
  loa_ft: 500,
  beam_ft: 60,
  mst_class: 'II',
  loading_conditions: [{ name: 'full_load', displacement_lt: 9000, draft_fwd_ft: 30, draft_aft_ft: 30, freeboard_ft: 20 }],
  fittings: [
    { fitting_id: 'BITT-1S', kind: 'bitt', x_ft: 200, y_ft: -9, z_ft: 24, side: 'starboard', swl_lbf: 1 },
    { fitting_id: 'BITT-2S', kind: 'bitt', x_ft: 100, y_ft: -9, z_ft: 24, side: 'starboard', swl_lbf: 1 },
  ],
} as unknown as ShipClass;

const env = { source: 'mock', wind_speed_kt: 10, wind_gust_kt: 15, wind_from_true_deg: 180, current_speed_kt: 1, current_set_true_deg: 0, water_level_mllw_ft: 0, air_density_kgm3: 1.2, water_density_kgm3: 1020 } as unknown as Environment;

function setup() {
  const store = new SceneStore();
  const c = new MooringController({ store });
  c.state.set({
    phase: 'ready',
    berth,
    ship,
    env,
    berthId: 'B1',
    shipClassId: 'S1',
    loading: 'full_load',
    side: 'starboard',
    shipXFt: 500,
    addLine: { active: false, shipFittingId: null, specId: 'NYLON', parts: 2 },
  });
  c.pushScene('full');
  return { store, c };
}

beforeEach(() => {
  vi.useFakeTimers();
  post.mockReset();
  post.mockResolvedValue({ data: undefined, error: 'stub', response: { status: 500, url: '', statusText: '' } });
});
afterEach(() => vi.useRealTimers());

describe('adding lines by clicking fittings', () => {
  it('creates a line after a ship bitt then a pier fitting are selected', () => {
    const { store, c } = setup();
    c.startAddLine();
    store.select({ type: 'entity', id: 'sfit:BITT-1S' });
    expect(c.state.get().addLine.shipFittingId).toBe('BITT-1S');
    store.select({ type: 'entity', id: 'pier:P2' });
    const { lines, addLine } = c.state.get();
    expect(lines).toEqual([
      { line_number: 1, spec_id: 'NYLON', parts: 2, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P2' },
    ]);
    expect(addLine.active).toBe(true);
    expect(addLine.shipFittingId).toBeNull();
    expect(Object.keys(store.getState().links)).toEqual(['line-1']);
    c.dispose();
  });

  it('ignores a pier fitting chosen before a ship fitting, and does nothing when not in add mode', () => {
    const { store, c } = setup();
    store.select({ type: 'entity', id: 'sfit:BITT-1S' });
    expect(c.state.get().addLine.shipFittingId).toBeNull();
    c.startAddLine();
    store.select({ type: 'entity', id: 'pier:P1' });
    expect(c.state.get().lines).toEqual([]);
    c.dispose();
  });

  it('numbers new lines after the highest existing number and renumbers nothing on removal', () => {
    const { c } = setup();
    c.addLine('BITT-1S', 'P1');
    c.addLine('BITT-2S', 'P2');
    c.removeLine(1);
    c.addLine('BITT-1S', 'P2');
    expect(c.state.get().lines.map((l) => l.line_number)).toEqual([2, 3]);
    c.dispose();
  });
});

describe('moving the ship on the canvas', () => {
  it('updates the position, the ship and its bitts, and re-analyzes only on release', () => {
    const { store, c } = setup();
    c.addLine('BITT-1S', 'P1');
    vi.advanceTimersByTime(1000);
    post.mockClear();
    const pose = { ...store.getState().entities.ship.pose, x: 0.3048 * 640 };
    store.moveEntity('ship', pose);
    c.onEdit({ type: 'move', entityId: 'ship', pose, final: false });
    expect(c.state.get().shipXFt).toBe(640);
    // bow bitt is 200 ft ahead of midships for a starboard-side-to ship
    expect(store.getState().entities['sfit:BITT-1S'].pose.x).toBeCloseTo(0.3048 * 840);
    vi.advanceTimersByTime(1000);
    expect(post).not.toHaveBeenCalled();
    c.onEdit({ type: 'move', entityId: 'ship', pose, final: true });
    vi.advanceTimersByTime(1000);
    expect(post).toHaveBeenCalledTimes(1);
    const [path, opts] = post.mock.calls[0];
    expect(path).toBe('/api/v1/mooring/analyze');
    expect(opts.body.config.ship_x_ft).toBe(640);
    expect(opts.body.mst).toBe('II');
    expect(opts.body.environment).toEqual(env);
    expect(opts.body.config.lines).toHaveLength(1);
    c.dispose();
  });

  it('does not call the API when there are no lines', () => {
    const { c } = setup();
    c.setShipX(300);
    vi.advanceTimersByTime(1000);
    expect(post).not.toHaveBeenCalled();
    expect(c.state.get().analysis.state).toBe('idle');
    c.dispose();
  });
});

it('discards an old analysis even when it resolves during the edit debounce', async () => {
  const { c } = setup();
  let resolve!: (value: unknown) => void;
  post.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
  c.addLine('BITT-1S', 'P1');
  await vi.advanceTimersByTimeAsync(250);
  c.setShipX(600);
  resolve({ data: { result_id: 'obsolete' } });
  await Promise.resolve();
  await Promise.resolve();
  expect(c.state.get().analysis.response).toBeNull();
  expect(c.state.get().analysis.state).toBe('pending');
  c.dispose();
});

it('saves the displayed weather and tugs rather than switching to the live mock feed', async () => {
  const { c } = setup();
  post.mockResolvedValueOnce({ data: { env_scenario_id: 'weather-snapshot' } });
  post.mockResolvedValueOnce({ data: { scenario_id: 'saved', name: 'test' } });
  vi.spyOn(c, 'refreshScenarioList').mockResolvedValue();
  await c.saveScenario('test');
  expect(post.mock.calls[0][0]).toBe('/api/v1/env/scenarios');
  expect(post.mock.calls[0][1].body).toMatchObject({ kind: 'steady', wind_speed_kt: 10, wind_gust_kt: 15, current_speed_kt: 1 });
  expect(post.mock.calls[1][1].body.env_source).toMatchObject({ mode: 'scenario', env_scenario_id: 'weather-snapshot' });
  expect(post.mock.calls[1][1].body.tugs).toEqual([]);
  c.dispose();
});


it('loads the saved scenario through its canonical environment resolver', async () => {
  const { c } = setup();
  const resolved = { ...env, wind_speed_kt: 7, wind_gust_kt: 9 };
  const scenario = { scenario_id: 'saved', berth_id: berth.berth_id, ship_class_id: ship.class_id,
    loading: 'full_load', side_to: 'starboard', env_source: { mode: 'mock' },
    config: { side_to: 'starboard', ship_x_ft: 500, lines: [] }, tugs: [] };
  const get = vi.mocked(modeling.GET);
  get.mockImplementation(async (path) => {
    const data = path === '/api/v1/scenarios/{scenario_id}' ? scenario
      : path === '/api/v1/scenarios/{scenario_id}/environment' ? resolved
      : path === '/api/v1/berths/{berth_id}' ? berth
      : path === '/api/v1/ships/{class_id}' ? ship
      : path === '/api/v1/env/now' ? { ...env, source: 'live', wind_speed_kt: 60 } : undefined;
    if (!data) throw new Error(`Unexpected request: ${path}`);
    return { data } as never;
  });
  try {
    await c.loadScenario('saved');
    expect(c.state.get().env).toEqual(resolved);
    expect(c.state.get().scenarioId).toBe('saved');
    expect(get).toHaveBeenCalledWith('/api/v1/scenarios/{scenario_id}/environment', {
      params: { path: { scenario_id: 'saved' } },
    });
    expect(get).not.toHaveBeenCalledWith('/api/v1/env/now', expect.anything());
  } finally { c.dispose(); get.mockReset(); }
});

it('does not substitute another source when saved environment resolution fails', async () => {
  const { c } = setup();
  const previous = c.state.get().env;
  const get = vi.mocked(modeling.GET);
  get.mockImplementation(async (path) => {
    if (path === '/api/v1/scenarios/{scenario_id}') {
      return { data: { scenario_id: 'failed', berth_id: 'B1', env_source: { mode: 'live' } } } as never;
    }
    throw new Error('Selected source unavailable');
  });
  try {
    await c.loadScenario('failed');
    expect(c.state.get().env).toBe(previous);
    expect(c.state.get().scenarioId).not.toBe('failed');
    expect(c.state.get().notice).toContain('Selected source unavailable');
    expect(get).not.toHaveBeenCalledWith('/api/v1/env/now', expect.anything());
  } finally { c.dispose(); get.mockReset(); }
});


describe('applying an assessed recommendation', () => {
  const oldTug: TugAssignment = { tug_id: 'OLD', push_point_id: 'PP', mode: 'push', force_lbf: 100 };
  const holdingTug: TugAssignment = { tug_id: 'HOLD', push_point_id: 'PP', mode: 'push', force_lbf: 200 };
  it.each([{ assignments: [holdingTug] }, { assignments: [] }])('reanalyzes with candidate assistance $assignments', ({ assignments }) => {
    const { c } = setup();
    c.state.set({ tugAssignments: [oldTug] });
    const candidate = {
      config: { side_to: 'starboard', ship_x_ft: 500, lines: [{
        line_number: 1, spec_id: 'NYLON', parts: 2, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P1',
        paid_out_unstretched_length_ft: 144, condition: 'wet',
      }] },
      tugs: assignments,
    } as unknown as Candidate;
    c.applyCandidate(candidate);
    const request = c.buildAnalyzeRequest();
    expect(request?.tugs ?? []).toEqual(assignments);
    expect(request?.config.lines).toEqual(candidate.config.lines);
    c.dispose();
  });
});

it('keeps the resolved recommendation installation in subsequent analysis', () => {
  const { c } = setup();
  const assigned = { line_number: 1, spec_id: 'NYLON', parts: 2, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P1' };
  const resolved = { ...assigned, paid_out_unstretched_length_ft: 144, condition: 'wet' };
  const candidate = {
    config: { ship_x_ft: 500, side_to: 'starboard', lines: [assigned] },
    resolved_config: { ship_x_ft: 500, side_to: 'starboard', lines: [resolved] },
  } as unknown as Candidate;
  c.applyCandidate(candidate);
  expect(c.buildAnalyzeRequest()?.config.lines).toEqual([resolved]);
  c.dispose();
});

it('searches recommendations with the selected standoff and existing assistance', async () => {
  const { awaitJob } = await import('./api');
  vi.mocked(awaitJob).mockResolvedValue({ result: { candidates: [] } });
  post.mockResolvedValue({ data: { job_id: 'job_recommend', status_url: '/api/v1/jobs/job_recommend' } });
  const { c } = setup();
  const tugs: TugAssignment[] = [{ tug_id: 'HOLD', push_point_id: 'PP', mode: 'push', force_lbf: 200 }];
  c.state.set({ standoffOverrideFt: 18, tugAssignments: tugs });
  await c.recommend({ apply: false });
  expect(post).toHaveBeenCalledWith('/api/v1/mooring/recommend', expect.objectContaining({
    body: expect.objectContaining({ standoff_ft: 18, tugs }),
  }));
  c.dispose();
});

it('does not apply a recommendation after assistance changes during the search', async () => {
  const { awaitJob } = await import('./api');
  let complete!: (value: { result: { candidates: Candidate[] } }) => void;
  const completed = new Promise<{ result: { candidates: Candidate[] } }>((resolve) => { complete = resolve; });
  vi.mocked(awaitJob).mockReturnValue(completed);
  post.mockResolvedValue({ data: { job_id: 'job_recommend', status_url: '/api/v1/jobs/job_recommend' } });
  const { c } = setup();
  const originalTug: TugAssignment = { tug_id: 'OLD', push_point_id: 'PP', mode: 'push', force_lbf: 200 };
  const changedTug = { ...originalTug, force_lbf: 300 };
  c.state.set({ tugAssignments: [originalTug] });
  const pending = c.recommend({ apply: true });
  c.setTugAssignments([changedTug]);
  complete({ result: { candidates: [{
    config: { ship_x_ft: 500, lines: [] }, tugs: [originalTug], min_margin_pct_wll: 10,
    limit_wind_kt_worst: null, line_count: 0, analysis_result_id: 'old_result', why: [],
  }] } });
  await pending;
  expect(c.state.get().tugAssignments).toEqual([changedTug]);
  expect(c.state.get().recommend.candidates).toEqual([]);
  c.dispose();
});

it('refuses a stored recommendation after its geometry changes', async () => {
  const { awaitJob } = await import('./api');
  const candidate: Candidate = {
    config: { ship_x_ft: 500, lines: [{ line_number: 1, spec_id: 'NYLON', parts: 2,
      ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P1' }] },
    min_margin_pct_wll: 10, limit_wind_kt_worst: null, line_count: 1,
    analysis_result_id: 'old_geometry', why: [],
  };
  vi.mocked(awaitJob).mockResolvedValue({ result: { candidates: [candidate] } });
  post.mockResolvedValue({ data: { job_id: 'job_recommend', status_url: '/api/v1/jobs/job_recommend' } });
  const { c } = setup();
  await c.recommend({ apply: false });
  c.setShipX(600);
  c.applyCandidate(candidate);
  expect(c.state.get().lines).toEqual([]);
  expect(c.state.get().recommend.error).toContain('changed');
  c.dispose();
});

it.each(['parts', 'drag'])('clears old map loads immediately after a %s edit', async (edit) => {
  const { c, store } = setup();
  c.state.set({ lines: [{ line_number: 1, spec_id: 'NYLON', parts: 1, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P1' }],
    analysis: { state: 'ok', error: null, response: { status: 'AMBER', validity: { state: 'limited' }, result: {
      lines: [{ line_number: 1, status: 'GREEN', tension_lbf: 100, pct_wll: 12, pct_mbs: 4, length_ft: 30, horiz_angle_deg: 25, vert_angle_deg: 15 }],
      pier_fittings: [], ship_fittings: [],
    } } as never } });
  c.pushScene('full');
  expect(store.getState().links['line-1'].status).toBe('GREEN');
  if (edit === 'parts') c.updateLine(1, { parts: 3 });
  else c.onEdit({ type: 'move', entityId: 'ship', pose: { ...store.getState().entities.ship.pose, x: 200 }, final: false });
  expect(c.state.get().analysis.response).toBeNull();
  expect(store.getState().links['line-1'].status).toBeUndefined();
  expect(store.getState().links['line-1'].label).not.toContain('%');
  if (edit === 'parts') {
    await vi.runAllTimersAsync();
    expect(c.state.get().analysis.state).toBe('error'); // A failed recheck must not resurrect the old map values.
    expect(store.getState().links['line-1'].status).toBeUndefined();
  }
  c.dispose();
});

it.each(['wind', 'loading', 'position', 'standoff', 'tugs'])('motion saves fresh inputs after changing %s on a saved scenario', async (change) => {
  const { c } = setup();
  post.mockResolvedValueOnce({ data: { env_scenario_id: 'weather-snapshot' } });
  post.mockResolvedValueOnce({ data: { scenario_id: 'saved', name: 'test' } });
  vi.spyOn(c, 'refreshScenarioList').mockResolvedValue();
  await c.saveScenario('test');
  if (change === 'wind') c.setEnv({ wind_speed_kt: 20 });
  if (change === 'loading') c.setLoading('light');
  if (change === 'position') c.setShipX(600);
  if (change === 'standoff') c.setStandoff(20);
  if (change === 'tugs') c.setTugAssignments([{ tug_id: 'T1', force_lbf: 100 }] as never);
  const save = vi.spyOn(c, 'saveScenario').mockResolvedValue('fresh');
  post.mockResolvedValue({ data: { session_id: 'session' } });
  await c.motion.startSession();
  expect(save).toHaveBeenCalledOnce();
  expect(post.mock.calls.at(-1)?.[1].body.scenario_id).toBe('fresh');
  c.dispose();
});
