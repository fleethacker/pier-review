import { Store } from '../../../lib/store';
import { awaitJob, describeError, modeling, MODELING_BASE, unwrap } from '../api';
import type { MooringController } from '../controller';
import type { Environment } from '../types';
import {
  DEFAULT_TRAINING,
  MAX_FORECAST_GAP_MIN,
  publicRequest,
  sameAcquisition,
  seriesProblems,
  type PublicSeriesInputs,
  defaultInputs,
  inputProblems,
  type AdvanceInputs,
  type BoundSeries,
  type ForecastPlanRequest,
  type ForecastPlanResponse,
  type RecheckResponse,
  type TrainingSeriesInputs,
} from './logic';

export interface AdvanceState {
  inputs: AdvanceInputs;
  training: TrainingSeriesInputs;
  publicInputs: PublicSeriesInputs;
  seriesMode: 'training' | 'public';
  series: BoundSeries | null;
  seriesState: 'idle' | 'loading' | 'error';
  seriesError: string | null;
  phase: 'idle' | 'running' | 'done' | 'error';
  progress: number;
  error: string | null;
  response: ForecastPlanResponse | null;
  /** Why the shown result no longer matches the inputs, or null while it does. */
  recheckReason: string | null;
  recheck: { state: 'idle' | 'running' | 'done' | 'error'; error: string | null; response: RecheckResponse | null };
  /** Set after `selected_config` is put on the layout. */
  applied: { arrivalUtc: string | null; installedAtFt: number | null } | null;
}

const initial = (now: number): AdvanceState => ({
  inputs: defaultInputs(now),
  training: DEFAULT_TRAINING,
  publicInputs: { currentDepthFt: null, currentBin: '' },
  seriesMode: 'training',
  series: null,
  seriesState: 'idle',
  seriesError: null,
  phase: 'idle',
  progress: 0,
  error: null,
  response: null,
  recheckReason: null,
  recheck: { state: 'idle', error: null, response: null },
  applied: null,
});

/**
 * Advance arrival planning (>= 24 h ahead) against a bound forecast series. The result is tied to the layout,
 * inputs and series revision it was computed for; any change marks it "recheck required" instead of silently reusing it.
 */
export class AdvanceSession {
  readonly state: Store<AdvanceState>;
  private request = 0;
  private seriesRequest = 0;
  private recheckRequest = 0;
  private recheckContext: string | null = null;
  private seriesContext: string | null = null;
  private disposed = false;
  /** Layout, inputs and series the shown result was computed for. */
  private resultKey: string | null = null;
  private unsubscribe: () => void;

  constructor(private readonly parent: MooringController, now: () => number = Date.now) {
    this.state = new Store<AdvanceState>(initial(now()));
    this.unsubscribe = parent.state.subscribe(() => this.checkStale());
  }

  private get s(): AdvanceState {
    return this.state.get();
  }

  dispose(): void {
    this.disposed = true;
    this.request++;
    this.seriesRequest++;
    this.unsubscribe();
  }

  private key(): string {
    const bound = this.s.series;
    return JSON.stringify([this.parent.scenarioKey(), this.s.inputs, bound ?
      [bound.sourceId, bound.revision, bound.series, bound.manifest, bound.resolved?.result.forecast_manifest] : null]);
  }

  private checkStale(): void {
    if (this.s.recheck.state === 'running' && this.recheckContext !== this.key()) {
      this.recheckRequest++;
      this.state.set({ recheck: { state: 'idle', error: null, response: null } });
    }
    if (this.s.seriesState === 'loading' && this.seriesContext !== this.sourceKey()) {
      this.seriesRequest++;
      this.recheckRequest++;
      this.state.set({ series: null, seriesState: 'idle', seriesError: 'Inputs changed while the series was loading. Fetch or generate again.',
        recheck: { state: 'idle', error: null, response: null } });
    }
    const publicBody = this.publicBody();
    if (this.s.seriesMode === 'public' && ((this.s.seriesState === 'loading' && this.seriesContext !== this.sourceKey()) ||
      (this.s.series?.manifest && (!publicBody || !sameAcquisition(this.s.series.manifest.request, publicBody))))) {
      this.seriesRequest++;
      this.recheckRequest++;
      this.state.set({ series: null, seriesState: 'idle', seriesError: 'Source, berth or forecast window changed. Fetch a new public forecast.',
        recheck: { state: 'idle', error: null, response: null } });
    }
    if (this.resultKey === null || !this.s.response || this.s.recheckReason) return;
    if (this.resultKey !== this.key()) {
      this.state.set({ recheckReason: 'Inputs changed since this assessment (layout, environment, times or forecast series). Recheck before using it.' });
    }
  }

  setInputs(patch: Partial<AdvanceInputs>): void {
    this.parent.setForecastSelection(null);
    this.recheckRequest++;
    this.state.set({ inputs: { ...this.s.inputs, ...patch }, recheck: { state: 'idle', error: null, response: null } });
    this.checkStale();
  }

  setTraining(patch: Partial<TrainingSeriesInputs>): void {
    this.parent.setForecastSelection(null);
    this.state.set({ training: { ...this.s.training, ...patch } });
    this.checkStale();
  }

  setPublicInputs(patch: Partial<PublicSeriesInputs>): void {
    this.parent.setForecastSelection(null);
    this.state.set({ publicInputs: { ...this.s.publicInputs, ...patch } });
    this.checkStale();
  }

  publicBody() {
    const c = this.parent.state.get();
    const id = c.berthId || c.berth?.berth_id || '';
    if (c.berth?.berth_id !== id) return null;
    return publicRequest(id, this.s.inputs, this.s.publicInputs);
  }

  private sourceKey(): string {
    const c = this.parent.state.get();
    return JSON.stringify([c.berthId || c.berth?.berth_id, this.s.seriesMode,
      this.s.seriesMode === 'public' ? this.publicBody() : [this.s.inputs.asOfUtc, this.s.training, c.env]]);
  }

  /** Explicit public acquisition; unavailable components remain visible and are never replaced with training data. */
  async fetchPublicSeries(): Promise<void> {
    this.parent.setForecastSelection(null);
    const body = this.publicBody();
    const request = ++this.seriesRequest;
    this.recheckRequest++;
    this.state.set({ seriesMode: 'public', series: null, seriesState: body ? 'loading' : 'error',
      seriesError: body ? null : 'Choose a valid arrival window and enter the exact current depth and station bin.',
      recheck: { state: 'idle', error: null, response: null } });
    this.seriesContext = this.sourceKey();
    this.checkStale();
    if (!body) return;
    const context = this.seriesContext;
    const current = () => !this.disposed && request === this.seriesRequest && context === this.sourceKey();
    try {
      const composed = structuredClone(unwrap(await modeling.POST('/api/v1/env/forecast/compose', { body })));
      if (!current()) return;
      if (!sameAcquisition(composed.manifest.request, body)) throw new Error('Returned forecast does not match the requested public source, berth, current layer or time window.');
      const bound: BoundSeries = {
        kind: 'public', berthId: body.berth_id, label: `Public forecast · ${composed.manifest.status} · unqualified planning inputs`,
        sourceId: `public:${body.berth_id}:depth=${body.current_depth_ft}:bin=${body.current_bin}`,
        revision: composed.manifest.revision, manifest: composed.manifest,
        series: composed.snapshots ?? [], stepMin: body.step_min,
      };
      this.state.set({ series: bound });
      if (bound.series.length >= 2) {
        const resolved = structuredClone(unwrap(await modeling.POST('/api/v1/mooring/forecast/resolve', { body: {
          berth_id: body.berth_id, as_of_utc: body.as_of_utc, from_utc: body.horizon_start_utc, to_utc: body.horizon_end_utc,
          max_gap_min: MAX_FORECAST_GAP_MIN, forecast: bound.series,
          forecast_binding: { source: 'supplied', source_id: bound.sourceId, revision: bound.revision },
        } })));
        if (!current()) return;
        const manifest = resolved.result.forecast_manifest;
        if (resolved.result.berth_id !== body.berth_id || manifest.source_id !== bound.sourceId || manifest.revision !== bound.revision ||
          Date.parse(manifest.as_of_utc) !== Date.parse(body.as_of_utc) || Date.parse(manifest.from_utc) !== Date.parse(body.horizon_start_utc) ||
          Date.parse(manifest.to_utc) !== Date.parse(body.horizon_end_utc)) throw new Error('Resolved forecast binding does not match the acquisition request.');
        this.state.set({ series: { ...bound, series: resolved.result.series, resolved } });
      }
      this.state.set({ seriesState: 'idle' });
      this.checkStale();
    } catch (e) {
      if (current()) this.state.set({ seriesState: 'error', seriesError: describeError(e) });
    }
  }

  latestRetrievalCutoff(): string | null {
    const times = (this.s.series?.manifest?.components ?? []).map((component) => component.availability.retrieved_at_utc)
      .filter((value): value is string => !!value && Number.isFinite(Date.parse(value)));
    if (!times.length) return null;
    const latest = times.reduce((a, b) => Date.parse(a) > Date.parse(b) ? a : b);
    return Date.parse(latest) > Date.parse(this.s.inputs.asOfUtc) ? latest : null;
  }

  /** Explicit user action only: keep arrival/horizon/depth/bin unchanged, reuse provider cache at its retrieval cutoff. */
  async retryAtRetrievalCutoff(): Promise<void> {
    const cutoff = this.latestRetrievalCutoff();
    if (!cutoff) return;
    this.setInputs({ asOfUtc: cutoff });
    await this.fetchPublicSeries();
  }

  /** Seeded synthetic conditions from the current environment, starting at the as-of time. Labeled training data. */
  async generateTrainingSeries(): Promise<void> {
    this.parent.setForecastSelection(null);
    const { berth, env } = this.parent.state.get();
    if (!berth || !env) {
      this.state.set({ seriesState: 'error', seriesError: 'Choose a berth and environment first.' });
      return;
    }
    const t = this.s.training;
    const startUtc = this.s.inputs.asOfUtc;
    const request = ++this.seriesRequest;
    this.recheckRequest++;
    this.state.set({ seriesMode: 'training', series: null, seriesState: 'loading', seriesError: null,
      recheck: { state: 'idle', error: null, response: null } });
    const context = this.sourceKey();
    this.seriesContext = context;
    this.checkStale();
    const current = () => !this.disposed && request === this.seriesRequest && context === this.sourceKey();
    try {
      const out = unwrap(
        await modeling.POST('/api/v1/data-simulation/forecast', {
          body: {
            berth_id: berth.berth_id,
            start_utc: startUtc,
            baseline: env,
            duration_hours: t.durationHours,
            step_min: 60,
            seed: t.seed,
            gust_peak_kt: t.gustPeakKt,
            gust_noise_sigma_kt: t.gustNoiseKt,
            water_level_amplitude_ft: t.waterLevelAmplitudeFt,
            water_level_period_hours: t.waterLevelPeriodHours,
          },
        }),
      );
      if (!current()) return;
      const revision = `seed${t.seed}-gust${t.gustPeakKt}-noise${t.gustNoiseKt}-wl${t.waterLevelAmplitudeFt}-period${t.waterLevelPeriodHours}-${t.durationHours}h-from-${startUtc}`;
      this.state.set({
        seriesState: 'idle',
        series: {
          kind: 'training',
          berthId: berth.berth_id,
          label: `Training scenario (seed ${t.seed}): synthetic, not a weather forecast`,
          sourceId: `ui-training-scenario-${berth.berth_id}`,
          revision,
          series: out.series as Environment[],
          stepMin: out.step_min,
        },
      });
      this.checkStale();
    } catch (e) {
      if (current()) this.state.set({ seriesState: 'error', seriesError: describeError(e) });
    }
  }

  buildRequest(): ForecastPlanRequest | null {
    const c = this.parent.state.get();
    const series = this.s.series;
    if (!c.ship || !c.berth || !series || c.lines.length === 0) return null;
    const i = this.s.inputs;
    return {
      ship_class_id: c.ship.class_id,
      loading: c.loading,
      berth_id: c.berth.berth_id,
      config: {
        side_to: c.side,
        ship_x_ft: c.shipXFt,
        ...(c.standoffOverrideFt != null ? { standoff_ft: c.standoffOverrideFt } : {}),
        lines: c.lines,
      },
      tugs: c.tugAssignments,
      mst: c.ship.mst_class as ForecastPlanRequest['mst'],
      as_of_utc: i.asOfUtc,
      arrival_from_utc: i.arrivalFromUtc,
      arrival_to_utc: i.arrivalToUtc,
      arrival_step_min: i.arrivalStepMin,
      operation_hours: i.operationHours,
      holding_hours: i.holdingHours,
      target_pct_wll: i.targetPctWll,
      optimize_lines: i.optimizeLines,
      forecast: series.series,
      max_gap_min: MAX_FORECAST_GAP_MIN,
      forecast_binding: { source: 'supplied', source_id: series.sourceId, revision: series.revision,
        ...(series.resolved ? { expected_content_hash: series.resolved.result.forecast_manifest.content_hash } : {}) },
    } as ForecastPlanRequest;
  }

  /** Problems that stop a run, including coverage of every arrival's docking and holding interval. */
  problems(): string[] {
    const c = this.parent.state.get();
    const p = inputProblems(this.s.inputs);
    if (!c.ship || !c.berth) p.push('Choose a berth and a ship.');
    else if (c.lines.length === 0) p.push('Add mooring lines (or run a recommendation) first.');
    if (this.s.seriesState === 'loading') p.push('Wait for the forecast binding to finish.');
    if (!this.s.series) p.push('Bind a forecast series first.');
    else {
      if (this.s.series.berthId && this.s.series.berthId !== (c.berthId || c.berth?.berth_id)) p.push('The bound forecast belongs to another berth. Fetch or generate a new series.');
      p.push(...seriesProblems(this.s.series, this.s.inputs));
    }
    return p;
  }

  async run(): Promise<void> {
    if (this.s.phase === 'running') return;
    const problems = this.problems();
    const body = this.buildRequest();
    if (problems.length || !body) {
      this.state.set({ phase: 'error', error: problems[0] ?? 'The plan inputs are incomplete.' });
      return;
    }
    const request = ++this.request;
    const key = this.key();
    const current = () => !this.disposed && request === this.request;
    this.state.set({ phase: 'running', progress: 0, error: null, response: null, recheckReason: null, applied: null,
      recheck: { state: 'idle', error: null, response: null } });
    this.resultKey = null;
    try {
      const accepted = unwrap(await modeling.POST('/api/v1/mooring/forecast-plan', { body }));
      if (!current()) return;
      const response = await awaitJob<ForecastPlanResponse>(MODELING_BASE, accepted, (progress) => {
        if (current()) this.state.set({ progress });
      });
      if (!current()) return;
      this.resultKey = key;
      this.state.set({ phase: 'done', response });
      this.checkStale();
    } catch (e) {
      if (current()) this.state.set({ phase: 'error', error: describeError(e) });
    }
  }

  /**
   * Put the selected arrival's configuration on the layout: its lines keep their modeled paid-out lengths and wet/dry
   * condition, so later checks do not silently reinstall at a different tide. Refused when the result is stale.
   */
  applySelected(): boolean {
    const result = this.s.response?.result;
    const selected = result?.selected_config;
    if (!result || !selected) return false;
    if (this.s.recheckReason) {
      this.state.set({ error: 'This assessment needs a recheck before its configuration can be applied.' });
      return false;
    }
    const series = this.s.series;
    const arrival = result.selected_arrival_utc;
    const manifest = result.forecast_manifest;
    if (!series || !arrival || !manifest?.content_hash) {
      this.state.set({ error: 'The selected assessment has no immutable forecast identity. Reassess before handing it to Intake.' });
      return false;
    }
    // Suspend the staleness check while the layout changes to the configuration this assessment selected.
    this.resultKey = null;
    this.parent.replaceLines(selected.lines.map((l) => ({ ...l })));
    this.parent.setForecastSelection({
      berth_id: this.parent.state.get().berth?.berth_id ?? this.parent.state.get().berthId,
      as_of_utc: manifest.as_of_utc,
      from_utc: arrival,
      to_utc: new Date(Date.parse(arrival) + (this.s.inputs.operationHours + this.s.inputs.holdingHours) * 3_600_000).toISOString(),
      max_gap_min: MAX_FORECAST_GAP_MIN,
      forecast: series.series,
      forecast_binding: { source: 'supplied', source_id: series.sourceId, revision: series.revision,
        expected_content_hash: manifest.content_hash },
    });
    this.resultKey = this.key();
    this.state.set({
      applied: { arrivalUtc: result.selected_arrival_utc ?? null, installedAtFt: result.installed_at_water_level_mllw_ft ?? null },
      error: null,
    });
    return true;
  }

  /** Compare the bound (possibly replaced) series with the one this result used. Never changes or approves the plan. */
  async recheck(): Promise<void> {
    const prior = this.s.response;
    const series = this.s.series;
    if (!prior || !series) return;
    const request = this.request;
    const recheckRequest = ++this.recheckRequest;
    const key = this.key();
    this.recheckContext = key;
    const current = () => !this.disposed && request === this.request && recheckRequest === this.recheckRequest && key === this.key();
    this.state.set({ recheck: { state: 'running', error: null, response: null } });
    try {
      const response = unwrap(
        await modeling.POST('/api/v1/mooring/forecast-plan/recheck', {
          body: {
            prior_result_id: prior.result_id,
            as_of_utc: this.s.inputs.asOfUtc,
            forecast: series.series,
            forecast_binding: { source: 'supplied', source_id: series.sourceId, revision: series.revision,
              ...(series.resolved ? { expected_content_hash: series.resolved.result.forecast_manifest.content_hash } : {}) },
          },
        }),
      );
      if (!current()) return;
      this.state.set({ recheck: { state: 'done', error: null, response } });
    } catch (e) {
      if (current()) this.state.set({ recheck: { state: 'error', error: describeError(e), response: null } });
    }
  }
}
