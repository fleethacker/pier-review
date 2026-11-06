// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SceneStore } from '../../scene/store';
import { Banner, Sidebar } from './Chrome';
import { CameraBanner, CameraStatus } from './CameraPanels';
import { ControllerContext } from './context';
import { MissionsController } from './controller';
import {
  PredictionThrottle,
  WHAT_IFS,
  bannerText,
  buildPredictionRequest,
  cameraContent,
  missingHazards,
  toObservedState,
  withWhatIf,
} from './camera';
import * as api from './api';
import { samplePreset, sampleResponse, samplePredictRequest, samplePrediction, sampleSeries } from './fixtures';
import { makeProjector } from './scene';
import type { PredictionAlternative, TransitVesselState } from './types';

const v0 = {
  ...sampleSeries.frames[0].vessels[0],
  v_kt: -0.4,
  r_degps: 0.5,
  rudder_deg: 10,
  engine_order: 0.3,
  tugs: [
    {
      tug_id: 'T9',
      point: 'bow',
      force_lbf: 5000,
      direction_rel_deg: 370,
      lat: 0,
      lon: 0,
      source: 'command',
    },
  ],
} as unknown as TransitVesselState;

describe('state mapping', () => {
  it('keeps sign conventions and fills source, tugs, surge', () => {
    const o = toObservedState(v0, 'DDG-51-FIIA', '2026-11-05T15:00:00Z', 'job1');
    expect(o.sway_kt).toBe(-0.4); // + port, unchanged
    expect(o.yaw_rate_degps).toBe(0.5); // + CCW
    expect(o.rudder_deg).toBe(10); // + port
    expect(o.surge_kt).toBe(v0.u_kt);
    expect(o.engine_order).toBe(0.3);
    expect(o.source).toBe('sim:job1');
    expect(o.observed_utc).toBe('2026-11-05T15:00:00Z');
    expect(o.tugs).toEqual([
      { tug_id: 'T9', point: 'bow', force_lbf: 5000, direction_rel_deg: 10 },
    ]);
    expect(o.position).toEqual({ lat: v0.lat, lon: v0.lon });
  });
});

describe('request construction', () => {
  const o = toObservedState(v0, 'DDG-51-FIIA', '2026-11-05T15:00:00Z', 'j');
  it('hold only by default with8 samples,300s and10s, without inventing a berth', () => {
    const r = buildPredictionRequest(o);
    expect(r.alternatives).toEqual([]);
    expect(r.uncertainty?.samples).toBe(8);
    expect([r.horizon_s, r.tick_s]).toEqual([300, 10]);
    expect(r.hazards?.berth_id).toBeNull();
  });
  it('each what-if', () => {
    const by = (id: string) => buildPredictionRequest(o, { whatIfId: id }).alternatives?.[0];
    expect(by('rudder-port-15')?.helm_commands).toEqual([{ t_s: 0, rudder_deg: 15 }]);
    expect(by('rudder-stbd-15')?.helm_commands).toEqual([{ t_s: 0, rudder_deg: -15 }]);
    expect(by('engine-astern-half')?.helm_commands).toEqual([{ t_s: 0, engine_order: -0.5 }]);
    const tug = by('tug-push-stbd')?.tug_commands?.[0];
    expect(tug?.point).toBe('port_shoulder');
    expect(tug?.direction_rel_deg).toBe(90);
    for (const w of WHAT_IFS) expect(w.alt.alt_id).toMatch(/^[a-z0-9_-]+$/);
  });
  it('preset what-if replaces alternatives without mutating the preset', () => {
    const r = withWhatIf(samplePredictRequest, 'rudder-port-15');
    expect(r.alternatives).toHaveLength(1);
    expect(samplePredictRequest.alternatives?.length).toBe(2);
  });
});

describe('banner text', () => {
  const base = samplePrediction.result.alternatives[0];
  it('breach', () => {
    const a = {
      ...base,
      first_breach: {
        t_s: 42,
        kind: 'pier',
        element_id: 'p',
        clearance_ft: -3.2,
        position: { lat: 0, lon: 0 },
        probability: 0.62,
      },
    } as PredictionAlternative;
    expect(bannerText(a).text).toBe(
      'Predicted pier contact in 42 s (clearance -3 ft, 62% of samples)',
    );
    expect(bannerText(a).level).toBe('breach');
  });
  it('no breach', () => {
    const a = {
      ...base,
      first_breach: null,
      closest_approach: {
        t_s: 120,
        kind: 'pier',
        element_id: 'p',
        clearance_ft: 210.4,
        position: { lat: 0, lon: 0 },
      },
    } as PredictionAlternative;
    expect(bannerText(a).text).toBe('Closest approach 210 ft at +120 s');
  });
  it('flags unchecked coastline', () => {
    expect(missingHazards(samplePrediction)).toEqual(['coastline']);
  });
});

describe('throttle', () => {
  it('drops calls while in flight or within 1 s, and force aborts the old one', async () => {
    let t = 0;
    const th = new PredictionThrottle(() => t, 1000);
    let signal1: AbortSignal | undefined;
    let release: (v: number) => void = () => {};
    const p1 = th.run(
      (s) =>
        new Promise<number>((res, rej) => {
          signal1 = s;
          release = res;
          s.addEventListener('abort', () => rej(new DOMException('x', 'AbortError')));
        }),
    );
    expect((await th.run(async () => 2)).ran).toBe(false); // in flight
    release(1);
    expect((await p1).value).toBe(1);
    t = 500;
    expect((await th.run(async () => 3)).ran).toBe(false); // too soon
    t = 1500;
    expect((await th.run(async () => 4)).value).toBe(4);
    const p5 = th.run(
      (s) =>
        new Promise<number>((_r, rej) =>
          s.addEventListener('abort', () => rej(new DOMException('x', 'AbortError'))),
        ),
      true,
    );
    const p6 = th.run(async () => 6, true);
    await expect(p5).rejects.toThrow();
    expect((await p6).value).toBe(6);
    expect(signal1?.aborted).toBe(false);
  });
});

describe('map content', () => {
  it('draws footprints every 30 s with labels, corridor ring and a breach marker', () => {
    const p = makeProjector(36.956, -76.326);
    const res = structuredClone(samplePrediction);
    res.result.alternatives[0].first_breach = {
      t_s: 40,
      kind: 'pier',
      element_id: 'p',
      clearance_ft: 5,
      position: { lat: 36.955, lon: -76.326 },
    };
    const c = cameraContent(res, p, null);
    const labels = c.entities.filter((e) => e.kind === 'cam-label').map((e) => e.label);
    expect(labels).toEqual(expect.arrayContaining(['+30s', '+60s']));
    expect(labels).not.toContain('+10s');
    expect(c.entities.some((e) => e.kind === 'cam-breach')).toBe(true);
    expect(c.links.some((l) => l.kind === 'cam-path')).toBe(true);
  });
});

describe('camera tab', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });
  it('falls back to the sample prediction with a banner when the backend returns 501', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue({ ok: false, status: 501, statusText: 'x', json: async () => ({}) }),
    );
    const c = new MissionsController({ store: new SceneStore() });
    await c.init();
    render(
      <ControllerContext.Provider value={c}>
        <Banner />
        <Sidebar />
      </ControllerContext.Provider>,
    );
    // The shell's tab bar selects the tab now; it calls the controller the same way.
    act(() => c.setTab('camera'));
    fireEvent.click(screen.getByRole('button', { name: 'Preset' }));
    await waitFor(() => expect(screen.getAllByText(/Sample prediction/).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/Hazards not checked: coastline/).length).toBeGreaterThan(0);
    expect(screen.getByText(/decision support, not navigational guidance/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Rudder 15° port' }));
    expect(c.state.camWhatIf).toBe('rudder-port-15');
    c.dispose();
  });
});

it('shows unavailable uncertainty and hazard limitations instead of an all-clear', () => {
  const c = new MissionsController({ store: new SceneStore() });
  const res = structuredClone(samplePrediction);
  res.result.alternatives.forEach((a) => { a.corridor = null; });
  res.validity = { state: 'limited', reasons: [
    { code: 'HAZARD_COVERAGE_UNKNOWN', message: 'Hazards were not supplied.' },
    { code: 'OTHER_VESSEL_PATH_SHORT', message: 'Other vessel path ends early.' },
    { code: 'UNCERTAINTY_UNAVAILABLE', message: 'No calibrated corridor supplied.' },
  ] };
  c.store.setState({ camResult: res, camSample: false });
  render(<ControllerContext.Provider value={c}><CameraBanner /><CameraStatus /></ControllerContext.Provider>);
  expect(screen.getAllByText(/Uncertainty unavailable/i).length).toBeGreaterThan(0);
  expect(screen.getByText(/no all-clear/i)).toBeTruthy();
  expect(screen.getByText(/OTHER_VESSEL_PATH_SHORT/)).toBeTruthy();
  c.dispose();
  cleanup();
});


describe('transit camera identity and forcing (F09/F10/T02)', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
  it('preserves completed-run forcing, aligns traffic, and renders only the newly selected vessel despite a late response', async () => {
    const pending: { body: import('./types').PredictionRequest; resolve: (response: Response) => void; signal?: AbortSignal | null }[] = [];
    vi.spyOn(api, 'runTransit').mockResolvedValue(structuredClone(sampleResponse));
    const longSeries = structuredClone(sampleSeries);
    // Extend the explicit test fixture, so an end inside the final sample gap must be interpolated.
    longSeries.frames.push({ ...structuredClone(longSeries.frames.at(-1)!), t_s: 360 });
    vi.spyOn(api.missionsApi, 'series').mockResolvedValue(longSeries);
    vi.stubGlobal('fetch', vi.fn((url: string | URL | Request, init?: RequestInit) => {
      if (String(url).includes('/ships/')) return Promise.resolve(new Response(JSON.stringify({ loa_ft: 500, beam_ft: 60 })));
      if (String(url).includes('/predict/trajectory')) return new Promise<Response>((resolve) => pending.push({ body: JSON.parse(String(init?.body)), resolve, signal: init?.signal }));
      throw new Error(`Unexpected fetch ${url}`);
    }));
    const c = new MissionsController({ store: new SceneStore() });
    const request = structuredClone(samplePreset.request);
    request.environment = { ...samplePredictRequest.environment!, source: 'scenario', wind_speed_kt: 27, wind_gust_kt: 35, wind_from_true_deg: 81,
      current_speed_kt: 1.8, current_set_true_deg: 249, water_level_mllw_ft: 2 };
    request.vessels[0].loading = 'light';
    c.store.setState({ request, sampleTransit: false, tab: 'transit' });
    await c.run();
    await waitFor(() => expect(c.buildCameraRequest()).not.toBeNull());
    // Editing the next run must not rewrite the evidence underlying the completed one.
    c.setRequestText(JSON.stringify({ ...request, environment: { ...request.environment, wind_speed_kt: 0 } }));
    c.setPlayhead(12.5);
    const built = c.buildCameraRequest()!;
    expect(built.environment).toEqual(request.environment);
    expect(built.vessel.loading).toBe('light');
    expect(built.as_of_utc).toBe('2026-11-05T12:00:12.500Z');
    expect(built.others).toHaveLength(1);
    expect(built.others![0]).toMatchObject({ vessel_id: 'MOCK-B', length_ft: 500, beam_ft: 60 });
    expect(built.others![0].path[0].t_utc).toBe(built.as_of_utc);
    expect(built.others![0].path.at(-1)!.t_utc).toBe(new Date(Date.parse(built.as_of_utc!) + 300000).toISOString());
    render(<ControllerContext.Provider value={c}><CameraBanner /></ControllerContext.Provider>);
    act(() => c.setCameraOn(true));
    await waitFor(() => expect(pending).toHaveLength(1));
    act(() => c.selectVessel('MOCK-B'));
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[0].signal?.aborted).toBe(true);
    expect(pending[1].body.vessel.vessel_id).toBe('MOCK-B');
    expect(pending[1].body.others![0].vessel_id).toBe('MOCK-A');
    const reply = (id: string) => { const value = structuredClone(samplePrediction); value.result.vessel_id = id; value.result.as_of_utc = built.as_of_utc!; return new Response(JSON.stringify(value)); };
    await act(async () => { pending[1].resolve(reply('MOCK-B')); });
    await waitFor(() => expect(screen.getByText(/Prediction for MOCK-B/)).toBeTruthy());
    await act(async () => { pending[0].resolve(reply('MOCK-A')); });
    expect(screen.queryByText(/Prediction for MOCK-A/)).toBeNull();
    expect(c.state.camResult?.result.vessel_id).toBe('MOCK-B');
    expect(c.state.clock.playing).toBe(false);
    act(() => c.store.setState({ clock: { ...c.state.clock, t: 22.5 } })); // continuous playback advances independently of a pending prediction
    expect(screen.getByText(/10 simulated seconds behind playback/)).toBeTruthy();
    const refresh = c.requestCamera(true);
    await waitFor(() => expect(pending.length).toBeGreaterThanOrEqual(3));
    const latest = pending.at(-1)!;
    const fresh = structuredClone(samplePrediction); fresh.result.vessel_id = 'MOCK-B'; fresh.result.as_of_utc = latest.body.as_of_utc!;
    await act(async () => { latest.resolve(new Response(JSON.stringify(fresh))); await refresh; });
    expect(screen.queryByText(/simulated seconds behind playback/)).toBeNull();
    expect(screen.getByText(/Prediction for MOCK-B at 2026-11-05T12:00:22.500Z/)).toBeTruthy();
    c.dispose();
  });
});


it('paused backward and forward seeks always replace the visible input, even inside the throttle interval', async () => {
  const pending: { request: import('./types').PredictionRequest; signal?: AbortSignal | null; resolve: (response: Response) => void }[] = [];
  vi.stubGlobal('fetch', vi.fn((_url: unknown, init: RequestInit) => new Promise<Response>((resolve) => pending.push({
    request: JSON.parse(String(init.body)), signal: init.signal, resolve,
  }))));
  const c = new MissionsController({ store: new SceneStore() });
  const response = structuredClone(sampleResponse); response.result.vessels = response.result.vessels.slice(0,1);
  const request = structuredClone(samplePreset.request); request.vessels = request.vessels.slice(0,1);
  const series = structuredClone(sampleSeries); series.frames.forEach((frame) => { frame.vessels = frame.vessels.slice(0,1); });
  c.store.setState({ tab: 'transit', response, completedRequest: request, series, selectedVesselId: request.vessels[0].vessel_id });
  c.setPlayhead(30); c.store.setState({ cameraOn: true });
  const old = c.requestCamera(true);
  expect(pending).toHaveLength(1);
  c.setPlayhead(0);
  expect(pending).toHaveLength(2);
  expect(pending[0].signal?.aborted).toBe(true);
  const reply = (index: number) => { const value = structuredClone(samplePrediction); value.result.vessel_id = pending[index].request.vessel.vessel_id;
    value.result.as_of_utc = pending[index].request.as_of_utc!; pending[index].resolve(new Response(JSON.stringify(value))); };
  reply(0); await old;
  expect(c.state.camResult).toBeNull(); // a response for a later playhead may never come back after a backward seek
  reply(1); await waitFor(() => expect(c.state.camInputTimeS).toBe(0));
  c.setPlayhead(25);
  expect(pending).toHaveLength(3); // final seek is never dropped by the one-second continuous-play throttle
  expect(c.state.camResult).toBeNull();
  reply(2); await waitFor(() => expect(c.state.camInputTimeS).toBe(25));
  expect(c.state.clock.playing).toBe(false);
  expect(pending[2].request.hazards?.berth_id).toBeNull();
  const unbound = structuredClone(c.state.camResult!); unbound.result.hazards_checked = ['vessel'];
  expect(missingHazards(unbound)).toEqual(['pier', 'fender', 'coastline']);
  c.dispose(); vi.unstubAllGlobals();
});
