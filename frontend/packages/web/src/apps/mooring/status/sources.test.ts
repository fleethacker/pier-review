import { describe, expect, it } from 'vitest';
import type { Environment, EnvironmentAvailability } from '../types';
import { deriveSources, formatAge, limitedCount } from './sources';
import type { Capability } from './sources';

const env = (over: Partial<Environment> = {}): Environment =>
  ({ source: 'mock', wind_speed_kt: 10, quality: [{ station_id: 'a', age_s: 30, flags: ['mock'] }, { station_id: 'b', age_s: 120, flags: ['mock'] }], ...over }) as Environment;

const caps: Capability[] = [
  { capability: 'Environment: live providers (CO-OPS, NWS, CBOFS)', module: 'M1', backend: 'mock', qualification: 'mock', limitations: [], blockers: ['Provider verification pending.'] },
  { capability: 'Environment: deterministic replay', module: 'M1', backend: 'real', qualification: 'demonstration', limitations: ['Library with fixtures.'], blockers: [] },
  { capability: 'Telemetry ingest', module: 'M13', backend: 'real', qualification: 'demonstration', limitations: ['NMEA only.'], blockers: ['Deployment controls first.'] },
];
const manual = { kind: 'manual' as const, status: 'idle', detail: null };
const byId = (rows: ReturnType<typeof deriveSources>, id: string) => rows.find((r) => r.id === id)!;

describe('deriveSources', () => {
  it('labels the mock environment as mock, with the oldest station age', () => {
    const rows = deriveSources({ env: env(), envMode: manual, capabilities: caps });
    expect(byId(rows, 'wind').state).toBe('mock');
    expect(byId(rows, 'wind').ageS).toBe(120);
    expect(byId(rows, 'water').state).toBe('mock');
  });

  it('says live mode is still the mock instead of calling it live', () => {
    const rows = deriveSources({ env: env(), envMode: { kind: 'live', status: 'open', detail: null }, capabilities: caps });
    expect(byId(rows, 'wind').state).toBe('mock');
    expect(byId(rows, 'wind').reason).toBe('Provider verification pending.');
  });

  it('shows a non-mock source as live only when the service says so', () => {
    const rows = deriveSources({ env: env({ source: 'live', quality: [{ station_id: 'a', age_s: 60, flags: [] }] }), envMode: { kind: 'live', status: 'open', detail: null }, capabilities: caps });
    expect(byId(rows, 'wind')).toMatchObject({ state: 'live', provider: 'live feed', ageS: 60, reason: null });
  });

  it('marks replay, storm ramps and hand-typed values distinctly', () => {
    expect(byId(deriveSources({ env: env({ source: 'replay', quality: [] }), envMode: { kind: 'replay', status: 'open', detail: null }, capabilities: caps }), 'wind').state).toBe('replay');
    expect(byId(deriveSources({ env: env(), envMode: { kind: 'storm', status: 'open', detail: null }, capabilities: caps }), 'wind').state).toBe('mock');
    expect(byId(deriveSources({ env: env({ source: 'scenario', quality: [] }), envMode: manual, capabilities: caps }), 'wind').state).toBe('manual');
  });

  it('never relabels recorded replay components as live observations', () => {
    const replay = env({
      source: 'replay',
      quality: [],
      metadata: {
        basis: 'observation', quality: 'suspect',
        components: [{ component: 'wind', source: 'recorded NOAA', basis: 'observation', quality: 'suspect', limitations: ['NOT current conditions.'] }],
      },
    } as Partial<Environment>);
    const row = byId(deriveSources({ env: replay, envMode: { kind: 'replay', status: 'open', detail: null }, capabilities: caps }), 'wind');
    expect(row).toMatchObject({ state: 'replay', provider: 'recorded NOAA', basis: 'observation' });
    expect(row.reason).toMatch(/not current/i);
  });

  it('drives forecast status from component availability and never calls a forecast live', () => {
    const base = { berth_id: 'b', checked_at_utc: '2026-11-05T18:00:00Z', complete_snapshot_available: true };
    const prediction = deriveSources({
      nowMs: Date.parse(base.checked_at_utc),
      env: env({ source: 'live', quality: [] }), envMode: { kind: 'live', status: 'open', detail: null }, capabilities: caps,
      availability: { ...base, components: [{ component: 'forecast', state: 'prediction', source: 'NWS + CO-OPS', basis: 'prediction', age_s: 900, quality: 'good', limitations: [] }] },
    });
    expect(byId(prediction, 'forecast')).toMatchObject({ state: 'prediction', provider: 'NWS + CO-OPS', ageS: 900, basis: 'prediction' });

    const invalidLive = deriveSources({
      env: env({ source: 'live', quality: [] }), envMode: { kind: 'live', status: 'open', detail: null }, capabilities: caps,
      availability: { ...base, components: [{ component: 'forecast', state: 'live', source: 'unknown', basis: 'observation', quality: 'unknown', limitations: [] }] },
    });
    expect(byId(invalidLive, 'forecast').state).toBe('unavailable');
    expect(byId(invalidLive, 'forecast').reason).toMatch(/not shown as live/);
  });

  it('keeps waves, wake and telemetry unavailable with a reason, never zero', () => {
    const rows = deriveSources({ env: env(), envMode: manual, capabilities: caps });
    for (const id of ['waves', 'wake', 'telemetry']) {
      const r = byId(rows, id);
      expect(r.state).toBe('unavailable');
      expect(r.ageS).toBeNull();
      expect(r.reason).toBeTruthy();
    }
    expect(byId(rows, 'waves').reason).toMatch(/never shown as zero/);
    expect(byId(rows, 'telemetry').reason).toBe('Deployment controls first.');
  });

  it('reports everything unavailable when no environment is loaded', () => {
    const rows = deriveSources({ env: null, envMode: manual, capabilities: null });
    expect(byId(rows, 'wind').state).toBe('unavailable');
    expect(byId(rows, 'forecast').state).toBe('unavailable');
  });
});

describe('independent provider availability and selected forcing', () => {
  const checked = '2026-11-05T18:00:00Z';
  const availability: EnvironmentAvailability = { berth_id: 'b', checked_at_utc: checked,
    complete_snapshot_available: false, components: [
      { component: 'wind', state: 'live', source: 'NOAA wind', basis: 'observation', age_s: 60, age_basis: 'valid_time', quality: 'good' },
      { component: 'current', state: 'unavailable', source: 'NOAA current bin 4', basis: 'observation', age_s: 2400, reason: 'Current is stale.', quality: 'suspect' },
      { component: 'water_level', state: 'live', source: 'NOAA tide', basis: 'observation', age_s: null, quality: 'good' },
      { component: 'forecast', state: 'prediction', source: 'NWS', basis: 'prediction', age_s: 600, quality: 'good' },
      { component: 'waves', state: 'prediction', source: 'GFS-Wave', basis: 'prediction', age_s: null, quality: 'unknown', limitations: ['Offshore grid; no berth transfer.'] },
    ] };

  it('reports partial live components even when no complete snapshot can be loaded', () => {
    const rows = deriveSources({ env: null, availability, envMode: manual, capabilities: null,
      envError: 'No aligned current', nowMs: Date.parse(checked) + 30000 });
    expect(byId(rows, 'wind')).toMatchObject({ state: 'live', provider: 'NOAA wind', ageS: 90 });
    expect(byId(rows, 'gust').provider).toBe('NOAA wind');
    expect(byId(rows, 'current')).toMatchObject({ state: 'unavailable', ageS: 2430, quality: 'suspect' });
    expect(byId(rows, 'water').ageS).toBeNull();
    expect(byId(rows, 'wind').reason).toContain('complete current snapshot is unavailable');
    expect(byId(rows, 'waves')).toMatchObject({ state: 'prediction', provider: 'GFS-Wave', ageS: null });
    expect(byId(rows, 'waves').reason).toContain('no berth transfer');
    expect(byId(rows, 'waves').reason).toContain('does not establish berth applicability');
  });

  it('does not label an old live current as available after its provider reports stale data', () => {
    const rows = deriveSources({ env: env({ source: 'live', quality: [] }), availability,
      envMode: manual, capabilities: null, nowMs: Date.parse(checked) });
    expect(byId(rows, 'current')).toMatchObject({ state: 'unavailable', provider: 'NOAA current bin 4' });
    expect(byId(rows, 'current').reason).toContain('Current is stale');
  });

  it('never labels prediction or scenario component values as live observations', () => {
    const rows = deriveSources({ env: null, envMode: manual, capabilities: null, nowMs: Date.parse(checked),
      availability: { ...availability, components: availability.components.map((component) => ({ ...component,
        ...(component.component === 'waves' ? { state: 'live' as const, basis: 'prediction' as const } : {}),
        ...(component.component === 'wind' ? { state: 'live' as const, basis: 'scenario' as const } : {}),
      })) } });
    expect(byId(rows, 'waves').state).toBe('prediction');
    expect(byId(rows, 'wind').state).toBe('mock');
  });

  it.each([['scenario', 'manual'], ['replay', 'replay'], ['mock', 'mock'], ['forecast', 'prediction'], ['ship_sensor', 'live']] as const)(
    'retains selected %s forcing while showing public availability separately', (source, expected) => {
      const rows = deriveSources({ env: env({ source, quality: [] }), availability,
        envMode: manual, capabilities: null, nowMs: Date.parse(checked) });
      expect(byId(rows, 'wind').state).toBe(expected);
      expect(byId(rows, 'wind').provider).not.toBe('NOAA wind');
      expect(byId(rows, 'wind').availabilityNote).toContain('live · NOAA wind');
    });

  it('keeps a closed selected feed in error while exposing independent provider availability', () => {
    const rows = deriveSources({ env: env({ source: 'live', quality: [] }), availability,
      envMode: { kind: 'live', status: 'closed', detail: null }, capabilities: null, nowMs: Date.parse(checked) });
    expect(byId(rows, 'wind').state).toBe('error');
    expect(byId(rows, 'wind').availabilityNote).toContain('NOAA wind');
  });
});

describe('helpers', () => {
  it('formats ages', () => {
    expect(formatAge(null)).toBe('age not stated');
    expect(formatAge(42)).toBe('42 s old');
    expect(formatAge(300)).toBe('5 min old');
    expect(formatAge(7200)).toBe('2.0 h old');
  });
  it('counts capabilities that are not qualified', () => {
    expect(limitedCount(caps)).toEqual({ limited: 3, total: 3 });
    expect(limitedCount(null)).toEqual({ limited: 0, total: 0 });
  });
});

describe('per-component availability (U3)', () => {
  const NOW = Date.parse('2026-11-05T18:00:00Z');
  const composed = (components: unknown[]) =>
    ({ source: 'forecast', wind_speed_kt: 10, quality: [], metadata: { basis: 'prediction', quality: 'good', components } }) as unknown as Environment;

  it('gives each component its own provider, basis and age from its issue time', () => {
    const rows = deriveSources({
      env: composed([
        { component: 'wind', source: 'NWS gridpoint AKQ/90,52', basis: 'prediction', issued_at_utc: '2026-11-05T17:00:00Z', quality: 'good' },
        { component: 'current', source: 'NOAA CO-OPS cb0402', basis: 'observation', issued_at_utc: '2026-11-05T17:54:00Z', quality: 'suspect' },
        { component: 'water_level', source: 'NOAA CO-OPS 8638610', basis: 'prediction', retrieved_at_utc: '2026-11-05T17:58:00Z', quality: 'good' },
      ]),
      envMode: manual, capabilities: caps, nowMs: NOW,
    });
    expect(byId(rows, 'wind')).toMatchObject({ provider: 'NWS gridpoint AKQ/90,52', state: 'prediction', basis: 'prediction', ageS: 3600 });
    expect(byId(rows, 'gust').provider).toBe('NWS gridpoint AKQ/90,52');
    expect(byId(rows, 'current')).toMatchObject({ state: 'live', ageS: 360, quality: 'suspect' });
    expect(byId(rows, 'current').reason).toMatch(/quality suspect/);
    // Retrieval time never stands in for issuance: age stays unknown.
    expect(byId(rows, 'water')).toMatchObject({ state: 'prediction', ageS: null });
    expect(byId(rows, 'water').reason).toMatch(/Issue time unknown; retrieved 2026-11-05 17:58Z/);
  });

  it('keeps a component the service did not describe on the aggregate source', () => {
    const rows = deriveSources({
      env: composed([{ component: 'wind', source: 'NWS', basis: 'prediction', issued_at_utc: '2026-11-05T17:00:00Z', quality: 'good' }]),
      envMode: manual, capabilities: caps, nowMs: NOW,
    });
    expect(byId(rows, 'current')).toMatchObject({ provider: 'forecast', basis: 'prediction' });
  });

  it('never lets component provenance relabel mock data', () => {
    const e = { ...env(), metadata: { basis: 'observation', quality: 'good',
      components: [{ component: 'wind', source: 'NWS', basis: 'observation', quality: 'good' }] } } as unknown as Environment;
    expect(byId(deriveSources({ env: e, envMode: manual, capabilities: caps }), 'wind').state).toBe('mock');
  });

  it('shows a failed or misconfigured source as an error, not as current values', () => {
    const rows = deriveSources({ env: env({ source: 'live' }), envMode: manual, capabilities: caps,
      envError: "The service rejected the request: unsupported MOORING_ENV_SOURCE 'auto'" });
    for (const id of ['wind', 'gust', 'current', 'water']) {
      expect(byId(rows, id)).toMatchObject({ state: 'error', ageS: null });
      expect(byId(rows, id).reason).toMatch(/not current/);
    }
    expect(byId(rows, 'waves').state).toBe('unavailable');
  });

  it('shows a closed live feed as an error', () => {
    const rows = deriveSources({ env: env({ source: 'live' }), envMode: { kind: 'live', status: 'closed', detail: 'source unavailable' }, capabilities: caps });
    expect(byId(rows, 'wind').state).toBe('error');
    expect(byId(rows, 'wind').reason).toMatch(/closed by the service \(source unavailable\)/);
  });
});
