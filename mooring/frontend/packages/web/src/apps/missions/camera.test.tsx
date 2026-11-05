// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SceneStore } from '../../scene/store';
import { Banner, Sidebar } from './Chrome';
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
import { samplePredictRequest, samplePrediction, sampleSeries } from './fixtures';
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
  it('hold only by default with defaults 8 samples, 300 s, 10 s, berth', () => {
    const r = buildPredictionRequest(o);
    expect(r.alternatives).toEqual([]);
    expect(r.uncertainty?.samples).toBe(8);
    expect([r.horizon_s, r.tick_s]).toEqual([300, 10]);
    expect(r.hazards?.berth_id).toBe('NAVSTA-NORFOLK-P12-N');
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
    expect(screen.getByText(/Hazards not checked: coastline/)).toBeTruthy();
    expect(screen.getByText(/decision support, not navigational guidance/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Rudder 15° port' }));
    expect(c.state.camWhatIf).toBe('rudder-port-15');
    c.dispose();
  });
});
