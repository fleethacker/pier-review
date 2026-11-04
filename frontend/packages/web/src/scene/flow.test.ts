import { describe, expect, it } from 'vitest';
import { FlowField, flowSpeed } from './flow';

const seeded = () => {
  let s = 7;
  return () => ((s = (s * 16807) % 2147483647) / 2147483647);
};
const region = { cx: 100, cy: 50, halfW: 200, halfH: 80 };

describe('FlowField', () => {
  it('starts inside the region', () => {
    const f = new FlowField(50, region, seeded());
    expect(f.streaks.every((s) => Math.abs(s.x - 100) <= 200 && Math.abs(s.y - 50) <= 80)).toBe(true);
  });

  it('keeps every particle inside while moving, in any direction', () => {
    for (const [dx, dy] of [[1, 0], [0, -1], [Math.SQRT1_2, Math.SQRT1_2], [-0.6, 0.8]]) {
      const f = new FlowField(80, region, seeded());
      for (let i = 0; i < 400; i++) f.step(0.1, dx, dy, 25);
      expect(f.streaks.every((s) => Math.abs(s.x - 100) <= 200.001 && Math.abs(s.y - 50) <= 80.001)).toBe(true);
    }
  });

  it('moves particles along the direction and respawns them on the upwind edge', () => {
    const f = new FlowField(1, { cx: 0, cy: 0, halfW: 10, halfH: 10 }, seeded());
    f.streaks[0].x = 9.5;
    f.streaks[0].y = 0;
    f.step(0.1, 1, 0, 10); // +1 m: leaves through the east edge
    expect(f.streaks[0].x).toBeCloseTo(-10, 6); // back on the west (upwind) edge
    f.streaks[0].x = 0;
    f.step(0.1, 1, 0, 10);
    expect(f.streaks[0].x).toBeCloseTo(1, 6);
  });

  it('follows a region that moves', () => {
    const f = new FlowField(10, region, seeded());
    f.region = { cx: 1000, cy: 1000, halfW: 50, halfH: 50 };
    f.step(0.1, 1, 0, 5);
    expect(f.streaks.every((s) => Math.abs(s.x - 1000) <= 50.001 && Math.abs(s.y - 1000) <= 50.001)).toBe(true);
  });
});

describe('flowSpeed', () => {
  it('is steady without gustiness and swings with it', () => {
    expect(flowSpeed(10, 0, 3)).toBe(10);
    expect(flowSpeed(10, undefined, 3)).toBe(10);
    const samples = Array.from({ length: 60 }, (_, i) => flowSpeed(10, 0.4, i * 0.3));
    expect(Math.max(...samples)).toBeGreaterThan(10.5);
    expect(Math.min(...samples)).toBeLessThan(9.5);
  });
});
