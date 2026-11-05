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
  tiltedPolygonRing,
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

describe('tilted poses', () => {
  const level = { x: 10, y: 20, z: 1, headingDeg: 40 };
  const r6 = (n: number) => Math.round(n * 1e6) / 1e6;

  it('is unchanged without roll or pitch, and for explicit zeros', () => {
    expect(entityToFrame({ ...level, rollDeg: 0, pitchDeg: 0 }, 3, 4, 2)).toEqual(entityToFrame(level, 3, 4, 2));
  });

  it('rolls right-hand about local +x: +y rises, +z tips toward -y', () => {
    const p = { ...level, headingDeg: 0, rollDeg: 90 };
    expect(entityToFrame(p, 0, 1, 0).map(r6)).toEqual([10, 20, 2]);
    expect(entityToFrame(p, 0, 0, 1).map(r6)).toEqual([10, 19, 1]);
  });

  it('pitches right-hand about local +y: +x drops, +z tips toward +x', () => {
    const p = { ...level, headingDeg: 0, pitchDeg: 90 };
    expect(entityToFrame(p, 1, 0, 0).map(r6)).toEqual([10, 20, 0]);
    expect(entityToFrame(p, 0, 0, 1).map(r6)).toEqual([11, 20, 1]);
  });

  it('keeps the heading rotation outermost and tilts about the pose origin', () => {
    const p = { ...level, rollDeg: 5 };
    const [x, y] = entityToFrame(p, 10, 0, 0);
    expect(x).toBeCloseTo(10 + 10 * Math.cos((40 * Math.PI) / 180));
    expect(y).toBeCloseTo(20 + 10 * Math.sin((40 * Math.PI) / 180));
    expect(entityToFrame(p, 0, 0, 0)).toEqual([10, 20, 1]);
  });

  it('builds a tilted top ring with a flat bottom kept below it', () => {
    const { ring, bottomZ } = tiltedPolygonRing({ ...level, headingDeg: 0, rollDeg: 5 }, [[-10, -5], [10, -5], [10, 5], [-10, 5]], 6);
    expect(ring).toHaveLength(4);
    expect(ring[2][2]).toBeGreaterThan(ring[1][2]);
    expect(bottomZ).toBeCloseTo(1);
    const steep = tiltedPolygonRing({ ...level, pitchDeg: 40 }, [[-50, 0], [50, 0]], 6);
    expect(steep.bottomZ).toBeLessThan(Math.min(...steep.ring.map((r) => r[2])));
  });

  it('skips entities flagged excludeFromFit when computing bounds', () => {
    const poly = (id: string, half: number, extra = {}) => ({ id, kind: 'k', pose: { x: 0, y: 0, z: 0, headingDeg: 0 }, geometry: { type: 'polygon' as const, points: [[-half, -half], [half, half]] as [number, number][], heightM: 0 }, ...extra });
    expect(sceneBounds([poly('a', 5), poly('w', 300, { excludeFromFit: true })])).toEqual({ minX: -5, maxX: 5, minY: -5, maxY: 5 });
  });
});
