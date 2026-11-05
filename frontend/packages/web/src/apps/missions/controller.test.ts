import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SceneStore } from '../../scene/store';
import { MissionsController } from './controller';
import { sampleSeries, sampleStoryboard } from './fixtures';

const json = (status: number, body: unknown) => ({ ok: status < 400, status, statusText: 'x', json: async () => body });

function make() {
  const store = new SceneStore();
  const c = new MissionsController({ store });
  return { store, c };
}

beforeEach(() => vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(501, { detail: 'not implemented' }))));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('sample data mode', () => {
  it('falls back to fixtures on 501 and shows markers only for located events', async () => {
    const { store, c } = make();
    await c.init();
    expect(c.state.sampleStoryboard).toBe(true);
    expect(c.state.sampleTransit).toBe(true);
    expect(c.state.storyboard?.mission.mission_id).toBe('sample-mission');
    const kinds = Object.values(store.getState().entities).map((e) => e.id);
    expect(kinds.filter((i) => i.startsWith('event:'))).toHaveLength(3);
    expect(Object.keys(store.getState().links).length).toBeGreaterThan(5);
  });

  it('moves the ship along the track, hides it in gaps and beyond the ends', async () => {
    const { store, c } = make();
    await c.init();
    const t0 = Date.parse(sampleStoryboard.track[0].t_utc);
    c.setScrub(t0 + 90_000);
    expect(c.state.shipPosition?.method).toBe('interpolated');
    expect(store.getState().entities['mission-ship']).toBeDefined();
    c.setScrub(t0 + 20 * 60_000);
    expect(c.state.shipPosition).toMatchObject({ method: 'gap', established: false });
    expect(store.getState().entities['mission-ship']).toBeUndefined();
    c.setScrub(t0 - 5 * 60_000);
    expect(c.state.shipPosition?.method).toBe('before_track');
    expect(store.getState().entities['mission-ship']).toBeUndefined();
  });

  it('selecting an event jumps the scrubber and highlights it', async () => {
    const { c } = make();
    await c.init();
    c.selectEvent('rep-2');
    expect(c.state.scrubMs).toBe(Date.parse('2026-11-05T12:05:30Z'));
    expect(c.currentEventId()).toBe('rep-2');
  });

  it('frames the data with invisible fit anchors, and follows the ship in the 2D view only', async () => {
    const { store, c } = make();
    await c.init();
    expect(Object.keys(store.getState().entities).filter((i) => i.startsWith('fit-anchor'))).toHaveLength(2);
    const t0 = Date.parse(sampleStoryboard.track[0].t_utc);
    const rev = () => store.getState().cameraPreset?.revision ?? 0;
    const before = rev();
    c.setScrub(t0 + 90_000);
    expect(rev()).toBeGreaterThan(before);
    expect(store.getState().cameraPreset?.target).toBeDefined();
    c.setFollow(false);
    const off = rev();
    c.setScrub(t0 + 120_000);
    expect(rev()).toBe(off);
    c.setFollow(true);
    store.setViewMode('3d');
    const in3d = rev();
    c.setScrub(t0 + 150_000);
    expect(rev()).toBe(in3d);
  });

  it('refuses writes with a clear message', async () => {
    const { c } = make();
    await c.init();
    await c.addReport({ t_utc: '2026-11-05T12:00:00Z', title: 't', body: '', tags: [] });
    expect(c.state.error).toMatch(/Sample data/);
  });

  it('runs the sample transit and plays back with a clock that stops at the end', async () => {
    vi.useFakeTimers();
    const { store, c } = make();
    await c.init();
    c.setTab('transit');
    await c.run();
    expect(c.state.series?.frames.length).toBe(sampleSeries.frames.length);
    expect(c.state.vessels).toHaveLength(2);
    expect(Object.keys(store.getState().entities).filter((i) => i.startsWith('vessel:'))).toHaveLength(2);
    c.setSpeed(60);
    c.play();
    expect(c.state.clock.playing).toBe(true);
    vi.advanceTimersByTime(60_000);
    expect(c.state.clock.t).toBe(sampleSeries.frames.at(-1)!.t_s);
    expect(c.state.clock.playing).toBe(false);
    // tugs show as force arrows at the end of the run
    expect(Object.keys(store.getState().vectors).length).toBeGreaterThan(0);
    c.dispose();
  });

  it('refuses to save missions from sample data', async () => {
    const { c } = make();
    await c.init();
    c.setTab('transit');
    await c.run();
    await c.saveAsMission();
    expect(c.state.transitError).toMatch(/Sample data/);
  });
});

describe('live backend', () => {
  it('lists missions and loads a storyboard', async () => {
    const mission = { ...sampleStoryboard.mission, mission_id: 'live-1' };
    const fetch = vi.fn(async (url: string) => {
      if (url.endsWith('/missions')) return json(200, [mission]);
      if (url.includes('/storyboard')) return json(200, { ...sampleStoryboard, mission });
      if (url.includes('/track?')) return json(200, { mission_id: mission.mission_id, fixes: sampleStoryboard.track, fix_count: sampleStoryboard.track.length, decimated: false });
      if (url.endsWith('/transit/presets')) return json(200, []);
      return json(404, {});
    });
    vi.stubGlobal('fetch', fetch);
    const { c } = make();
    await c.init();
    expect(c.state.sampleStoryboard).toBe(false);
    expect(c.state.missionId).toBe('live-1');
    expect(c.state.storyboard?.events).toHaveLength(sampleStoryboard.events.length);
  });

  it('saves one mission per vessel and opens the storyboard tab', async () => {
    const posts: string[] = [];
    let n = 0;
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^https?:\/\/[^/]+\/api\/modeling/, '');
      if (init?.method === 'POST' && path === '/api/v1/missions') {
        const m = { ...sampleStoryboard.mission, mission_id: `m${++n}` };
        posts.push(`create:${(JSON.parse(init.body as string) as { vessel_id: string }).vessel_id}`);
        return json(201, m);
      }
      if (init?.method === 'POST' && path.endsWith('/track')) {
        posts.push(`track:${path.split('/')[4]}:${(JSON.parse(init.body as string) as { fixes: unknown[] }).fixes.length > 0}`);
        return json(200, {});
      }
      if (path === '/api/v1/missions') return json(200, [{ ...sampleStoryboard.mission, mission_id: 'm1' }]);
      if (path.includes('/storyboard')) return json(200, { ...sampleStoryboard, mission: { ...sampleStoryboard.mission, mission_id: path.split('/')[4] } });
      if (path.includes('/transit/presets')) return json(200, []);
      return json(404, {});
    });
    vi.stubGlobal('fetch', fetch);
    const { c } = make();
    await c.init();
    c.store.setState({ tab: 'transit', response: (await import('./fixtures')).sampleResponse, sampleTransit: false });
    await c.saveAsMission();
    expect(posts).toEqual(['create:MOCK-A', 'track:m1:true', 'create:MOCK-B', 'track:m2:true']);
    expect(c.state.tab).toBe('storyboard');
  });
});


const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
};
const storyboardFor = (id: string) => ({ ...sampleStoryboard, mission: { ...sampleStoryboard.mission, mission_id: id } });
const fullTrackFor = (id: string) => ({ mission_id: id, fixes: sampleStoryboard.track, fix_count: sampleStoryboard.stats.fix_count, decimated: false });

describe('mission evidence ownership', () => {
  it('keeps the latest selection when earlier requests complete last, including busy state', async () => {
    const a = deferred<ReturnType<typeof json>>();
    const b = deferred<ReturnType<typeof json>>();
    vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('/track?')
      ? Promise.resolve(json(200, fullTrackFor(url.includes('/A/') ? 'A' : 'B')))
      : url.includes('/A/') ? a.promise : b.promise));
    const { c } = make();
    const first = c.selectMission('A');
    const second = c.selectMission('B');
    a.resolve(json(200, storyboardFor('A')));
    await first;
    expect(c.state.missionId).toBe('B');
    expect(c.state.busy).toBe('Loading storyboard');
    b.resolve(json(200, storyboardFor('B')));
    await second;
    expect(c.state.storyboard?.mission.mission_id).toBe('B');
    expect(c.state.busy).toBeNull();
    c.dispose();
  });

  it('clears the old scene and evidence as soon as another selection starts, including failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('/good/')
      ? json(200, url.includes('/track?') ? fullTrackFor('good') : storyboardFor('good'))
      : json(404, { detail: 'not found' })));
    const { c, store } = make();
    await c.selectMission('good');
    expect(Object.keys(store.getState().entities).length).toBeGreaterThan(0);
    const request = c.selectMission('missing');
    expect(Object.keys(store.getState().entities)).toHaveLength(0);
    await request;
    expect(c.state).toMatchObject({ missionId: 'missing', storyboard: null, shipPosition: null, selectedEventId: null, trackResult: null });
    expect(Object.keys(store.getState().links)).toHaveLength(0);
    c.dispose();
  });

  it('does not apply a request after disposal', async () => {
    const pending = deferred<ReturnType<typeof json>>();
    vi.stubGlobal('fetch', vi.fn(() => pending.promise));
    const { c, store } = make();
    const request = c.selectMission('A');
    c.dispose();
    pending.resolve(json(200, storyboardFor('A')));
    await request;
    expect(c.state.storyboard).toBeNull();
    expect(Object.keys(store.getState().entities)).toHaveLength(0);
  });

  it('uses every recorded fix for playback, independent of a misleading display decimation', async () => {
    const start = Date.parse('2026-11-05T12:00:00Z');
    const fixes = Array.from({ length: 2001 }, (_, i) => ({
      t_utc: new Date(start + i * 100).toISOString(), lat: 0,
      lon: i <= 1000 ? 0 : (i - 1000) * 1e-6, quality: 'good' as const,
    }));
    const sb = { ...storyboardFor('dense'), track: [fixes[0], fixes.at(-1)!], max_interp_gap_s: 1,
      mission: { ...storyboardFor('dense').mission, fix_count: fixes.length },
      stats: { ...sampleStoryboard.stats, fix_count: fixes.length, start_utc: fixes[0].t_utc, end_utc: fixes.at(-1)!.t_utc } };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => json(200, url.includes('/track?')
      ? { mission_id: 'dense', fixes, fix_count: fixes.length, decimated: false } : sb)));
    const { c } = make();
    await c.selectMission('dense');
    c.setScrub(start + 50_000);
    expect(c.state.shipPosition).toMatchObject({ established: true, method: 'exact_fix', lon: 0 });
    c.setScrub(start + 50_050);
    // Documented 0.5 s tolerance snaps this dense interval to an original fix.
    expect(c.state.shipPosition).toMatchObject({ established: true, method: 'exact_fix', lon: 0 });
    c.dispose();
  });

  it.each(['decimated', 'missing', 'mismatched'])('withholds playback when full track is %s', async (reason) => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('/track?')
      ? reason === 'missing' ? json(404, {}) : json(200, { ...fullTrackFor('A'), decimated: reason === 'decimated', mission_id: reason === 'mismatched' ? 'other' : 'A' })
      : json(200, storyboardFor('A'))));
    const { c, store } = make();
    await c.selectMission('A');
    expect(c.state.storyboard).not.toBeNull();
    expect(c.state.shipPosition?.established).toBe(false);
    expect(c.state.notice).toMatch(/Playback position unavailable/);
    expect(store.getState().entities['mission-ship']).toBeUndefined();
    c.dispose();
  });

  it('does not let an upload for the previous selection reload or show success on the new mission', async () => {
    const upload = deferred<ReturnType<typeof json>>();
    const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST' ? upload.promise
      : Promise.resolve(json(200, url.includes('/track?') ? fullTrackFor('B') : storyboardFor('B'))));
    vi.stubGlobal('fetch', fetch);
    const { c } = make();
    c.store.setState({ missionId: 'A' });
    const request = c.addReport({ t_utc: '2026-11-05T12:00:00Z', title: 'A report', body: '', tags: [] });
    await c.selectMission('B');
    upload.resolve(json(201, {}));
    await request;
    expect(c.state.missionId).toBe('B');
    expect(c.state.notice).toBeNull();
    expect(fetch.mock.calls).toHaveLength(3);
    c.dispose();
  });
});


it('retains upload counts and warnings while reloading the same mission', async () => {
  const sb = storyboardFor('A');
  const result = { mission_id: 'A', format: 'csv', accepted: 3, rejected: 1, duplicates: 0,
    reordered: 0, fix_count: sb.stats.fix_count, issues: [] };
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return json(200, result);
    if (url.endsWith('/missions')) return json(200, [sb.mission]);
    return json(200, url.includes('/track?') ? fullTrackFor('A') : sb);
  }));
  const { c } = make();
  await c.selectMission('A');
  await c.uploadTrack({ file: new Blob(['track']), filename: 'track.csv', format: 'csv' });
  expect(c.state.trackResult).toMatchObject({ accepted: 3, rejected: 1 });
  expect(c.state.storyboard?.mission.mission_id).toBe('A');
  c.dispose();
});

it('does not let a late earlier success or failure overwrite an already loaded selection', async () => {
  for (const status of [200, 404]) {
    const pending = deferred<ReturnType<typeof json>>();
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/A/') && url.includes('/storyboard')) return pending.promise;
      const id = url.includes('/A/') ? 'A' : 'B';
      return json(200, url.includes('/track?') ? fullTrackFor(id) : storyboardFor(id));
    }));
    const { c } = make();
    const first = c.selectMission('A');
    await c.selectMission('B');
    pending.resolve(json(status, status === 200 ? storyboardFor('A') : { detail: 'missing' }));
    await first;
    expect(c.state.storyboard?.mission.mission_id).toBe('B');
    expect(c.state.error).toBeNull();
    c.dispose();
  }
});


it.each(['count', 'bounds', 'geometry'])('withholds playback when %s metadata disproves track consistency', async (kind) => {
  const sb = structuredClone(storyboardFor('A'));
  const full = structuredClone(fullTrackFor('A'));
  if (kind === 'count') sb.mission.fix_count++;
  if (kind === 'bounds') sb.stats.end_utc = '2026-11-05T15:00:00Z';
  if (kind === 'geometry') full.fixes[0].lon += 0.01;
  vi.stubGlobal('fetch', vi.fn(async (url: string) => json(200, url.includes('/track?') ? full : sb)));
  const { c } = make();
  await c.selectMission('A');
  expect(c.state.shipPosition?.established).toBe(false);
  expect(c.state.notice).toMatch(/complete recorded track could not be verified/);
  c.dispose();
});
