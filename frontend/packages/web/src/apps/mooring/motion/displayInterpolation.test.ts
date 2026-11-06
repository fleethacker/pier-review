import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { adaptFrame } from './frames';
import type { SimFrame, ViewFrame } from './frames';
import { angleBetween, interpolateGeometry, MotionDisplayBuffer } from './displayInterpolation';
const raw = JSON.parse(readFileSync(path.resolve(__dirname, '../../../../../../../contract/examples/modeling/sim_frame.json'), 'utf8')) as SimFrame;
const frame = (t: number, x: number, yaw = 0): ViewFrame => {
  const base = adaptFrame(raw, { faceBearingDeg: 90 });
  return { ...base, tS: t, runId: 'run', sceneId: 'scene', sceneRevision: '1', badge: { ...base.badge, validity: 'limited' }, ship: { ...base.ship, x_ft: x, y_ft: 0, yawDeg: yaw, headingTrueDeg: (90 - yaw + 360) % 360, surgeFps: t } };
};
function freeze<T>(value: T): T {
  if (value && typeof value === 'object') { Object.freeze(value); Object.values(value).forEach(freeze); }
  return value;
}
describe('Bounded display interpolation', () => {
  it('draws over 30 distinct positions per second from a healthy 10 Hz stream without changing its clock or velocities', () => {
    const buffer = new MotionDisplayBuffer();
    let latest = frame(0, 0), received = -1;
    const positions = new Set<number>();
    for (let wall = 0; wall <= 2000; wall += 1000 / 60) {
      const tick = Math.floor(wall / 100);
      if (tick !== received) { received = tick; latest = frame(tick / 10, tick * 10); buffer.push(latest, tick * 100, true); }
      const drawn = buffer.sample(latest, wall);
      expect(drawn.tS).toBe(latest.tS);
      expect(drawn.ship.surgeFps).toBe(latest.ship.surgeFps);
      expect(drawn.ship.x_ft).toBeLessThanOrEqual(latest.ship.x_ft);
      if (wall > 1000) positions.add(drawn.ship.x_ft);
    }
    expect(positions.size).toBeGreaterThanOrEqual(50);
  });
  it('never extrapolates during a gap and snaps when an excessively delayed frame arrives', () => {
    const buffer = new MotionDisplayBuffer(), a = frame(0, 0), b = frame(0.1, 10), c = frame(1, 100);
    buffer.push(a, 0, true); buffer.push(b, 100, true);
    expect(buffer.sample(b, 500)).toBe(b);
    expect(buffer.sample(b, 900)).toBe(b);
    buffer.push(c, 1000, true);
    expect(buffer.sample(c, 1000)).toBe(c);
  });
  it.each(['paused', 'run', 'scene', 'invalid', 'rewind'] as const)('snaps and clears the interpolation history on %s', (event) => {
    const buffer = new MotionDisplayBuffer(), a = frame(0, 0), b = frame(0.1, 10);
    buffer.push(a, 0, true); buffer.push(b, 100, true);
    const next = frame(0.2, 20);
    if (event === 'run') next.runId = 'new-run';
    if (event === 'scene') next.sceneRevision = '2';
    if (event === 'invalid') next.badge.validity = 'invalid';
    if (event === 'rewind') next.tS = 0;
    buffer.push(next, 200, event !== 'paused');
    expect(buffer.sample(next, 200)).toBe(next);
  });
  it('uses shortest-angle turns and keeps line attachments coherent without mutating evidence', () => {
    expect(angleBetween(359, 1, 0.5)).toBe(0);
    expect(angleBetween(1079, 1, 0.5)).toBe(0);
    const a = frame(0, 0, 0), b = frame(0.1, 100, 90);
    a.lines = [{ ...a.lines[0], shipEnd: { x: 10, y: 0 }, pierEnd: { x: 200, y: 0 }, polyline: [{ x: 10, y: 0 }, { x: 200, y: 0 }] }];
    b.lines = [{ ...b.lines[0], shipEnd: { x: 100, y: 10 }, pierEnd: { x: 200, y: 0 }, polyline: [{ x: 100, y: 10 }, { x: 150, y: 5 }, { x: 200, y: 0 }], status: 'overloaded', tensionLbf: 999 }];
    freeze(a); freeze(b);
    const drawn = interpolateGeometry(a, b, b, 0.5);
    expect(drawn.ship.x_ft).toBe(50); expect(drawn.ship.yawDeg).toBe(45);
    expect(drawn.lines[0].shipEnd!.x).toBeCloseTo(50 + Math.sqrt(50));
    expect(drawn.lines[0].shipEnd!.y).toBeCloseTo(Math.sqrt(50));
    expect(drawn.lines[0].status).toBe('overloaded'); expect(drawn.lines[0].tensionLbf).toBe(999);
    expect(b.lines[0].polyline![0]).toEqual({ x: 100, y: 10 });
  });

  it('moves tug poses and hull force application points while retaining the newest force and availability', () => {
    const a = frame(0, 0), b = frame(0.1, 100);
    a.tugs = [{ ...a.tugs[0], id: 'T1', position: { x: 0, y: 10 }, headingTrueDeg: 359, applicationPoint: { x: 10, y: 0 } }];
    b.tugs = [{ ...b.tugs[0], id: 'T1', position: { x: 100, y: 10 }, headingTrueDeg: 1, applicationPoint: { x: 110, y: 0 }, actualForce: { x: 23, y: 45 }, availability: 'available' }];
    const drawn = interpolateGeometry(a, b, b, 0.5);
    expect(drawn.tugs[0].position).toEqual({ x: 50, y: 10 });
    expect(drawn.tugs[0].headingTrueDeg).toBe(0);
    expect(drawn.tugs[0].applicationPoint).toEqual({ x: 60, y: 0 });
    expect(drawn.tugs[0].actualForce).toBe(b.tugs[0].actualForce);
    expect(drawn.tugs[0].availability).toBe('available');
  });
});
