import { useId } from 'react';
import type { MotionState } from './controller';
import { sectionSilhouette } from './sectionSilhouette';
import type { SectionPoint, SectionView } from './sectionSilhouette';

export type { SectionView } from './sectionSilhouette';
const fmt = (v: number | null | undefined, unit: string) => v == null ? 'unavailable' : `${v.toFixed(2)} ${unit}`;

export function SectionViews({ s, view, compact = false }: { s: MotionState; view: SectionView; compact?: boolean }) {
  const underwaterId = useId();
  const frame = s.frame;
  const loading = frame?.loading;
  const ship = s.workspace?.ship;
  if (!frame || !loading || !ship) return <div className="flex h-full items-center justify-center p-3 text-center text-xs text-mil-dim">Section view unavailable. This session has no backend loading and vessel geometry state.</div>;
  const condition = ship.loading_conditions.find((x) => x.name === s.workspace?.scenario.configuration.loading);
  const freeboard = condition?.freeboard_ft;
  const usable = (loading.validity.state === 'valid' || loading.validity.state === 'limited') && (frame.badge.validity === 'valid' || frame.badge.validity === 'limited');
  const clearanceInvalid = loading.validity.state === 'invalid' || (loading.under_keel_ft != null && loading.under_keel_ft <= 0) || (loading.under_keel_lower_ft != null && loading.under_keel_lower_ft <= 0);
  const water = frame.environment?.water.available ? frame.environment.water.levelMllwFt : null;
  const depth = loading.local_depth_mllw_ft;
  const side = view === 'side';
  const extent = side ? ship.loa_ft : ship.beam_ft;
  const half = extent / 2;
  const roll = frame.ship.rollDeg;
  const pitch = frame.ship.pitchDeg;
  const draft = view === 'forward' ? loading.draft_fwd_ft : loading.draft_aft_ft;
  const hullType = ship.hull_type ?? ship.class_id.split('-')[0];
  const carrier = ['CVN', 'LHD', 'LHA'].includes(hullType);
  const topsides = freeboard == null ? [] : sectionSilhouette(hullType, view, ship.loa_ft, ship.beam_ft, freeboard);
  const maxTop = Math.max(30, ...topsides.flatMap(part => part.points.map(([, z]) => z)));
  const maxBottom = Math.max(loading.maximum_draft_ft, depth != null && water != null ? depth + water : 0, 30);
  // One feet-to-pixel scale preserves recognizable vessel proportions in every elevation.
  const sy = Math.min(700 / extent, 150 / maxTop, 145 / maxBottom);
  const sx = sy;
  const x = (n: number) => 450 + n * sx;
  const y = (n: number) => 205 - n * sy;
  const angle = (side ? -(pitch ?? 0) : view === 'forward' ? (roll ?? 0) : -(roll ?? 0)) * Math.PI / 180;
  // Reference-waterline body coordinates: sinkage moves deck, CG and payloads together.
  // End views use the supplied end-draft offset, not an additional pitch rotation.
  const offset = -loading.sinkage_ft - (side ? 0 : draft - loading.mean_draft_ft);
  const project = (h: number, z: number): SectionPoint => [x(h * Math.cos(angle) - z * Math.sin(angle)), y(h * Math.sin(angle) + z * Math.cos(angle) + offset)];
  const points = (values: SectionPoint[]) => values.map(([h, z]) => project(h, z).join(',')).join(' ');
  // Draft outputs already include trim: draw the modeled envelope directly, never pitch it twice.
  const keel: SectionPoint[] = side
    ? [[x(-half), y(-loading.draft_aft_ft)], [x(half), y(-loading.draft_fwd_ft)]]
    : [-half, half].map(h => [x(h * Math.cos(angle)), y(h * Math.sin(angle) - draft)] as SectionPoint);
  let hull: SectionPoint[] | null = null;
  if (freeboard != null) {
    if (side) {
      const aftKeel = keel[0], fwdKeel = keel[1];
      hull = [project(-half, freeboard * 0.86), project(half * 0.91, freeboard), project(half, freeboard), project(half * 0.96, 0),
        [fwdKeel[0] - 28, fwdKeel[1] - 10], [fwdKeel[0] - 65, fwdKeel[1]], [aftKeel[0] + 35, aftKeel[1]], [aftKeel[0] + 9, aftKeel[1] - 14], project(-half, 0)];
    } else {
      // Bow flare / stern transom is artwork inside the explicitly drawn modeled beam/draft envelope.
      const lowerWidth = view === 'forward' ? 0.34 : carrier ? 0.68 : 0.76;
      const projectBelow = (h: number, rise: number): SectionPoint => [x(h * Math.cos(angle)), y(h * Math.sin(angle) - draft + rise)];
      hull = [project(-half, freeboard), project(half, freeboard), project(half * 0.94, 0), projectBelow(half * lowerWidth, 0), projectBelow(-half * lowerWidth, 0), project(-half * 0.94, 0)];
    }
  }
  const hullPoints = hull?.map(p => p.join(',')).join(' ');
  const title = side ? 'Port side elevation' : view === 'forward' ? 'Looking aft from bow' : 'Looking forward from stern';
  const noDepth = `Local seabed / clearance unavailable: ${depth == null ? 'outside supplied depth coverage' : 'water level unavailable'}`;
  const invalidMessage = loading.validity.reasons?.filter(reason => !reason.code.startsWith('SYNTHETIC_')).map(reason => reason.message).join(' ') || 'Loading model is invalid. Supplied depth and clearance evidence remain visible.';
  const profileDetail = 'Illustrative profile. Class artwork is not surveyed hull geometry. Dashed line: modeled draft envelope. Draft, CG, attitude and clearance are backend outputs.';
  const textSize = compact ? (side ? 24 : 16) : 12;
  const sectionBottom = compact ? Math.max(260, y(-maxBottom) + 32) : 390;
  const viewWidth = compact && !side ? Math.max(240, extent * sx + 80) : 900;
  const viewLeft = 450 - viewWidth / 2;
  const labelLeft = compact ? viewLeft + 12 : 30;
  return <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#0b2437]" data-section-view={view} data-vessel-class={hullType}>
    <div className={`flex shrink-0 items-center justify-between gap-1 border-b border-mil-border bg-mil-panel/90 ${compact ? 'px-2 py-0.5 text-[9px]' : 'px-4 py-2 text-[10px]'}`}>
      <span className="truncate uppercase tracking-wider" title={title}>{compact ? (side ? 'Side' : view === 'forward' ? 'Forward' : 'Aft') : title}</span>
      <span className="shrink-0 text-mil-dim" title={loading.source}>{loading.basis} · {loading.validity.state}</span>
    </div>
    <svg role="img" aria-label={`${view} hull, waterline, payload and local seabed section`} viewBox={`${viewLeft} ${compact ? 10 : 0} ${viewWidth} ${sectionBottom - (compact ? 10 : 0)}`} className="min-h-0 w-full flex-1">
      <title>{`${hullType} · ${title} · illustrative profile`}</title>
      <defs><clipPath id={underwaterId}><rect x={0} y={205} width={900} height={185} /></clipPath></defs>
      {water != null && <rect x={0} y={205} width={900} height={185} fill="#0a4261" opacity={0.65} />}
      {depth != null && water != null ? <g data-section-seabed="supplied">
        <path d={`M 25 ${y(-depth - water)} H 875 V 390 H 25 Z`} fill="#645642" opacity={0.8} />
        <line x1={25} y1={y(-depth - water)} x2={875} y2={y(-depth - water)} stroke="#d2b78e" strokeWidth={2} />
        <text x={labelLeft} y={Math.min(y(-depth - water) + 26, 380)} fill="#e7d7be" fontSize={textSize}>{compact ? `Seabed ${depth.toFixed(1)} ft MLLW` : `Local supplied seabed: ${depth.toFixed(1)} ft below MLLW · uncertainty ${fmt(loading.depth_uncertainty_ft, 'ft')}`}</text>
      </g> : <text x={labelLeft} y={sectionBottom - 9} fill="#ffc66b" fontSize={textSize}>{compact && <title>{noDepth}</title>}{compact ? 'Depth unavailable' : noDepth}</text>}
      {usable && hull ? <g data-section-vessel="illustrative">
        <polygon data-section-hull="true" points={hullPoints} fill="#8296a4" stroke="#d7e7ef" strokeWidth={2} strokeLinejoin="round" />
        {water != null && <polygon points={hullPoints} fill="#9b5c56" opacity={0.9} clipPath={`url(#${underwaterId})`} />}
        {topsides.map(part => part.closed
          ? <polygon key={part.name} data-vessel-part={part.name} points={points(part.points)} fill={part.fill} stroke="#b5cad7" strokeWidth={1.5} strokeLinejoin="round" />
          : <polyline key={part.name} data-vessel-part={part.name} points={points(part.points)} fill="none" stroke="#d7e7ef" strokeWidth={2.5} />)}
        <polyline data-modeled-draft="true" points={keel.map(p => p.join(',')).join(' ')} fill="none" stroke="#b6d8e8" strokeWidth={2} strokeDasharray="7 6"><title>Modeled draft envelope; illustrative hull shape does not change contact dimensions.</title></polyline>
        {keel.map(([kx, ky], i) => <line key={i} x1={kx} y1={ky - 8} x2={kx} y2={ky + 8} stroke="#b6d8e8" strokeWidth={2} />)}
      </g> : <text x={450} y={115} textAnchor="middle" fill="#ffc66b" fontSize={textSize}>Hull section unavailable: {usable ? 'freeboard not supplied' : 'invalid loading model'}</text>}
      {water != null && <line data-section-waterline="true" x1={25} y1={205} x2={875} y2={205} stroke="#7dd3fc" strokeWidth={2} />}
      {usable && loading.payloads.map((p) => {
        const [px, py] = project(side ? p.x_ft : (view === 'forward' ? p.y_ft : -p.y_ft), p.z_ft);
        return <g key={p.payload_id} data-section-payload={p.payload_id}>{compact && <title>{`${p.label} · ${p.weight_lbf.toFixed(0)} lbf`}</title>}<rect x={px - 6} y={py - 6} width={12} height={12} fill="#ffc66b" stroke="#0a1628" />{!compact && <text x={px + 10} y={py - 6} fill="#ffe4b5" fontSize={11}>{p.label} · {p.weight_lbf.toFixed(0)} lbf</text>}</g>;
      })}
      {usable && (() => { const [cx, cy] = project(side ? loading.cg_x_ft : (view === 'forward' ? loading.cg_y_ft : -loading.cg_y_ft), loading.cg_z_ft); return <g data-section-cg="true"><circle cx={cx} cy={cy} r={compact ? 9 : 7} fill="#0a1628" stroke="#f9a8d4" strokeWidth={2} /><text x={cx + 12} y={cy + 4} fill="#f9a8d4" fontSize={compact ? 22 : 11}>CG</text></g>; })()}
      <text x={labelLeft} y={194} fill="#b5ddf5" stroke="#0b2437" strokeWidth={3} paintOrder="stroke" fontSize={textSize}>{water == null ? (compact ? 'Water level unavailable' : 'Water level unavailable · section referenced to modeled draft') : (compact ? `Water ${water.toFixed(1)} ft MLLW` : `Waterline · ${water.toFixed(2)} ft MLLW`)}</text>
      <text x={compact ? viewLeft + 12 : 65} y={30} fill="#8ba4c4" fontSize={textSize}>{side ? 'AFT' : view === 'forward' ? 'STARBOARD' : 'PORT'}</text><text x={compact ? viewLeft + viewWidth - 12 : 835} y={30} fill="#8ba4c4" fontSize={textSize} textAnchor="end">{side ? 'FWD' : view === 'forward' ? 'PORT' : 'STARBOARD'}</text>
    </svg>
    <div className={`grid shrink-0 gap-x-2 border-t border-mil-border bg-mil-panel/90 ${compact ? 'grid-cols-2 px-2 py-0.5 text-[9px]' : 'grid-cols-2 gap-y-3 p-3 text-[11px] sm:grid-cols-4'}`}>
      <div><span className={`${compact ? 'mr-1' : 'block'} text-[9px] uppercase text-mil-dim`}>{compact ? 'Draft F / A' : 'Forward / aft draft'}</span>{usable ? `${fmt(loading.draft_fwd_ft, 'ft')} / ${fmt(loading.draft_aft_ft, 'ft')}` : 'unavailable'}</div>
      <div><span className={`${compact ? 'mr-1' : 'block'} text-[9px] uppercase text-mil-dim`}>Heel / trim</span>{fmt(roll, '°')} / {fmt(pitch, '°')}</div>
      <div className={`${compact ? 'col-span-2' : ''} ${clearanceInvalid ? 'text-mil-red' : ''}`}><span className={`${compact ? 'mr-1' : 'block'} text-[9px] uppercase text-mil-dim`}>{compact ? 'UKC / lower' : 'Under keel / lower bound'}</span>{fmt(loading.under_keel_ft, 'ft')} / {fmt(loading.under_keel_lower_ft, 'ft')}{clearanceInvalid && !compact && <span className="block text-[9px]">Invalid loading / clearance evidence</span>}</div>
      {!compact && <div><span className="block text-[9px] uppercase text-mil-dim">Total modeled weight</span>{fmt(loading.total_weight_lbf, 'lbf')}</div>}
    </div>
    {loading.validity.state === 'invalid' && <p role="alert" className={`shrink-0 text-mil-red ${compact ? 'truncate px-2 text-[9px]' : 'px-3 py-2 text-[10px]'}`} title={loading.validity.reasons?.map(reason => reason.message).join(' ')}>{invalidMessage}</p>}
    <p className={`shrink-0 text-mil-dim ${compact ? 'px-2 text-[8px]' : 'px-3 py-1 text-[9px]'}`} title={`${profileDetail}${(roll == null || pitch == null) ? ' Unsupported attitude axes use a neutral drawing projection, not a reported zero.' : ''}`}>Illustrative profile{!compact && ' · dashed line: modeled draft envelope'}</p>
  </div>;
}
