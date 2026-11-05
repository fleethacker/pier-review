import { describe, expect, it } from 'vitest';
import {
  bearingToLocalAngle,
  constrainMove,
  enuToFrame,
  entityToFrame,
  frameToEnu,
  localAngleToBearing,
  resolveAnchor,
  sceneBounds,
  topDownHeadingDeg,
} from './geometry';
import type { LocalFrame, SceneEntity } from './types';

// Pier 12 North face: +x runs along bearing 105, so +y (into the water) is bearing 15.
const frame: LocalFrame = { lonDeg: -76.3305, latDeg: 36.9585, xBearingTrueDeg: 105 };

describe('frame conversions', () => {
  it('points +x along the x bearing and +y along bearing - 90', () => {
    const [e, n] = frameToEnu(frame, 1, 0);
    expect(Math.atan2(e, n) * (180 / Math.PI)).toBeCloseTo(105, 6);
    const [ey, ny] = frameToEnu(frame, 0, 1);
    expect(Math.atan2(ey, ny) * (180 / Math.PI)).toBeCloseTo(15, 6);
  });

  it('round-trips through East/North', () => {
    const [e, n] = frameToEnu(frame, 123, -45);
    const [x, y] = enuToFrame(frame, e, n);
    expect(x).toBeCloseTo(123, 9);
    expect(y).toBeCloseTo(-45, 9);
  });

  it('maps wind and current bearings to local angles and back', () => {
    // A direction along the x axis has bearing 105 and local angle 0.
    expect(bearingToLocalAngle(frame, 105)).toBeCloseTo(0);
    // Bearing 15 is +y, local angle 90.
    expect(bearingToLocalAngle(frame, 15)).toBeCloseTo(90);
    expect(localAngleToBearing(frame, bearingToLocalAngle(frame, 227))).toBeCloseTo(227);
  });

  it('uses bearing - 90 for the top-down camera heading', () => {
    expect(topDownHeadingDeg(frame)).toBe(15);
    expect(topDownHeadingDeg({ ...frame, xBearingTrueDeg: 45 })).toBe(315);
  });
});

describe('entity and anchor geometry', () => {
  const ship: SceneEntity = {
    id: 'ship',
    kind: 'ship',
    pose: { x: 100, y: 20, z: 0, headingDeg: 180 },
    geometry: { type: 'polygon', points: [[10, 0], [-10, 5], [-10, -5]], heightM: 5 },
  };

  it('rotates entity-local points by heading', () => {
    const [x, y] = entityToFrame(ship.pose, 10, 0);
    expect(x).toBeCloseTo(90);
    expect(y).toBeCloseTo(20);
  });

  it('follows the entity when it moves', () => {
    const anchor = { entityId: 'ship', x: 10, y: 0, z: 7 };
    expect(resolveAnchor(anchor, { ship })).toEqual([90, expect.closeTo(20), 7]);
    const moved = { ...ship, pose: { ...ship.pose, x: 300 } };
    expect(resolveAnchor(anchor, { ship: moved })![0]).toBeCloseTo(290);
    expect(resolveAnchor({ entityId: 'gone', x: 0, y: 0, z: 0 }, { ship })).toBeNull();
  });

  it('computes scene bounds from rotated footprints', () => {
    const b = sceneBounds([ship])!;
    expect(b.minX).toBeCloseTo(90);
    expect(b.maxX).toBeCloseTo(110);
  });
});

describe('constrainMove', () => {
  const start = { x: 100, y: 20, z: 0, headingDeg: 0 };
  it('locks the other axis', () => {
    expect(constrainMove({ x: 150, y: 90 }, start, { moveAxis: 'x' })).toEqual({ x: 150, y: 20 });
  });
  it('snaps then clamps to bounds', () => {
    const policy = { moveAxis: 'x' as const, snapM: 5, bounds: { minX: 0, maxX: 200 } };
    expect(constrainMove({ x: 152.4, y: 0 }, start, policy).x).toBe(150);
    expect(constrainMove({ x: 900, y: 0 }, start, policy).x).toBe(200);
    expect(constrainMove({ x: -30, y: 0 }, start, policy).x).toBe(0);
  });
});
