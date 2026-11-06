import { describe, expect, it } from 'vitest';
import { berthToGeographic, geographicToBerth, rasterTiles, type MapOrigin } from './basemap';

const north = { lat: 36.957533, lon: -76.331655, bearingDeg: 99.5 };
const south = { lat: 36.956497, lon: -76.327035, bearingDeg: 279.5 };

describe('Motion geographic frame agreement', () => {
  // Fixed Norfolk origins and geographic points from the berth catalog and authored route.
  // Expected feet were evaluated independently in the backend WGS84 LocalPlane.
  it.each([
    [north, 36.995, -76.045, 80359.03802026073, 27278.811569548347],
    [north, 36.95736648563323, -76.32927463240735, 696, 55],
    [south, 36.995, -76.045, -78966.4537163344, -27428.22022945697],
    [south, 36.957533, -76.331655, 1393.7037413212947, -149.22374918324928],
  ] as const)('agrees at fixed berth and channel control points', (origin, lat, lon, x, y) => {
    const p = geographicToBerth(origin, lat, lon);
    expect(p.x).toBeCloseTo(x, 5);
    expect(p.y).toBeCloseTo(y, 5);
    const g = berthToGeographic(origin, x, y);
    expect(g.lat).toBeCloseTo(lat, 10);
    expect(g.lon).toBeCloseTo(lon, 10);
  });

  it.each([0, 90, 180, 270])('preserves the handed berth convention at bearing %s', (bearingDeg) => {
    const origin = { ...north, bearingDeg };
    const east = geographicToBerth(origin, north.lat, north.lon + 0.001);
    const northward = geographicToBerth(origin, north.lat + 0.001, north.lon);
    const a = bearingDeg * Math.PI / 180;
    expect(east.x / Math.hypot(east.x, east.y)).toBeCloseTo(Math.sin(a), 10);
    expect(east.y / Math.hypot(east.x, east.y)).toBeCloseTo(-Math.cos(a), 10);
    expect(northward.x / Math.hypot(northward.x, northward.y)).toBeCloseTo(Math.cos(a), 10);
    expect(northward.y / Math.hypot(northward.x, northward.y)).toBeCloseTo(Math.sin(a), 10);
  });

  // Locate the source raster pixel with the published slippy-map equations, then
  // evaluate its displayed strip. This catches an aligned route over misaligned imagery.
  function displayedPoint(origin: MapOrigin, lat: number, lon: number, span: number) {
    const p = geographicToBerth(origin, lat, lon);
    const layer = rasterTiles(origin, { x: p.x - span / 2, y: p.y - span / 2, w: span, h: span }, 'satellite');
    const zoom = Number(layer.tiles[0].key.split('/')[1]);
    const size = 256 * 2 ** zoom;
    const px = (lon + 180) / 360 * size;
    const py = (1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2 * size;
    const tile = layer.tiles.find((t) => px >= t.x && px < t.x + 256 && py >= t.y && py < t.y + 256)!;
    expect(tile).toBeDefined();
    const row = tile.strips.find((s) => py - tile.y >= s.sourceY && py - tile.y < s.sourceY + 32)!;
    const east = row.x + (px - tile.x) / 256 * row.w;
    const southward = row.y + (py - tile.y - row.sourceY) / 32 * row.h;
    const matrix = layer.transform.match(/matrix\((.*)\)/)![1].split(' ').map(Number);
    return { expected: p, drawn: { x: matrix[0] * east + matrix[2] * southward, y: matrix[1] * east + matrix[3] * southward }, tiles: layer.tiles.length };
  }

  it.each([north, south])('aligns imagery throughout Norfolk at close and route scales', (origin) => {
    for (const [lat, lon] of [[36.995, -76.045], [36.969, -76.330], [36.957533, -76.331655]]) {
      for (const span of [1800, 116508]) {
        const { expected, drawn, tiles } = displayedPoint(origin, lat, lon, span);
        // Less than 0.5 m interpolation error in the Norfolk demo extent. This
        // is image-to-model agreement, not a claim of geodesic/navigation accuracy.
        expect(Math.hypot(drawn.x - expected.x, drawn.y - expected.y) * 0.3048).toBeLessThan(0.5);
        expect(tiles).toBeLessThan(80);
      }
    }
  });

  it('keeps tile demand bounded when zooming out beyond the Norfolk route', () => {
    for (const span of [1000, 100000, 1000000, 10000000]) {
      const layer = rasterTiles(north, { x: -span / 2, y: -span / 2, w: span, h: span }, 'street');
      expect(layer.tiles.length).toBeGreaterThan(0);
      expect(layer.tiles.length).toBeLessThan(80);
    }
  });
});
