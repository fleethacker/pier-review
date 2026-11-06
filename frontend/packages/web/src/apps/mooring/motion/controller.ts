import { Store } from '../../../lib/store';
import { credentialState, GATEWAY_REQUIRED } from '../../../lib/credentials';
import { authHeaders, modeling, MODELING_BASE, unwrap, wsUrl } from '../api';
import { openJsonStream } from '../streams';
import type { StreamHandle, StreamStatus } from '../streams';
import { adaptFrame, frameIndexAt, parseSimMessage } from './frames';
import type { SimFrame, SimLifecycle, SimRecording, SimScene, Vec2, ViewFrame } from './frames';
import { forcingOf, SimClock } from './clock';
import type { SimClockView } from './clock';
import { motionSceneParts } from './sceneMapper';
import type { MotionSceneParts, ShipDims } from './sceneMapper';
import type { CameraPreset } from '../../../scene/types';
import { motionRequest, releaseMotionSession } from './workspace';
import type { HelmOrder, PayloadItem, Prediction, StateInput, StateSnapshot, TugOrder, WorkspaceCatalog, WorkspaceScenario, WorkspaceSession, WorkspaceSpec } from './workspace';

export type MotionSource = 'none' | 'live' | 'recording';
export type LinkState = StreamStatus | 'idle';
export type ViewKind = 'plan' | 'map';

export const REPLAY_SPEEDS = [0.5, 1, 2, 4, 8] as const;
const TRAIL_MAX = 600;
const REPLAY_TICK_MS = 50;

export interface MotionState {
  catalog: WorkspaceCatalog | null;
  catalogBusy: boolean;
  catalogError: string | null;
  savedScenarios: WorkspaceScenario[];
  savedScenariosBusy: boolean;
  savedScenariosError: string | null;
  workspace: WorkspaceSession | null;
  prediction: Prediction | null;
  predictionBusy: boolean;
  predictionPreviewPending: boolean;
  predictionError: string | null;
  predictionEnabled: boolean;
  predictionWhatIf: boolean;
  command: { status: 'pending' | 'applied' | 'unconfirmed'; message: string } | null;
  importedState: StateSnapshot | null;
  stateImportBusy: boolean;
  stateImportError: string | null;
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
  lifecycleReasons: string[];
  lifecycleInvalid: boolean;
  forcingRevision: string | null;
  forcingSynthetic: boolean | null;
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
  forcingRevision?: string | null;
  forcingSynthetic?: boolean | null;
}

/** Live speeds the session protocol accepts (simulated seconds per wall second; the physics step never changes). */
export const LIVE_SPEEDS = [0.5, 1, 2, 4, 8, 16] as const;
const MAX_SESSION_RECORDINGS = 10;

const INITIAL: MotionState = {
  catalog: null, catalogBusy: false, catalogError: null, workspace: null,
  savedScenarios: [], savedScenariosBusy: false, savedScenariosError: null,
  prediction: null, predictionBusy: false, predictionPreviewPending: false, predictionError: null, predictionEnabled: true, predictionWhatIf: false, command: null,
  importedState: null, stateImportBusy: false, stateImportError: null,
  open: false,
  view: 'plan',
  notDrawn: [],
  source: 'none',
  link: 'idle',
  sessionId: null,
  lifecycle: null,
  lifecycleMessage: null,
  lifecycleReasons: [],
  lifecycleInvalid: false,
  forcingRevision: null,
  forcingSynthetic: null,
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
  private loadEpoch = 0;
  private forcingSyntheticOverride: boolean | null = null;
  private rawFrames: SimFrame[] = [];
  private sessionLayoutKey: string | null = null;
  /** Newest lifecycle sequence received; a reconnect asks only for lifecycle messages after it. */
  private lastLifecycleSeq = -1;
  private readonly simClock = new SimClock();
  private catalogPromise: Promise<void> | null = null;
  private predictionTimer: ReturnType<typeof setTimeout> | undefined;
  private predictionInFlight = false;
  private predictionQueued = false;
  private predictionUrgent = false;
  private predictionLastKey: string | null = null;
  private predictionLastStarted = -Infinity;
  private predictionRetryAt = 0;
  private predictionFailures = 0;
  private predictionEpoch = 0;
  private predictionContext: Pick<SimLifecycle, 'run_id' | 'scene_id' | 'scene_revision'> | null = null;
  private predictionFailureFrame: ViewFrame | null = null;
  private pendingHelm: HelmOrder | null = null;
  private pendingLine: { line_number: number; attached?: boolean; paid_out_length_ft?: number } | null = null;
  private pendingPayloads: PayloadItem[] | null = null;
  private pendingTug: { id: string; order: TugOrder } | null = null;
  private previewOrder: HelmOrder | null = null;
  private releases: Promise<void> = Promise.resolve();
  private releasingIds = new Set<string>();
  private unreleasedIds = new Set<string>();
  private workspaceViewEpoch = 0;
  private stateImportEpoch = 0;
  private acceptedStateSequences = new Map<string, number>();
  private savedScenariosPromise: Promise<void> | null = null;

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

  open(workspace = false): void {
    this.state.set({ open: true });
    if (workspace) void this.initializeWorkspace();
    if (this.s.workspace) this.startPredictions();
  }

  async initializeWorkspace(): Promise<void> {
    void this.loadSavedScenarios();
    await this.loadCatalog();
    const preset = this.s.catalog?.presets[0];
    if (this.s.open && this.s.source === 'none' && !this.s.busy && preset) await this.loadWorkspace(preset.configuration);
  }

  /** StrictMode rehearsal or an immediate remount keeps the view; a true departure pauses the session. */
  bindWorkspaceView(): () => void {
    const epoch = ++this.workspaceViewEpoch;
    return () => queueMicrotask(() => { if (this.workspaceViewEpoch === epoch && this.s.open) this.close(); });
  }

  async loadCatalog(): Promise<void> {
    if (this.s.catalog) return;
    if (this.catalogPromise) return this.catalogPromise;
    this.state.set({ catalogBusy: true, catalogError: null });
    this.catalogPromise = (async () => {
      try {
        const catalog = await motionRequest<WorkspaceCatalog>('/catalog');
        if (!this.disposed) this.state.set({ catalog, catalogBusy: false });
      } catch (e) {
        if (!this.disposed) this.state.set({ catalogBusy: false, catalogError: e instanceof Error ? e.message : String(e) });
      } finally { this.catalogPromise = null; }
    })();
    return this.catalogPromise;
  }

  async loadSavedScenarios(): Promise<void> {
    if (this.savedScenariosPromise) return this.savedScenariosPromise;
    this.state.set({ savedScenariosBusy: true, savedScenariosError: null });
    this.savedScenariosPromise = (async () => {
      try {
        const savedScenarios = await motionRequest<WorkspaceScenario[]>('/scenarios');
        if (!this.disposed) this.state.set((s) => ({ savedScenarios: [...s.savedScenarios, ...savedScenarios.filter((entry) => !s.savedScenarios.some((known) => known.motion_scenario_id === entry.motion_scenario_id))], savedScenariosBusy: false }));
      } catch (e) {
        if (!this.disposed) this.state.set({ savedScenariosBusy: false, savedScenariosError: e instanceof Error ? e.message : String(e) });
      } finally { this.savedScenariosPromise = null; }
    })();
    return this.savedScenariosPromise;
  }

  /** Each selection creates a server-owned scenario and a paused session. Only Start sends resume. */
  async loadWorkspace(configuration: WorkspaceSpec): Promise<void> {
    if (credentialState.get().configured) { this.state.set({ error: GATEWAY_REQUIRED }); return; }
    this.stopEverything();
    const epoch = this.loadEpoch;
    this.lastLifecycleSeq = -1;
    this.simClock.reset();
    this.state.set({ busy: true, error: null, notice: null, source: 'live', link: 'connecting', workspace: null,
      scene: null, sceneError: null, frame: null, trail: [], lifecycle: null, lifecycleMessage: null,
      lifecycleReasons: [], lifecycleInvalid: false, sessionId: null, recording: null, playing: false,
      lastSequence: null, droppedForDisplay: 0, speed: 1, clock: null, forcingRevision: null, forcingSynthetic: null, command: null });
    try {
      await this.releases;
      if (this.unreleasedIds.size) {
        for (const id of this.unreleasedIds) this.releaseWorkspaceSession(id);
        await this.releases;
        if (this.unreleasedIds.size) throw new Error('A previous session could not be released. Its recording remains on the service. Retry loading after the service recovers.');
      }
      if (epoch !== this.loadEpoch || this.disposed) return;
      const scenario = await motionRequest<WorkspaceScenario>('/scenarios', configuration);
      if (epoch !== this.loadEpoch || this.disposed) return;
      this.state.set({ savedScenarios: [scenario, ...this.s.savedScenarios.filter((entry) => entry.motion_scenario_id !== scenario.motion_scenario_id)] });
      const workspace = await motionRequest<WorkspaceSession>('/sessions', { motion_scenario_id: scenario.motion_scenario_id });
      if (epoch !== this.loadEpoch || this.disposed) { this.releaseWorkspaceSession(workspace.session.session_id); return; }
      const created = workspace.session;
      this.forcingSyntheticOverride = created.forcing_synthetic ?? null;
      this.state.set({ workspace, sessionId: created.session_id, forcingRevision: created.forcing_revision ?? null, forcingSynthetic: created.forcing_synthetic ?? null });
      const sceneUrl = created.scene_url ? serviceUrl(MODELING_BASE, created.scene_url) : null;
      if (created.recording_url) this.state.set({ sessionRecordings: [{ sessionId: created.session_id,
        recordingUrl: serviceUrl(MODELING_BASE, created.recording_url), sceneUrl, startedAt: new Date().toISOString(),
        forcingRevision: created.forcing_revision, forcingSynthetic: created.forcing_synthetic }, ...this.s.sessionRecordings].slice(0, MAX_SESSION_RECORDINGS) });
      await this.loadScene(sceneUrl, epoch);
      if (epoch !== this.loadEpoch || this.disposed) return;
      this.connect(created.session_id);
      this.state.set({ busy: false });
      this.startPredictions();
    } catch (e) {
      if (epoch !== this.loadEpoch || this.disposed) return;
      this.state.set({ busy: false, source: 'none', link: 'idle', error: `Could not load maneuver: ${e instanceof Error ? e.message : String(e)}` });
    }
  }

  /**
   * Hides the view. A live session is paused and kept, so reopening shows the same session instead of using up one of
   * the few the simulator allows; a recording is simply dropped.
   */
  close(): void {
    this.stopPredictions();
    if (this.s.view === 'map') this.setView('plan');
    if (this.s.source === 'live' && this.stream) {
      this.pause();
      this.state.set({ open: false });
      return;
    }
    this.stopEverything();
    this.state.set({ ...INITIAL, catalog: this.s.catalog, sessionRecordings: this.s.sessionRecordings });
  }

  dispose(): void {
    if (this.s.view === 'map') this.host.map?.leave();
    this.disposed = true;
    this.stopEverything();
  }

  private stopEverything(): void {
    this.stopPredictions();
    this.predictionContext = null;
    this.predictionFailureFrame = null;
    this.stateImportEpoch += 1;
    this.acceptedStateSequences.clear();
    this.pendingHelm = null; this.pendingLine = null; this.pendingPayloads = null;
    this.pendingTug = null;
    this.state.set({ importedState: null, stateImportBusy: false, stateImportError: null });
    this.loadEpoch += 1;
    this.forcingSyntheticOverride = null;
    this.stopReplay();
    this.stream?.close();
    this.stream = null;
    this.pending = null;
    if (this.s.workspace && this.s.sessionId) this.releaseWorkspaceSession(this.s.sessionId);
  }

  private releaseWorkspaceSession(id: string): void {
    this.unreleasedIds.add(id);
    if (this.releasingIds.has(id)) return;
    this.releasingIds.add(id);
    this.releases = this.releases.catch(() => undefined).then(async () => {
      try {
        await releaseMotionSession(id);
        this.unreleasedIds.delete(id);
        if (!this.disposed && this.s.notice?.startsWith('Previous session could not be released')) this.state.set({ notice: null });
      } catch (e) {
        if (!this.disposed) this.state.set({ notice: e instanceof Error ? e.message : String(e) });
      } finally { this.releasingIds.delete(id); }
    });
  }

  // ---- display ---------------------------------------------------------------------------------------------

  private face(): number | null {
    return this.s.scene?.face_bearing_true_deg ?? this.host.faceBearingDeg();
  }

  /** Draws one frame now (replay, scrub) or the newest pending frame (live). */
  private show(raw: SimFrame): void {
    const frame = adaptFrame(raw, { faceBearingDeg: this.face() });
    for (const snapshot of frame.stateInputs) this.rememberStateSequence(snapshot.input);
    if (this.s.frame && this.s.frame.runId !== frame.runId) {
      this.pendingHelm = null; this.pendingLine = null; this.pendingPayloads = null; this.pendingTug = null;
      if (this.s.command?.status === 'pending') this.state.set({ command: { status: 'unconfirmed', message: 'Run changed before backend acknowledgement. Inspect the new run state before sending another order.' } });
    }
    if (this.s.frame && (this.s.frame.runId !== frame.runId || this.s.frame.sceneId !== frame.sceneId || this.s.frame.sceneRevision !== frame.sceneRevision || this.s.frame.badge.validity !== frame.badge.validity || frame.tS < this.s.frame.tS || (raw.forcing_revision != null && raw.forcing_revision !== this.s.forcingRevision))) this.invalidatePrediction();
    const existing = this.s.prediction;
    if (existing && frame.tS > existing.source.t_s && frame.tS >= (existing.path.at(-1)?.t_s ?? existing.source.t_s)) {
      this.state.set({ prediction: null, predictionError: 'Prediction horizon expired. Waiting for a fresh backend snapshot; future coverage is unavailable.' });
    }
    if (this.pendingHelm && frame.controls && Object.entries(this.pendingHelm).every(([k, v]) => Math.abs(frame.controls!.commanded[k as keyof HelmOrder] - v) < 1e-6)) {
      this.pendingHelm = null;
      this.state.set({ command: { status: 'applied', message: 'Helm order acknowledged by the backend. Actual actuator values follow their response rates.' } });
    }
    if (this.pendingLine) {
      const request = this.pendingLine;
      const line = frame.lineControls.find((l) => l.line_number === request.line_number);
      if (line && (request.attached === undefined || line.attached === request.attached) && (request.paid_out_length_ft === undefined || Math.abs(line.paid_out_length_ft - request.paid_out_length_ft) < 1e-6)) {
        this.pendingLine = null;
        this.state.set({ command: { status: 'applied', message: `Line ${line.line_number} change acknowledged by the backend.` } });
      }
    }
    if (this.pendingPayloads && frame.loading && JSON.stringify(frame.loading.payloads) === JSON.stringify(this.pendingPayloads)) {
      this.pendingPayloads = null;
      this.state.set({ command: { status: 'applied', message: 'Payload inventory acknowledged by the backend.' } });
    }
    if (this.pendingTug) {
      const pending = this.pendingTug;
      const reported = frame.tugDynamics.find((t) => t.tug_id === pending.id);
      if (reported && Object.entries(pending.order).every(([k, v]) => reported.commanded[k as keyof TugOrder] === v)) {
        this.pendingTug = null;
        this.state.set({ command: { status: 'applied', message: `Tug ${pending.id} maneuver order acknowledged. Force transfer requires reported contact or a taut tow.` } });
      }
    }
    if (this.hasPendingOrders() && this.s.command?.status === 'applied') this.state.set({ command: { status: 'pending', message: 'Some orders are acknowledged. Waiting for the remaining backend command echoes.' } });
    const forcing = forcingOf(raw);
    this.state.set({ forcingRevision: forcing.forcingRevision ?? this.s.forcingRevision,
      forcingSynthetic: this.forcingSyntheticOverride ?? (this.s.forcingSynthetic === true || forcing.training) });
    const clock = this.s.source === 'live' ? this.simClock.observe(raw, Date.now(), this.s.lifecycle === 'running') : null;
    if (clock) clock.training = this.s.forcingSynthetic ?? clock.training;
    if (clock || this.s.clock) this.state.set({ clock });
    const p = { x: frame.ship.x_ft, y: frame.ship.y_ft };
    this.state.set((s) => {
      // A new run (reset) starts a fresh trail; time never runs backwards within a run.
      const newRun = s.frame != null && (s.frame.runId !== frame.runId || frame.tS < s.frame.tS);
      const trail = newRun ? [p] : [...s.trail, p].slice(-TRAIL_MAX);
      return { frame, trail, cursorS: frame.tS, lastSequence: frame.sequence ?? s.lastSequence };
    });
    if (this.s.view === 'map') this.drawMap(frame);
    if (this.s.open) void this.requestPrediction();
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

  private async loadScene(url: string | null | undefined, epoch = this.loadEpoch): Promise<void> {
    if (!url) {
      this.state.set({ scene: null, sceneError: 'This session does not publish a scene; the berth outline is not drawn.' });
      return;
    }
    try {
      const res = await fetch(url, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const scene = (await res.json()) as SimScene;
      if (epoch !== this.loadEpoch || this.disposed) return;
      this.state.set({ scene, sceneError: null });
    } catch (e) {
      if (epoch !== this.loadEpoch || this.disposed) return;
      this.state.set({ scene: null, sceneError: `Scene unavailable: ${e instanceof Error ? e.message : String(e)}` });
    }
  }

  // ---- recording playback -----------------------------------------------------------------------------------

  async loadRecording(url: string = FIXTURE_RECORDING_URL, sceneUrl: string | null = FIXTURE_SCENE_URL, label = 'Recorded fixture (mock)', forcing?: Pick<SessionRecordingRef, 'forcingRevision' | 'forcingSynthetic'>): Promise<void> {
    this.stopEverything();
    const epoch = this.loadEpoch;
    this.forcingSyntheticOverride = forcing?.forcingSynthetic ?? null;
    this.state.set({ forcingRevision: forcing?.forcingRevision ?? null, forcingSynthetic: forcing?.forcingSynthetic ?? null, lifecycleReasons: [], lifecycleInvalid: false });
    this.state.set({ busy: true, error: null, source: 'recording', workspace: null, command: null, link: 'idle', lifecycle: null, frame: null, trail: [], playing: false, sessionId: null });
    try {
      const res = await fetch(url, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const rec = (await res.json()) as SimRecording;
      if (epoch !== this.loadEpoch || this.disposed) return;
      if (!rec.frames?.length) throw new Error('The recording has no frames.');
      this.rawFrames = rec.frames;
      await this.loadScene(sceneUrl, epoch);
      if (epoch !== this.loadEpoch || this.disposed) return;
      this.state.set({
        recording: { id: rec.recording_id, durationS: rec.duration_s ?? rec.frames[rec.frames.length - 1].t_s, frames: rec.frames, label },
        busy: false,
        speed: 1,
        notice: null,
      });
      this.seek(rec.frames[0].t_s);
    } catch (e) {
      if (epoch !== this.loadEpoch || this.disposed) return;
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
    await this.loadRecording(ref.recordingUrl, ref.sceneUrl, `Session ${sessionId} recording (synthetic dynamics)`, ref);
  }

  // ---- live session -----------------------------------------------------------------------------------------

  /** Create a session from the current layout and connect to it. Sessions start paused; call `resume()` to run. */
  async startSession(offsetFt = 120): Promise<void> {
    if (credentialState.get().configured) { this.state.set({ error: GATEWAY_REQUIRED }); return; }
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
    const epoch = this.loadEpoch;
    this.lastLifecycleSeq = -1;
    this.simClock.reset();
    this.state.set({ speed: 1, clock: null, forcingRevision: null, forcingSynthetic: null, lifecycleReasons: [], lifecycleInvalid: false });
    this.state.set({ busy: true, error: null, source: 'live', workspace: null, command: null, link: 'connecting', frame: null, trail: [], lifecycle: null, lifecycleMessage: null, lastSequence: null, droppedForDisplay: 0, recording: null, playing: false });
    try {
      const scenarioId = await this.host.ensureScenario();
      if (epoch !== this.loadEpoch || this.disposed) return;
      if (inputKey !== this.host.layoutKey()) throw new Error('Inputs changed while saving the scenario. Start a new session.');
      if (!scenarioId) throw new Error('A scenario is needed to start a session; set up the berth, ship and lines first.');
      const created = unwrap(await modeling.POST('/api/v1/berthing/sessions', { body: { scenario_id: scenarioId, initial_state: initial } }));
      if (epoch !== this.loadEpoch || this.disposed) return;
      if (inputKey !== this.host.layoutKey()) throw new Error('Inputs changed while creating the session. The new session remains paused; start again.');
      this.sessionLayoutKey = layoutKey;
      this.forcingSyntheticOverride = created.forcing_synthetic ?? null;
      this.state.set({ sessionId: created.session_id, forcingRevision: created.forcing_revision ?? null,
        forcingSynthetic: created.forcing_synthetic ?? null });
      const sceneUrl = created.scene_url ? serviceUrl(MODELING_BASE, created.scene_url) : null;
      const recordingUrl = created.recording_url;
      if (recordingUrl) {
        const ref: SessionRecordingRef = {
          sessionId: created.session_id,
          recordingUrl: serviceUrl(MODELING_BASE, recordingUrl),
          sceneUrl,
          startedAt: new Date().toISOString(),
          forcingRevision: created.forcing_revision,
          forcingSynthetic: created.forcing_synthetic,
        };
        this.state.set({ sessionRecordings: [ref, ...this.s.sessionRecordings].slice(0, MAX_SESSION_RECORDINGS) });
      }
      await this.loadScene(sceneUrl, epoch);
      if (epoch !== this.loadEpoch || this.disposed) return;
      if (inputKey !== this.host.layoutKey()) throw new Error('Inputs changed while loading the scene. The session remains paused; start again.');
      this.connect(created.session_id);
      this.state.set({ busy: false });
    } catch (e) {
      if (epoch !== this.loadEpoch || this.disposed) return;
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
      (link, detail) => {
        if (this.disposed) return;
        const unconfirmed = (link === 'error' || link === 'closed') && (this.s.command?.status === 'pending' || this.hasPendingOrders());
        if (unconfirmed) {
          this.pendingHelm = null; this.pendingLine = null; this.pendingPayloads = null; this.pendingTug = null;
          this.predictionFailureFrame = this.s.frame;
          this.invalidatePrediction();
        }
        this.state.set({ link });
        if (link === 'open' && !first) {
          // The server returns a reconnected session paused; the user must resume explicitly.
          this.state.set({ notice: 'Reconnected. The session comes back paused: press Resume to continue.', lifecycle: 'paused' });
        }
        if (link === 'open') { first = false; if (this.s.open) void this.requestPrediction(); }
        if (link === 'error') this.state.set({ notice: 'Connection lost; retrying…', ...(unconfirmed ? { command: { status: 'unconfirmed' as const, message: 'Connection interrupted. The command is unconfirmed; inspect the reported state before sending again.' } } : {}) });
        if (link === 'closed') this.state.set({
          notice: `${detail?.code === 1008 ? 'Command rejected' : 'Simulation connection closed'}${detail?.reason ? `: ${detail.reason}` : ''}. Load a paused scenario to reconnect.`,
          ...(unconfirmed ? { command: { status: 'unconfirmed' as const, message: 'Connection closed before acknowledgement. The last command is unconfirmed.' } } : {}),
        });
      },
    );
  }

  private onLifecycle(lifecycle: SimLifecycle): void {
    // Retained lifecycle messages can be resent; never step backwards.
    if (lifecycle.sequence <= this.lastLifecycleSeq) return;
    this.lastLifecycleSeq = lifecycle.sequence;
    this.predictionContext = lifecycle;
    const invalid = lifecycle.state === 'error' || lifecycle.validity?.state === 'invalid';
    if (invalid) this.predictionFailureFrame = this.s.frame;
    if (invalid || !this.predictionFrameMatchesLifecycle()) this.invalidatePrediction();
    this.state.set({
      lifecycle: lifecycle.state,
      lifecycleMessage: lifecycle.message ?? null,
      lifecycleReasons: (lifecycle.validity?.reasons ?? []).map((reason) => `${reason.code}: ${reason.message}`),
      lifecycleInvalid: lifecycle.validity?.state === 'invalid',
      ...(lifecycle.speed != null ? { speed: lifecycle.speed } : {}),
    });
    if (invalid) this.state.set({ predictionError: 'Simulation reported an error or invalid state. Future coverage is unavailable until authoritative state recovers.' });
    if (this.s.open) void this.requestPrediction();
  }

  /** Control messages and commands. Returns false when there is no live session to send to. */
  private send(message: Record<string, unknown>): boolean {
    if (this.s.source !== 'live' || !this.stream) return false;
    const sent = this.stream.send(JSON.stringify(message));
    if (!sent) this.state.set({ notice: 'Not connected: the command was not sent.' });
    return sent;
  }

  resume(): boolean {
    if (this.s.stateImportBusy) return false;
    this.state.set({ notice: null });
    return this.send({ type: 'resume' });
  }

  pause(): boolean {
    return this.send({ type: 'pause' });
  }

  reset(): boolean {
    this.invalidatePrediction();
    this.stateImportEpoch += 1;
    this.pendingHelm = null; this.pendingLine = null; this.pendingPayloads = null; this.pendingTug = null;
    this.state.set({ trail: [], notice: null, command: null, importedState: null, stateImportBusy: false, stateImportError: null });
    return this.send({ type: 'reset' });
  }

  tugCommand(tugId: string, forceLbf: number, directionRelDeg: number): boolean {
    const sent = this.send({ type: 'tug_command', tug_id: tugId, force_lbf: Math.max(0, forceLbf), direction_rel_deg: ((directionRelDeg % 360) + 360) % 360 });
    if (sent && this.s.workspace) { this.invalidatePrediction(); this.state.set({ command: { status: 'unconfirmed', message: `Tug ${tugId} order sent. Compare the reported force after simulation advances; this protocol supplies no command receipt.` } }); }
    return sent;
  }

  lineEvent(lineNumber: number, event: 'secured' | 'tensioned' | 'released'): boolean {
    return this.send({ type: 'line_event', line_number: lineNumber, event });
  }

  helmCommand(order: HelmOrder): boolean {
    const sent = this.send({ type: 'helm_command', ...order });
    if (sent) { this.pendingHelm = { ...order }; this.commandSent('Helm order sent. Waiting for the backend state.'); }
    return sent;
  }

  lineControl(line: { line_number: number; attached?: boolean; paid_out_length_ft?: number }): boolean {
    const sent = this.send({ type: 'line_control', ...line });
    if (sent) { this.pendingLine = { ...line }; this.commandSent(`Line ${line.line_number} command sent. Waiting for the backend state.`); }
    return sent;
  }

  loadingCommand(payloads: PayloadItem[]): boolean {
    const sent = this.send({ type: 'loading_command', payloads });
    if (sent) { this.pendingPayloads = structuredClone(payloads); this.commandSent('Payload change sent. Waiting for the backend state.'); }
    return sent;
  }

  tugMotionCommand(id: string, order: TugOrder): boolean {
    const sent = this.send({ type: 'tug_motion_command', tug_id: id, ...order });
    if (sent) { this.pendingTug = { id, order: { ...order } }; this.commandSent(`Tug ${id} maneuver order sent. Waiting for backend state.`); }
    return sent;
  }

  async importState(input: StateInput): Promise<void> {
    const id = this.s.sessionId;
    if (!id || this.s.source !== 'live' || !['created', 'paused', 'reset'].includes(this.s.lifecycle ?? '') || this.s.stateImportBusy) return;
    const epoch = this.loadEpoch;
    const operation = ++this.stateImportEpoch;
    const previousRun = this.s.frame?.runId;
    this.invalidatePrediction();
    this.state.set({ stateImportBusy: true, stateImportError: null });
    try {
      const snapshot = await motionRequest<StateSnapshot>(`/sessions/${encodeURIComponent(id)}/state`, input);
      if (epoch !== this.loadEpoch || this.disposed || this.s.sessionId !== snapshot.session_id) return;
      this.rememberStateSequence(snapshot.input);
      if (operation !== this.stateImportEpoch) return;
      if (this.s.frame?.runId !== previousRun && this.s.frame?.runId !== snapshot.run_id) {
        this.state.set({ stateImportBusy: false, stateImportError: 'Accepted input belongs to a previous run. The displayed run has since changed.' });
        if (this.s.open) void this.requestPrediction(true);
        return;
      }
      this.state.set({ importedState: snapshot, stateImportBusy: false, command: { status: 'applied', message: 'Supplied state accepted into a new paused run. Start continues backend simulation from this input.' } });
      if (this.s.open && this.s.frame?.runId === snapshot.run_id) void this.requestPrediction(true);
    } catch (e) {
      if (epoch !== this.loadEpoch || operation !== this.stateImportEpoch || this.disposed) return;
      this.state.set({ stateImportBusy: false, stateImportError: e instanceof Error ? e.message : String(e) });
      if (this.s.open) void this.requestPrediction(true);
    }
  }

  private rememberStateSequence(input: StateInput): void {
    const key = `${input.entity}:${input.entity_id}`;
    this.acceptedStateSequences.set(key, Math.max(this.acceptedStateSequences.get(key) ?? 0, input.sequence));
  }

  nextStateSequence(entity: StateInput['entity'], entityId: string): number {
    for (const snapshot of this.s.frame?.stateInputs ?? []) this.rememberStateSequence(snapshot.input);
    if (this.s.importedState) this.rememberStateSequence(this.s.importedState.input);
    return (this.acceptedStateSequences.get(`${entity}:${entityId}`) ?? 0) + 1;
  }

  private commandSent(message: string): void {
    this.invalidatePrediction();
    this.state.set({ command: { status: 'pending', message } });
    if (this.s.open) void this.requestPrediction(true);
  }

  private invalidatePrediction(): void {
    this.previewOrder = null;
    this.predictionEpoch += 1;
    this.predictionLastKey = null;
    this.predictionRetryAt = 0;
    this.predictionFailures = 0;
    this.predictionQueued = false;
    this.predictionUrgent = false;
    clearTimeout(this.predictionTimer); this.predictionTimer = undefined;
    // Invalidating a response does not cancel the server's work. Keep its request slot until it settles.
    this.state.set({ prediction: null, predictionBusy: false, predictionPreviewPending: false, predictionError: null, predictionWhatIf: false });
  }

  private stopPredictions(): void {
    this.invalidatePrediction();
  }

  private startPredictions(): void {
    if (this.s.open) void this.requestPrediction();
  }

  setPredictionEnabled(enabled: boolean): void {
    this.state.set({ predictionEnabled: enabled });
    if (!enabled) this.invalidatePrediction();
    else void this.refreshPrediction();
  }

  /** Explicit previews supersede intent, but queue behind server work already in progress. */
  async refreshPrediction(whatIf?: HelmOrder): Promise<void> {
    if (whatIf && JSON.stringify(whatIf) !== JSON.stringify(this.previewOrder)) {
      this.invalidatePrediction();
      this.previewOrder = { ...whatIf };
      this.state.set({ predictionEnabled: true, predictionWhatIf: true, predictionPreviewPending: true });
    }
    return this.requestPrediction(true);
  }

  private predictionKey(): string {
    const s = this.s;
    return JSON.stringify([s.sessionId, s.frame?.runId, s.frame?.sceneId, s.frame?.sceneRevision,
      s.frame?.sequence, s.frame?.tS, s.forcingRevision, this.predictionEpoch]);
  }

  private predictionFrameMatchesLifecycle(): boolean {
    const context = this.predictionContext, frame = this.s.frame;
    return !context || !!frame && frame.runId === context.run_id
      && (context.scene_id == null || frame.sceneId === context.scene_id)
      && (context.scene_revision == null || frame.sceneRevision === context.scene_revision);
  }

  private hasPendingOrders(): boolean {
    return !!(this.pendingHelm || this.pendingLine || this.pendingPayloads || this.pendingTug);
  }

  /** Coalesce advancing frames at <=1 Hz. Unchanged paused snapshots perform no background work. */
  private async requestPrediction(urgent = false): Promise<void> {
    const s = this.s;
    if (this.disposed || !s.predictionEnabled || s.stateImportBusy || s.lifecycleInvalid || s.lifecycle === 'error' || s.frame === this.predictionFailureFrame || s.command?.status === 'pending' || this.hasPendingOrders() || !this.predictionFrameMatchesLifecycle() || !s.workspace || !s.sessionId || !s.frame || s.source !== 'live' || s.link !== 'open') return;
    const key = this.predictionKey();
    if (key === this.predictionLastKey) return;
    if (this.predictionInFlight) {
      this.predictionQueued = true; this.predictionUrgent ||= urgent;
      return;
    }
    const delay = urgent ? 0 : Math.max(this.predictionLastStarted + 1000, this.predictionRetryAt) - performance.now();
    if (delay > 0) {
      this.predictionQueued = true;
      if (!this.predictionTimer) this.predictionTimer = setTimeout(() => {
        this.predictionTimer = undefined;
        void this.requestPrediction(this.predictionUrgent);
      }, delay);
      return;
    }
    clearTimeout(this.predictionTimer); this.predictionTimer = undefined;
    this.predictionQueued = false; this.predictionUrgent = false;
    this.predictionInFlight = true;
    this.predictionLastKey = key;
    this.predictionLastStarted = performance.now();
    const epoch = this.predictionEpoch;
    const previewOrder = this.previewOrder;
    this.state.set({ predictionBusy: true });
    const abort = new AbortController();
    let deadline: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => { deadline = setTimeout(() => { abort.abort(); reject(new Error('Backend prediction timed out after 8 seconds.')); }, 8000); });
    try {
      const prediction = await Promise.race([motionRequest<Prediction>(`/sessions/${encodeURIComponent(s.sessionId)}/prediction`, {
        horizon_s: 60, sample_interval_s: 2, what_if_commands: previewOrder ? [{ type: 'helm_command', ...previewOrder }] : [],
      }, abort.signal), timeout]);
      if (epoch !== this.predictionEpoch || this.disposed) return;
      if (prediction.source.session_id !== this.s.sessionId || (this.s.frame?.runId && prediction.source.run_id !== this.s.frame.runId)) throw new Error('Prediction snapshot does not match the displayed run. Waiting for a fresh backend snapshot.');
      const currentTime = this.s.frame?.tS;
      if (currentTime != null && currentTime > prediction.source.t_s && currentTime >= (prediction.path.at(-1)?.t_s ?? prediction.source.t_s)) throw new Error('Prediction arrived after its horizon expired. Future coverage is unavailable until the next snapshot.');
      this.predictionFailures = 0; this.predictionRetryAt = 0;
      this.state.set({ prediction, predictionBusy: false, predictionPreviewPending: false, predictionError: null });
    } catch (e) {
      if (epoch !== this.predictionEpoch || this.disposed) return;
      // A still-current result remains visible until its authoritative horizon expires.
      this.state.set({ predictionBusy: false, predictionPreviewPending: false, predictionError: e instanceof Error ? e.message : String(e) });
      this.predictionLastKey = null;
      this.predictionRetryAt = performance.now() + Math.min(10000, 1000 * 2 ** ++this.predictionFailures);
      this.predictionQueued = this.s.open;
    } finally {
      clearTimeout(deadline);
      this.predictionInFlight = false;
      if (this.predictionQueued && !this.disposed) void this.requestPrediction(this.predictionUrgent);
    }
  }
}
