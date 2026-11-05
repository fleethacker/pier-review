import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const stream = vi.hoisted(() => ({
  handlers: null as null | { onMessage: (m: unknown) => void; onStatus: (s: string) => void },
  send: vi.fn<(data: string) => boolean>(() => true),
  close: vi.fn(),
}));

vi.mock('../api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling',
  modeling: { POST: vi.fn() },
  unwrap: <T,>(r: { data: T }) => r.data,
  wsUrl: (_base: string, p: string) => `ws://localhost${p}`,
}));
vi.mock('../streams', () => ({
  openJsonStream: (_url: string, onMessage: (m: unknown) => void, onStatus: (s: string) => void) => {
    stream.handlers = { onMessage, onStatus };
    return { send: stream.send, close: stream.close };
  },
}));

import { modeling } from '../api';
import { MotionController, serviceUrl } from './controller';
import type { MotionHost } from './controller';
import type { SimFrame, SimRecording, SimScene } from './frames';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const load = <T,>(n: string): T => JSON.parse(readFileSync(path.join(dir, n), 'utf8')) as T;
const recording = load<SimRecording>('sim_recording_60s.json');
const scene = load<SimScene>('sim_scene.json');

const host: MotionHost = {
  faceBearingDeg: () => 90,
  tugIds: () => ['T1'],
  lineNumbers: () => [1, 2],
  layoutKey: () => 'k1',
  ensureScenario: async () => 'sc1',
  initialState: (offset) => ({ x_ft: 100, y_ft: 50 + offset, heading_true_deg: 90, u_kt: 0, v_kt: 0, r_degps: 0 }),
};

const legacy = (t: number, seq: number, run = 'r1'): SimFrame => ({
  t_s: t,
  pose: { x_ft: t, y_ft: 10, heading_true_deg: 90, u_kt: 0, v_kt: 0, r_degps: 0 },
  tugs: [],
  lines: [],
  fenders: [],
  alerts: [],
  sequence: seq,
  run_id: run,
});

let raf: (() => void)[] = [];
const flush = () => {
  const cbs = raf;
  raf = [];
  cbs.forEach((c) => c());
};
const make = () => new MotionController(host, (cb) => raf.push(cb));

beforeEach(() => {
  raf = [];
  stream.send.mockClear().mockReturnValue(true);
  stream.close.mockClear();
  stream.handlers = null;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => (String(url).includes('scene') ? scene : recording),
    })),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('serviceUrl', () => {
  it('puts service-rooted paths under the proxy prefix and leaves absolute urls alone', () => {
    expect(serviceUrl('http://h/api/modeling', '/api/v1/scenes/x')).toBe('http://h/api/modeling/api/v1/scenes/x');
    expect(serviceUrl('http://h/api/modeling', 'https://other/x')).toBe('https://other/x');
  });
});

describe('recording playback', () => {
  it('loads a recording with its scene and shows the first frame', async () => {
    const m = make();
    await m.loadRecording();
    expect(m.s.source).toBe('recording');
    expect(m.s.recording!.frames.length).toBe(recording.frames.length);
    expect(m.s.scene?.scene_id).toBe(scene.scene_id);
    expect(m.s.frame?.tS).toBe(recording.frames[0].t_s);
    m.dispose();
  });

  it('reports a load failure instead of showing a blank view', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })));
    const m = make();
    await m.loadRecording();
    expect(m.s.source).toBe('none');
    expect(m.s.error).toMatch(/Could not load the recording/);
  });

  it('scrubs to a time and rebuilds the trail up to it', async () => {
    const m = make();
    await m.loadRecording();
    m.seek(30);
    expect(m.s.frame!.tS).toBeLessThanOrEqual(30);
    expect(m.s.frame!.tS).toBeGreaterThan(25);
    expect(m.s.trail.length).toBeGreaterThan(20);
    m.seek(10);
    expect(m.s.trail.length).toBeLessThan(15);
    m.dispose();
  });

  it('plays at the chosen speed, stops at the end and restarts from the beginning', async () => {
    vi.useFakeTimers();
    const m = make();
    await m.loadRecording();
    m.setSpeed(4);
    m.play();
    expect(m.s.playing).toBe(true);
    vi.advanceTimersByTime(5000);
    expect(m.s.cursorS).toBeGreaterThan(15);
    vi.advanceTimersByTime(20000);
    expect(m.s.playing).toBe(false);
    expect(m.s.cursorS).toBe(recording.frames[recording.frames.length - 1].t_s);
    m.play();
    expect(m.s.cursorS).toBe(recording.frames[0].t_s);
    m.pauseReplay();
    m.dispose();
  });
});

describe('live session', () => {
  async function started() {
    vi.mocked(modeling.POST).mockResolvedValue({ data: { session_id: 's1', ws_url: '/ws/sim/s1', scene_url: '/api/v1/scenes/s1' } } as never);
    const m = make();
    await m.startSession(120);
    return m;
  }

  it('creates a session from the saved scenario and the layout start state, then connects', async () => {
    const m = await started();
    expect(modeling.POST).toHaveBeenCalledWith('/api/v1/berthing/sessions', {
      body: { scenario_id: 'sc1', initial_state: expect.objectContaining({ y_ft: 170 }) },
    });
    expect(m.s.sessionId).toBe('s1');
    expect(m.s.source).toBe('live');
    expect(stream.handlers).not.toBeNull();
    expect(m.s.scene?.scene_id).toBe(scene.scene_id);
    m.dispose();
  });

  it('surfaces a session failure and returns to idle', async () => {
    vi.mocked(modeling.POST).mockRejectedValue(new Error('503 busy'));
    const m = make();
    await m.startSession();
    expect(m.s.source).toBe('none');
    expect(m.s.error).toMatch(/503 busy/);
  });

  it('explains a 429 session limit in plain words', async () => {
    vi.mocked(modeling.POST).mockRejectedValue(new Error('429 /api/v1/berthing/sessions: {"detail":"too many"}'));
    const m = make();
    await m.startSession();
    expect(m.s.error).toMatch(/session limit/);
    expect(m.s.source).toBe('none');
  });

  it('reuses the running session with a reset while the layout is unchanged, and makes a new one when it changes', async () => {
    let key = 'k1';
    vi.mocked(modeling.POST).mockClear();
    vi.mocked(modeling.POST).mockResolvedValue({ data: { session_id: 's1', ws_url: '/ws/sim/s1', scene_url: null } } as never);
    const m = new MotionController({ ...host, layoutKey: () => key }, (cb) => raf.push(cb));
    await m.startSession();
    stream.handlers!.onStatus('open');
    stream.send.mockClear();
    await m.startSession();
    expect(modeling.POST).toHaveBeenCalledTimes(1);
    expect(JSON.parse(stream.send.mock.calls[0][0])).toEqual({ type: 'reset' });
    key = 'k2';
    await m.startSession();
    expect(modeling.POST).toHaveBeenCalledTimes(2);
    m.dispose();
  });

  it('asks for a berth and ship when there is no start state', async () => {
    const m = new MotionController({ ...host, initialState: () => null }, (cb) => raf.push(cb));
    await m.startSession();
    expect(m.s.error).toMatch(/berth and a ship/);
  });

  it('draws only the newest of several frames that arrive before the next paint', async () => {
    const m = await started();
    stream.handlers!.onMessage(legacy(1, 1));
    stream.handlers!.onMessage(legacy(2, 2));
    stream.handlers!.onMessage(legacy(3, 3));
    expect(m.s.frame).toBeNull();
    flush();
    expect(m.s.frame!.tS).toBe(3);
    expect(m.s.droppedForDisplay).toBe(2);
    expect(m.s.lastSequence).toBe(3);
    m.dispose();
  });

  it('ignores a stale frame from the same run but accepts a new run, which starts a new trail', async () => {
    const m = await started();
    stream.handlers!.onMessage(legacy(5, 10));
    flush();
    stream.handlers!.onMessage(legacy(4, 9));
    flush();
    expect(m.s.frame!.tS).toBe(5);
    stream.handlers!.onMessage(legacy(0, 11, 'r2'));
    flush();
    expect(m.s.frame!.tS).toBe(0);
    expect(m.s.trail).toHaveLength(1);
    m.dispose();
  });

  it('follows lifecycle messages and warns that a reconnected session is paused', async () => {
    const m = await started();
    stream.handlers!.onStatus('open');
    stream.handlers!.onMessage({ ...load<object>('sim_lifecycle_running.json') });
    expect(m.s.lifecycle).toBe('running');
    stream.handlers!.onStatus('error');
    expect(m.s.notice).toMatch(/retrying/);
    stream.handlers!.onStatus('open');
    expect(m.s.lifecycle).toBe('paused');
    expect(m.s.notice).toMatch(/Resume/);
    m.dispose();
  });

  it('sends control and command messages over the one session socket', async () => {
    const m = await started();
    expect(m.resume()).toBe(true);
    expect(m.pause()).toBe(true);
    expect(m.reset()).toBe(true);
    expect(m.tugCommand('T1', 5000, 450)).toBe(true);
    expect(m.lineEvent(3, 'secured')).toBe(true);
    const sent = stream.send.mock.calls.map((c) => JSON.parse(c[0]));
    expect(sent).toEqual([
      { type: 'resume' },
      { type: 'pause' },
      { type: 'reset' },
      { type: 'tug_command', tug_id: 'T1', force_lbf: 5000, direction_rel_deg: 90 },
      { type: 'line_event', line_number: 3, event: 'secured' },
    ]);
    m.dispose();
  });

  it('keeps a live session, paused, when the view is closed', async () => {
    const m = await started();
    stream.send.mockClear();
    m.close();
    expect(m.s.open).toBe(false);
    expect(m.s.source).toBe('live');
    expect(JSON.parse(stream.send.mock.calls[0][0])).toEqual({ type: 'pause' });
    expect(stream.close).not.toHaveBeenCalled();
    m.dispose();
  });

  it('says so when a command cannot be sent', async () => {
    const m = await started();
    stream.send.mockReturnValue(false);
    expect(m.pause()).toBe(false);
    expect(m.s.notice).toMatch(/not sent/);
    m.dispose();
    const idle = make();
    expect(idle.pause()).toBe(false);
  });
});
