import type { Environment } from '../types';

/** One backend capability as /capabilities reports it. */
export interface Capability {
  capability: string;
  module: string;
  backend: string;
  qualification: string;
  limitations: string[];
  blockers: string[];
}

export type SourceState = 'live' | 'replay' | 'mock' | 'manual' | 'unavailable';

export interface SourceRow {
  id: 'wind' | 'gust' | 'current' | 'water' | 'forecast' | 'waves' | 'wake' | 'telemetry';
  label: string;
  provider: string;
  state: SourceState;
  /** Seconds since the provider's observation, when it says. */
  ageS: number | null;
  /** Why it is not live, in plain words. Null only when it is live. */
  reason: string | null;
}

export interface SourceInput {
  env: Environment | null;
  envMode: { kind: 'manual' | 'live' | 'replay' | 'storm'; status: string; detail: string | null };
  capabilities: Capability[] | null;
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
export function deriveSources({ env, envMode, capabilities }: SourceInput): SourceRow[] {
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
      core = { provider: 'forecast', state: 'live', reason: 'Forecast values, not observations.' };
    } else {
      core = { provider: src === 'ship_sensor' ? "ship's own sensors" : 'live feed', state: 'live', reason: null };
    }
  }
  const age = ageOf(env);
  const row = (id: SourceRow['id'], label: string): SourceRow => ({ id, label, ...core, ageS: core.state === 'unavailable' ? null : age });

  const forecast: SourceRow = {
    id: 'forecast',
    label: 'Forecast',
    provider: providers && providers.backend !== 'real' ? 'deterministic mock' : (env ? core.provider : 'none'),
    state: providers && providers.backend !== 'real' ? 'mock' : env ? (core.state === 'live' ? 'live' : 'mock') : 'unavailable',
    ageS: null,
    reason: providers?.blockers[0] ?? 'The forecast follows the environment source.',
  };

  return [
    row('wind', 'Wind'),
    row('gust', 'Gust'),
    row('current', 'Current'),
    row('water', 'Water level'),
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
