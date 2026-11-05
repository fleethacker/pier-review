import { describe, expect, it } from 'vitest';
import type { Environment } from '../types';
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
