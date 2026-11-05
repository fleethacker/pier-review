import { Store } from '../../lib/store';
import type { AppHost } from '../../scene/app';
import type { SceneEdit, SceneState } from '../../scene/types';
import { awaitJob, modeling, MODELING_BASE, unwrap, wsUrl } from './api';
import { AgentSession } from './agent';
import { openJsonStream } from './streams';
import type { StreamHandle, StreamStatus } from './streams';
import {
  buildScene,
  envReadouts,
  envVectors,
  tugScene,
  IDS,
  lineLinks,
  pierEntities,
  shipEntities,
  standoffFt as resolveStandoff,
} from './mapping';
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  Berth,
  BerthSummary,
  Alert,
  Environment,
  LineSpec,
  MooringLine,
  Scenario,
  ShipClass,
  ShipClassSummary,
  SideTo,
  TugAssignment,
  TugSpec,
} from './types';
import { ft, subscribeUnits, toFt } from './units';
import type { BerthSite } from './world';

export interface Candidate {
  config: { lines: MooringLine[]; ship_x_ft: number };
  min_margin_pct_wll: number;
  limit_wind_kt_worst: number | null;
  line_count: number;
  analysis_result_id: string;
  why: string[];
}

export interface TimelineStep {
  valid_at_utc: string;
  status: 'GREEN' | 'AMBER' | 'RED';
  wind_speed_kt: number;
  wind_gust_kt: number;
  p_any_exceeds_wll: number | null;
  governing_element: string | null;
}
export interface TimelineResult {
  steps: TimelineStep[];
  first_amber_utc: string | null;
  first_red_utc: string | null;
  recommended_actions: unknown[];
}
export interface EnvelopePoint {
  wind_rel_deg: number;
  limit_wind_kt: number | null;
  first_failure_element: string | null;
  failure_mode: string;
}
export interface EnvelopeResult {
  points: EnvelopePoint[];
  worst: EnvelopePoint | null;
}
export interface ExceedanceResult {
  n_samples: number;
  p_any_exceeds_wll: number;
  p_any_exceeds_mbs: number;
  governing_element: string | null;
  elements: { element_id: string; p_exceed_wll: number; p_exceed_mbs: number; tension_p50_lbf: number; tension_p95_lbf: number }[];
}
export interface Enveloped<R> {
  result_id: string;
  backend: string;
  status: 'GREEN' | 'AMBER' | 'RED';
  computed_at_utc: string;
  assumptions?: string[];
  result: R;
}
export interface AlertItem {
  id: string;
  at: string;
  severity: 'INFO' | 'AMBER' | 'RED';
  message: string;
  reference?: string;
  elementId?: string | null;
  source: 'service' | 'analysis';
  windKt?: number;
  gustKt?: number;
}
export type EnvMode = 'manual' | 'live' | 'replay' | 'storm';
export interface WindSample {
  t: number;
  wind: number;
  gust: number;
}
export type RiskKind = 'timeline' | 'envelope' | 'exceedance';

export interface MooringState {
  phase: 'loading' | 'ready' | 'error';
  error: string | null;
  ships: ShipClassSummary[];
  berths: BerthSummary[];
  /** Where each berth is, for the world map. Filled from the berth details after startup. */
  berthSites: BerthSite[];
  lineSpecs: LineSpec[];
  tugs: TugSpec[];
  scenarios: Scenario[];
  berthId: string;
  shipClassId: string;
  loading: string;
  side: SideTo;
  shipXFt: number;
  standoffOverrideFt: number | null;
  berth: Berth | null;
  ship: ShipClass | null;
  lines: MooringLine[];
  env: Environment | null;
  analysis: { state: 'idle' | 'pending' | 'ok' | 'error'; response: AnalyzeResponse | null; error: string | null };
  recommend: { state: 'idle' | 'running' | 'error'; progress: number; candidates: Candidate[]; error: string | null };
  addLine: { active: boolean; shipFittingId: string | null; specId: string; parts: 1 | 2 | 3 };
  scenarioId: string | null;
  notice: string | null;
  backend: string | null;
  envMode: { kind: EnvMode; status: StreamStatus | 'idle'; detail: string | null };
  windHistory: WindSample[];
  alerts: AlertItem[];
  alertsStatus: StreamStatus | 'idle';
  tugAssignments: TugAssignment[];
  overlay: { kind: 'result'; id: string } | { kind: 'sheet'; id: string } | null;
  risk: {
    running: RiskKind | null;
    error: string | null;
    timeline: Enveloped<TimelineResult> | null;
    envelope: Enveloped<EnvelopeResult> | null;
    exceedance: Enveloped<ExceedanceResult> | null;
  };
}

const INITIAL: MooringState = {
  phase: 'loading',
  error: null,
  ships: [],
  berths: [],
  berthSites: [],
  lineSpecs: [],
  tugs: [],
  scenarios: [],
  berthId: '',
  shipClassId: '',
  loading: '',
  side: 'starboard',
  shipXFt: 0,
  standoffOverrideFt: null,
  berth: null,
  ship: null,
  lines: [],
  env: null,
  analysis: { state: 'idle', response: null, error: null },
  recommend: { state: 'idle', progress: 0, candidates: [], error: null },
  addLine: { active: false, shipFittingId: null, specId: '', parts: 1 },
  scenarioId: null,
  notice: null,
  backend: null,
  envMode: { kind: 'manual', status: 'idle', detail: null },
  windHistory: [],
  alerts: [],
  alertsStatus: 'idle',
  tugAssignments: [],
  overlay: null,
  risk: { running: null, error: null, timeline: null, envelope: null, exceedance: null },
};

const ANALYZE_DEBOUNCE_MS = 250;

/** Owns the mooring app's state, talks to the modeling API and keeps the shared scene in sync. */
export class MooringController {
  readonly state = new Store<MooringState>(INITIAL);
  readonly agent: AgentSession = new AgentSession(this);
  private analyzeTimer: ReturnType<typeof setTimeout> | undefined;
  private analyzeSeq = 0;
  private selectionSeq = 0;
  private analyzeAbort: AbortController | null = null;
  private recommendAbort: AbortController | null = null;
  private unsubscribeScene: () => void;
  private unsubscribeUnits: () => void;
  private disposed = false;
  private envStream: StreamHandle | null = null;
  private alertStream: StreamHandle | null = null;
  private riskSeq = 0;
  private lastAnalysisKey = '';

  constructor(readonly host: AppHost) {
    this.unsubscribeScene = host.store.subscribe(() => this.onSelectionChange());
    // Property text in the scene is formatted in the chosen units, so redraw when they change.
    this.unsubscribeUnits = subscribeUnits(() => this.pushScene('update'));
  }

  dispose(): void {
    this.disposed = true;
    clearTimeout(this.analyzeTimer);
    this.analyzeAbort?.abort();
    this.recommendAbort?.abort();
    this.envStream?.close();
    this.alertStream?.close();
    this.agent.dispose();
    this.unsubscribeScene();
    this.unsubscribeUnits();
  }

  private get s(): MooringState {
    return this.state.get();
  }

  // ---- startup -------------------------------------------------------------------------------------------

  async init(): Promise<void> {
    this.state.set({ phase: 'loading', error: null });
    try {
      const [health, ships, berths, lineSpecs, tugs] = await Promise.all([
        modeling.GET('/api/v1/health').then(unwrap),
        modeling.GET('/api/v1/ships').then(unwrap),
        modeling.GET('/api/v1/berths').then(unwrap),
        modeling.GET('/api/v1/lines').then(unwrap),
        modeling.GET('/api/v1/tugs').then(unwrap),
      ]);
      const defaultShip = ships.find((x) => x.has_fittings) ?? ships[0];
      this.state.set({
        backend: health.backend,
        ships,
        berths,
        lineSpecs,
        tugs,
        berthId: berths[0]?.berth_id ?? '',
        shipClassId: defaultShip?.class_id ?? '',
        addLine: { ...this.s.addLine, specId: lineSpecs[0]?.spec_id ?? '' },
      });
      await this.loadSelection({ recommend: true });
      void this.loadBerthSites(berths.map((b) => b.berth_id));
      this.refreshScenarioList().catch(() => undefined);
      this.startAlerts();
      this.state.set({ phase: 'ready' });
    } catch (e) {
      this.state.set({ phase: 'error', error: message(e) });
    }
  }

  /** Positions of every berth. A berth that fails to load is left off the map; it stays in the list. */
  private async loadBerthSites(ids: string[]): Promise<void> {
    const sites = await Promise.all(
      ids.map((id) =>
        modeling
          .GET('/api/v1/berths/{berth_id}', { params: { path: { berth_id: id } } })
          .then(unwrap)
          .then((b): BerthSite => ({ berthId: b.berth_id, name: b.name, lat: b.origin_lat, lon: b.origin_lon }))
          .catch(() => null),
      ),
    );
    if (!this.disposed) this.state.set({ berthSites: sites.filter((s): s is BerthSite => s !== null) });
  }

  /** Reload berth, ship and environment for the current selection, redraw everything, optionally recommend lines. */
  private async loadSelection(opts: { recommend: boolean }): Promise<void> {
    const seq = ++this.selectionSeq;
    this.resetAnalysis();
    this.state.set({ recommend: { state: 'idle', progress: 0, candidates: [], error: null }, tugAssignments: [] });
    this.recommendAbort?.abort();
    const { berthId, shipClassId } = this.s;
    const [berth, ship, env] = await Promise.all([
      modeling.GET('/api/v1/berths/{berth_id}', { params: { path: { berth_id: berthId } } }).then(unwrap),
      shipClassId
        ? modeling.GET('/api/v1/ships/{class_id}', { params: { path: { class_id: shipClassId } } }).then(unwrap)
        : Promise.resolve(null),
      this.s.env ?? this.fetchEnv(berthId),
    ]);
    if (this.disposed || seq !== this.selectionSeq) return;
    const loading = ship?.loading_conditions.find((c) => c.name === this.s.loading)?.name ?? ship?.loading_conditions[0]?.name ?? '';
    const shipXFt = this.s.shipXFt > 0 && this.s.shipXFt < berth.face_length_ft ? this.s.shipXFt : Math.round(berth.face_length_ft / 2 / 5) * 5;
    this.state.set({ berth, ship, env, loading, shipXFt, lines: [], scenarioId: null });
    this.resetAnalysis();
    this.pushScene('full');
    if (opts.recommend && ship && (ship.fittings?.length ?? 0) > 0) void this.recommend({ apply: true });
  }

  private async fetchEnv(berthId: string): Promise<Environment> {
    return unwrap(await modeling.GET('/api/v1/env/now', { params: { query: { berth_id: berthId } } }));
  }

  async refreshEnv(): Promise<void> {
    try {
      const env = await this.fetchEnv(this.s.berthId);
      this.state.set({ env });
      this.pushScene('update');
      this.scheduleAnalyze();
    } catch (e) {
      this.state.set({ notice: `Could not refresh environment: ${message(e)}` });
    }
  }

  // ---- setup actions ---------------------------------------------------------------------------------------

  async setBerth(berthId: string): Promise<void> {
    await this.setEnvMode('manual');
    this.alertStream?.close();
    this.state.set({ berthId, env: null });
    await this.guarded(() => this.loadSelection({ recommend: true }));
    await this.setEnvMode('manual');
    this.startAlerts();
  }

  async setShip(shipClassId: string): Promise<void> {
    this.state.set({ shipClassId, loading: '' });
    await this.guarded(() => this.loadSelection({ recommend: true }));
  }

  async setSide(side: SideTo): Promise<void> {
    this.state.set({ side, tugAssignments: [], recommend: { state: 'idle', progress: 0, candidates: [], error: null } });
    await this.guarded(async () => {
      this.state.set({ lines: [], scenarioId: null });
      this.resetAnalysis();
      this.pushScene('full');
      if (this.s.ship && (this.s.ship.fittings?.length ?? 0) > 0) void this.recommend({ apply: true });
    });
  }

  setLoading(loading: string): void {
    this.state.set({ loading });
    this.pushScene('update');
    this.scheduleAnalyze();
  }

  setShipX(shipXFt: number): void {
    const berth = this.s.berth;
    if (!berth) return;
    const clamped = Math.min(Math.max(shipXFt, 0), berth.face_length_ft);
    this.state.set({ shipXFt: clamped });
    this.pushScene('update');
    this.scheduleAnalyze();
  }

  setStandoff(value: number | null): void {
    this.state.set({ standoffOverrideFt: value });
    this.pushScene('update');
    this.scheduleAnalyze();
  }

  setEnv(patch: Partial<Environment>): void {
    if (!this.s.env) return;
    if (this.s.envMode.kind !== 'manual') void this.setEnvMode('manual');
    this.state.set({ env: { ...this.s.env, ...patch } });
    this.pushScene('update');
    this.scheduleAnalyze();
  }

  private async guarded(fn: () => Promise<void>): Promise<void> {
    try {
      await fn();
    } catch (e) {
      if (!this.disposed) this.state.set({ notice: message(e) });
    }
  }

  // ---- line editing ----------------------------------------------------------------------------------------

  startAddLine(): void {
    this.host.store.select(null);
    this.state.set({ addLine: { ...this.s.addLine, active: true, shipFittingId: null } });
  }

  cancelAddLine(): void {
    this.state.set({ addLine: { ...this.s.addLine, active: false, shipFittingId: null } });
  }

  setNewLineSpec(specId: string, parts: 1 | 2 | 3): void {
    this.state.set({ addLine: { ...this.s.addLine, specId, parts } });
  }

  private lastSelectionKey: string | null = null;

  /** The scene store notifies on every change; only act when the selection itself changed. */
  private onSelectionChange(): void {
    const sel = this.host.store.getState().selection;
    const key = sel ? `${sel.type}:${sel.id}` : null;
    if (key === this.lastSelectionKey) return;
    this.lastSelectionKey = key;
    const al = this.s.addLine;
    if (!al.active || sel?.type !== 'entity') return;
    if (sel.id.startsWith('sfit:')) {
      this.state.set({ addLine: { ...al, shipFittingId: sel.id.slice(5) } });
    } else if (sel.id.startsWith('pier:') && al.shipFittingId) {
      const shipFittingId = al.shipFittingId;
      this.state.set({ addLine: { ...al, shipFittingId: null } });
      this.addLine(shipFittingId, sel.id.slice(5));
      // Deselect so the same pier fitting can be picked again for the next line.
      this.host.store.select(null);
    }
  }

  addLine(shipFittingId: string, pierFittingId: string): void {
    const { lines, addLine } = this.s;
    const next = lines.length === 0 ? 1 : Math.max(...lines.map((l) => l.line_number)) + 1;
    const line: MooringLine = {
      line_number: next,
      spec_id: addLine.specId || this.s.lineSpecs[0]?.spec_id || '',
      parts: addLine.parts,
      ship_fitting_id: shipFittingId,
      pier_fitting_id: pierFittingId,
    };
    this.setLines([...lines, line]);
  }

  removeLine(lineNumber: number): void {
    this.setLines(this.s.lines.filter((l) => l.line_number !== lineNumber));
    const sel = this.host.store.getState().selection;
    if (sel?.id === IDS.line(lineNumber)) this.host.store.select(null);
  }

  updateLine(lineNumber: number, patch: Partial<MooringLine>): void {
    this.setLines(this.s.lines.map((l) => (l.line_number === lineNumber ? { ...l, ...patch } : l)));
  }

  /** Double up or single up every line at once, keeping each line's rope and fittings. */
  setAllParts(parts: 1 | 2 | 3): void {
    if (this.s.lines.length === 0) return;
    this.setLines(this.s.lines.map((l) => ({ ...l, parts })));
  }

  private setLines(lines: MooringLine[]): void {
    this.state.set({ lines, scenarioId: null });
    this.pushScene('update');
    this.scheduleAnalyze();
  }

  // ---- canvas edits ----------------------------------------------------------------------------------------

  onEdit(edit: SceneEdit): void {
    if (edit.type !== 'move' || edit.entityId !== IDS.ship) return;
    this.state.set({ shipXFt: Math.round(toFt(edit.pose.x)) });
    this.pushScene('ship');
    if (edit.final) this.scheduleAnalyze();
  }

  // ---- analysis --------------------------------------------------------------------------------------------

  private resetAnalysis(): void {
    ++this.analyzeSeq;
    ++this.riskSeq;
    this.state.set({ risk: { running: null, error: null, timeline: null, envelope: null, exceedance: null } });
    clearTimeout(this.analyzeTimer);
    this.analyzeAbort?.abort();
    this.state.set({ analysis: { state: 'idle', response: null, error: null } });
  }

  private scheduleAnalyze(): void {
    this.resetAnalysis();
    const { lines } = this.s;
    if (lines.length === 0) {
      this.resetAnalysis();
      this.pushScene('update');
      return;
    }
    this.state.set({ analysis: { state: 'pending', response: null, error: null } });
    this.analyzeTimer = setTimeout(() => void this.analyze(), ANALYZE_DEBOUNCE_MS);
  }

  buildAnalyzeRequest(): AnalyzeRequest | null {
    const { berth, ship, env, lines, side, shipXFt, loading, standoffOverrideFt } = this.s;
    if (!berth || !ship || !env || lines.length === 0) return null;
    return {
      ship_class_id: ship.class_id,
      loading,
      berth_id: berth.berth_id,
      config: {
        side_to: side,
        ship_x_ft: shipXFt,
        ...(standoffOverrideFt != null ? { standoff_ft: standoffOverrideFt } : {}),
        lines,
      },
      environment: env,
      ...(this.s.tugAssignments.length ? { tugs: this.s.tugAssignments } : {}),
      mst: ship.mst_class as AnalyzeRequest['mst'],
      lines_wet: true,
    };
  }

  private async analyze(): Promise<void> {
    const body = this.buildAnalyzeRequest();
    if (!body) return;
    const seq = ++this.analyzeSeq;
    this.analyzeAbort?.abort();
    const abort = (this.analyzeAbort = new AbortController());
    try {
      const response = unwrap(await modeling.POST('/api/v1/mooring/analyze', { body, signal: abort.signal }));
      if (seq !== this.analyzeSeq || this.disposed) return;
      this.state.set({ analysis: { state: 'ok', response, error: null } });
      this.pushScene('update');
      this.recordAnalysisAlerts(response);
    } catch (e) {
      if (abort.signal.aborted || seq !== this.analyzeSeq || this.disposed) return;
      this.state.set({ analysis: { state: 'error', response: null, error: message(e) } });
    }
  }

  // ---- recommend -------------------------------------------------------------------------------------------

  async recommend(opts: { apply: boolean }): Promise<void> {
    const { ship, berth, side, shipXFt, loading } = this.s;
    if (!ship || !berth) return;
    this.recommendAbort?.abort();
    const abort = (this.recommendAbort = new AbortController());
    const context = this.contextKey();
    this.state.set({ recommend: { state: 'running', progress: 0, candidates: [], error: null } });
    try {
      const accepted = unwrap(
        await modeling.POST('/api/v1/mooring/recommend', {
          body: {
            ship_class_id: ship.class_id,
            loading,
            berth_id: berth.berth_id,
            side_to: side,
            ship_x_ft: shipXFt,
            design_mst: ship.mst_class as 'I' | 'II' | 'IIA' | 'III',
            max_candidates: 3,
            max_evaluations: 1500,
            neighbors_per_line: 3,
          },
          signal: abort.signal,
        }),
      );
      const envelope = await awaitJob<{ result: { candidates: Candidate[] } }>(
        MODELING_BASE,
        accepted as never,
        (progress) => this.state.set({ recommend: { ...this.s.recommend, progress } }),
        abort.signal,
      );
      if (this.disposed || abort.signal.aborted || this.recommendAbort !== abort) return;
      if (context !== this.contextKey()) {
        this.state.set({ recommend: { state: 'idle', progress: 0, candidates: [], error: null } });
        return;
      }
      const candidates = [...envelope.result.candidates].sort((a, b) => a.min_margin_pct_wll - b.min_margin_pct_wll);
      this.state.set({ recommend: { state: 'idle', progress: 1, candidates, error: null } });
      if (opts.apply && candidates[0]) this.applyCandidate(candidates[0]);
    } catch (e) {
      if (abort.signal.aborted || this.disposed) return;
      this.state.set({ recommend: { state: 'error', progress: 0, candidates: [], error: message(e) } });
    }
  }

  /** Identity and geometry that make a generated plan applicable. */
  contextKey(): string {
    const s = this.s;
    return JSON.stringify([s.berthId, s.shipClassId, s.loading, s.side, s.shipXFt, s.standoffOverrideFt]);
  }

  applyCandidate(candidate: Candidate): void {
    this.setLines(candidate.config.lines.map((l) => ({ ...l })));
  }

  // ---- scenarios -------------------------------------------------------------------------------------------

  async refreshScenarioList(): Promise<void> {
    const scenarios = unwrap(await modeling.GET('/api/v1/scenarios'));
    this.state.set({ scenarios });
  }

  async saveScenario(name: string): Promise<string | null> {
    const { ship, berth, side, shipXFt, lines, loading, standoffOverrideFt } = this.s;
    if (!ship || !berth || !this.s.env) return null;
    const env = this.s.env;
    const snapshot = unwrap(await modeling.POST('/api/v1/env/scenarios', { body: {
      name: `${name} environment snapshot`, kind: 'steady', replay_source: 'synthetic',
      wind_speed_kt: env.wind_speed_kt, wind_gust_kt: env.wind_gust_kt,
      wind_from_true_deg: env.wind_from_true_deg, current_speed_kt: env.current_speed_kt,
      current_set_true_deg: env.current_set_true_deg, water_level_mllw_ft: env.water_level_mllw_ft,
    } }));
    const saved = unwrap(
      await modeling.POST('/api/v1/scenarios', {
        body: {
          name,
          ship_class_id: ship.class_id,
          loading,
          berth_id: berth.berth_id,
          side_to: side,
          env_source: { mode: 'scenario', env_scenario_id: snapshot.env_scenario_id, replay_speed: 1 },
          tugs: this.s.tugAssignments,
          config: {
            side_to: side,
            ship_x_ft: shipXFt,
            ...(standoffOverrideFt != null ? { standoff_ft: standoffOverrideFt } : {}),
            lines,
          },
        },
      }),
    );
    this.state.set({ scenarioId: saved.scenario_id, notice: `Saved scenario “${saved.name}”` });
    await this.refreshScenarioList();
    return saved.scenario_id;
  }

  async loadScenario(id: string): Promise<void> {
    await this.guarded(async () => {
      const sc = unwrap(await modeling.GET('/api/v1/scenarios/{scenario_id}', { params: { path: { scenario_id: id } } }));
      await this.setEnvMode('manual');
      const env = unwrap(await modeling.GET('/api/v1/scenarios/{scenario_id}/environment', { params: { path: { scenario_id: id } } }));
      this.state.set({
        berthId: sc.berth_id,
        shipClassId: sc.ship_class_id,
        loading: sc.loading,
        side: sc.side_to,
        shipXFt: sc.config?.ship_x_ft ?? 0,
        standoffOverrideFt: sc.config?.standoff_ft ?? null,
        env,
        tugAssignments: sc.tugs ?? [],
      });
      await this.loadSelection({ recommend: false });
      this.state.set({ lines: sc.config?.lines ?? [], tugAssignments: sc.tugs ?? [], scenarioId: sc.scenario_id });
      this.pushScene('update');
      this.scheduleAnalyze();
    });
  }

  // ---- live environment and alerts -------------------------------------------------------------------------

  async setEnvMode(
    kind: EnvMode,
    opts: { replayStartUtc?: string; speed?: number; rampToKt?: number; rampMinutes?: number } = {},
  ): Promise<void> {
    this.envStream?.close();
    this.envStream = null;
    if (kind === 'manual') {
      this.state.set({ envMode: { kind, status: 'idle', detail: null } });
      return;
    }
    const query: Record<string, string | number | undefined> = { berth_id: this.s.berthId };
    try {
      if (kind === 'live') {
        Object.assign(query, { mode: 'live', interval_s: 3 });
      } else if (kind === 'replay') {
        Object.assign(query, {
          mode: 'replay',
          replay_start_utc: opts.replayStartUtc,
          speed: opts.speed ?? 3600,
          interval_s: 1,
        });
      } else {
        const base = this.s.env;
        const wind = base?.wind_speed_kt ?? 10;
        const created = unwrap(
          await modeling.POST('/api/v1/env/scenarios', {
            body: {
              name: 'Storm ramp (from UI)',
              kind: 'ramp',
              replay_source: 'synthetic',
              wind_speed_kt: wind,
              wind_gust_kt: base?.wind_gust_kt ?? wind * 1.4,
              wind_from_true_deg: base?.wind_from_true_deg ?? 200,
              current_speed_kt: base?.current_speed_kt ?? 0.5,
              current_set_true_deg: base?.current_set_true_deg ?? 10,
              water_level_mllw_ft: base?.water_level_mllw_ft ?? 0,
              ramp_to_wind_kt: opts.rampToKt ?? 50,
              ramp_minutes: opts.rampMinutes ?? 3,
            },
          }),
        );
        Object.assign(query, { mode: 'scenario', env_scenario_id: created.env_scenario_id, interval_s: 2 });
      }
    } catch (e) {
      this.state.set({ notice: `Could not start the ${kind} environment: ${message(e)}` });
      return;
    }
    this.state.set({ windHistory: [], envMode: { kind, status: 'connecting', detail: null } });
    this.envStream = openJsonStream<Partial<Environment>>(
      wsUrl(MODELING_BASE, '/ws/env', query),
      (m) => this.onEnvMessage(m),
      (status) => this.state.set({ envMode: { ...this.s.envMode, kind, status } }),
    );
  }

  private onEnvMessage(m: Partial<Environment>): void {
    if (this.disposed || !this.s.env) return;
    const env = { ...this.s.env, ...m } as Environment;
    const sample: WindSample = { t: Date.now(), wind: env.wind_speed_kt, gust: env.wind_gust_kt };
    this.state.set({ env, windHistory: [...this.s.windHistory, sample].slice(-120) });
    this.pushScene('update');
    this.scheduleAnalyze();
  }

  startAlerts(): void {
    this.alertStream?.close();
    this.state.set({ alerts: [], alertsStatus: 'connecting' });
    this.alertStream = openJsonStream<Alert>(
      wsUrl(MODELING_BASE, '/ws/alerts', { berth_id: this.s.berthId, interval_s: 5 }),
      (a) => this.pushAlert({
        id: a.alert_id,
        at: a.at_utc,
        severity: a.severity,
        message: a.message,
        elementId: a.element_id,
        source: 'service',
        windKt: a.env.wind_speed_kt,
        gustKt: a.env.wind_gust_kt,
      }),
      (status) => this.state.set({ alertsStatus: status }),
    );
  }

  private pushAlert(item: AlertItem): void {
    const prev = this.s.alerts[0];
    // The service repeats the same message every tick; show it once until it changes.
    if (prev && prev.source === item.source && prev.message === item.message && prev.severity === item.severity) return;
    this.state.set({ alerts: [item, ...this.s.alerts].slice(0, 60) });
  }

  /** Turn non-green analysis findings into warnings in the feed, once per distinct situation. */
  private recordAnalysisAlerts(res: AnalyzeResponse): void {
    const findings = [...(res.warnings ?? []), ...res.result.findings].filter((f) => f.severity !== 'INFO');
    const key = `${res.status}|${findings.map((f) => f.rule_id + f.element_ids?.join('+')).join(',')}`;
    if (key === this.lastAnalysisKey) return;
    this.lastAnalysisKey = key;
    const env = this.s.env;
    const unique = findings.filter((f, i) => findings.findIndex((g) => g.message === f.message) === i);
    for (const [i, f] of unique.slice(0, 3).entries()) {
      this.pushAlert({
        id: `${res.result_id}-${i}`,
        at: res.computed_at_utc,
        severity: f.severity,
        message: f.message,
        reference: f.reference,
        elementId: f.element_ids?.[0] ?? null,
        source: 'analysis',
        windKt: env?.wind_speed_kt,
        gustKt: env?.wind_gust_kt,
      });
    }
  }

  // ---- risk, envelope, exceedance --------------------------------------------------------------------------

  async runRisk(kind: RiskKind): Promise<void> {
    const base = this.buildAnalyzeRequest();
    if (!base) {
      this.state.set({ risk: { ...this.s.risk, error: 'Add at least one line first.' } });
      return;
    }
    const seq = ++this.riskSeq;
    this.state.set({ risk: { ...this.s.risk, running: kind, error: null } });
    try {
      if (kind === 'timeline') {
        const out = await this.callMaybeJob<Enveloped<TimelineResult>>(
          modeling.POST('/api/v1/risk/timeline', { body: { ...base, forecast_hours: 24, step_min: 60, n_samples_per_step: 50 } }),
        );
        if (seq !== this.riskSeq || this.disposed) return;
        this.state.set({ risk: { ...this.s.risk, running: null, timeline: out } });
      } else if (kind === 'envelope') {
        const out = await this.callMaybeJob<Enveloped<EnvelopeResult>>(
          modeling.POST('/api/v1/mooring/envelope', { body: { ...base, step_deg: 15, max_search_kt: 100, sampling_step_kt: 5, tolerance_kt: 0.25 } }),
        );
        if (seq !== this.riskSeq || this.disposed) return;
        this.state.set({ risk: { ...this.s.risk, running: null, envelope: out } });
      } else {
        const out = await this.callMaybeJob<Enveloped<ExceedanceResult>>(
          modeling.POST('/api/v1/risk/exceedance', {
            body: { ...base, horizon_hours: 6, n_samples: 200, seed: 42, gust_dynamic_factor: 1.3, include_horizon: false, n_trajectories: 200, horizon_step_min: 30 },
          }),
        );
        if (seq !== this.riskSeq || this.disposed) return;
        this.state.set({ risk: { ...this.s.risk, running: null, exceedance: out } });
      }
    } catch (e) {
      if (seq !== this.riskSeq || this.disposed) return;
      this.state.set({ risk: { ...this.s.risk, running: null, error: message(e) } });
    }
  }

  /** Compute endpoints answer directly, or with a 202 job for slow runs; accept either. */
  private async callMaybeJob<T>(request: Promise<{ data?: unknown; error?: unknown; response: Response }>): Promise<T> {
    const data = unwrap(await request) as unknown as T & { job_id?: string };
    if (data && typeof data === 'object' && 'job_id' in data && data.job_id) {
      return awaitJob<T>(MODELING_BASE, data as never);
    }
    return data;
  }

  setTugAssignments(tugAssignments: TugAssignment[]): void {
    this.state.set({ tugAssignments });
    this.pushScene('update');
    this.scheduleAnalyze();
  }

  /** Replace the lines wholesale (agent plans) and re-analyze. */
  replaceLines(lines: MooringLine[]): void {
    this.setLines(lines);
  }

  openOverlay(overlay: MooringState['overlay']): void {
    this.state.set({ overlay });
  }

  // ---- scene sync ------------------------------------------------------------------------------------------

  /**
   * full: replace the whole scene (new berth, ship or side). update: redraw entities, links and arrows without
   * resetting the camera or selection. ship: cheap redraw while dragging.
   */
  pushScene(mode: 'full' | 'update' | 'ship'): void {
    const s = this.s;
    if (!s.berth) return;
    const store = this.host.store;
    const standoff = resolveStandoff(s.berth, s.standoffOverrideFt);
    const analysis = s.analysis.response;
    if (mode === 'full') {
      store.setContent(
        buildScene({
          berth: s.berth,
          ship: s.ship,
          loading: s.loading,
          side: s.side,
          shipXFt: s.shipXFt,
          standoffFt: standoff,
          lines: s.lines,
          analysis,
          env: s.env,
          tugs: s.tugAssignments,
        }),
      );
      return;
    }
    const frame = store.getState().frame;
    if (!frame || !s.ship) return;
    const hasFittings = (s.ship.fittings?.length ?? 0) > 0;
    const ship = shipEntities(s.ship, s.loading, s.side, s.shipXFt, standoff, analysis, hasFittings, s.berth);
    // Keep the drag in progress: the shell already owns the hull pose while the pointer is down.
    store.upsertEntities(mode === 'ship' ? ship : [...pierEntities(s.berth, analysis), ...ship]);
    const tugs = tugScene(s.ship, s.side, s.shipXFt, standoff, s.tugAssignments, frame);
    const center = { x: ft(s.shipXFt), y: ft(s.ship.beam_ft + standoff + 120) };
    store.replaceEntitiesOfKind(['tug', 'wake', 'readout'], [...tugs.entities, ...envReadouts(s.env, center)]);
    store.setLinks(lineLinks(s.berth, s.ship, s.lines, analysis));
    store.setVectors([
      ...envVectors(frame, s.env, center),
      ...tugs.vectors,
    ]);
  }
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export type { SceneState };
