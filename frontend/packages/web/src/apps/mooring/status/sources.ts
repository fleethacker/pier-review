import type { Environment, EnvironmentAvailability } from '../types';

/** One backend capability as /capabilities reports it. */
export interface Capability {
  capability: string;
  module: string;
  backend: string;
  qualification: string;
  limitations: string[];
  blockers: string[];
}

export type SourceState = 'live' | 'prediction' | 'replay' | 'mock' | 'manual' | 'unavailable' | 'error';

export interface SourceRow {
  id: 'wind' | 'gust' | 'current' | 'water' | 'forecast' | 'waves' | 'wake' | 'telemetry';
  label: string;
  provider: string;
  state: SourceState;
  /** Seconds since the provider's observation, when it says. */
  ageS: number | null;
  /** Why it is not live, in plain words. Null only when it is live. */
  reason: string | null;
  /** Observation, prediction or scenario, when the service states it; null means undocumented. */
  basis?: string | null;
  /** Provider quality flag for this component, when stated. */
  quality?: string | null;
}

export interface SourceInput {
  env: Environment | null;
  availability?: EnvironmentAvailability | null;
  envMode: { kind: 'manual' | 'live' | 'replay' | 'storm'; status: string; detail: string | null };
  capabilities: Capability[] | null;
  /** The last environment request failed (e.g. an unsupported or misconfigured source). Shown as an error, never as current data. */
  envError?: string | null;
  nowMs?: number;
}

type Component = NonNullable<NonNullable<Environment['metadata']>['components']>[number];

const BASIS_STATE: Record<Component['basis'], SourceState> = { observation: 'live', prediction: 'prediction', scenario: 'manual' };

/** One component's own provenance: its provider, basis, quality and age from its actual issue time (never retrieval time). */
function componentRow(base: SourceRow, comp: Component, nowMs: number): SourceRow {
  const issued = comp.issued_at_utc ? Date.parse(comp.issued_at_utc) : NaN;
  const notes: string[] = base.reason ? [base.reason] : [];
  if (Number.isNaN(issued)) {
    notes.push(comp.retrieved_at_utc
      ? `Issue time unknown; retrieved ${comp.retrieved_at_utc.slice(0, 16).replace('T', ' ')}Z, so freshness is unknown.`
      : 'Issue time unknown, so freshness is unknown.');
  }
  if (comp.quality === 'poor' || comp.quality === 'suspect') notes.push(`Provider quality ${comp.quality}.`);
  if (comp.basis === 'prediction') notes.push('Predicted values, not observations.');
  if (comp.basis === 'scenario') notes.push('Synthetic what-if input, not an observation.');
  notes.push(...(comp.limitations ?? []));
  return {
    ...base,
    provider: comp.source,
    state: base.state === 'replay' || base.state === 'manual' ? base.state : (BASIS_STATE[comp.basis] ?? 'unavailable'),
    ageS: Number.isNaN(issued) ? null : Math.max(0, (nowMs - issued) / 1000),
    reason: notes.length ? notes.join(' ') : null,
    basis: comp.basis,
    quality: comp.quality,
  };
}

function forecastRow(availability: EnvironmentAvailability | null | undefined): SourceRow {
  const component = availability?.components.find((item) => item.component === 'forecast');
  if (!component) {
    return {
      id: 'forecast', label: 'Forecast', provider: 'none', state: 'unavailable', ageS: null,
      reason: 'Forecast availability has not been reported.',
    };
  }
  const notes = [component.reason, ...(component.limitations ?? [])].filter((item): item is string => Boolean(item));
  let state: SourceState = component.state;
  if (state === 'live') {
    if (component.basis === 'prediction') state = 'prediction';
    else {
      state = 'unavailable';
      notes.push('Forecast status did not identify a prediction basis, so it is not shown as live.');
    }
  }
  if (state === 'prediction' && !notes.length) notes.push('Predicted values, not observations.');
  if (state === 'unavailable' && !notes.length) notes.push('No forecast source is available.');
  return {
    id: 'forecast',
    label: 'Forecast',
    provider: component.source ?? 'none',
    state,
    ageS: component.age_s ?? null,
    reason: notes.length ? notes.join(' ') : null,
    basis: component.basis ?? null,
    quality: component.quality,
  };
}

const find = (caps: Capability[] | null, needle: string) => caps?.find((c) => c.capability.toLowerCase().includes(needle.toLowerCase())) ?? null;

function ageOf(env: Environment | null): number | null {
  const ages = (env?.quality ?? []).map((q) => q.age_s).filter((a) => Number.isFinite(a));
  return ages.length ? Math.max(...ages) : null;
}

/**
 * What each data stream is actually backed by right now. Nothing here is guessed: a stream is `live` only when the
 * service says its snapshot did not come from the mock, and a missing stream is `unavailable` with the reason, never zero.
 */
export function deriveSources({ env, availability, envMode, capabilities, envError = null, nowMs = Date.now() }: SourceInput): SourceRow[] {
  const providers = find(capabilities, 'live providers');
  const telemetry = find(capabilities, 'telemetry');
  const replay = find(capabilities, 'deterministic replay');

  let core: Pick<SourceRow, 'provider' | 'state' | 'reason'>;
  if (!env) {
    core = { provider: 'none', state: 'unavailable', reason: 'No environment has been loaded.' };
  } else {
    const src = env.source ?? 'scenario';
    const isMock = src === 'mock' || (env.quality ?? []).some((q) => (q.flags ?? []).includes('mock'));
    if (envMode.kind === 'storm') {
      core = { provider: 'synthetic storm ramp', state: 'mock', reason: 'A scripted ramp for what-if checks, not an observation or forecast.' };
    } else if (isMock) {
      core = {
        provider: 'deterministic mock',
        state: 'mock',
        reason: envMode.kind === 'live'
          ? (providers?.blockers[0] ?? 'Live mode is selected, but the service is still serving the mock.')
          : 'Illustrative values from the mock environment.',
      };
    } else if (envMode.kind === 'replay' || src === 'replay') {
      core = { provider: 'recorded conditions', state: 'replay', reason: replay?.limitations[0] ?? 'Recorded conditions, not current ones.' };
    } else if (src === 'scenario') {
      core = { provider: 'saved or typed values', state: 'manual', reason: 'Entered by hand or saved in a scenario; not an observation.' };
    } else if (src === 'forecast') {
      core = { provider: 'forecast', state: 'prediction', reason: 'Forecast values, not observations.' };
    } else {
      core = { provider: src === 'ship_sensor' ? "ship's own sensors" : 'live feed', state: 'live', reason: null };
    }
  }
  const feedFailed = envMode.kind !== 'manual' && (envMode.status === 'error' || envMode.status === 'closed');
  if (envError || feedFailed) {
    core = {
      provider: core.provider,
      state: 'error',
      reason: envError
        ? `The environment source failed: ${envError} The values on screen are not current.`
        : `The ${envMode.kind} feed ${envMode.status === 'closed' ? 'was closed by the service' : 'is failing'}${envMode.detail ? ` (${envMode.detail})` : ''}. The values on screen are not current.`,
    };
  }
  const age = ageOf(env);
  const aggregateBasis = env?.metadata?.basis ?? null;
  const components = core.state === 'mock' || core.state === 'error' ? [] : (env?.metadata?.components ?? []);
  const row = (id: SourceRow['id'], label: string, component?: Component['component']): SourceRow => {
    const base: SourceRow = { id, label, ...core, ageS: core.state === 'unavailable' || core.state === 'error' ? null : age, basis: aggregateBasis };
    const comp = component ? components.find((x) => x.component === component) : undefined;
    return comp ? componentRow(base, comp, nowMs) : base;
  };

  const forecast = forecastRow(availability);

  return [
    row('wind', 'Wind', 'wind'),
    row('gust', 'Gust', 'wind'),
    row('current', 'Current', 'current'),
    row('water', 'Water level', 'water_level'),
    forecast,
    {
      id: 'waves',
      label: 'Waves',
      provider: 'none connected',
      state: 'unavailable',
      ageS: null,
      reason: 'No wave source is connected, so wave height is not reported (never shown as zero). Approved order: NDBC 44099 observations, then GFS-Wave forecast.',
    },
    {
      id: 'wake',
      label: 'Wake',
      provider: 'none',
      state: 'unavailable',
      ageS: null,
      reason: 'Wake is not modelled. It is unavailable, not zero.',
    },
    {
      id: 'telemetry',
      label: 'Telemetry',
      provider: 'no feed connected',
      state: 'unavailable',
      ageS: null,
      reason: telemetry ? (telemetry.blockers[0] ?? telemetry.limitations[0] ?? 'No live feed is connected.') : 'No live feed is connected.',
    },
  ];
}

/** Human age: "42 s", "5 min", "3 h". */
export function formatAge(ageS: number | null): string {
  if (ageS == null) return 'age not stated';
  if (ageS < 90) return `${Math.round(ageS)} s old`;
  if (ageS < 5400) return `${Math.round(ageS / 60)} min old`;
  return `${(ageS / 3600).toFixed(1)} h old`;
}

/** Capabilities that are not yet qualified, for the standing summary. */
export function limitedCount(caps: Capability[] | null): { limited: number; total: number } {
  if (!caps) return { limited: 0, total: 0 };
  return { limited: caps.filter((c) => c.qualification !== 'qualified').length, total: caps.length };
}
