import type { Environment, ModelingSchemas } from '../types';

export type ForecastPlanRequest = ModelingSchemas['ForecastDockingRequest'];
export type ForecastPlanResponse = ModelingSchemas['ForecastDockingResponse'];
export type ForecastPlanResult = ForecastPlanResponse['result'];
export type ArrivalWindow = ModelingSchemas['DockingArrivalWindow'];
export type RecheckResponse = ModelingSchemas['ForecastRecheckResponse'];

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
  kind: 'training';
  label: string;
  sourceId: string;
  revision: string;
  series: Environment[];
  stepMin: number;
}

export function isoMinute(ms: number): string {
  return new Date(Math.floor(ms / 60_000) * 60_000).toISOString().replace(/:00\.000Z$/, ':00Z');
}

/** Defaults: as-of now (to the hour), arrival window 24–30 h ahead hourly, 2 h docking, 6 h holding, 80% WLL target. */
export function defaultInputs(nowMs: number): AdvanceInputs {
  const asOf = Math.floor(nowMs / HOUR_MS) * HOUR_MS;
  return {
    asOfUtc: isoMinute(asOf),
    arrivalFromUtc: isoMinute(asOf + MIN_LEAD_HOURS * HOUR_MS),
    arrivalToUtc: isoMinute(asOf + (MIN_LEAD_HOURS + 6) * HOUR_MS),
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
    maxGapMin: Math.round(maxGap),
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
