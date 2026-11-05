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
import { beginConnection } from '../../scene/linkEditing';
import { ft } from './units';
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
    { fitting_id: 'BITT-1P', kind: 'bitt', x_ft: 200, y_ft: 9, z_ft: 24, side: 'port', swl_lbf: 1 },
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
  it.each(['starboard', 'port'] as const)('updates both request axes without changing heading for %s side to', (side) => {
    const { store, c } = setup();
    c.state.set({ side });
    // A stored installation is preserved even when moving it makes its geometry unsuitable.
    const line = { line_number: 17, spec_id: 'NYLON', parts: 3 as const, ship_fitting_id: side === 'port' ? 'BITT-1P' : 'BITT-1S',
      pier_fitting_id: 'P1', paid_out_unstretched_length_ft: 199, condition: 'wet' as const };
    c.state.set({ lines: [line] });
    c.pushScene('full');
    const pose = { ...store.getState().entities.ship.pose, x: ft(725), y: ft(ship.beam_ft / 2 + 43) };
    c.onEdit({ type: 'move', entityId: 'ship', pose, final: false });
    expect(c.buildAnalyzeRequest()?.config).toMatchObject({ side_to: side, ship_x_ft: 725, standoff_ft: 43, lines: [line] });
    expect(store.getState().entities.ship.pose.headingDeg).toBe(side === 'starboard' ? 0 : 180);
    expect(c.state.get().analysis.state).toBe('idle');
    c.onEdit({ type: 'move', entityId: 'ship', pose, final: true });
    expect(c.state.get().analysis.state).toBe('pending');
    c.dispose();
  });

  it('clamps pointer placement to the berth and prevents hull penetration; ignores nonfinite input', () => {
    const { store, c } = setup();
    const pose = { ...store.getState().entities.ship.pose, x: ft(1200), y: -100 };
    c.onEdit({ type: 'move', entityId: 'ship', pose, final: true });
    expect(c.state.get()).toMatchObject({ shipXFt: 1000, standoffOverrideFt: 0 });
    c.onEdit({ type: 'move', entityId: 'ship', pose: { ...pose, x: NaN }, final: true });
    c.setShipX(NaN);
    c.setStandoff(-4);
    c.setStandoff(NaN);
    expect(c.state.get()).toMatchObject({ shipXFt: 1000, standoffOverrideFt: 0 });
    c.dispose();
  });

  it.each([null, 12.5])('cancellation restores the exact original placement and standoff %s', (standoffOverrideFt) => {
    const { store, c } = setup();
    c.state.set({ shipXFt: 500.5, standoffOverrideFt });
    c.pushScene('full');
    const initialPose = store.getState().entities.ship.pose;
    c.onEdit({ type: 'move', entityId: 'ship', pose: { ...initialPose, x: ft(700), y: ft(80) }, final: false });
    c.onEdit({ type: 'move', entityId: 'ship', pose: initialPose, final: true, cancelled: true });
    expect(c.state.get()).toMatchObject({ shipXFt: 500.5, standoffOverrideFt });
    expect(store.getState().entities.ship.pose).toEqual(initialPose);
    c.dispose();
  });
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

describe('fitting drags', () => {
  it('finishes a pending click-to-connect choice after a successful pointer connection', () => {
    const { c, store } = setup();
    c.startAddLine();
    store.select({ type: 'entity', id: 'sfit:BITT-1S' });
    const edit = beginConnection(store.getState(), 'sfit:BITT-2S')!;
    c.onEdit({ ...edit, toEntityId: 'pier:P2', final: true });
    expect(c.state.get().lines).toHaveLength(1);
    expect(c.state.get().addLine.shipFittingId).toBeNull();
    store.select({ type: 'entity', id: 'pier:P1' });
    expect(c.state.get().lines).toHaveLength(1);
    c.dispose();
  });
  it.each([['sfit:BITT-1S', 'pier:P2'], ['pier:P2', 'sfit:BITT-1S']])('creates from %s to %s using selected rope and parts', (source, target) => {
    const { c, store } = setup();
    c.setNewLineSpec('SYNTHETIC-TEST', 3);
    const edit = beginConnection(store.getState(), source)!;
    c.onEdit(edit);
    expect(c.state.get().lines).toEqual([]);
    c.onEdit({ ...edit, toEntityId: target, final: true });
    expect(c.buildAnalyzeRequest()?.config.lines).toEqual([{ line_number: 1, spec_id: 'SYNTHETIC-TEST', parts: 3,
      ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P2' }]);
    c.dispose();
  });

  it.each([['sfit:BITT-1S', 'sfit:BITT-2S', 'ship_fitting_id', 'BITT-2S'],
    ['pier:P1', 'pier:P2', 'pier_fitting_id', 'P2']])('reconnects %s while retaining every installation field', (source, target, field, value) => {
    const { c, store } = setup();
    const line = { line_number: 8, spec_id: 'NYLON', parts: 2 as const, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P1',
      role: 'bow' as const, chock_id: 'EXPLICIT-CHOCK', paid_out_unstretched_length_ft: 178.5, condition: 'dry' as const };
    c.state.set({ lines: [line] });
    c.pushScene('full');
    store.select({ type: 'link', id: 'line-8' });
    const edit = beginConnection(store.getState(), source)!;
    expect(edit.linkId).toBe('line-8');
    c.onEdit({ ...edit, toEntityId: target, final: true });
    expect(c.state.get().lines).toEqual([{ ...line, [field]: value }]);
    c.dispose();
  });

  it.each([{ target: null, cancelled: true }, { target: 'sfit:BITT-2S', cancelled: false },
    { target: 'pier:missing', cancelled: false }])('invalid or cancelled drops leave configuration unchanged: %j', ({ target, cancelled }) => {
    const { c, store } = setup();
    c.addLine('BITT-1S', 'P1');
    const before = c.buildAnalyzeRequest()?.config;
    const edit = beginConnection(store.getState(), 'sfit:BITT-1S')!;
    c.onEdit({ ...edit, toEntityId: target, final: true, cancelled });
    expect(c.buildAnalyzeRequest()?.config).toEqual(before);
    c.dispose();
  });

  it('rejects foreign fitting ids and a drag completed after the selected class changes', () => {
    const { c, store } = setup();
    c.addLine('OTHER-SHIP', 'P1');
    c.addLine('BITT-1S', 'OTHER-PIER');
    const edit = beginConnection(store.getState(), 'sfit:BITT-1S')!;
    c.state.set({ shipClassId: 'NEW-CLASS' });
    c.onEdit({ ...edit, toEntityId: 'pier:P1', final: true });
    expect(c.state.get().lines).toEqual([]);
    c.dispose();
  });
});

describe('selection changes during editing', () => {
  it.each(['side', 'loading', 'position', 'standoff'] as const)('a pending scenario cannot overwrite a later %s edit', async (edit) => {
    const { c } = setup();
    let finish!: (value: unknown) => void;
    const pending = new Promise((resolve) => { finish = resolve; });
    const get = vi.mocked(modeling.GET);
    get.mockReturnValue(pending as never);
    vi.spyOn(c, 'recommend').mockResolvedValue();
    try {
      const old = c.loadScenario('old');
      if (edit === 'side') await c.setSide('port');
      if (edit === 'loading') c.setLoading('light');
      if (edit === 'position') c.setShipX(740);
      if (edit === 'standoff') c.setStandoff(35);
      const intended = { side: c.state.get().side, loading: c.state.get().loading,
        shipXFt: c.state.get().shipXFt, standoffOverrideFt: c.state.get().standoffOverrideFt };
      finish({ data: { scenario_id: 'old', ship_class_id: 'S1', berth_id: 'B1', side_to: 'starboard' } });
      await old;
      expect(c.state.get()).toMatchObject({ ...intended, scenarioId: null });
      expect(get).toHaveBeenCalledTimes(1);
    } finally { get.mockReset(); c.dispose(); }
  });

  it('a side edit does not strand an in-flight class catalog fetch', async () => {
    const { c } = setup();
    let finish!: (value: unknown) => void;
    const pending = new Promise((resolve) => { finish = resolve; });
    const get = vi.mocked(modeling.GET);
    get.mockImplementation(async (path) => path === '/api/v1/ships/{class_id}' ? pending as never : { data: berth } as never);
    vi.spyOn(c, 'recommend').mockResolvedValue();
    try {
      const selected = c.setShip('NEW');
      await c.setSide('port');
      finish({ data: { ...ship, class_id: 'NEW' } });
      await selected;
      expect(c.state.get()).toMatchObject({ side: 'port', shipClassId: 'NEW', ship: { class_id: 'NEW' } });
    } finally { get.mockReset(); c.dispose(); }
  });

  it('a late berth load cannot switch a newer environment mode back to manual or restart its alerts', async () => {
    const { c } = setup();
    let finishA!: (value: unknown) => void;
    const pending = new Promise((resolve) => { finishA = resolve; });
    const get = vi.mocked(modeling.GET);
    get.mockImplementation(async (path, options) => {
      if (path === '/api/v1/berths/{berth_id}') {
        const id = (options as { params: { path: { berth_id: string } } }).params.path.berth_id;
        return id === 'A' ? pending as never : { data: { ...berth, berth_id: id } } as never;
      }
      return { data: path === '/api/v1/ships/{class_id}' ? { ...ship, fittings: [] } : env } as never;
    });
    const alerts = vi.spyOn(c, 'startAlerts').mockImplementation(() => {});
    vi.spyOn(c, 'setEnvMode').mockImplementation(async (kind) => c.state.set({ envMode: { kind, status: 'idle', detail: null } }));
    try {
      const first = c.setBerth('A');
      await c.setBerth('B');
      await c.setEnvMode('live');
      finishA({ data: { ...berth, berth_id: 'A' } });
      await first;
      expect(c.state.get().berthId).toBe('B');
      expect(c.state.get().envMode.kind).toBe('live');
      expect(alerts).toHaveBeenCalledTimes(1);
    } finally { get.mockReset(); c.dispose(); }
  });

  it.each(['chock-only', 'opposite-side', 'missing-loading'])('blocks recommendation and pointer edits for %s coverage', async (coverage) => {
    const { c, store } = setup();
    const unsupported = { ...ship, fittings: ship.fittings!.map((f) => ({ ...f,
      kind: coverage === 'chock-only' ? 'chock' as const : f.kind,
      side: coverage === 'opposite-side' ? 'port' as const : f.side })) };
    c.state.set({ ship: unsupported, ...(coverage === 'missing-loading' ? { loading: 'missing' } : {}) });
    c.pushScene('full');
    expect(store.getState().entities.ship.editable).toBeUndefined();
    expect(Object.values(store.getState().entities).filter((e) => e.kind === 'ship-fitting').every((e) => !e.connectable)).toBe(true);
    c.onEdit({ type: 'move', entityId: 'ship', pose: { x: ft(900), y: ft(100), z: 0, headingDeg: 0 }, final: true });
    expect(c.state.get().shipXFt).toBe(500);
    await c.recommend({ apply: false });
    expect(post).not.toHaveBeenCalled();
    expect(c.state.get().recommend.state).toBe('error');
    c.dispose();
  });

  it.each(['chock-only', 'opposite-side'])('does not auto-recommend a selected %s catalog', async (coverage) => {
    const { c } = setup();
    const unsupported = { ...ship, class_id: 'OTHER', fittings: [{ ...ship.fittings![0],
      ...(coverage === 'chock-only' ? { kind: 'chock' } : { side: 'port' }) }] };
    const get = vi.mocked(modeling.GET);
    get.mockImplementation(async (path) => ({ data: path === '/api/v1/ships/{class_id}' ? unsupported : berth }) as never);
    try {
      await c.setShip('OTHER');
      expect(post).not.toHaveBeenCalled();
      expect(c.state.get().recommend.state).toBe('idle');
    } finally { get.mockReset(); c.dispose(); }
  });

  it('cannot restore an old scenario after a newer class selection', async () => {
    const { c } = setup();
    let finish!: (value: unknown) => void;
    const pending = new Promise((resolve) => { finish = resolve; });
    const get = vi.mocked(modeling.GET);
    get.mockImplementation(async (path) => {
      if (path === '/api/v1/scenarios/{scenario_id}') return pending as never;
      return { data: path === '/api/v1/ships/{class_id}' ? { ...ship, class_id: 'NEW', fittings: [] } : berth } as never;
    });
    try {
      const oldScenario = c.loadScenario('old');
      await c.setShip('NEW');
      finish({ data: { scenario_id: 'old', ship_class_id: 'S1', berth_id: 'B1' } });
      await oldScenario;
      expect(c.state.get().shipClassId).toBe('NEW');
      expect(c.state.get().scenarioId).toBeNull();
      expect(get).not.toHaveBeenCalledWith('/api/v1/scenarios/{scenario_id}/environment', expect.anything());
    } finally { get.mockReset(); c.dispose(); }
  });

  it('clears old lines and agent plan immediately, and ignores a late class response', async () => {
    const { c, store } = setup();
    c.addLine('BITT-1S', 'P1');
    c.startAddLine();
    store.select({ type: 'entity', id: 'sfit:BITT-1S' });
    c.agent.state.set({ planId: 'stale', plan: {} as never });
    let finishA!: (value: unknown) => void;
    const pendingA = new Promise((resolve) => { finishA = resolve; });
    const get = vi.mocked(modeling.GET);
    get.mockImplementation(async (path, options) => {
      if (path === '/api/v1/berths/{berth_id}') return { data: berth } as never;
      const classId = (options as { params: { path: { class_id: string } } }).params.path.class_id;
      if (classId === 'A') return pendingA as never;
      return { data: { ...ship, class_id: 'B', fittings: [] } } as never;
    });
    try {
      const first = c.setShip('A');
      expect(c.state.get().lines).toEqual([]);
      expect(c.state.get().analysis.response).toBeNull();
      expect(c.state.get().addLine.active).toBe(false);
      expect(c.agent.state.get().plan).toBeNull();
      expect(store.getState().links).toEqual({});
      expect(store.getState().entities.ship.editable).toBeUndefined();
      await c.setShip('B');
      finishA({ data: { ...ship, class_id: 'A' } });
      await first;
      expect(c.state.get().ship?.class_id).toBe('B');
      expect(store.getState().entities.ship.editable).toBeUndefined();
    } finally { get.mockReset(); c.dispose(); }
  });

  it('clears foreign pier connections before the new berth finishes loading', async () => {
    const { c, store } = setup();
    c.addLine('BITT-1S', 'P1');
    const get = vi.mocked(modeling.GET);
    let finishBerth!: (value: unknown) => void;
    const pending = new Promise((resolve) => { finishBerth = resolve; });
    get.mockImplementation(async (path) => {
      if (path === '/api/v1/berths/{berth_id}') return pending as never;
      return { data: path === '/api/v1/ships/{class_id}' ? { ...ship, fittings: [] } : env } as never;
    });
    vi.spyOn(c, 'startAlerts').mockImplementation(() => {});
    try {
      const loading = c.setBerth('B2');
      expect(c.state.get().lines).toEqual([]);
      expect(store.getState().links).toEqual({});
      finishBerth({ data: { ...berth, berth_id: 'B2' } });
      await loading;
      expect(c.state.get().berth?.berth_id).toBe('B2');
    } finally { get.mockReset(); c.dispose(); }
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
