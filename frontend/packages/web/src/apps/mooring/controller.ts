import { Store } from '../../lib/store';
import type { AppHost } from '../../scene/app';
import type { SceneEdit, SceneState } from '../../scene/types';
import { awaitJob, modeling, MODELING_BASE, unwrap } from './api';
import {
  buildScene,
  envVectors,
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
  Environment,
  LineSpec,
  MooringLine,
  Scenario,
  ShipClass,
  ShipClassSummary,
  SideTo,
  TugSpec,
} from './types';
import { ft, toFt } from './units';

export interface Candidate {
  config: { lines: MooringLine[]; ship_x_ft: number };
  min_margin_pct_wll: number;
  limit_wind_kt_worst: number;
  line_count: number;
  analysis_result_id: string;
  why: string[];
}

export interface MooringState {
  phase: 'loading' | 'ready' | 'error';
  error: string | null;
  ships: ShipClassSummary[];
  berths: BerthSummary[];
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
}

const INITIAL: MooringState = {
  phase: 'loading',
  error: null,
  ships: [],
  berths: [],
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
};

const ANALYZE_DEBOUNCE_MS = 250;

/** Owns the mooring app's state, talks to the modeling API and keeps the shared scene in sync. */
export class MooringController {
  readonly state = new Store<MooringState>(INITIAL);
  private analyzeTimer: ReturnType<typeof setTimeout> | undefined;
  private analyzeSeq = 0;
  private analyzeAbort: AbortController | null = null;
  private recommendAbort: AbortController | null = null;
  private unsubscribeScene: () => void;
  private disposed = false;

  constructor(readonly host: AppHost) {
    this.unsubscribeScene = host.store.subscribe(() => this.onSelectionChange());
  }

  dispose(): void {
    this.disposed = true;
    clearTimeout(this.analyzeTimer);
    this.analyzeAbort?.abort();
    this.recommendAbort?.abort();
    this.unsubscribeScene();
  }

  private get s(): MooringState {
    return this.state.get();
  }

  // ---- startup -------------------------------------------------------------------------------------------

  async init(): Promise<void> {
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
      this.refreshScenarioList().catch(() => undefined);
      this.state.set({ phase: 'ready' });
    } catch (e) {
      this.state.set({ phase: 'error', error: message(e) });
    }
  }

  /** Reload berth, ship and environment for the current selection, redraw everything, optionally recommend lines. */
  private async loadSelection(opts: { recommend: boolean }): Promise<void> {
    const { berthId, shipClassId } = this.s;
    const [berth, ship, env] = await Promise.all([
      modeling.GET('/api/v1/berths/{berth_id}', { params: { path: { berth_id: berthId } } }).then(unwrap),
      shipClassId
        ? modeling.GET('/api/v1/ships/{class_id}', { params: { path: { class_id: shipClassId } } }).then(unwrap)
        : Promise.resolve(null),
      this.s.env ?? this.fetchEnv(berthId),
    ]);
    if (this.disposed) return;
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
    this.state.set({ berthId, env: null });
    await this.guarded(() => this.loadSelection({ recommend: true }));
  }

  async setShip(shipClassId: string): Promise<void> {
    this.state.set({ shipClassId, loading: '' });
    await this.guarded(() => this.loadSelection({ recommend: true }));
  }

  async setSide(side: SideTo): Promise<void> {
    this.state.set({ side });
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
    clearTimeout(this.analyzeTimer);
    this.analyzeAbort?.abort();
    this.state.set({ analysis: { state: 'idle', response: null, error: null } });
  }

  private scheduleAnalyze(): void {
    clearTimeout(this.analyzeTimer);
    const { lines, analysis } = this.s;
    if (lines.length === 0) {
      this.resetAnalysis();
      this.pushScene('update');
      return;
    }
    this.state.set({ analysis: { ...analysis, state: 'pending' } });
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
    } catch (e) {
      if (abort.signal.aborted || seq !== this.analyzeSeq || this.disposed) return;
      this.state.set({ analysis: { state: 'error', response: this.s.analysis.response, error: message(e) } });
    }
  }

  // ---- recommend -------------------------------------------------------------------------------------------

  async recommend(opts: { apply: boolean }): Promise<void> {
    const { ship, berth, side, shipXFt, loading } = this.s;
    if (!ship || !berth) return;
    this.recommendAbort?.abort();
    const abort = (this.recommendAbort = new AbortController());
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
      if (this.disposed) return;
      const candidates = [...envelope.result.candidates].sort((a, b) => a.min_margin_pct_wll - b.min_margin_pct_wll);
      this.state.set({ recommend: { state: 'idle', progress: 1, candidates, error: null } });
      if (opts.apply && candidates[0]) this.applyCandidate(candidates[0]);
    } catch (e) {
      if (abort.signal.aborted || this.disposed) return;
      this.state.set({ recommend: { state: 'error', progress: 0, candidates: [], error: message(e) } });
    }
  }

  applyCandidate(candidate: Candidate): void {
    this.setLines(candidate.config.lines.map((l) => ({ ...l })));
  }

  // ---- scenarios -------------------------------------------------------------------------------------------

  async refreshScenarioList(): Promise<void> {
    const scenarios = unwrap(await modeling.GET('/api/v1/scenarios'));
    this.state.set({ scenarios });
  }

  async saveScenario(name: string): Promise<void> {
    const { ship, berth, side, shipXFt, lines, loading, standoffOverrideFt } = this.s;
    if (!ship || !berth) return;
    const saved = unwrap(
      await modeling.POST('/api/v1/scenarios', {
        body: {
          name,
          ship_class_id: ship.class_id,
          loading,
          berth_id: berth.berth_id,
          side_to: side,
          env_source: { mode: 'mock', replay_speed: 1 },
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
  }

  async loadScenario(id: string): Promise<void> {
    await this.guarded(async () => {
      const sc = unwrap(await modeling.GET('/api/v1/scenarios/{scenario_id}', { params: { path: { scenario_id: id } } }));
      this.state.set({
        berthId: sc.berth_id,
        shipClassId: sc.ship_class_id,
        loading: sc.loading,
        side: sc.side_to,
        shipXFt: sc.config?.ship_x_ft ?? 0,
        standoffOverrideFt: sc.config?.standoff_ft ?? null,
        env: null,
      });
      await this.loadSelection({ recommend: false });
      this.state.set({ lines: sc.config?.lines ?? [], scenarioId: sc.scenario_id });
      this.pushScene('update');
      this.scheduleAnalyze();
    });
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
    store.setLinks(lineLinks(s.berth, s.ship, s.lines, analysis));
    if (mode === 'update') {
      store.setVectors(envVectors(frame, s.env, { x: ft(s.shipXFt), y: ft(s.ship.beam_ft + standoff + 120) }));
    }
  }
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export type { SceneState };
