import { describe, expect, it } from 'vitest';
import { angleDiff, currentEventIndex, lerpAngle, locateOnTrack, prepareTrack, thin } from './geo';
import type { TrackFix } from './types';

const fx = (t: string, lat: number, lon: number, hdg?: number, sog?: number): TrackFix => ({ t_utc: t, lat, lon, heading_true_deg: hdg, sog_kt: sog, quality: 'good' });
const T = (s: number) => Date.parse('2026-11-05T12:00:00Z') + s * 1000;
const track = prepareTrack([fx('2026-11-05T12:00:00Z', 36, -76, 90, 10), fx('2026-11-05T12:01:00Z', 36, -75.99, 90, 12), fx('2026-11-05T12:30:00Z', 36.1, -75.9)]);

describe('locateOnTrack', () => {
  it('is exact on a fix', () => {
    expect(locateOnTrack(track, T(60), 300)).toMatchObject({ method: 'exact_fix', lat: 36, lon: -75.99, established: true });
  });
  it('interpolates between close fixes', () => {
    const p = locateOnTrack(track, T(30), 300);
    expect(p.method).toBe('interpolated');
    expect(p.lon).toBeCloseTo(-75.995, 6);
    expect(p.sogKt).toBeCloseTo(11, 6);
  });
  it('never extrapolates before or after the track', () => {
    expect(locateOnTrack(track, T(-1), 300)).toEqual({ method: 'before_track', established: false });
    expect(locateOnTrack(track, T(1801), 300)).toEqual({ method: 'after_track', established: false });
    expect(locateOnTrack(track, T(1800), 300).method).toBe('exact_fix');
  });
  it('does not interpolate across a gap longer than the limit', () => {
    const p = locateOnTrack(track, T(600), 300);
    expect(p).toMatchObject({ method: 'gap', established: false, gapS: 1740 });
    expect(p.lat).toBeUndefined();
    expect(locateOnTrack(track, T(600), 2000).method).toBe('interpolated');
  });
  it('handles empty tracks and the antimeridian', () => {
    expect(locateOnTrack([], T(0), 300).method).toBe('no_track');
    const t = prepareTrack([fx('2026-11-05T12:00:00Z', 0, 179.9), fx('2026-11-05T12:01:00Z', 0, -179.9)]);
    expect(Math.abs(locateOnTrack(t, T(30), 300).lon as number)).toBeCloseTo(180, 5);
  });
  it('derives a heading from the segment when fixes carry none', () => {
    expect(locateOnTrack(track.slice(1), T(1000), 2000).headingDeg).toBeGreaterThan(0);
  });
});

describe('helpers', () => {
  it('sorts and drops duplicate timestamps', () => {
    const t = prepareTrack([fx('2026-11-05T12:01:00Z', 1, 1), fx('2026-11-05T12:00:00Z', 0, 0), fx('2026-11-05T12:01:00Z', 9, 9)]);
    expect(t.map((x) => x.lat)).toEqual([0, 1]);
  });
  it('interpolates angles the short way', () => {
    expect(lerpAngle(350, 10, 0.5)).toBeCloseTo(0, 6);
    expect(angleDiff(10, 350)).toBe(-20);
  });
  it('finds the current event', () => {
    expect(currentEventIndex([null, 10, 20, 30], 25)).toBe(2);
    expect(currentEventIndex([10], 5)).toBe(-1);
  });
  it('thins keeping the ends', () => {
    const t = thin(Array.from({ length: 1000 }, (_, i) => i), 50);
    expect(t).toHaveLength(50);
    expect([t[0], t[49]]).toEqual([0, 999]);
  });
});


describe('spherical position evidence', () => {
  const make = (a: [number, number], b: [number, number]) => prepareTrack([
    fx('2026-11-05T12:00:00Z', ...a), fx('2026-11-05T12:01:00Z', ...b),
  ]);
  it('refuses the nonunique midpoint of antipodal fixes, while retaining exact endpoints', () => {
    const t = make([0, 0], [0, 180]);
    expect(locateOnTrack(t, T(30), 300)).toMatchObject({ established: false, reason: expect.stringContaining('Antipodal') });
    expect(locateOnTrack(t, T(0), 300)).toMatchObject({ established: true, lat: 0, lon: 0 });
  });
  it('follows the spherical arc at high latitude, not a latitude/longitude chord', () => {
    // Symmetry gives longitude 0; normalize midpoint Cartesian vector to obtain latitude.
    const p = locateOnTrack(make([60, -60], [60, 60]), T(30), 300);
    expect(p.lat).toBeCloseTo(73.897886248, 7);
    expect(p.lon).toBeCloseTo(0, 9);
  });
  it('handles coincident points without a division by zero', () => {
    const p = locateOnTrack(make([36, -76], [36, -76]), T(30), 300);
    expect(p).toMatchObject({ established: true, method: 'interpolated' });
    expect(p.lat).toBeCloseTo(36, 9);
    expect(p.lon).toBeCloseTo(-76, 9);
  });
});
