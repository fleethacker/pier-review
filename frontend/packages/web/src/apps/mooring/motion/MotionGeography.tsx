import { memo, useMemo } from 'react';
import type { SimScene } from './frames';

type Context = NonNullable<SimScene['geographic_context']>;
type Point = { x_ft?: number | null; y_ft?: number | null };
const finite = (p: Point) => Number.isFinite(p.x_ft) && Number.isFinite(p.y_ft);

/** Preserve holes and open source lines. Malformed geometry never becomes an inferred land area. */
export function contextPaths(context: Context) {
  return context.features.flatMap((feature) => {
    const polygon = feature.geometry_type === 'Polygon';
    const valid = feature.rings.length > 0 && feature.rings.every((ring) => ring.length >= (polygon ? 4 : 2) && ring.every(finite)
      && (!polygon || ring[0].x_ft === ring.at(-1)!.x_ft && ring[0].y_ft === ring.at(-1)!.y_ft));
    if (!valid) return [];
    const d = feature.rings.map((ring) => `M ${ring.map((p) => `${p.x_ft},${p.y_ft}`).join(' L ')}${polygon ? ' Z' : ''}`).join(' ');
    return [{ ...feature, d, polygon }];
  });
}

export const GeographicContextLayer = memo(function GeographicContextLayer({ context, imagery }: { context: Context; imagery: boolean }) {
  const paths = useMemo(() => contextPaths(context), [context]);
  const coverage = context.coverage_outline;
  const boundedCoverage = coverage.length > 3 && coverage.every(finite) && coverage[0].x_ft === coverage.at(-1)!.x_ft && coverage[0].y_ft === coverage.at(-1)!.y_ft;
  return <g aria-label="Supplied geographic context — partial coverage, not hazard clearance">
    {paths.map((feature) => <path key={feature.feature_id} aria-label={`${feature.name ?? feature.kind} · supplied ${feature.geometry_type}`} d={feature.d}
      fill={feature.polygon && !imagery ? '#47534d' : 'none'} fillRule="evenodd" fillOpacity={0.95}
      stroke={imagery ? '#e7dcc2' : '#a8b8a1'} strokeOpacity={imagery ? 0.65 : 0.9} strokeWidth={feature.kind === 'shoreline_construction' ? 1.6 : 1}
      vectorEffect="non-scaling-stroke"><title>{feature.name ?? feature.kind} · source date {feature.source_date ?? 'unknown'} · context only</title></path>)}
    {boundedCoverage && <path aria-label="Geographic dataset boundary — coverage inside remains partial" d={`M ${coverage.map((p) => `${p.x_ft},${p.y_ft}`).join(' L ')} Z`} fill="none" stroke="#c9a2df" strokeWidth="1.5" strokeDasharray="9 6" vectorEffect="non-scaling-stroke"><title>Partial geographic dataset extent, not a physical shoreline or navigable-water boundary.</title></path>}
  </g>;
});

export function scaleBar(widthFt: number, heightFt: number, widthPx: number, heightPx: number) {
  if (![widthFt, heightFt, widthPx, heightPx].every((n) => Number.isFinite(n) && n > 0)) return null;
  const feetPerPixel = Math.max(widthFt / widthPx, heightFt / heightPx);
  const desired = feetPerPixel * 95;
  const power = 10 ** Math.floor(Math.log10(desired));
  const feet = [1, 2, 5, 10].map((n) => n * power).filter((n) => n <= desired).at(-1) ?? power;
  return { feet, pixels: feet / feetPerPixel };
}

export function GeographyScale({ faceBearingDeg, scale }: { faceBearingDeg: number; scale: ReturnType<typeof scaleBar> }) {
  const a = faceBearingDeg * Math.PI / 180;
  const north = { x: Math.cos(a), y: -Math.sin(a) };
  const tip = { x: 148 + north.x * 20, y: 26 + north.y * 20 };
  return <svg width="190" height="52" viewBox="0 0 190 52" role="img" aria-label="Physical distance scale and true north" className="text-mil-text">
    {scale ? <g aria-label={`${scale.feet} feet distance scale`}>
      <text x="8" y="18" fill="currentColor" fontSize="9">{scale.feet.toLocaleString()} ft · {(scale.feet * 0.3048).toLocaleString(undefined, { maximumFractionDigits: 1 })} m</text>
      <path d={`M 8,25 v 7 h ${scale.pixels} v -7`} fill="none" stroke="currentColor" strokeWidth="2" />
    </g> : <text x="8" y="28" fill="currentColor" fontSize="9">Scale awaiting view size</text>}
    <g aria-label="True north" data-north-x={north.x} data-north-y={north.y}>
      <line x1="148" y1="26" x2={tip.x} y2={tip.y} stroke="#e7dcc2" strokeWidth="2" />
      <polygon points={`${tip.x},${tip.y} ${tip.x - north.x * 8 - north.y * 4},${tip.y - north.y * 8 + north.x * 4} ${tip.x - north.x * 8 + north.y * 4},${tip.y - north.y * 8 - north.x * 4}`} fill="#e7dcc2" />
      <text x="148" y="48" textAnchor="middle" fill="#e7dcc2" fontSize="9">TRUE N</text>
    </g>
  </svg>;
}
