import type { Environment, ModelingSchemas } from '../types';

export type ForecastPlanRequest = ModelingSchemas['ForecastDockingRequest'];
export type ForecastPlanResponse = ModelingSchemas['ForecastDockingResponse'];
export type ForecastPlanResult = ForecastPlanResponse['result'];
export type ArrivalWindow = ModelingSchemas['DockingArrivalWindow'];
export type RecheckResponse = ModelingSchemas['ForecastRecheckResponse'];
export type ComposedForecast = ModelingSchemas['ComposedForecast'];
export type ComposeRequest = ModelingSchemas['ComposedForecastRequest'];
export type ResolvedForecast = ModelingSchemas['ForecastResolvedResponse'];
export const MAX_FORECAST_GAP_MIN = 60;

export const HOUR_MS = 3_600_000;
/** Advance planning means arrival at least this far after the as-of time (the API rejects less without allow_short_lead). */
export const MIN_LEAD_HOURS = 24;

/** The planning inputs the user edits. Times are ISO UTC strings, minute precision. */
export interface AdvanceInputs {
  asOfUtc: string;
  arrivalFromUtc: string;
  arrivalToUtc: string;
  arrivalStepMin: number;
  operationHours: number;
  holdingHours: number;
  targetPctWll: number;
  optimizeLines: boolean;
}

/** Seeded training conditions (POST /data-simulation/forecast). Labeled synthetic everywhere; never a weather forecast. */
export interface TrainingSeriesInputs {
  seed: number;
  gustPeakKt: number;
  gustNoiseKt: number;
  waterLevelAmplitudeFt: number;
  /** Scenario oscillation period; not a fitted tidal constituent. */
  waterLevelPeriodHours: number;
  durationHours: number;
}

/** A forecast series bound to the plan: the snapshots plus where they came from, in words the UI can show. */
export interface BoundSeries {
  kind: 'training' | 'public';
  berthId?: string;
  manifest?: ComposedForecast['manifest'];
  resolved?: ResolvedForecast;
  label: string;
  sourceId: string;
  revision: string;
  series: Environment[];
  stepMin: number;
}

export function isoMinute(ms: number): string {
  return new Date(Math.floor(ms / 60_000) * 60_000).toISOString().replace(/:00\.000Z$/, ':00Z');
}

/** Defaults: as-of now (to the hour), arrival window 25–31 h ahead hourly (one hour for acquisition), 2 h docking, 6 h holding, 80% WLL target. */
export function defaultInputs(nowMs: number): AdvanceInputs {
  const asOf = Math.floor(nowMs / HOUR_MS) * HOUR_MS;
  return {
    asOfUtc: isoMinute(asOf),
    arrivalFromUtc: isoMinute(asOf + (MIN_LEAD_HOURS + 1) * HOUR_MS),
    arrivalToUtc: isoMinute(asOf + (MIN_LEAD_HOURS + 7) * HOUR_MS),
    arrivalStepMin: 60,
    operationHours: 2,
    holdingHours: 6,
    targetPctWll: 80,
    optimizeLines: false,
  };
}

export const DEFAULT_TRAINING: TrainingSeriesInputs = {
  seed: 7,
  gustPeakKt: 30,
  gustNoiseKt: 2,
  waterLevelAmplitudeFt: 1.5,
  waterLevelPeriodHours: 12,
  durationHours: 48,
};

const ms = (iso: string) => Date.parse(iso);

/** Input problems that stop a run, in plain sentences. Empty when the inputs can be submitted. */
export function inputProblems(i: AdvanceInputs): string[] {
  const p: string[] = [];
  const [asOf, from, to] = [ms(i.asOfUtc), ms(i.arrivalFromUtc), ms(i.arrivalToUtc)];
  if ([asOf, from, to].some(Number.isNaN)) return ['Enter the as-of time and the arrival window as UTC date-times.'];
  if (from - asOf < MIN_LEAD_HOURS * HOUR_MS) p.push(`Earliest arrival must be at least ${MIN_LEAD_HOURS} h after the as-of time.`);
  if (to < from) p.push('The latest arrival is before the earliest arrival.');
  if (!(i.arrivalStepMin >= 15)) p.push('Arrival step must be at least 15 minutes.');
  if (to + (i.operationHours + i.holdingHours) * HOUR_MS - asOf > 120 * HOUR_MS) p.push('Docking and holding must finish within 120 hours of the as-of time.');
  if (!(i.operationHours > 0)) p.push('Docking duration must be more than zero.');
  if (!(i.holdingHours >= 0)) p.push('Holding duration cannot be negative.');
  if (!(i.targetPctWll > 0 && i.targetPctWll <= 100)) p.push('Target utilization must be between 1 and 100% of WLL.');
  return p;
}

export interface Coverage {
  /** First and last snapshot times in the series. */
  startUtc: string;
  endUtc: string;
  /** What the plan needs: from the earliest arrival to the end of holding after the latest arrival. */
  neededFromUtc: string;
  neededToUtc: string;
  covered: boolean;
  /** Largest gap between consecutive snapshots, minutes. */
  maxGapMin: number;
  count: number;
}

/** Whether the bound series covers every arrival alternative through its docking and holding interval. */
export function coverage(series: { valid_at_utc?: string | null }[], i: AdvanceInputs): Coverage | null {
  // A snapshot without a time covers nothing; it is not assumed to fill a gap.
  const times = series.map((s) => (s.valid_at_utc ? ms(s.valid_at_utc) : NaN)).filter((t) => !Number.isNaN(t)).sort((a, b) => a - b);
  if (times.length < 2) return null;
  let maxGap = 0;
  for (let k = 1; k < times.length; k++) maxGap = Math.max(maxGap, (times[k] - times[k - 1]) / 60_000);
  const needFrom = ms(i.arrivalFromUtc);
  const needTo = ms(i.arrivalToUtc) + (i.operationHours + i.holdingHours) * HOUR_MS;
  return {
    startUtc: isoMinute(times[0]),
    endUtc: isoMinute(times[times.length - 1]),
    neededFromUtc: isoMinute(needFrom),
    neededToUtc: isoMinute(needTo),
    covered: times[0] <= needFrom && times[times.length - 1] >= needTo,
    maxGapMin: Math.ceil(maxGap),
    count: times.length,
  };
}

export const OUTCOME_LABEL: Record<ArrivalWindow['outcome'], string> = {
  within_target: 'Within target',
  supported_limited: 'Supported, limited',
  overloaded: 'Over target',
  invalid: 'Invalid input',
  undetermined: 'Undetermined',
  unavailable: 'No coverage',
};

export function outcomeStatus(outcome: ArrivalWindow['outcome']): 'GREEN' | 'AMBER' | 'RED' | 'NONE' {
  switch (outcome) {
    case 'within_target':
    case 'supported_limited':
      return 'AMBER'; // static, sampled forecast planning is never unconditionally GREEN
    case 'overloaded':
    case 'invalid':
      return 'RED';
    default:
      return 'NONE';
  }
}

/** "Thu 14:00Z" style; raw text when unparseable. */
export function shortUtc(iso: string | null | undefined): string {
  if (!iso) return 'n/a';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const day = d.toUTCString().slice(0, 3);
  return `${day} ${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}Z`;
}

/** Value for an <input type="datetime-local"> holding a UTC time, and back. */
export function toLocalInput(iso: string): string {
  return iso.slice(0, 16);
}
export function fromLocalInput(value: string): string {
  return value ? `${value.slice(0, 16)}:00Z` : '';
}


export interface PublicSeriesInputs {
  currentDepthFt: number | null;
  currentBin: string;
}

/** No current depth or station bin can be inferred safely from ship draft or another berth. */
export function publicRequest(berthId: string, i: AdvanceInputs, source: PublicSeriesInputs): ComposeRequest | null {
  // Acquisition may retain its original horizon after an explicit cutoff update; the planning run still enforces 24 h lead.
  if (!berthId || inputProblems(i).some((problem) => !problem.startsWith('Earliest arrival must be at least')) ||
    Date.parse(i.arrivalFromUtc) < Date.parse(i.asOfUtc) || source.currentDepthFt == null ||
    !Number.isFinite(source.currentDepthFt) || source.currentDepthFt < 0 || !source.currentBin.trim()) return null;
  return {
    berth_id: berthId, source: { mode: 'public' }, as_of_utc: i.asOfUtc,
    horizon_start_utc: i.arrivalFromUtc,
    horizon_end_utc: new Date(Date.parse(i.arrivalToUtc) + (i.operationHours + i.holdingHours) * HOUR_MS).toISOString(),
    current_depth_ft: source.currentDepthFt, current_bin: source.currentBin.trim(), step_min: MAX_FORECAST_GAP_MIN,
  };
}

export function sameAcquisition(a: ComposeRequest, b: ComposeRequest): boolean {
  return a.berth_id === b.berth_id && a.source.mode === 'public' && b.source.mode === 'public' &&
    a.current_depth_ft === b.current_depth_ft && a.current_bin === b.current_bin && a.step_min === b.step_min &&
    Date.parse(a.as_of_utc) === Date.parse(b.as_of_utc) &&
    Date.parse(a.horizon_start_utc) === Date.parse(b.horizon_start_utc) && Date.parse(a.horizon_end_utc) === Date.parse(b.horizon_end_utc);
}

export function seriesProblems(bound: BoundSeries, inputs: AdvanceInputs): string[] {
  const problems: string[] = [];
  const times = bound.series.map((s) => s.valid_at_utc ? Date.parse(s.valid_at_utc) : NaN);
  if (times.length < 2) problems.push('At least two usable forecast snapshots are required. Missing components are never filled.');
  if (times.some((t, i) => !Number.isFinite(t) || (i > 0 && t <= times[i - 1])))
    problems.push('Forecast snapshot times must be present and strictly increasing.');
  const cov = coverage(bound.series, inputs);
  if (cov && !cov.covered) problems.push(`The series covers ${cov.startUtc} to ${cov.endUtc}; the plan needs ${cov.neededFromUtc} to ${cov.neededToUtc}.`);
  if (cov && cov.maxGapMin > MAX_FORECAST_GAP_MIN) problems.push(`Forecast has a ${cov.maxGapMin}-minute gap; the planning limit is ${MAX_FORECAST_GAP_MIN} minutes. Fetch covered data or narrow the operation.`);
  if (bound.kind === 'public') {
    if (bound.manifest?.status !== 'complete') problems.push(`Public forecast is ${bound.manifest?.status ?? 'unavailable'}; inspect component availability.`);
    if (!bound.resolved?.result.coverage_complete || !bound.resolved.result.forecast_manifest.content_hash ||
      !['valid', 'limited'].includes(bound.resolved.validity?.state ?? 'unknown')) problems.push('Canonical forecast binding is unavailable or does not cover the complete operation.');
    for (const component of ['wind', 'current', 'water_level']) {
      const data = bound.manifest?.components.find((item) => item.availability.component === component)?.availability;
      if (!data || data.state !== 'prediction' || data.basis !== 'prediction') problems.push(`${component.replace('_', ' ')} prediction unavailable${data?.reason ? `: ${data.reason}` : '.'}`);
    }
    problems.push(...(bound.resolved?.result.problems ?? []));
  }
  return problems;
}
