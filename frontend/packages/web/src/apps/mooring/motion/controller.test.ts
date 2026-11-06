import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const stream = vi.hoisted(() => ({
  handlers: null as null | { onMessage: (m: unknown) => void; onStatus: (s: string, close?: { code: number; reason: string }) => void },
  url: null as null | string | (() => string),
  send: vi.fn<(data: string) => boolean>(() => true),
  close: vi.fn(),
}));

vi.mock('../api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling',
  authHeaders: () => ({}),
  modeling: { POST: vi.fn() },
  unwrap: <T,>(r: { data: T }) => r.data,
  wsUrl: (_base: string, p: string, q: Record<string, unknown> = {}) =>
    `ws://localhost${p}${Object.entries(q).filter(([, v]) => v !== undefined).map(([k, v], i) => `${i ? '&' : '?'}${k}=${v}`).join('')}`,
}));
vi.mock('../streams', () => ({
  openJsonStream: (url: string | (() => string), onMessage: (m: unknown) => void, onStatus: (s: string, close?: { code: number; reason: string }) => void) => {
    stream.handlers = { onMessage, onStatus };
    stream.url = url;
    return { send: stream.send, close: stream.close };
  },
}));

import { modeling } from '../api';
import { MotionController, serviceUrl } from './controller';
import type { MotionHost } from './controller';
import type { SimFrame, SimRecording, SimScene } from './frames';
import type { StateInput, StateSnapshot } from './workspace';
import { catalog, configuration, controls, order, prediction, workspace } from './workspace.test-fixtures';

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

function workspaceFetch() {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => ({ ok: true, status: 200, json: async () => {
    if (init?.method === 'DELETE') return {};
    if (url.endsWith('/catalog')) return catalog;
    if (url.endsWith('/scenarios')) return init?.method === 'POST' ? workspace.scenario : [];
    if (url.endsWith('/sessions')) return workspace;
    if (url.endsWith('/prediction')) return prediction;
    return scene;
  } }));
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

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

describe('map mode', () => {
  const makeMap = () => ({ enter: vi.fn(), draw: vi.fn(), leave: vi.fn(), shipDims: vi.fn(() => null), setCamera: vi.fn() });

  it('takes over the scene, draws every shown frame, and gives the scene back on close', async () => {
    const map = makeMap();
    const m = new MotionController({ ...host, map }, (cb) => raf.push(cb));
    await m.loadRecording();
    m.setView('map');
    expect(map.enter).toHaveBeenCalledTimes(1);
    expect(map.draw).toHaveBeenCalled(); // the frame already on screen is drawn at once
    const drawn = map.draw.mock.calls.length;
    m.seek(20);
    expect(map.draw.mock.calls.length).toBeGreaterThan(drawn);
    expect(m.s.notDrawn).toContain('roll and pitch');
    m.close();
    expect(map.leave).toHaveBeenCalledTimes(1);
    expect(m.s.view).toBe('plan');
  });

  it('does nothing without a map host and returns to the plan view', async () => {
    const m = make();
    await m.loadRecording();
    m.setView('map');
    expect(m.s.view).toBe('plan');
    m.dispose();
  });

  it('gives the scene back if disposed while the map is showing, and forwards camera presets', async () => {
    const map = makeMap();
    const m = new MotionController({ ...host, map }, (cb) => raf.push(cb));
    await m.loadRecording();
    m.setView('map');
    m.setCamera('bow');
    expect(map.setCamera).toHaveBeenCalledWith('bow', { x: expect.any(Number), y: expect.any(Number) });
    m.dispose();
    expect(map.leave).toHaveBeenCalledTimes(1);
  });
});

it('rejects inputs changed while the motion scenario is being saved', async () => {
  let key = 'before';
  let resolve!: (value: string) => void;
  const pending = new Promise<string>((r) => { resolve = r; });
  const m = new MotionController({ ...host, layoutKey: () => key, ensureScenario: () => pending });
  vi.mocked(modeling.POST).mockClear();
  const start = m.startSession();
  key = 'after';
  resolve('old');
  await start;
  expect(modeling.POST).not.toHaveBeenCalled();
  expect(m.s.error).toMatch(/changed/i);
  m.dispose();
});

it('starts a new session when only the initial offset changes', async () => {
  const m = make();
  vi.mocked(modeling.POST).mockClear().mockResolvedValue({ data: { session_id: 's' } } as never);
  await m.startSession(120);
  stream.handlers!.onStatus('open');
  await m.startSession(240);
  expect(modeling.POST).toHaveBeenCalledTimes(2);
  // New multipart endpoints widen POST's overloads; read the init argument structurally.
  const init = vi.mocked(modeling.POST).mock.calls.at(-1)?.[1] as { body?: unknown } | undefined;
  expect(init?.body).toMatchObject({ initial_state: { y_ft: 290 } });
  m.dispose();
});

it('does not connect a stale session if inputs change while its scene loads', async () => {
  let key = 'before';
  let release!: () => void;
  let entered!: () => void;
  const loading = new Promise<void>((r) => { entered = r; });
  const pending = new Promise<void>((r) => { release = r; });
  vi.stubGlobal('fetch', vi.fn(async () => {
    entered();
    await pending;
    return { ok: true, json: async () => scene };
  }));
  vi.mocked(modeling.POST).mockResolvedValue({ data: { session_id: 's', scene_url: '/scene' } } as never);
  const m = new MotionController({ ...host, layoutKey: () => key });
  const start = m.startSession();
  await loading;
  key = 'after';
  release();
  await start;
  expect(stream.handlers).toBeNull();
  expect(m.s.error).toMatch(/changed/i);
  m.dispose();
});


describe('rm0-v1 session protocol (S1)', () => {
  const lifecycle = (sequence: number, state: string, speed?: number) => ({
    type: 'session_lifecycle', schema_version: 'rm0-v1', session_id: 's1', run_id: 'r1', sequence, t_s: 0, state,
    scene_id: 'sc', scene_revision: '1', ...(speed !== undefined ? { speed } : {}),
  });
  async function rich() {
    vi.mocked(modeling.POST).mockResolvedValue({ data: { session_id: 's1', ws_url: '/ws/sim/s1', protocol: 'rm0-v1',
      scene_url: '/api/v1/berthing/sessions/s1/scene', recording_url: '/api/v1/berthing/sessions/s1/recording' } } as never);
    const m = make();
    await m.startSession(120);
    return m;
  }
  const url = () => (typeof stream.url === 'function' ? stream.url() : stream.url);

  it('reconnects asking only for lifecycle messages after the last one seen', async () => {
    const m = await rich();
    expect(url()).toBe('ws://localhost/ws/sim/s1');
    stream.handlers!.onMessage(lifecycle(4, 'running'));
    expect(url()).toBe('ws://localhost/ws/sim/s1?after_sequence=4');
    m.dispose();
  });

  it('ignores a resent older lifecycle message', async () => {
    const m = await rich();
    stream.handlers!.onMessage(lifecycle(5, 'paused'));
    stream.handlers!.onMessage(lifecycle(3, 'running'));
    expect(m.s.lifecycle).toBe('paused');
    m.dispose();
  });

  it('sends set_speed on a live session and follows the speed the session reports', async () => {
    const m = await rich();
    m.setSpeed(4);
    expect(JSON.parse(stream.send.mock.calls.at(-1)![0])).toEqual({ type: 'set_speed', speed: 4 });
    expect(m.s.speed).toBe(4);
    stream.handlers!.onMessage(lifecycle(6, 'running', 2));
    expect(m.s.speed).toBe(2);
    stream.send.mockClear();
    m.setSpeed(32);
    expect(stream.send).not.toHaveBeenCalled();
    m.dispose();
  });

  it('does not claim a speed change that could not be sent', async () => {
    const m = await rich();
    stream.send.mockReturnValue(false);
    m.setSpeed(8);
    expect(m.s.speed).toBe(1);
    m.dispose();
  });

  it('lists the session recording and replays it with the session scene', async () => {
    const m = await rich();
    expect(m.s.sessionRecordings).toEqual([expect.objectContaining({
      sessionId: 's1',
      recordingUrl: 'http://localhost/api/modeling/api/v1/berthing/sessions/s1/recording',
      sceneUrl: 'http://localhost/api/modeling/api/v1/berthing/sessions/s1/scene',
    })]);
    await m.loadSessionRecording('s1');
    expect(fetch).toHaveBeenCalledWith('http://localhost/api/modeling/api/v1/berthing/sessions/s1/recording', expect.anything());
    expect(m.s.source).toBe('recording');
    expect(m.s.recording?.label).toMatch(/Session s1 recording/);
    m.close();
    expect(m.s.sessionRecordings).toHaveLength(1);
    m.dispose();
  });

  it('shows simulation time for live frames and none for recordings', async () => {
    const m = await rich();
    stream.handlers!.onMessage(lifecycle(1, 'running'));
    stream.handlers!.onMessage({ ...legacy(2.5, 3), environment: { t_s: 2.5 } });
    flush();
    expect(m.s.clock).toMatchObject({ simS: 2.5, forcingTS: 2.5, forcingRevision: null });
    await m.loadRecording();
    expect(m.s.clock).toBeNull();
    m.dispose();
  });

  it('does not list a recording for a legacy session', async () => {
    vi.mocked(modeling.POST).mockResolvedValue({ data: { session_id: 's0', ws_url: '/ws/sim/s0' } } as never);
    const m = make();
    await m.startSession(120);
    expect(m.s.sessionRecordings).toEqual([]);
    m.dispose();
  });
});

it('retains synthetic forcing metadata and surfaces uncovered validity through lifecycle messages', async () => {
  vi.mocked(modeling.POST).mockResolvedValue({ data: { session_id: 's1', ws_url: '/ws/sim/s1', forcing_revision: 'rev-a', forcing_synthetic: true } } as never);
  const m = make();
  await m.startSession();
  expect(m.s).toMatchObject({ forcingRevision: 'rev-a', forcingSynthetic: true });
  stream.handlers!.onMessage({ ...legacy(2, 1), forcing_revision: 'rev-a' });
  flush();
  expect(m.s).toMatchObject({ forcingRevision: 'rev-a', forcingSynthetic: true });
  stream.handlers!.onMessage({ type: 'session_lifecycle', schema_version: 'rm0-v1', session_id: 's1', run_id: 'r1', sequence: 2, t_s: 2, state: 'paused', scene_id: 'sc', scene_revision: '1', validity: { state: 'invalid', reasons: [{ code: 'FORCING_UNCOVERED', message: 'Forcing ends before this step.' }] } });
  expect(m.s.lifecycleInvalid).toBe(true);
  expect(m.s.lifecycleReasons).toEqual(['FORCING_UNCOVERED: Forcing ends before this step.']);
  m.dispose();
});

it('keeps explicit real forcing authoritative even with mock dynamics or component provenance', async () => {
  vi.mocked(modeling.POST).mockResolvedValue({ data: { session_id: 's1', ws_url: '/ws/sim/s1', forcing_synthetic: false } } as never);
  const m = make();
  await m.startSession();
  stream.handlers!.onMessage({ ...recording.frames[10], sequence: 1 });
  flush();
  expect(m.s.forcingSynthetic).toBe(false);
  expect(m.s.clock?.training).toBe(false);
  m.dispose();
});

it('does not apply an old session recording or its provenance after another recording is selected', async () => {
  let finish!: (value: unknown) => void;
  const old = new Promise((resolve) => { finish = resolve; });
  vi.stubGlobal('fetch', vi.fn((url: string) => url === '/old' ? old : Promise.resolve({ ok: true, json: async () => ({ ...recording, recording_id: 'new' }) })));
  const m = make();
  m.state.set({ sessionRecordings: [{ sessionId: 'old', recordingUrl: '/old', sceneUrl: null, startedAt: '', forcingRevision: 'old-revision', forcingSynthetic: true }] });
  const pending = m.loadSessionRecording('old');
  await m.loadRecording('/new', null, 'New');
  finish({ ok: true, json: async () => ({ ...recording, recording_id: 'old' }) });
  await pending;
  expect(m.s.recording?.id).toBe('new');
  expect(m.s.forcingRevision).not.toBe('old-revision');
  m.dispose();
});

it.each([false, true])('ignores a session creation completing after a recording selection (reject=%s)', async (reject) => {
  let release!: () => void;
  let entered!: () => void;
  const started = new Promise<void>((resolve) => { entered = resolve; });
  const pending = new Promise<void>((resolve) => { release = resolve; });
  vi.mocked(modeling.POST).mockImplementationOnce(async () => {
    entered();
    await pending;
    if (reject) throw new Error('Old provider failure');
    return { data: { session_id: 'old', forcing_synthetic: true, forcing_revision: 'old' } } as never;
  });
  const m = make();
  const creating = m.startSession();
  await started;
  await m.loadRecording();
  const selected = m.s.recording!.id;
  release();
  await creating;
  expect(m.s.source).toBe('recording');
  expect(m.s.recording?.id).toBe(selected);
  expect(m.s.sessionId).toBeNull();
  expect(m.s.forcingRevision).not.toBe('old');
  expect(m.s.error).toBeNull();
  expect(stream.handlers).toBeNull();
  m.dispose();
});

describe('Motion workspace', () => {
  const observation: StateInput = { entity: 'ship', entity_id: 'DDG-51-FIIA', frame: 'berth', berth_id: 'NORFOLK', source: 'synthetic', observed_at_utc: '2026-11-05T00:00:00Z', sequence: 100, x_ft: 300, y_ft: 80, heading_true_deg: 90, surge_fps: 1, sway_fps: 0, yaw_degps: 0, measured_acceleration: null, quality: 'unknown' };

  it('predicts a paused snapshot once and refreshes only when its authoritative input changes', async () => {
    vi.useFakeTimers(); const fetcher = workspaceFetch(); const m = make();
    await m.loadWorkspace(configuration); stream.handlers!.onStatus('open');
    m.state.set({ open: true, lifecycle: 'paused' }); stream.handlers!.onMessage(legacy(0, 1)); flush();
    await vi.advanceTimersByTimeAsync(30000);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(1);
    stream.handlers!.onMessage(legacy(0, 2)); flush();
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(2);
    m.dispose();
  });

  it('coalesces advancing frames to one refresh per second using a monotonic clock', async () => {
    vi.useFakeTimers(); const baseline = workspaceFetch(); const starts: number[] = [];
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => { if (url.endsWith('/prediction')) starts.push(performance.now()); return baseline(url, init); }));
    const m = make(); await m.loadWorkspace(configuration); stream.handlers!.onStatus('open');
    m.state.set({ open: true, lifecycle: 'running' }); stream.handlers!.onMessage(legacy(0, 1)); flush();
    for (let i = 1; i <= 30; i++) {
      if (i === 15) vi.setSystemTime(Date.now() - 3600000);
      await vi.advanceTimersByTimeAsync(100);
      stream.handlers!.onMessage(legacy(i / 10, i + 1)); flush();
    }
    expect(starts).toHaveLength(4);
    expect(starts.slice(1).every((time, i) => time - starts[i] >= 1000)).toBe(true);
    m.close(); await vi.advanceTimersByTimeAsync(5000); expect(starts).toHaveLength(4); m.dispose();
  });

  it('clears the old path on a new-run lifecycle and waits for its matching frame before refreshing', async () => {
    vi.useFakeTimers(); const fetcher = workspaceFetch(); const m = make();
    await m.loadWorkspace(configuration); stream.handlers!.onStatus('open');
    stream.handlers!.onMessage(legacy(0, 1)); flush(); await m.refreshPrediction();
    expect(m.s.prediction).not.toBeNull(); m.state.set({ open: true });
    stream.handlers!.onMessage({ type: 'session_lifecycle', schema_version: 'rm0-v1', session_id: 'motion-1', run_id: 'reset-run', sequence: 2, t_s: 0, state: 'reset', scene_id: 'new-scene', scene_revision: '2' });
    expect(m.s.prediction).toBeNull();
    await m.refreshPrediction(); await vi.advanceTimersByTimeAsync(5000);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(1);
    stream.handlers!.onMessage({ ...legacy(0, 3, 'reset-run'), scene_id: 'new-scene', scene_revision: '1' }); flush();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(1);
    stream.handlers!.onMessage({ ...legacy(0, 4, 'reset-run'), scene_id: 'new-scene', scene_revision: '2' }); flush();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(2);
    m.dispose(); await vi.advanceTimersByTimeAsync(0);
  });

  it.each(['error', 'invalid'] as const)('removes future coverage immediately on an %s lifecycle even without a new frame', async (failure) => {
    vi.useFakeTimers(); const fetcher = workspaceFetch(); const m = make();
    await m.loadWorkspace(configuration); stream.handlers!.onStatus('open');
    stream.handlers!.onMessage(legacy(0, 1)); flush(); await m.refreshPrediction();
    expect(m.s.prediction).not.toBeNull(); m.state.set({ open: true });
    stream.handlers!.onMessage({ type: 'session_lifecycle', schema_version: 'rm0-v1', session_id: 'motion-1', run_id: 'r1', sequence: 2, t_s: 0, state: failure === 'error' ? 'error' : 'paused', validity: failure === 'invalid' ? { state: 'invalid', reasons: [{ code: 'FAILED', message: 'No valid next state.' }] } : null });
    expect(m.s.prediction).toBeNull(); expect(m.s.predictionError).toContain('Future coverage is unavailable');
    await m.refreshPrediction(); await vi.advanceTimersByTimeAsync(5000);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(1);
    stream.handlers!.onMessage({ type: 'session_lifecycle', schema_version: 'rm0-v1', session_id: 'motion-1', run_id: 'r1', sequence: 3, t_s: 0, state: 'paused' });
    await m.refreshPrediction();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(1);
    stream.handlers!.onMessage(legacy(0, 4)); flush();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(2);
    m.dispose(); await vi.advanceTimersByTimeAsync(0);
  });

  it('waits for queued command acknowledgement before forecasting and preserves an explicit preview intent', async () => {
    vi.useFakeTimers(); const fetcher = workspaceFetch(); const m = make();
    await m.loadWorkspace(configuration); stream.handlers!.onStatus('open'); stream.handlers!.onMessage({ ...legacy(0, 1), controls }); flush();
    m.state.set({ open: true, lifecycle: 'paused' });
    m.helmCommand(order); await m.refreshPrediction({ ...order, rudder_deg: 20 });
    await vi.advanceTimersByTimeAsync(10000);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(0);
    expect(m.s.predictionPreviewPending).toBe(true);
    stream.handlers!.onMessage({ ...legacy(0.1, 2), controls: { ...controls, commanded: order } }); flush();
    await vi.advanceTimersByTimeAsync(0);
    const request = fetcher.mock.calls.find(([url]) => url.endsWith('/prediction'));
    expect(JSON.parse(String(request?.[1]?.body)).what_if_commands).toEqual([{ type: 'helm_command', ...order, rudder_deg: 20 }]);
    expect(m.s.predictionPreviewPending).toBe(false); m.dispose();
  });

  it('waits for every pending order when separate command echoes arrive in different frames', async () => {
    vi.useFakeTimers(); const fetcher = workspaceFetch(); const m = make();
    await m.loadWorkspace(configuration); stream.handlers!.onStatus('open'); stream.handlers!.onMessage(legacy(0, 1)); flush();
    m.state.set({ open: true, lifecycle: 'paused' });
    m.helmCommand(order); m.lineControl({ line_number: 1, attached: false });
    stream.handlers!.onMessage({ ...legacy(0, 2), controls: { ...controls, commanded: order } }); flush();
    await vi.advanceTimersByTimeAsync(5000);
    expect(m.s.command?.status).toBe('pending');
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(0);
    stream.handlers!.onMessage({ ...legacy(0.1, 3), controls: { ...controls, commanded: order }, line_controls: [{ line_number: 1, attached: false, paid_out_length_ft: 100, geometric_length_ft: 80, extension_ft: 0, tension_lbf: 0 }] }); flush();
    expect(m.s.command?.status).toBe('applied');
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(1);
    m.dispose(); await vi.advanceTimersByTimeAsync(0);
  });

  it.each(['error', 'closed'])('retires lost command echoes on %s and forecasts only from fresh reconnect state', async (link) => {
    vi.useFakeTimers(); const fetcher = workspaceFetch(); const m = make();
    await m.loadWorkspace(configuration); stream.handlers!.onStatus('open');
    stream.handlers!.onMessage({ ...legacy(0, 1), controls }); flush(); await m.refreshPrediction();
    m.state.set({ open: true, lifecycle: 'paused' });
    m.helmCommand(order); m.lineControl({ line_number: 1, attached: false });
    stream.handlers!.onStatus(link); expect(m.s.command?.status).toBe('unconfirmed');
    expect(m.s.prediction).toBeNull();
    stream.handlers!.onStatus('open'); await m.refreshPrediction(); await vi.advanceTimersByTimeAsync(5000);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(1);
    stream.handlers!.onMessage({ ...legacy(0, 2), controls }); flush();
    expect(m.s.command?.status).toBe('unconfirmed');
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(2);
    m.dispose(); await vi.advanceTimersByTimeAsync(0);
  });

  it('coalesces user previews behind actual in-flight work and never publishes an obsolete result', async () => {
    const baseline = workspaceFetch(); let finish!: (value: unknown) => void; let calls = 0;
    const fetcher = vi.fn((url: string, init?: RequestInit) => {
      if (!url.endsWith('/prediction')) return baseline(url, init);
      calls += 1;
      return calls === 1 ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve({ ok: true, json: async () => ({ ...prediction, prediction_id: 'latest-preview' }) });
    });
    vi.stubGlobal('fetch', fetcher); const m = make();
    await m.loadWorkspace(configuration); stream.handlers!.onStatus('open'); stream.handlers!.onMessage(legacy(0, 1)); flush();
    const background = m.refreshPrediction();
    await m.refreshPrediction(order); await m.refreshPrediction({ ...order, rudder_deg: 20 });
    expect(calls).toBe(1); expect(m.s.prediction).toBeNull();
    finish({ ok: true, json: async () => prediction }); await background;
    await vi.waitFor(() => expect(m.s.prediction?.prediction_id).toBe('latest-preview'));
    expect(calls).toBe(2);
    const requests = fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'));
    expect(requests[0][1]?.signal?.aborted).toBe(false);
    expect(JSON.parse(String(requests[1][1]?.body)).what_if_commands).toEqual([{ type: 'helm_command', ...order, rudder_deg: 20 }]);
    m.dispose();
  });

  it('bounds a hung request slot and allows the latest queued preview to proceed after timeout', async () => {
    vi.useFakeTimers(); const baseline = workspaceFetch(); let calls = 0;
    const fetcher = vi.fn((url: string, init?: RequestInit) => {
      if (!url.endsWith('/prediction')) return baseline(url, init);
      calls += 1;
      return calls === 1 ? new Promise(() => undefined) : Promise.resolve({ ok: true, json: async () => prediction });
    });
    vi.stubGlobal('fetch', fetcher); const m = make();
    await m.loadWorkspace(configuration); stream.handlers!.onStatus('open'); stream.handlers!.onMessage(legacy(0, 1)); flush();
    const background = m.refreshPrediction(); await m.refreshPrediction(order);
    await vi.advanceTimersByTimeAsync(7999); expect(calls).toBe(1);
    await vi.advanceTimersByTimeAsync(1); await background;
    expect(calls).toBe(2); expect(m.s.predictionPreviewPending).toBe(false);
    expect(fetcher.mock.calls.find(([url]) => url.endsWith('/prediction'))?.[1]?.signal?.aborted).toBe(true);
    m.dispose();
  });

  it('refreshes a paused imported run when its authoritative frame precedes the HTTP response', async () => {
    vi.useFakeTimers(); const baseline = workspaceFetch(); let finish!: (value: unknown) => void;
    const fetcher = vi.fn((url: string, init?: RequestInit) => url.endsWith('/state') ? new Promise((resolve) => { finish = resolve; }) : baseline(url, init));
    vi.stubGlobal('fetch', fetcher); const m = make(); await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open'); stream.handlers!.onMessage(legacy(0, 1)); flush();
    m.state.set({ open: true, lifecycle: 'paused' }); const importing = m.importState(observation);
    stream.handlers!.onMessage(legacy(0, 2, 'imported-run')); flush();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(0);
    finish({ ok: true, json: async () => ({ session_id: 'motion-1', run_id: 'imported-run', input: observation }) }); await importing;
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(1);
    m.dispose(); await vi.advanceTimersByTimeAsync(0);
  });

  it('retains a current forecast through a refresh failure while keeping its error and expiry visible', async () => {
    const baseline = workspaceFetch(); const m = make(); await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open'); stream.handlers!.onMessage(legacy(0, 1)); flush(); await m.refreshPrediction();
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => url.endsWith('/prediction') ? Promise.reject(new Error('Service unavailable')) : baseline(url, init)));
    stream.handlers!.onMessage(legacy(1, 2)); flush(); await m.refreshPrediction();
    expect(m.s.prediction).toEqual(prediction); expect(m.s.predictionError).toContain('Service unavailable');
    stream.handlers!.onMessage(legacy(10, 3)); flush(); expect(m.s.prediction).toBeNull(); expect(m.s.predictionError).toContain('horizon expired');
    m.dispose();
  });

  it.each(['reset', 'superseded', 'response-first', 'frame-first'] as const)('accepts only the current state import when %s', async (mode) => {
    const baseline = workspaceFetch();
    let finish!: (v: unknown) => void;
    const pending = new Promise((r) => { finish = r; });
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => url.endsWith('/state') ? pending : baseline(url, init)));
    const m = make(); await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open'); stream.handlers!.onMessage(legacy(0, 1)); flush();
    m.state.set({ lifecycle: 'paused' });
    const importing = m.importState(observation);
    expect(m.resume()).toBe(false);
    if (mode === 'reset') m.reset();
    if (mode !== 'response-first') { stream.handlers!.onMessage(legacy(0, 2, mode === 'frame-first' ? 'imported-run' : 'later-run')); flush(); }
    finish({ ok: true, json: async () => ({ session_id: 'motion-1', run_id: 'imported-run', input: observation }) });
    await importing;
    if (mode === 'reset' || mode === 'superseded') {
      expect(m.s.importedState).toBeNull();
      expect(m.s.command).toBeNull();
    } else {
      expect(m.s.importedState?.run_id).toBe('imported-run');
      expect(m.s.command?.status).toBe('applied');
    }
    expect(m.s.stateImportBusy).toBe(false);
    expect(m.nextStateSequence('ship', observation.entity_id)).toBe(101);
    m.dispose();
  });

  it('keeps imported sequence history per entity across reset, including frame-supplied evidence', async () => {
    workspaceFetch(); const m = make(); await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open');
    const stateInputs = [{ input: observation }, { input: { ...observation, entity: 'tug', entity_id: 'T1', sequence: 1 } }] as StateSnapshot[];
    stream.handlers!.onMessage({ ...legacy(0, 1), state_inputs: stateInputs }); flush();
    expect(m.nextStateSequence('ship', observation.entity_id)).toBe(101);
    expect(m.nextStateSequence('tug', 'T1')).toBe(2);
    m.reset(); stream.handlers!.onMessage(legacy(0, 2, 'reset-run')); flush();
    expect(m.nextStateSequence('ship', observation.entity_id)).toBe(101);
    m.dispose();
  });

  it('keeps direct entry through StrictMode and immediate remounts, then pauses on departure', async () => {
    const m = make(); m.open();
    const close = vi.spyOn(m, 'close');
    m.bindWorkspaceView()();
    const detach = m.bindWorkspaceView();
    await Promise.resolve();
    expect(close).not.toHaveBeenCalled();
    detach();
    await Promise.resolve();
    expect(close).toHaveBeenCalledOnce();
    expect(m.s.open).toBe(false);
    m.dispose();
  });
  it('loads one paused default on direct entry and reuses it when the tab is reopened', async () => {
    const fetcher = workspaceFetch();
    const m = make();
    m.open();
    await Promise.all([m.initializeWorkspace(), m.initializeWorkspace()]);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/catalog'))).toHaveLength(1);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/sessions'))).toHaveLength(1);
    expect(stream.send).not.toHaveBeenCalled();
    expect(m.s.workspace?.ship.name).toBe('Test destroyer');
    stream.handlers!.onStatus('open');
    m.close();
    m.open();
    await m.initializeWorkspace();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/sessions'))).toHaveLength(1);
    expect(stream.send.mock.calls.map(([data]) => JSON.parse(data).type)).toEqual(['pause']);
    m.dispose();
  });

  it('fetches saved configurations without saving or allocating a simulation', async () => {
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => [workspace.scenario] }));
    vi.stubGlobal('fetch', fetcher);
    const m = make();
    await Promise.all([m.loadSavedScenarios(), m.loadSavedScenarios()]);
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith(expect.stringMatching(/\/motion\/scenarios$/), expect.objectContaining({ method: 'GET' }));
    expect(m.s.savedScenarios).toEqual([workspace.scenario]);
    expect(m.s.sessionId).toBeNull();
    m.dispose();
  });

  it('closes and releases an old workspace before allocating its replacement', async () => {
    const fetcher = workspaceFetch();
    const m = make();
    await m.loadWorkspace(configuration);
    await m.loadWorkspace({ ...configuration, name: 'Replacement' });
    const calls = fetcher.mock.calls;
    const deletion = calls.findIndex(([, init]) => init?.method === 'DELETE');
    const lastSession = calls.map(([url]) => url).lastIndexOf('http://localhost/api/modeling/api/v1/motion/sessions');
    expect(stream.close).toHaveBeenCalledTimes(1);
    expect(deletion).toBeGreaterThan(0);
    expect(deletion).toBeLessThan(lastSession);
    m.dispose();
  });

  it('retries a failed release and never allocates past retained capacity while persistence is failing', async () => {
    const baseline = workspaceFetch();
    let failRelease = true;
    const fetcher = vi.fn((url: string, init?: RequestInit) => init?.method === 'DELETE' && failRelease ? Promise.resolve({ ok: false, status: 503 }) : baseline(url, init));
    vi.stubGlobal('fetch', fetcher);
    const m = make();
    await m.loadWorkspace(configuration);
    await m.loadWorkspace({ ...configuration, name: 'Pending replacement' });
    expect(m.s.error).toMatch(/previous session could not be released/);
    expect(fetcher.mock.calls.filter(([url, init]) => url.endsWith('/sessions') && init?.method === 'POST')).toHaveLength(1);
    const attempts = fetcher.mock.calls.filter(([, init]) => init?.method === 'DELETE').length;
    failRelease = false;
    await m.loadWorkspace({ ...configuration, name: 'Retried replacement' });
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'DELETE').length).toBeGreaterThan(attempts);
    expect(fetcher.mock.calls.filter(([url, init]) => url.endsWith('/sessions') && init?.method === 'POST')).toHaveLength(2);
    expect(m.s.error).toBeNull();
    m.dispose();
  });

  it('does not connect or leak a session that finishes creating after a replay is chosen', async () => {
    const baseline = workspaceFetch();
    let finish!: (v: unknown) => void;
    let entered!: () => void;
    const started = new Promise<void>((r) => { entered = r; });
    const pending = new Promise((r) => { finish = r; });
    const fetcher = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/sessions') && init?.method === 'POST') { entered(); return pending; }
      if (url === '/replay') return Promise.resolve({ ok: true, json: async () => recording });
      return baseline(url, init);
    });
    vi.stubGlobal('fetch', fetcher);
    const m = make();
    const creating = m.loadWorkspace(configuration);
    await started;
    await m.loadRecording('/replay', null);
    finish({ ok: true, json: async () => workspace });
    await creating;
    await Promise.resolve();
    expect(m.s.source).toBe('recording');
    expect(stream.handlers).toBeNull();
    expect(fetcher.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true);
    m.dispose();
  });

  it('holds helm feedback pending until a backend frame echoes the order, without inventing actual response', async () => {
    workspaceFetch();
    const m = make();
    await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open');
    stream.handlers!.onMessage({ ...legacy(0, 1), controls }); flush();
    m.helmCommand(order);
    expect(m.s.command?.status).toBe('pending');
    expect(m.s.frame?.controls?.actual.port_throttle).toBe(0);
    stream.handlers!.onMessage({ ...legacy(1, 2), controls: { ...controls, commanded: order } }); flush();
    expect(m.s.command?.status).toBe('applied');
    expect(m.s.frame?.controls?.actual.port_throttle).toBe(0);
    m.dispose();
  });

  it.each([false, true])('requires manual authority as well as matching helm values (configured automatic=%s)', async (configured) => {
    workspaceFetch(); const m = make();
    await m.loadWorkspace(configuration);
    m.state.set({ workspace: { ...workspace, scenario: { ...workspace.scenario, configuration: { ...configuration, route_follow: configured } } } });
    stream.handlers!.onStatus('open');
    const guidance = { source: 'synthetic' as const, active: true, route_id: 'route', waypoint_index: 1, waypoint_name: 'Channel', target_speed_kt: 10, cross_track_ft: 0, remaining_ft: 10000, completed: false };
    const sameOrder = { ...controls, commanded: order };
    stream.handlers!.onMessage({ ...legacy(0, 1), controls: sameOrder, guidance }); flush();
    m.helmCommand(order);
    // AUTO may coincidentally issue the same values before the queued manual command applies.
    stream.handlers!.onMessage({ ...legacy(0, 2), controls: sameOrder, guidance }); flush();
    expect(m.s.command?.status).toBe('pending');
    if (configured) {
      stream.handlers!.onMessage({ ...legacy(0, 3), controls: sameOrder }); flush();
      expect(m.s.command?.status).toBe('pending');
    }
    stream.handlers!.onMessage({ ...legacy(1, 4), controls: sameOrder, guidance: { ...guidance, active: false } }); flush();
    expect(m.s.command?.status).toBe('applied');
    expect(m.s.frame?.controls?.actual.port_throttle).toBe(0);
    m.dispose();
  });

  it('limits prediction to one request at a time and rejects a response invalidated by reset', async () => {
    const baseline = workspaceFetch();
    let finish!: (v: unknown) => void;
    const pending = new Promise((r) => { finish = r; });
    const fetcher = vi.fn((url: string, init?: RequestInit) => url.endsWith('/prediction') ? pending : baseline(url, init));
    vi.stubGlobal('fetch', fetcher);
    const m = make();
    await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open');
    stream.handlers!.onMessage(legacy(0, 1)); flush();
    const request = m.refreshPrediction();
    await m.refreshPrediction();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/prediction'))).toHaveLength(1);
    m.reset();
    finish({ ok: true, json: async () => prediction });
    await request;
    expect(m.s.prediction).toBeNull();
    expect(m.s.predictionBusy).toBe(false);
    m.dispose();
  });

  it('sends what-if commands only to a prediction clone', async () => {
    const fetcher = workspaceFetch();
    const m = make();
    await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open'); stream.handlers!.onMessage(legacy(0, 1)); flush();
    await m.refreshPrediction(order);
    const request = fetcher.mock.calls.find(([url]) => url.endsWith('/prediction'));
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ what_if_commands: [{ type: 'helm_command', ...order }] });
    expect(stream.send).not.toHaveBeenCalled();
    expect(m.s.predictionWhatIf).toBe(true);
    m.dispose();
  });

  it('rejects a same-run prediction that arrives after its entire horizon has elapsed', async () => {
    const baseline = workspaceFetch();
    let finish!: (v: unknown) => void;
    const pending = new Promise((r) => { finish = r; });
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => url.endsWith('/prediction') ? pending : baseline(url, init)));
    const m = make();
    await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open'); stream.handlers!.onMessage(legacy(0, 1)); flush();
    const request = m.refreshPrediction();
    stream.handlers!.onMessage(legacy(80, 2)); flush();
    finish({ ok: true, json: async () => prediction });
    await request;
    expect(m.s.prediction).toBeNull();
    expect(m.s.predictionBusy).toBe(false);
    expect(m.s.predictionError).toMatch(/horizon expired/);
    m.dispose();
  });

  it('removes an already displayed prediction when simulation time reaches its end', async () => {
    workspaceFetch();
    const m = make();
    await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open'); stream.handlers!.onMessage(legacy(0, 1)); flush();
    await m.refreshPrediction();
    expect(m.s.prediction).not.toBeNull();
    stream.handlers!.onMessage(legacy(10, 2)); flush();
    expect(m.s.prediction).toBeNull();
    expect(m.s.predictionError).toMatch(/horizon expired/);
    m.dispose();
  });

  it('surfaces a rejected command reason and keeps the unacknowledged command unconfirmed', async () => {
    workspaceFetch(); const m = make();
    await m.loadWorkspace(configuration);
    stream.handlers!.onStatus('open');
    m.helmCommand(order);
    stream.handlers!.onStatus('closed', { code: 1008, reason: 'Command exceeds supplied limit' });
    expect(m.s.notice).toContain('Command rejected: Command exceeds supplied limit');
    expect(m.s.notice).toContain('Load a paused scenario');
    expect(m.s.command?.status).toBe('unconfirmed');
    m.dispose();
  });
});
