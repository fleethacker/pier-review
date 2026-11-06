import { useEffect, useMemo, useState } from 'react';

export type BasemapKind = 'schematic' | 'satellite' | 'street';
export interface MapOrigin { lat: number; lon: number; bearingDeg: number }
export interface MapBounds { x: number; y: number; w: number; h: number }

const R = 6378137;
const DEG = Math.PI / 180;
const TILE_PX = 256;

/** Display projection only: local berth feet to Web Mercator image pixels. No state integration. */
export function rasterTiles(origin: MapOrigin, bounds: MapBounds, kind: Exclude<BasemapKind, 'schematic'>) {
  const cosine = Math.cos(origin.lat * DEG);
  const spanM = Math.max(bounds.w, bounds.h) * 0.3048;
  const zoom = Math.max(10, Math.min(19, Math.floor(Math.log2(2 * Math.PI * R * cosine / Math.max(spanM / 3, 1)))));
  const circumference = 2 * Math.PI * R;
  const metersPerPixel = circumference / (TILE_PX * 2 ** zoom);
  const pixelFeet = metersPerPixel * cosine / 0.3048;
  const ox = ((origin.lon + 180) / 360) * TILE_PX * 2 ** zoom;
  const oy = (1 - Math.asinh(Math.tan(origin.lat * DEG)) / Math.PI) / 2 * TILE_PX * 2 ** zoom;
  const a = origin.bearingDeg * DEG;
  const sin = Math.sin(a), cos = Math.cos(a);
  const corners = [[bounds.x, bounds.y], [bounds.x + bounds.w, bounds.y], [bounds.x, bounds.y + bounds.h], [bounds.x + bounds.w, bounds.y + bounds.h]];
  const pixels = corners.map(([x, y]) => ({ x: ox + (sin * x - cos * y) / pixelFeet, y: oy - (cos * x + sin * y) / pixelFeet }));
  const x0 = Math.floor(Math.min(...pixels.map((p) => p.x)) / TILE_PX);
  const x1 = Math.floor(Math.max(...pixels.map((p) => p.x)) / TILE_PX);
  const y0 = Math.floor(Math.min(...pixels.map((p) => p.y)) / TILE_PX);
  const y1 = Math.floor(Math.max(...pixels.map((p) => p.y)) / TILE_PX);
  const tiles: { key: string; url: string; x: number; y: number }[] = [];
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    tiles.push({ key: `${kind}/${zoom}/${x}/${y}`, x: x * TILE_PX, y: y * TILE_PX,
      url: kind === 'satellite' ? `https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${zoom}/${y}/${x}` : `https://tile.openstreetmap.org/${zoom}/${x}/${y}.png` });
  }
  // Pixel east/down to berth x/y. Images live inside the SVG's y-up world group.
  const m = [sin * pixelFeet, -cos * pixelFeet, -cos * pixelFeet, -sin * pixelFeet];
  return { tiles, transform: `matrix(${m[0]} ${m[1]} ${m[2]} ${m[3]} ${-m[0] * ox - m[2] * oy} ${-m[1] * ox - m[3] * oy})` };
}

export function RasterLayer({ kind, origin, bounds, onStatus }: { kind: Exclude<BasemapKind, 'schematic'>; origin: MapOrigin; bounds: MapBounds; onStatus: (message: string) => void }) {
  const { lat, lon, bearingDeg } = origin;
  const { x, y, w, h } = bounds;
  const layer = useMemo(() => rasterTiles({ lat, lon, bearingDeg }, { x, y, w, h }, kind), [lat, lon, bearingDeg, x, y, w, h, kind]);
  const [states, setStates] = useState<Record<string, 'loaded' | 'failed'>>({});
  const loaded = layer.tiles.filter((t) => states[t.key] === 'loaded').length;
  const failed = layer.tiles.filter((t) => states[t.key] === 'failed').length;
  useEffect(() => {
    onStatus(failed ? `Imagery incomplete (${failed} tiles unavailable). Schematic remains visible.` : loaded === layer.tiles.length ? 'Imagery loaded · context only, not a nautical chart.' : 'Loading imagery… schematic remains available.');
  }, [failed, loaded, layer.tiles.length, onStatus]);
  return <g transform={layer.transform} opacity={0.72} aria-label={`${kind} basemap`}>
    {layer.tiles.map((t) => <image key={t.key} href={t.url} x={t.x} y={t.y} width={256} height={256} onLoad={() => setStates((s) => ({ ...s, [t.key]: 'loaded' }))} onError={() => setStates((s) => ({ ...s, [t.key]: 'failed' }))} />)}
  </g>;
}

export function BasemapCredit({ kind }: { kind: BasemapKind }) {
  if (kind === 'schematic') return <span>Offline schematic · supplied scenario geometry</span>;
  return kind === 'satellite'
    ? <a href="https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer" target="_blank" rel="noreferrer" className="underline">Imagery © Esri, Vantor, Earthstar Geographics, GIS User Community</a>
    : <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" className="underline">© OpenStreetMap contributors</a>;
}
