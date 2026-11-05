import { describe, expect, it } from 'vitest';
import { sceneBounds } from '../../scene/geometry';
import { fitAnchors, makeProjector } from './scene';

describe('fitAnchors', () => {
  const p = makeProjector(36.9, -76.2);
  it('spans the bounding box of the points, with a margin, so the shell camera frames the whole track or route', () => {
    const pts = [{ lat: 36.95, lon: -76.33 }, { lat: 37.01, lon: -76.16 }, { lat: 36.97, lon: -76.2 }];
    const b = sceneBounds(fitAnchors(pts, p))!;
    const xy = pts.map((q) => p.toXY(q.lat, q.lon));
    expect(b.minX).toBeLessThan(Math.min(...xy.map((q) => q.x)));
    expect(b.maxX).toBeGreaterThan(Math.max(...xy.map((q) => q.x)));
    expect(b.minY).toBeLessThan(Math.min(...xy.map((q) => q.y)));
    expect(b.maxY).toBeGreaterThan(Math.max(...xy.map((q) => q.y)));
  });
  it('is invisible and unselectable, and empty for no points', () => {
    const [a] = fitAnchors([{ lat: 36.9, lon: -76.2 }], p);
    expect(a).toMatchObject({ opacity: 0, selectable: false });
    expect(fitAnchors([], p)).toEqual([]);
  });
});
