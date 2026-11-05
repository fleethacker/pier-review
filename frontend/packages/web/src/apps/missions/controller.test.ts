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
      if (path.includes('/storyboard')) return json(200, sampleStoryboard);
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
