import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { SimClock, clockText, forcingOf } from './clock';
import type { SimFrame, SimRecording } from './frames';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const recording = JSON.parse(readFileSync(path.join(dir, 'sim_recording_60s.json'), 'utf8')) as SimRecording;
const f = (t: number, run = 'r1', env: Record<string, unknown> | null = null): SimFrame =>
  ({ t_s: t, run_id: run, pose: {}, tugs: [], lines: [], fenders: [], alerts: [], environment: env }) as unknown as SimFrame;

describe('SimClock', () => {
  it('measures simulated seconds per wall second while running', () => {
    const c = new SimClock();
    c.observe(f(0), 0, true);
    c.observe(f(2), 1000, true);
    const v = c.observe(f(4), 2000, true);
    expect(v).toMatchObject({ simS: 4, wallRunningS: 2, effectiveSpeed: 2 });
  });

  it('excludes paused wall time and does not measure a rate across a pause', () => {
    const c = new SimClock();
    c.observe(f(0), 0, true);
    c.observe(f(1), 1000, true);
    c.observe(f(1), 60_000, false);
    const v = c.observe(f(1.1), 60_100, true);
    expect(v.wallRunningS).toBeCloseTo(1, 5);
    expect(v.effectiveSpeed).toBeNull();
  });

  it('starts again on a reset or new run', () => {
    const c = new SimClock();
    c.observe(f(0), 0, true);
    c.observe(f(5), 5000, true);
    expect(c.observe(f(0, 'r2'), 6000, true)).toMatchObject({ simS: 0, wallRunningS: 0, effectiveSpeed: null });
  });
});

describe('forcingOf', () => {
  it('binds a top-level forcing revision to simulation time', () => {
    expect(forcingOf({ ...f(12), forcing_revision: 'series-abc' })).toEqual({ forcingTS: 12, forcingRevision: 'series-abc', training: false });
  });

  it('reports forcing time from the frame and no revision when none is sent', () => {
    expect(forcingOf(f(3, 'r1', { t_s: 3 }))).toEqual({ forcingTS: 3, forcingRevision: null, training: false });
  });

  it('reports nothing when the simulator does not say when forcing applies', () => {
    expect(forcingOf(f(3))).toEqual({ forcingTS: null, forcingRevision: null, training: false });
  });

  it('reads a forcing revision when a simulator publishes one', () => {
    expect(forcingOf(f(3, 'r1', { t_s: 3, forcing_revision: 'gusts-seed7' })).forcingRevision).toBe('gusts-seed7');
  });

  it('labels mock forcing as training', () => {
    expect(forcingOf(f(3, 'r1', { t_s: 3, wind: { provenance: { kind: 'mock' } } })).training).toBe(true);
    expect(forcingOf({ ...recording.frames[10], environment: null }).training).toBe(false);
  });
});

it('formats clock text', () => {
  expect(clockText(65)).toBe('1:05');
  expect(clockText(3723)).toBe('1:02:03');
  expect(clockText(-4)).toBe('0:00');
});

it('does not confuse surrogate body dynamics with synthetic environmental forcing', () => {
  expect(forcingOf({ ...recording.frames[10], environment: { wind: { provenance: { kind: 'measured' } } } } as unknown as SimFrame).training).toBe(false);
});
