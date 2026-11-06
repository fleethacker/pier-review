import type { MotionState } from './controller';

export type SectionView = 'side' | 'forward' | 'aft';
const fmt = (v: number | null | undefined, unit: string) => v == null ? 'unavailable' : `${v.toFixed(2)} ${unit}`;

export function SectionViews({ s, view }: { s: MotionState; view: SectionView }) {
  const frame = s.frame;
  const loading = frame?.loading;
  const ship = s.workspace?.ship;
  if (!frame || !loading || !ship) return <div className="flex h-full items-center justify-center p-8 text-center text-xs text-mil-dim">Section view unavailable. This session has no backend loading and vessel geometry state.</div>;
  const condition = ship.loading_conditions.find((x) => x.name === s.workspace?.scenario.configuration.loading);
  const freeboard = condition?.freeboard_ft;
  const usable = (loading.validity.state === 'valid' || loading.validity.state === 'limited') && (frame.badge.validity === 'valid' || frame.badge.validity === 'limited');
  const clearanceInvalid = loading.validity.state === 'invalid' || (loading.under_keel_ft != null && loading.under_keel_ft <= 0) || (loading.under_keel_lower_ft != null && loading.under_keel_lower_ft <= 0);
  const water = frame.environment?.water.available ? frame.environment.water.levelMllwFt : null;
  const depth = loading.local_depth_mllw_ft;
  const beam = ship.beam_ft;
  const extent = view === 'side' ? ship.loa_ft : beam;
  const sx = 700 / extent;
  const maxVertical = Math.max(loading.maximum_draft_ft, depth != null && water != null ? depth + water : 0, freeboard ?? 0, 30);
  const sy = 145 / maxVertical;
  const x = (n: number) => 450 + n * sx;
  const y = (n: number) => 190 - n * sy;
  const draft = view === 'forward' ? loading.draft_fwd_ft : loading.draft_aft_ft;
  const half = extent / 2;
  const roll = frame.ship.rollDeg;
  const pitch = frame.ship.pitchDeg;
  // Only geometric projection of backend attitude: no estimated draft, seabed or hydrostatic computation.
  const project = (h: number, z: number): [number, number] => {
    const angle = (view === 'side' ? -(pitch ?? 0) : (view === 'forward' ? (roll ?? 0) : -(roll ?? 0))) * Math.PI / 180;
    return [x(h * Math.cos(angle) - z * Math.sin(angle)), y(h * Math.sin(angle) + z * Math.cos(angle))];
  };
  const body = freeboard != null ? [[-half, freeboard], [half, freeboard], [half * 0.95, -(view === 'side' ? loading.draft_fwd_ft : draft)], [-half * 0.95, -(view === 'side' ? loading.draft_aft_ft : draft)]] : null;
  return <div className="flex h-full min-h-0 flex-col bg-[#0b2437]">
    <div className="flex flex-wrap justify-between gap-2 border-b border-mil-border bg-mil-panel/90 px-4 py-2 text-[10px]"><span className="uppercase tracking-wider">{view === 'side' ? 'Port side elevation' : view === 'forward' ? 'Looking aft from bow' : 'Looking forward from stern'}</span><span className="text-mil-amber">{loading.basis} loading · {loading.validity.state} · vertical scale exaggerated</span></div>
    <svg role="img" aria-label={`${view} hull, waterline, payload and local seabed section`} viewBox="0 0 900 390" className="min-h-0 flex-1">
      {water != null && <><rect x={0} y={190} width={900} height={200} fill="#0a4261" opacity={0.65} /><line x1={25} y1={190} x2={875} y2={190} stroke="#7dd3fc" strokeWidth={2} /></>}
      {depth != null && water != null ? <><path d={`M 25 ${y(-depth - water)} H 875 V 390 H 25 Z`} fill="#645642" opacity={0.8} /><line x1={25} y1={y(-depth - water)} x2={875} y2={y(-depth - water)} stroke="#d2b78e" strokeWidth={2} /><text x={30} y={y(-depth - water) + 18} fill="#e7d7be" fontSize={12}>Local supplied seabed: {depth.toFixed(1)} ft below MLLW · uncertainty {fmt(loading.depth_uncertainty_ft, 'ft')}</text></> : <text x={30} y={350} fill="#ffc66b" fontSize={12}>Local seabed / clearance unavailable: {depth == null ? 'outside supplied depth coverage' : 'water level unavailable'}</text>}
      {usable && body ? <polygon points={body.map(([h, z]) => (view === 'side' ? [x(h), y(z)] : project(h, z)).join(',')).join(' ')} fill="#637c8f" fillOpacity={0.8} stroke="#d7e7ef" strokeWidth={2} /> : <text x={450} y={110} textAnchor="middle" fill="#ffc66b" fontSize={12}>Hull section unavailable: {usable ? 'freeboard not supplied' : 'invalid loading model'}</text>}
      {usable && loading.payloads.map((p) => {
        const [px, py] = project(view === 'side' ? p.x_ft : (view === 'forward' ? p.y_ft : -p.y_ft), p.z_ft);
        return <g key={p.payload_id}><rect x={px - 6} y={py - 6} width={12} height={12} fill="#ffc66b" stroke="#0a1628" /><text x={px + 10} y={py - 6} fill="#ffe4b5" fontSize={11}>{p.label} · {p.weight_lbf.toFixed(0)} lbf</text></g>;
      })}
      {usable && (() => { const [cx, cy] = project(view === 'side' ? loading.cg_x_ft : (view === 'forward' ? loading.cg_y_ft : -loading.cg_y_ft), loading.cg_z_ft); return <g><circle cx={cx} cy={cy} r={7} fill="#0a1628" stroke="#f9a8d4" strokeWidth={2} /><text x={cx + 11} y={cy + 4} fill="#f9a8d4" fontSize={11}>CG</text></g>; })()}
      <text x={30} y={178} fill="#b5ddf5" stroke="#0b2437" strokeWidth={3} paintOrder="stroke" fontSize={12}>{water == null ? 'Water level unavailable · section referenced to modeled draft' : `Waterline · ${water.toFixed(2)} ft MLLW`}</text>
      <text x={100} y={30} fill="#8ba4c4" fontSize={11}>{view === 'side' ? 'AFT' : view === 'forward' ? 'STARBOARD' : 'PORT'}</text><text x={800} y={30} fill="#8ba4c4" fontSize={11} textAnchor="end">{view === 'side' ? 'FWD' : view === 'forward' ? 'PORT' : 'STARBOARD'}</text>
    </svg>
    <div className="grid grid-cols-2 gap-3 border-t border-mil-border bg-mil-panel/90 p-3 text-[11px] sm:grid-cols-4"><div><span className="block text-[9px] uppercase text-mil-dim">Forward / aft draft</span>{usable ? `${fmt(loading.draft_fwd_ft, 'ft')} / ${fmt(loading.draft_aft_ft, 'ft')}` : 'unavailable'}</div><div><span className="block text-[9px] uppercase text-mil-dim">Heel / trim</span>{fmt(roll, '°')} / {fmt(pitch, '°')}</div><div className={clearanceInvalid ? 'text-mil-red' : ''}><span className="block text-[9px] uppercase text-mil-dim">Under keel / lower bound</span>{fmt(loading.under_keel_ft, 'ft')} / {fmt(loading.under_keel_lower_ft, 'ft')}{clearanceInvalid && <span className="block text-[9px]">Invalid loading / clearance evidence</span>}</div><div><span className="block text-[9px] uppercase text-mil-dim">Total modeled weight</span>{fmt(loading.total_weight_lbf, 'lbf')}</div></div>
    {loading.validity.state === 'invalid' && <p role="alert" className="px-3 py-2 text-[10px] text-mil-red">{loading.validity.reasons?.map((reason) => reason.message).join(' ') || 'Loading model is invalid. Supplied depth and clearance evidence remain visible.'}</p>}
    <p className="px-3 py-2 text-[9px] text-mil-dim">Schematic hull section. Draft, CG, attitude and local clearance are backend outputs. Water and seabed are supplied levels; waves and squat are not inferred.{(roll == null || pitch == null) && ' Unsupported attitude axes use a neutral drawing projection, not a reported zero.'}</p>
  </div>;
}
