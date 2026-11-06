import { memo, useEffect, useMemo, useState } from 'react';

export type BasemapKind = 'schematic' | 'satellite' | 'street';
export interface MapOrigin { lat: number; lon: number; bearingDeg: number }
export interface MapBounds { x: number; y: number; w: number; h: number }

// WGS84 ellipsoid, matching modeling/mooring/transit/geo.py LocalPlane.
// This is the model's declared first-order local plane, not an ECEF/ENU transform.
const R = 6378137;
const FLATTENING = 1 / 298.257223563;
const E2 = FLATTENING * (2 - FLATTENING);
const DEG = Math.PI / 180;
const FT_TO_M = 0.3048;
const TILE_PX = 256;
const STRIP_PX = 32;
const MERCATOR_LAT_LIMIT = 85.0511287798066;

function localScale(origin: MapOrigin) {
  const phi = origin.lat * DEG;
  const w = Math.sqrt(1 - E2 * Math.sin(phi) ** 2);
  return { eastPerDeg: DEG * R / w * Math.cos(phi), northPerDeg: DEG * R * (1 - E2) / w ** 3 };
}

/** WGS84 to the same berth plane used by backend route and scene geometry. */
export function geographicToBerth(origin: MapOrigin, lat: number, lon: number): { x: number; y: number } {
  const scale = localScale(origin);
  const east = (((lon - origin.lon + 540) % 360) - 180) * scale.eastPerDeg / FT_TO_M;
  const north = (lat - origin.lat) * scale.northPerDeg / FT_TO_M;
  const a = origin.bearingDeg * DEG;
  return { x: east * Math.sin(a) + north * Math.cos(a), y: -east * Math.cos(a) + north * Math.sin(a) };
}

export function berthToGeographic(origin: MapOrigin, x: number, y: number): { lat: number; lon: number } {
  const scale = localScale(origin);
  const a = origin.bearingDeg * DEG;
  const east = FT_TO_M * (x * Math.sin(a) - y * Math.cos(a));
  const north = FT_TO_M * (x * Math.cos(a) + y * Math.sin(a));
  return { lat: origin.lat + north / scale.northPerDeg, lon: ((origin.lon + east / scale.eastPerDeg + 540) % 360) - 180 };
}

function worldPixel(lat: number, lon: number, size: number) {
  const latitude = Math.max(-MERCATOR_LAT_LIMIT, Math.min(MERCATOR_LAT_LIMIT, lat));
  return { x: (lon + 180) / 360 * size, y: (1 - Math.asinh(Math.tan(latitude * DEG)) / Math.PI) / 2 * size };
}

/** Display projection only. Latitude strips avoid one affine approximation over the channel route. */
export function rasterTiles(origin: MapOrigin, bounds: MapBounds, kind: Exclude<BasemapKind, 'schematic'>) {
  const cosine = Math.cos(origin.lat * DEG);
  const spanM = Math.max(bounds.w, bounds.h) * FT_TO_M;
  const zoom = Math.max(0, Math.min(19, Math.floor(Math.log2(2 * Math.PI * R * cosine / Math.max(spanM / 3, 1)))));
  const size = TILE_PX * 2 ** zoom;
  const corners = [[bounds.x, bounds.y], [bounds.x + bounds.w, bounds.y], [bounds.x, bounds.y + bounds.h], [bounds.x + bounds.w, bounds.y + bounds.h]];
  const pixels = corners.map(([x, y]) => { const p = berthToGeographic(origin, x, y); return worldPixel(p.lat, p.lon, size); });
  const x0 = Math.max(0, Math.floor(Math.min(...pixels.map((p) => p.x)) / TILE_PX));
  const x1 = Math.min(2 ** zoom - 1, Math.floor(Math.max(...pixels.map((p) => p.x)) / TILE_PX));
  const y0 = Math.max(0, Math.floor(Math.min(...pixels.map((p) => p.y)) / TILE_PX));
  const y1 = Math.min(2 ** zoom - 1, Math.floor(Math.max(...pixels.map((p) => p.y)) / TILE_PX));
  const scale = localScale(origin);
  const eastAt = (px: number) => (px / size * 360 - 180 - origin.lon) * scale.eastPerDeg / FT_TO_M;
  const southAt = (py: number) => -(Math.atan(Math.sinh(Math.PI * (1 - 2 * py / size))) / DEG - origin.lat) * scale.northPerDeg / FT_TO_M;
  const tiles: { key: string; url: string; x: number; y: number; strips: { sourceY: number; x: number; y: number; w: number; h: number }[] }[] = [];
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    const px = x * TILE_PX, py = y * TILE_PX;
    const strips = Array.from({ length: TILE_PX / STRIP_PX }, (_, i) => {
      const sourceY = i * STRIP_PX;
      return { sourceY, x: eastAt(px), y: southAt(py + sourceY), w: eastAt(px + TILE_PX) - eastAt(px), h: southAt(py + sourceY + STRIP_PX) - southAt(py + sourceY) };
    });
    tiles.push({ key: `${kind}/${zoom}/${x}/${y}`, x: px, y: py, strips,
      url: kind === 'satellite' ? `https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${zoom}/${y}/${x}` : `https://tile.openstreetmap.org/${zoom}/${x}/${y}.png` });
  }
  // East/south feet to berth x/y. The parent SVG uses a y-up world group.
  const a = origin.bearingDeg * DEG;
  return { tiles, transform: `matrix(${Math.sin(a)} ${-Math.cos(a)} ${-Math.cos(a)} ${-Math.sin(a)} 0 0)` };
}

export const RasterLayer = memo(function RasterLayer({ kind, origin, bounds, onStatus }: { kind: Exclude<BasemapKind, 'schematic'>; origin: MapOrigin; bounds: MapBounds; onStatus: (message: string) => void }) {
  const { lat, lon, bearingDeg } = origin;
  const { x, y, w, h } = bounds;
  const layer = useMemo(() => rasterTiles({ lat, lon, bearingDeg }, { x, y, w, h }, kind), [lat, lon, bearingDeg, x, y, w, h, kind]);
  const [states, setStates] = useState<Record<string, 'loaded' | 'failed'>>({});
  const loaded = layer.tiles.filter((t) => states[t.key] === 'loaded').length;
  const failed = layer.tiles.filter((t) => states[t.key] === 'failed').length;
  useEffect(() => {
    onStatus(failed ? `Imagery incomplete (${failed} tiles unavailable). Schematic remains visible.` : loaded === layer.tiles.length ? 'Imagery loaded · archived background, not live traffic or a nautical chart.' : 'Loading imagery… schematic remains available.');
  }, [failed, loaded, layer.tiles.length, onStatus]);
  return <g transform={layer.transform} opacity={0.72} aria-label={`${kind} basemap`}>
    {layer.tiles.map((t) => <g key={t.key}>{t.strips.map((strip) => <svg key={strip.sourceY} x={strip.x} y={strip.y} width={strip.w} height={strip.h} viewBox={`0 ${strip.sourceY} ${TILE_PX} ${STRIP_PX}`} preserveAspectRatio="none" overflow="hidden">
      <image href={t.url} x={0} y={0} width={TILE_PX} height={TILE_PX} onLoad={() => setStates((s) => s[t.key] === 'loaded' ? s : ({ ...s, [t.key]: 'loaded' }))} onError={() => setStates((s) => s[t.key] === 'failed' ? s : ({ ...s, [t.key]: 'failed' }))} />
    </svg>)}</g>)}
  </g>;
}, (a, b) => a.kind === b.kind && a.onStatus === b.onStatus
  && a.origin.lat === b.origin.lat && a.origin.lon === b.origin.lon && a.origin.bearingDeg === b.origin.bearingDeg
  && a.bounds.x === b.bounds.x && a.bounds.y === b.bounds.y && a.bounds.w === b.bounds.w && a.bounds.h === b.bounds.h);

export function BasemapCredit({ kind }: { kind: BasemapKind }) {
  if (kind === 'schematic') return <span>Offline schematic · supplied scenario geometry</span>;
  return kind === 'satellite'
    ? <a href="https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer" target="_blank" rel="noreferrer" className="underline">Imagery © Esri, Vantor, Earthstar Geographics, GIS User Community</a>
    : <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" className="underline">© OpenStreetMap contributors</a>;
}
