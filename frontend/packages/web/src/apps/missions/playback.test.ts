import { describe, expect, it } from 'vitest';
import { sampleSeries } from './fixtures';
import { MAX_TRAIL_POINTS, advanceClock, bracket, clampSpeed, endTime, stateAt, trailPoints } from './playback';

const frames = sampleSeries.frames;

describe('frame interpolation', () => {
  it('returns exact frames at frame times and clamps outside', () => {
    expect(bracket(frames, -5)).toEqual({ i0: 0, i1: 0, f: 0 });
    expect(bracket(frames, 1e9)).toEqual({ i0: frames.length - 1, i1: frames.length - 1, f: 0 });
    expect(stateAt(frames, frames[3].t_s)[0].lat).toBe(frames[3].vessels[0].lat);
  });
  it('blends midway and never extrapolates', () => {
    const mid = (frames[2].t_s + frames[3].t_s) / 2;
    const s = stateAt(frames, mid)[0];
    expect(s.lat).toBeCloseTo((frames[2].vessels[0].lat + frames[3].vessels[0].lat) / 2, 9);
    const end = stateAt(frames, endTime(frames) + 100)[0];
    expect(end.lat).toBe(frames.at(-1)!.vessels[0].lat);
  });
  it('interpolates heading across north', () => {
    const mk = (t: number, h: number) => ({ t_s: t, vessels: [{ ...frames[0].vessels[0], heading_true_deg: h }] });
    expect(stateAt([mk(0, 350), mk(10, 10)], 5)[0].heading_true_deg).toBeCloseTo(0, 6);
  });
  it('keeps discrete state from the earlier frame', () => {
    const t = (frames[11].t_s + frames[12].t_s) / 2;
    expect(stateAt(frames, t)[0].leg_index).toBe(frames[11].vessels[0].leg_index);
  });
});

describe('playback clock', () => {
  it('advances by wall time times speed and stops at the end', () => {
    let c = { t: 0, playing: true, speed: 10 };
    c = advanceClock(c, 2, 100);
    expect(c).toEqual({ t: 20, playing: true, speed: 10 });
    c = advanceClock(c, 1000, 100);
    expect(c).toEqual({ t: 100, playing: false, speed: 10 });
  });
  it('does nothing when paused and bounds the speed to 1..60', () => {
    const c = { t: 5, playing: false, speed: 1 };
    expect(advanceClock(c, 10, 100)).toBe(c);
    expect([clampSpeed(0), clampSpeed(500), clampSpeed(7)]).toEqual([1, 60, 7]);
  });
});

describe('trails', () => {
  it('only include frames up to the playhead and end at the current position', () => {
    const now = { lat: 1, lon: 2 };
    const t = trailPoints(frames, 'MOCK-A', frames[4].t_s, now);
    expect(t).toHaveLength(6);
    expect(t.at(-1)).toEqual(now);
  });
  it('are capped', () => {
    const many = Array.from({ length: 5000 }, (_, i) => ({ t_s: i, vessels: [{ ...frames[0].vessels[0], lat: i * 1e-5 }] }));
    expect(trailPoints(many, 'MOCK-A', 1e9, null).length).toBeLessThanOrEqual(MAX_TRAIL_POINTS);
  });
});


it('plays a dateline crossing along the short path, retaining endpoint coordinates', () => {
  const mk = (t: number, lon: number) => ({ t_s: t, vessels: [{ ...frames[0].vessels[0], lon }] });
  const crossing = [mk(0, 179.99), mk(10, -179.99)];
  expect(Math.abs(stateAt(crossing, 5)[0].lon)).toBeCloseTo(180, 9);
  expect(stateAt(crossing, 0)[0].lon).toBe(179.99);
  expect(stateAt(crossing, 10)[0].lon).toBe(-179.99);
});
