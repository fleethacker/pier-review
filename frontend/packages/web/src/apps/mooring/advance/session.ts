import { Store } from '../../../lib/store';
import { awaitJob, describeError, modeling, MODELING_BASE, unwrap } from '../api';
import type { MooringController } from '../controller';
import type { Environment } from '../types';
import {
  DEFAULT_TRAINING,
  coverage,
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
    this.unsubscribe();
  }

  private key(): string {
    return JSON.stringify([this.parent.scenarioKey(), this.s.inputs, this.s.series?.revision ?? null]);
  }

  private checkStale(): void {
    if (this.resultKey === null || !this.s.response || this.s.recheckReason) return;
    if (this.resultKey !== this.key()) {
      this.state.set({ recheckReason: 'Inputs changed since this assessment (layout, environment, times or forecast series). Recheck before using it.' });
    }
  }

  setInputs(patch: Partial<AdvanceInputs>): void {
    this.state.set({ inputs: { ...this.s.inputs, ...patch } });
    this.checkStale();
  }

  setTraining(patch: Partial<TrainingSeriesInputs>): void {
    this.state.set({ training: { ...this.s.training, ...patch } });
  }

  /** Seeded synthetic conditions from the current environment, starting at the as-of time. Labeled training data. */
  async generateTrainingSeries(): Promise<void> {
    const { berth, env } = this.parent.state.get();
    if (!berth || !env) {
      this.state.set({ seriesState: 'error', seriesError: 'Choose a berth and environment first.' });
      return;
    }
    const t = this.s.training;
    const startUtc = this.s.inputs.asOfUtc;
    this.state.set({ seriesState: 'loading', seriesError: null });
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
      if (this.disposed) return;
      const revision = `seed${t.seed}-gust${t.gustPeakKt}-noise${t.gustNoiseKt}-wl${t.waterLevelAmplitudeFt}-${t.durationHours}h-from-${startUtc}`;
      this.state.set({
        seriesState: 'idle',
        series: {
          kind: 'training',
          label: `Training scenario (seed ${t.seed}): synthetic, not a weather forecast`,
          sourceId: `ui-training-scenario-${berth.berth_id}`,
          revision,
          series: out.series as Environment[],
          stepMin: out.step_min,
        },
      });
      this.checkStale();
    } catch (e) {
      if (!this.disposed) this.state.set({ seriesState: 'error', seriesError: describeError(e) });
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
      forecast_binding: { source: 'supplied', source_id: series.sourceId, revision: series.revision },
    } as ForecastPlanRequest;
  }

  /** Problems that stop a run, including coverage of every arrival's docking and holding interval. */
  problems(): string[] {
    const c = this.parent.state.get();
    const p = inputProblems(this.s.inputs);
    if (!c.ship || !c.berth) p.push('Choose a berth and a ship.');
    else if (c.lines.length === 0) p.push('Add mooring lines (or run a recommendation) first.');
    if (!this.s.series) p.push('Bind a forecast series first.');
    else {
      const cov = coverage(this.s.series.series, this.s.inputs);
      if (cov && !cov.covered) p.push(`The series covers ${cov.startUtc} to ${cov.endUtc}; the plan needs ${cov.neededFromUtc} to ${cov.neededToUtc}.`);
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
    // Suspend the staleness check while the layout changes to the configuration this assessment selected.
    this.resultKey = null;
    this.parent.replaceLines(selected.lines.map((l) => ({ ...l })));
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
    this.state.set({ recheck: { state: 'running', error: null, response: null } });
    try {
      const response = unwrap(
        await modeling.POST('/api/v1/mooring/forecast-plan/recheck', {
          body: {
            prior_result_id: prior.result_id,
            as_of_utc: this.s.inputs.asOfUtc,
            forecast: series.series,
            forecast_binding: { source: 'supplied', source_id: series.sourceId, revision: series.revision },
          },
        }),
      );
      if (this.disposed || request !== this.request) return;
      this.state.set({ recheck: { state: 'done', error: null, response } });
    } catch (e) {
      if (!this.disposed && request === this.request) this.state.set({ recheck: { state: 'error', error: describeError(e), response: null } });
    }
  }
}
