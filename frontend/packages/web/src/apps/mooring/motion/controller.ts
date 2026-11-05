import { Store } from '../../../lib/store';
import { authHeaders, modeling, MODELING_BASE, unwrap, wsUrl } from '../api';
import { openJsonStream } from '../streams';
import type { StreamHandle, StreamStatus } from '../streams';
import { adaptFrame, frameIndexAt, parseSimMessage } from './frames';
import type { SimFrame, SimLifecycle, SimRecording, SimScene, Vec2, ViewFrame } from './frames';
import { SimClock } from './clock';
import type { SimClockView } from './clock';
import { motionSceneParts } from './sceneMapper';
import type { MotionSceneParts, ShipDims } from './sceneMapper';
import type { CameraPreset } from '../../../scene/types';

export type MotionSource = 'none' | 'live' | 'recording';
export type LinkState = StreamStatus | 'idle';
export type ViewKind = 'plan' | 'map';

export const REPLAY_SPEEDS = [0.5, 1, 2, 4, 8] as const;
const TRAIL_MAX = 600;
const REPLAY_TICK_MS = 50;

export interface MotionState {
  open: boolean;
  /** `plan` is the SVG panel; `map` drives the Cesium scene (2D or 3D) and leaves it visible. */
  view: ViewKind;
  /** What the map could not draw from the supplied frame. */
  notDrawn: string[];
  source: MotionSource;
  link: LinkState;
  sessionId: string | null;
  /** Lifecycle state last reported by the session; null until one arrives (legacy sessions never send one). */
  lifecycle: SimLifecycle['state'] | null;
  lifecycleMessage: string | null;
  scene: SimScene | null;
  sceneError: string | null;
  frame: ViewFrame | null;
  /** Ship positions from displayed frames, berth axes, for the trail. Bounded. */
  trail: Vec2[];
  lastSequence: number | null;
  /** Frames that arrived while the previous one had not been drawn yet. Informational: only the newest is drawn. */
  droppedForDisplay: number;
  busy: boolean;
  error: string | null;
  notice: string | null;
  // recording playback
  recording: { id: string; durationS: number; frames: SimFrame[]; label: string } | null;
  playing: boolean;
  speed: number;
  cursorS: number;
  /** Live sessions: simulation vs wall time and when the forcing applies. Null for recordings and before the first frame. */
  clock: SimClockView | null;
  /** Interactive sessions started from this browser whose recording can be replayed (live copy, else persisted). */
  sessionRecordings: SessionRecordingRef[];
}

export interface SessionRecordingRef {
  sessionId: string;
  recordingUrl: string;
  sceneUrl: string | null;
  startedAt: string;
}

/**
 * Fields the S1 session protocol adds (ws-e/s1-rm0-live-frames). Optional here so the generated types can follow this
 * branch's contract: absent means a legacy session, and recordings and confirmed speed simply do not appear.
 */
type S1SessionCreated = { recording_url?: string | null };
type S1Lifecycle = SimLifecycle & { speed?: number | null };

/** Live speeds the session protocol accepts (simulated seconds per wall second; the physics step never changes). */
export const LIVE_SPEEDS = [0.5, 1, 2, 4, 8, 16] as const;
const MAX_SESSION_RECORDINGS = 10;

const INITIAL: MotionState = {
  open: false,
  view: 'plan',
  notDrawn: [],
  source: 'none',
  link: 'idle',
  sessionId: null,
  lifecycle: null,
  lifecycleMessage: null,
  scene: null,
  sceneError: null,
  frame: null,
  trail: [],
  lastSequence: null,
  droppedForDisplay: 0,
  busy: false,
  error: null,
  notice: null,
  recording: null,
  playing: false,
  speed: 1,
  cursorS: 0,
  sessionRecordings: [],
  clock: null,
};

/** What the motion view needs from the mooring setup. */
export interface MotionHost {
  faceBearingDeg(): number | null;
  /** Drives the shared Cesium scene. Absent in tests and in hosts without a map. */
  map?: {
    /** Hide the planning layout and hold the scene for motion. */
    enter(): void;
    draw(parts: MotionSceneParts): void;
    /** Give the scene back to the planning layout. */
    leave(): void;
    shipDims(): ShipDims | null;
    setCamera(preset: CameraPreset, target?: { x: number; y: number }): void;
  };
  /** Tugs assigned in the current layout and the line numbers it defines: choices for commands before a frame names them. */
  tugIds(): string[];
  lineNumbers(): number[];
  /** Changes whenever the berth, ship, lines or tugs change, i.e. whenever a running session no longer matches the layout. */
  layoutKey(): string;
  /** Saves the current layout as a scenario (sessions are created from one) and returns its id. */
  ensureScenario(): Promise<string | null>;
  /** Where to start the ship, berth axes; null when no berth or ship is selected. */
  initialState(offsetFt: number): { x_ft: number; y_ft: number; heading_true_deg: number; u_kt: number; v_kt: number; r_degps: number } | null;
}

/** Joins a service-rooted path ("/api/v1/...") onto our base, which may carry a proxy prefix. */
export function serviceUrl(base: string, path: string): string {
  if (/^https?:/.test(path)) return path;
  const u = new URL(base);
  return `${u.origin}${u.pathname.replace(/\/$/, '')}${path}`;
}

export const FIXTURE_RECORDING_URL = './fixtures/sim_recording_60s.json';
export const FIXTURE_SCENE_URL = './fixtures/sim_scene.json';

type Scheduler = (cb: () => void) => void;
const rafOrTimeout: Scheduler = (cb) => {
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(cb);
  else setTimeout(cb, 16);
};

export class MotionController {
  readonly state = new Store<MotionState>(INITIAL);
  private stream: StreamHandle | null = null;
  private pending: SimFrame | null = null;
  private flushScheduled = false;
  private replayTimer: ReturnType<typeof setInterval> | undefined;
  private replayClock = 0;
  private disposed = false;
  private rawFrames: SimFrame[] = [];
  private sessionLayoutKey: string | null = null;
  /** Newest lifecycle sequence received; a reconnect asks only for lifecycle messages after it. */
  private lastLifecycleSeq = -1;
  private readonly simClock = new SimClock();

  constructor(
    private readonly host: MotionHost,
    private readonly schedule: Scheduler = rafOrTimeout,
  ) {}

  tugIds(): string[] {
    return this.host.tugIds();
  }

  lineNumbers(): number[] {
    return this.host.lineNumbers();
  }

  get s(): MotionState {
    return this.state.get();
  }

  open(): void {
    this.state.set({ open: true });
  }

  /**
   * Hides the view. A live session is paused and kept, so reopening shows the same session instead of using up one of
   * the few the simulator allows; a recording is simply dropped.
   */
  close(): void {
    if (this.s.view === 'map') this.setView('plan');
    if (this.s.source === 'live' && this.stream) {
      this.pause();
      this.state.set({ open: false });
      return;
    }
    this.stopEverything();
    this.state.set({ ...INITIAL, sessionRecordings: this.s.sessionRecordings });
  }

  dispose(): void {
    if (this.s.view === 'map') this.host.map?.leave();
    this.disposed = true;
    this.stopEverything();
  }

  private stopEverything(): void {
    this.stopReplay();
    this.stream?.close();
    this.stream = null;
    this.pending = null;
  }

  // ---- display ---------------------------------------------------------------------------------------------

  private face(): number | null {
    return this.s.scene?.face_bearing_true_deg ?? this.host.faceBearingDeg();
  }

  /** Draws one frame now (replay, scrub) or the newest pending frame (live). */
  private show(raw: SimFrame): void {
    const frame = adaptFrame(raw, { faceBearingDeg: this.face() });
    const clock = this.s.source === 'live' ? this.simClock.observe(raw, Date.now(), this.s.lifecycle === 'running') : null;
    if (clock || this.s.clock) this.state.set({ clock });
    const p = { x: frame.ship.x_ft, y: frame.ship.y_ft };
    this.state.set((s) => {
      // A new run (reset) starts a fresh trail; time never runs backwards within a run.
      const newRun = s.frame != null && (s.frame.runId !== frame.runId || frame.tS < s.frame.tS);
      const trail = newRun ? [p] : [...s.trail, p].slice(-TRAIL_MAX);
      return { frame, trail, cursorS: frame.tS, lastSequence: frame.sequence ?? s.lastSequence };
    });
    if (this.s.view === 'map') this.drawMap(frame);
  }

  private drawMap(frame: ViewFrame): void {
    const map = this.host.map;
    if (!map) return;
    const parts = motionSceneParts(frame, this.s.scene, map.shipDims());
    map.draw(parts);
    const key = parts.notDrawn.join('|');
    if (key !== this.s.notDrawn.join('|')) this.state.set({ notDrawn: parts.notDrawn });
  }

  /** Switch between the SVG plan panel and the Cesium map (2D or 3D). */
  setView(view: ViewKind): void {
    if (view === this.s.view) return;
    if (view === 'map' && this.host.map) {
      this.host.map.enter();
      this.state.set({ view: 'map' });
      if (this.s.frame) this.drawMap(this.s.frame);
    } else {
      this.host.map?.leave();
      this.state.set({ view: 'plan', notDrawn: [] });
    }
  }

  setCamera(preset: CameraPreset): void {
    const ship = this.s.frame?.ship;
    // Aim at the ship (feet to meters) when there is one; otherwise keep the current target.
    this.host.map?.setCamera(preset, ship ? { x: ship.x_ft * 0.3048, y: ship.y_ft * 0.3048 } : undefined);
  }

  /** Live path: keep only the newest frame and draw it on the next animation frame. Never queues. */
  private receive(raw: SimFrame): void {
    const last = this.s.lastSequence;
    const prev = this.pending ?? null;
    // Ignore stale frames from the same run that arrive out of order.
    if (raw.sequence != null && last != null && raw.sequence <= last && raw.run_id === this.s.frame?.runId) return;
    if (prev) this.state.set((s) => ({ droppedForDisplay: s.droppedForDisplay + 1 }));
    this.pending = raw;
    if (this.flushScheduled) return;
    this.flushScheduled = true;
    this.schedule(() => {
      this.flushScheduled = false;
      const next = this.pending;
      this.pending = null;
      if (next && !this.disposed && this.s.source === 'live') this.show(next);
    });
  }

  // ---- scene ----------------------------------------------------------------------------------------------

  private async loadScene(url: string | null | undefined): Promise<void> {
    if (!url) {
      this.state.set({ scene: null, sceneError: 'This session does not publish a scene; the berth outline is not drawn.' });
      return;
    }
    try {
      const res = await fetch(url, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.state.set({ scene: (await res.json()) as SimScene, sceneError: null });
    } catch (e) {
      this.state.set({ scene: null, sceneError: `Scene unavailable: ${e instanceof Error ? e.message : String(e)}` });
    }
  }

  // ---- recording playback -----------------------------------------------------------------------------------

  async loadRecording(url: string = FIXTURE_RECORDING_URL, sceneUrl: string | null = FIXTURE_SCENE_URL, label = 'Recorded fixture (mock)'): Promise<void> {
    this.stopEverything();
    this.state.set({ busy: true, error: null, source: 'recording', link: 'idle', lifecycle: null, frame: null, trail: [], playing: false, sessionId: null });
    try {
      const res = await fetch(url, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const rec = (await res.json()) as SimRecording;
      if (!rec.frames?.length) throw new Error('The recording has no frames.');
      this.rawFrames = rec.frames;
      await this.loadScene(sceneUrl);
      this.state.set({
        recording: { id: rec.recording_id, durationS: rec.duration_s ?? rec.frames[rec.frames.length - 1].t_s, frames: rec.frames, label },
        busy: false,
        speed: 1,
        notice: null,
      });
      this.seek(rec.frames[0].t_s);
    } catch (e) {
      this.state.set({ busy: false, source: 'none', recording: null, error: `Could not load the recording: ${e instanceof Error ? e.message : String(e)}` });
    }
  }

  seek(tS: number): void {
    if (this.s.source !== 'recording' || !this.rawFrames.length) return;
    const i = frameIndexAt(this.rawFrames, tS);
    if (i >= 0) {
      this.replayClock = tS;
      // Scrubbing rebuilds the trail from the frames up to here so it matches what is on screen.
      const trail = this.rawFrames.slice(0, i + 1).map((f) => ({ x: f.motion?.pose.x_ft ?? f.pose.x_ft, y: f.motion?.pose.y_ft ?? f.pose.y_ft })).slice(-TRAIL_MAX);
      this.state.set({ trail: [] });
      this.show(this.rawFrames[i]);
      this.state.set({ trail });
    }
  }

  play(): void {
    const rec = this.s.recording;
    if (this.s.source !== 'recording' || !rec) return;
    if (this.s.cursorS >= rec.durationS) this.seek(this.rawFrames[0].t_s);
    this.replayClock = this.s.cursorS;
    this.state.set({ playing: true });
    clearInterval(this.replayTimer);
    let last = Date.now();
    this.replayTimer = setInterval(() => {
      const now = Date.now();
      const dt = (now - last) / 1000;
      last = now;
      this.replayClock += dt * this.s.speed;
      const end = this.rawFrames[this.rawFrames.length - 1].t_s;
      if (this.replayClock >= end) {
        this.seek(end);
        this.pauseReplay();
        return;
      }
      const i = frameIndexAt(this.rawFrames, this.replayClock);
      if (this.rawFrames[i] && this.s.frame?.tS !== this.rawFrames[i].t_s) this.show(this.rawFrames[i]);
    }, REPLAY_TICK_MS);
  }

  pauseReplay(): void {
    clearInterval(this.replayTimer);
    this.state.set({ playing: false });
  }

  private stopReplay(): void {
    clearInterval(this.replayTimer);
    this.replayTimer = undefined;
    this.rawFrames = [];
  }

  /** Recording: playback rate. Live: asks the session to run at this many simulated seconds per wall second. */
  setSpeed(speed: number): void {
    if (this.s.source === 'recording') this.state.set({ speed });
    else if (this.s.source === 'live' && speed > 0 && speed <= 16) {
      // The session confirms the applied speed in its next lifecycle message.
      if (this.send({ type: 'set_speed', speed })) this.state.set({ speed });
    }
  }

  /** Replay the recording of a session started from this browser. */
  async loadSessionRecording(sessionId: string): Promise<void> {
    const ref = this.s.sessionRecordings.find((r) => r.sessionId === sessionId);
    if (!ref) return;
    await this.loadRecording(ref.recordingUrl, ref.sceneUrl, `Session ${sessionId} recording (synthetic dynamics)`);
  }

  // ---- live session -----------------------------------------------------------------------------------------

  /** Create a session from the current layout and connect to it. Sessions start paused; call `resume()` to run. */
  async startSession(offsetFt = 120): Promise<void> {
    const inputKey = this.host.layoutKey();
    const layoutKey = JSON.stringify([inputKey, offsetFt]);
    const initial = this.host.initialState(offsetFt);
    if (!initial) {
      this.state.set({ error: 'Choose a berth and a ship first.' });
      return;
    }
    // The simulator allows only a few sessions at once, shared by every client, so reuse the running one when it
    // still matches the layout: a reset returns it to time zero, paused.
    if (this.s.source === 'live' && this.stream && this.s.link === 'open' && this.sessionLayoutKey === layoutKey) {
      this.state.set({ error: null });
      this.reset();
      return;
    }
    this.stopEverything();
    this.lastLifecycleSeq = -1;
    this.simClock.reset();
    this.state.set({ speed: 1, clock: null });
    this.state.set({ busy: true, error: null, source: 'live', link: 'connecting', frame: null, trail: [], lifecycle: null, lifecycleMessage: null, lastSequence: null, droppedForDisplay: 0, recording: null, playing: false });
    try {
      const scenarioId = await this.host.ensureScenario();
      if (inputKey !== this.host.layoutKey()) throw new Error('Inputs changed while saving the scenario. Start a new session.');
      if (!scenarioId) throw new Error('A scenario is needed to start a session; set up the berth, ship and lines first.');
      const created = unwrap(await modeling.POST('/api/v1/berthing/sessions', { body: { scenario_id: scenarioId, initial_state: initial } }));
      if (inputKey !== this.host.layoutKey()) throw new Error('Inputs changed while creating the session. The new session remains paused; start again.');
      this.sessionLayoutKey = layoutKey;
      this.state.set({ sessionId: created.session_id });
      const sceneUrl = created.scene_url ? serviceUrl(MODELING_BASE, created.scene_url) : null;
      const recordingUrl = (created as S1SessionCreated).recording_url;
      if (recordingUrl) {
        const ref: SessionRecordingRef = {
          sessionId: created.session_id,
          recordingUrl: serviceUrl(MODELING_BASE, recordingUrl),
          sceneUrl,
          startedAt: new Date().toISOString(),
        };
        this.state.set({ sessionRecordings: [ref, ...this.s.sessionRecordings].slice(0, MAX_SESSION_RECORDINGS) });
      }
      await this.loadScene(sceneUrl);
      if (this.disposed) return;
      if (inputKey !== this.host.layoutKey()) throw new Error('Inputs changed while loading the scene. The session remains paused; start again.');
      this.connect(created.session_id);
      this.state.set({ busy: false });
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      this.state.set({
        busy: false,
        source: 'none',
        link: 'idle',
        error: /^429\b/.test(detail)
          ? 'The simulator is at its session limit. A few sessions are shared by every client, and idle ones are freed after about 30 minutes. Try again shortly, or restart the modeling service.'
          : `Could not start a session: ${detail}`,
      });
    }
  }

  private connect(sessionId: string): void {
    // On reconnect, ask only for lifecycle messages newer than the last one seen; frames are latest-state only.
    const url = () =>
      wsUrl(MODELING_BASE, `/ws/sim/${encodeURIComponent(sessionId)}`, {
        after_sequence: this.lastLifecycleSeq >= 0 ? this.lastLifecycleSeq : undefined,
      });
    let first = true;
    this.stream = openJsonStream<unknown>(
      url,
      (raw) => {
        const msg = parseSimMessage(raw);
        if (msg.kind === 'frame') this.receive(msg.frame);
        else if (msg.kind === 'lifecycle') this.onLifecycle(msg.lifecycle);
      },
      (link) => {
        if (this.disposed) return;
        this.state.set({ link });
        if (link === 'open' && !first) {
          // The server returns a reconnected session paused; the user must resume explicitly.
          this.state.set({ notice: 'Reconnected. The session comes back paused: press Resume to continue.', lifecycle: 'paused' });
        }
        if (link === 'open') first = false;
        if (link === 'error') this.state.set({ notice: 'Connection lost; retrying…' });
      },
    );
  }

  private onLifecycle(lifecycle: SimLifecycle): void {
    // Retained lifecycle messages can be resent; never step backwards.
    if (lifecycle.sequence <= this.lastLifecycleSeq) return;
    this.lastLifecycleSeq = lifecycle.sequence;
    this.state.set({
      lifecycle: lifecycle.state,
      lifecycleMessage: lifecycle.message ?? null,
      ...((lifecycle as S1Lifecycle).speed != null ? { speed: (lifecycle as S1Lifecycle).speed! } : {}),
    });
  }

  /** Control messages and commands. Returns false when there is no live session to send to. */
  private send(message: Record<string, unknown>): boolean {
    if (this.s.source !== 'live' || !this.stream) return false;
    const sent = this.stream.send(JSON.stringify(message));
    if (!sent) this.state.set({ notice: 'Not connected: the command was not sent.' });
    return sent;
  }

  resume(): boolean {
    this.state.set({ notice: null });
    return this.send({ type: 'resume' });
  }

  pause(): boolean {
    return this.send({ type: 'pause' });
  }

  reset(): boolean {
    this.state.set({ trail: [], notice: null });
    return this.send({ type: 'reset' });
  }

  tugCommand(tugId: string, forceLbf: number, directionRelDeg: number): boolean {
    return this.send({ type: 'tug_command', tug_id: tugId, force_lbf: Math.max(0, forceLbf), direction_rel_deg: ((directionRelDeg % 360) + 360) % 360 });
  }

  lineEvent(lineNumber: number, event: 'secured' | 'tensioned' | 'released'): boolean {
    return this.send({ type: 'line_event', line_number: lineNumber, event });
  }
}
