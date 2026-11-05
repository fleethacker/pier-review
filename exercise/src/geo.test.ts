import { describe, expect, it } from 'vitest';
import {
  angleDiff,
  bearingTo,
  circleRing,
  destination,
  distanceM,
  formatClock,
  formatLatLon,
  ktToMs,
  normalizeBearing,
  offsetM,
  stationFrom,
} from './geo';

const origin = { lon: -62, lat: 33 };

describe('geo', () => {
  it('measures a degree of latitude as about 111 km', () => {
    const d = distanceM(origin, { lon: -62, lat: 34 });
    expect(d).toBeGreaterThan(111_000);
    expect(d).toBeLessThan(111_400);
  });

  it('converts knots to meters per second', () => {
    expect(ktToMs(1)).toBeCloseTo(0.5144, 3);
  });

  it('round-trips destination, distance and bearing', () => {
    for (const bearing of [0, 37, 90, 181, 275]) {
      const p = destination(origin, bearing, 20_000);
      expect(distanceM(origin, p)).toBeCloseTo(20_000, 0);
      expect(bearingTo(origin, p)).toBeCloseTo(bearing, 1);
    }
  });

  it('normalizes bearings and takes the short way round', () => {
    expect(normalizeBearing(-10)).toBe(350);
    expect(normalizeBearing(370)).toBe(10);
    expect(angleDiff(10, 350)).toBe(20);
    expect(angleDiff(350, 10)).toBe(-20);
    expect(angleDiff(180, 0)).toBe(180);
  });

  it('puts stations ahead and to starboard of a heading', () => {
    const north = stationFrom(origin, 0, 1000, 0);
    expect(north.lat).toBeGreaterThan(origin.lat);
    expect(north.lon).toBeCloseTo(origin.lon, 6);
    // Heading north, starboard is east.
    expect(stationFrom(origin, 0, 0, 500).lon).toBeGreaterThan(origin.lon);
    // Heading east, starboard is south and ahead is east.
    const east = stationFrom(origin, 90, 1000, 500);
    expect(east.lon).toBeGreaterThan(origin.lon);
    expect(east.lat).toBeLessThan(origin.lat);
    expect(distanceM(origin, east)).toBeCloseTo(Math.hypot(1000, 500), 0);
  });

  it('offsets in meters east and north', () => {
    const p = offsetM(origin, 1000, 2000);
    expect(distanceM(origin, p)).toBeCloseTo(Math.hypot(1000, 2000), 0);
    expect(bearingTo(origin, p)).toBeCloseTo((Math.atan2(1000, 2000) * 180) / Math.PI, 1);
  });

  it('draws a closed ring at the requested radius', () => {
    const ring = circleRing(origin, 5000, 16);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    for (const [lon, lat] of ring) expect(distanceM(origin, { lon, lat })).toBeCloseTo(5000, 0);
  });

  it('formats clocks and positions', () => {
    expect(formatClock(0)).toBe('00:00:00');
    expect(formatClock(3725)).toBe('01:02:05');
    expect(formatLatLon({ lon: -62.5, lat: 33.25 })).toBe("33°15.00'N 062°30.00'W");
  });
});
