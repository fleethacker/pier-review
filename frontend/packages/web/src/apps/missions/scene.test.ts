import { describe, expect, it } from 'vitest';
import { sampleStoryboard } from './fixtures';
import { prepareTrack } from './geo';
import { sceneBounds } from '../../scene/geometry';
import { centroid, fitAnchors, makeProjector, storyboardContent } from './scene';

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


it('centers and projects a dateline crossing as a local 2.2 km path', () => {
  const points = [{ lat: 0, lon: 179.99 }, { lat: 0, lon: -179.99 }];
  const center = centroid(points);
  expect(Math.abs(center.lon)).toBeCloseTo(180, 9);
  const p = makeProjector(center.lat, center.lon);
  const [a, b] = points.map((point) => p.toXY(point.lat, point.lon));
  expect(Math.abs(b.x - a.x)).toBeCloseTo(2222.64, 2);
  expect(Math.max(Math.abs(a.x), Math.abs(b.x))).toBeLessThan(1200);
});


describe('display geometry and recording coverage', () => {
  const start = Date.parse('2026-11-05T12:00:00Z');
  const fixes = Array.from({ length: 2001 }, (_, i) => ({
    t_utc: new Date(start + i * 100).toISOString(), lat: 0, lon: i * 1e-6, quality: 'good' as const,
  }));
  const sb = { ...sampleStoryboard, max_interp_gap_s: 1, track: [fixes[0], fixes.at(-1)!] };
  it('does not invent a recording gap from display decimation', () => {
    const { links } = storyboardContent(sb, makeProjector(0, 0), null, prepareTrack(fixes));
    expect(links).toHaveLength(1);
    expect(links[0].kind).toBe('track');
  });
  it('dims a display segment that contains a real recording gap', () => {
    const original = fixes.filter((_, i) => i < 500 || i > 1500);
    const { links } = storyboardContent(sb, makeProjector(0, 0), null, prepareTrack(original));
    expect(links[0].kind).toBe('track-gap');
  });
  it('does not imply continuous coverage when only display geometry is available', () => {
    const { links } = storyboardContent(sb, makeProjector(0, 0), null);
    expect(links[0].kind).toBe('track-gap');
  });
});


it('does not draw a nonunique antipodal interval as continuous recorded geometry', () => {
  const track = [
    { t_utc: '2026-11-05T12:00:00Z', lat: 0, lon: 0, quality: 'good' as const },
    { t_utc: '2026-11-05T12:01:00Z', lat: 0, lon: 180, quality: 'good' as const },
  ];
  const { links } = storyboardContent({ ...sampleStoryboard, track }, makeProjector(0, 0), null, prepareTrack(track));
  expect(links).toHaveLength(1);
  expect(links[0].kind).toBe('track-gap');
});
