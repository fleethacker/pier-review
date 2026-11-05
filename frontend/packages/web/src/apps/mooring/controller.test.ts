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

import { MooringController } from './controller';
import type { Berth, Environment, ShipClass } from './types';

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
