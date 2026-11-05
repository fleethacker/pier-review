import { useRef } from 'react';
import { STATUS_COLOR } from '../../../shell/theme';
import { fmt } from '../units';
import { currentArrow, shipToBerth, utilizationStatus, windArrow } from './frames';
import type { SimScene, Vec2, ViewFrame } from './frames';

const FORCE_COLOR: Record<string, string> = {
  wind: '#7dd3fc',
  current: '#38bdf8',
  wave: '#a78bfa',
  tugs: '#f59e0b',
  lines: '#34d399',
  fenders: '#f472b6',
};
const DIM = '#4a6a8a';
const WATER = '#0d2f4d';

interface Bounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

function extend(b: Bounds, p: Vec2 | null | undefined): void {
  if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return;
  b.minX = Math.min(b.minX, p.x);
  b.maxX = Math.max(b.maxX, p.x);
  b.minY = Math.min(b.minY, p.y);
  b.maxY = Math.max(b.maxY, p.y);
}

function sceneKey(scene: SimScene | null): string {
  return scene ? `${scene.scene_id}@${scene.revision}` : 'none';
}

function pt(p: { x_ft?: number | null; y_ft?: number | null } | null | undefined): Vec2 | null {
  return p && p.x_ft != null && p.y_ft != null ? { x: p.x_ft, y: p.y_ft } : null;
}

/** Arrow with a head, in world units. */
function Arrow({ from, vec, color, width, dashed, label, fontSize, head }: { from: Vec2; vec: Vec2; color: string; width: number; dashed?: boolean; label?: string; fontSize: number; head: number }) {
  const len = Math.hypot(vec.x, vec.y);
  if (len < 1e-6) return null;
  const ux = vec.x / len;
  const uy = vec.y / len;
  const tip = { x: from.x + vec.x, y: from.y + vec.y };
  const base = { x: tip.x - ux * head, y: tip.y - uy * head };
  const wing = head * 0.45;
  return (
    <g>
      <line x1={from.x} y1={from.y} x2={base.x} y2={base.y} stroke={color} strokeWidth={width} strokeDasharray={dashed ? `${width * 3} ${width * 2}` : undefined} strokeLinecap="round" />
      <polygon points={`${tip.x},${tip.y} ${base.x - uy * wing},${base.y + ux * wing} ${base.x + uy * wing},${base.y - ux * wing}`} fill={color} />
      {label && <Label at={{ x: tip.x + ux * head * 0.4, y: tip.y + uy * head * 0.4 }} text={label} size={fontSize} color={color} />}
    </g>
  );
}

/** Text that stays upright inside the y-flipped world group. */
function Label({ at, text, size, color = '#d6e4f5', anchor = 'start' }: { at: Vec2; text: string; size: number; color?: string; anchor?: 'start' | 'middle' | 'end' }) {
  return (
    <text transform={`translate(${at.x} ${at.y}) scale(1 -1)`} fontSize={size} fill={color} textAnchor={anchor} fontFamily="ui-monospace, monospace" style={{ paintOrder: 'stroke' }} stroke="#0a1628" strokeWidth={size * 0.18}>
      {text}
    </text>
  );
}

export interface MotionCanvasProps {
  frame: ViewFrame | null;
  scene: SimScene | null;
  trail: Vec2[];
  faceBearingDeg: number;
}

export function MotionCanvas({ frame, scene, trail, faceBearingDeg }: MotionCanvasProps) {
  // The view only grows while a scene is shown, so the picture does not jitter as the ship moves.
  const bounds = useRef<{ key: string; b: Bounds | null }>({ key: '', b: null });
  const key = sceneKey(scene);
  if (bounds.current.key !== key) bounds.current = { key, b: null };

  const b: Bounds = bounds.current.b ?? { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
  scene?.berth_outline?.forEach((p) => extend(b, pt(p)));
  scene?.fenders?.forEach((f) => extend(b, pt(f.position)));
  scene?.pier_fittings?.forEach((f) => extend(b, pt(f.position)));
  extend(b, { x: 0, y: 0 });
  if (frame) {
    extend(b, { x: frame.ship.x_ft, y: frame.ship.y_ft });
    scene?.ship_hull_outline?.forEach((p) => extend(b, shipToBerth(p, frame.ship)));
    frame.tugs.forEach((t) => extend(b, t.position));
    frame.lines.forEach((l) => {
      extend(b, l.shipEnd);
      extend(b, l.pierEnd);
    });
  }
  trail.forEach((p) => extend(b, p));
  if (!Number.isFinite(b.minX)) Object.assign(b, { minX: -100, maxX: 100, minY: -50, maxY: 150 });
  bounds.current.b = b;

  const spanX = Math.max(b.maxX - b.minX, 120);
  const spanY = Math.max(b.maxY - b.minY, 80);
  const span = Math.max(spanX, spanY * 1.5);
  const pad = span * 0.12;
  const vb = { x: b.minX - pad, y: b.minY - pad, w: b.maxX - b.minX + 2 * pad, h: b.maxY - b.minY + 2 * pad };
  const font = span / 52;
  const lw = span / 600;
  const head = span / 45;

  // One scale for every force arrow so lengths compare; the largest drawn force is about a seventh of the view.
  const forceVecs: Vec2[] = [];
  frame?.forces.forEach((f) => f.force && forceVecs.push(f.force));
  frame?.tugs.forEach((t) => {
    if (t.actualForce) forceVecs.push(t.actualForce);
  });
  const maxForce = Math.max(1, ...forceVecs.map((v) => Math.hypot(v.x, v.y)));
  const fScale = (span / 7) / maxForce;
  const maxVel = Math.max(0.5, ...(frame?.tugs.map((t) => (t.velocity ? Math.hypot(t.velocity.x, t.velocity.y) : 0)) ?? [0]));
  const vScale = (span / 14) / maxVel;
  const maxTension = Math.max(1, ...(frame?.lines.map((l) => l.tensionLbf ?? 0) ?? [0]));

  const ship = frame?.ship;
  const hull = scene?.ship_hull_outline && ship ? scene.ship_hull_outline.map((p) => shipToBerth(p, ship)) : null;

  const drawnForces = frame?.forces.filter((f) => f.force) ?? [];
  return (
    <div className="relative h-full w-full">
    <svg
      role="img"
      aria-label="Plan view of the ship, pier, lines and tugs"
      viewBox={`${vb.x} ${-(vb.y + vb.h)} ${vb.w} ${vb.h}`}
      preserveAspectRatio="xMidYMid meet"
      className="h-full w-full"
      style={{ background: WATER }}
    >
      <g transform="scale(1 -1)">
        {/* Pier */}
        {scene?.berth_outline && scene.berth_outline.length > 2 ? (
          <polygon points={scene.berth_outline.map((p) => `${p.x_ft},${p.y_ft}`).join(' ')} fill="#3b4a5c" stroke="#8ba4c4" strokeWidth={lw * 2} opacity={0.9} />
        ) : (
          <>
            <rect x={vb.x} y={vb.y} width={vb.w} height={-vb.y} fill="#3b4a5c" opacity={0.6} />
            <line x1={vb.x} y1={0} x2={vb.x + vb.w} y2={0} stroke="#8ba4c4" strokeWidth={lw * 2} />
          </>
        )}
        <Label at={{ x: vb.x + font, y: -font * 2 }} text={scene ? 'PIER' : 'PIER FACE (outline not supplied)'} size={font} color="#8ba4c4" />

        {/* Fenders: compression and status come only from the frame */}
        {scene?.fenders?.map((f) => {
          const p = pt(f.position);
          if (!p) return null;
          const live = frame?.fenders.find((x) => x.id === f.fender_id);
          const color = live?.status ? STATUS_COLOR[live.status] : DIM;
          const len = f.length_ft ?? font * 4;
          return (
            <g key={f.fender_id}>
              <rect x={p.x - len / 2} y={p.y - font * 0.5} width={len} height={font} fill={color} opacity={0.85} rx={font * 0.3} />
              {live?.compressionFt != null && <Label at={{ x: p.x, y: p.y - font * 2.2 }} text={fmt.ft(live.compressionFt, 2)} size={font * 0.85} color={color} anchor="middle" />}
            </g>
          );
        })}

        {/* Pier fittings */}
        {scene?.pier_fittings?.map((f) => {
          const p = pt(f.position);
          if (!p) return null;
          const live = frame?.fittings.find((x) => x.id === f.fitting_id && x.owner === 'pier');
          const st = live?.status ?? utilizationStatus(live?.loadLbf ?? null, live?.capacityLbf ?? f.capacity_lbf);
          return <circle key={f.fitting_id} cx={p.x} cy={p.y} r={font * 0.7} fill={st ? STATUS_COLOR[st] : DIM} stroke="#0a1628" strokeWidth={lw} />;
        })}

        {/* Trail */}
        {trail.length > 1 && <polyline points={trail.map((p) => `${p.x},${p.y}`).join(' ')} fill="none" stroke="#00e5ff" strokeOpacity={0.35} strokeWidth={lw * 2} strokeDasharray={`${lw * 6} ${lw * 5}`} />}

        {/* Ship */}
        {ship && (
          <g>
            {hull ? (
              <polygon points={hull.map((p) => `${p.x},${p.y}`).join(' ')} fill="#00e5ff" fillOpacity={0.14} stroke="#00e5ff" strokeWidth={lw * 3} strokeLinejoin="round" />
            ) : (
              <g transform={`translate(${ship.x_ft} ${ship.y_ft}) rotate(${ship.yawDeg})`}>
                <polygon points={`${font * 6},0 ${-font * 4},${font * 3} ${-font * 4},${-font * 3}`} fill="#00e5ff" fillOpacity={0.2} stroke="#00e5ff" strokeWidth={lw * 3} />
              </g>
            )}
            {/* Ship fittings */}
            {scene?.ship_fittings?.map((f) => {
              const p = shipToBerth(f.position, ship);
              const live = frame?.fittings.find((x) => x.id === f.fitting_id && x.owner === 'ship');
              const st = live?.status ?? utilizationStatus(live?.loadLbf ?? null, live?.capacityLbf ?? f.capacity_lbf);
              return <circle key={f.fitting_id} cx={p.x} cy={p.y} r={font * 0.7} fill={st ? STATUS_COLOR[st] : DIM} stroke="#0a1628" strokeWidth={lw} />;
            })}
            <circle cx={ship.x_ft} cy={ship.y_ft} r={font * 0.5} fill="#00e5ff" />
            {(() => {
              const at = hull ? { x: Math.min(...hull.map((p) => p.x)), y: Math.max(...hull.map((p) => p.y)) + font * 1.4 } : { x: ship.x_ft, y: ship.y_ft + font * 4 };
              return <Label at={at} text={`ship · hdg ${Math.round(ship.headingTrueDeg)}°`} size={font} color="#00e5ff" />;
            })()}
            {!hull && <Label at={{ x: ship.x_ft, y: ship.y_ft - font * 4.5 }} text="hull outline not supplied" size={font * 0.85} color={DIM} anchor="middle" />}
          </g>
        )}

        {/* Lines */}
        {frame?.lines.map((l) => {
          const pts = l.polyline && l.polyline.length > 1 ? l.polyline : l.shipEnd && l.pierEnd ? [l.shipEnd, l.pierEnd] : null;
          if (!pts) return null;
          const color = l.status === 'overloaded' ? STATUS_COLOR.RED : l.status === 'taut' ? STATUS_COLOR.GREEN : DIM;
          const w = lw * (l.tensionLbf != null ? 2 + 4 * (l.tensionLbf / maxTension) : 2);
          const mid = pts[Math.floor(pts.length / 2)];
          return (
            <g key={l.lineNumber}>
              <polyline points={pts.map((p) => `${p.x},${p.y}`).join(' ')} fill="none" stroke={color} strokeWidth={w} strokeDasharray={l.status === 'slack' || l.status === 'unknown' ? `${lw * 5} ${lw * 4}` : undefined} />
              <Label at={{ x: mid.x + font * 0.6, y: mid.y + font * 0.6 }} text={`${l.lineNumber}${l.tensionLbf != null ? ` · ${fmt.lbf(l.tensionLbf)}` : ''}`} size={font * 0.8} color={color} />
            </g>
          );
        })}

        {/* Force breakdown, from the ship's reference point */}
        {ship &&
          frame?.forces.map((f) =>
            f.force ? (
              <Arrow key={f.key} from={{ x: ship.x_ft, y: ship.y_ft }} vec={{ x: f.force.x * fScale, y: f.force.y * fScale }} color={FORCE_COLOR[f.key]} width={lw * 3} fontSize={font * 0.85} head={head * 0.7} />
            ) : null,
          )}

        {/* Tugs */}
        {frame?.tugs.map((t) => {
          if (!t.position) return null;
          const hdg = t.headingTrueDeg != null ? faceBearingDeg - t.headingTrueDeg : 0;
          return (
            <g key={t.id}>
              <g transform={`translate(${t.position.x} ${t.position.y}) rotate(${hdg})`}>
                <polygon points={`${font * 2.4},0 ${-font * 1.6},${font * 1.2} ${-font * 1.6},${-font * 1.2}`} fill="#f59e0b" fillOpacity={0.9} stroke="#0a1628" strokeWidth={lw} />
              </g>
              <Label at={{ x: t.position.x + font * 1.5, y: t.position.y + font * 1.8 }} text={`${t.id}${t.utilizationPct != null ? ` · ${t.utilizationPct.toFixed(0)}%` : ''}`} size={font * 0.9} color="#f59e0b" />
              {t.velocity && <Arrow from={t.position} vec={{ x: t.velocity.x * vScale, y: t.velocity.y * vScale }} color="#e2e8f0" width={lw * 2} fontSize={font * 0.8} head={head * 0.6} />}
              {t.acceleration && <Arrow from={t.position} vec={{ x: t.acceleration.x * vScale * 4, y: t.acceleration.y * vScale * 4 }} color="#fb7185" width={lw * 2} fontSize={font * 0.8} head={head * 0.6} />}
              {t.commandedForce && <Arrow from={t.position} vec={{ x: t.commandedForce.x * fScale, y: t.commandedForce.y * fScale }} color="#f59e0b" dashed width={lw * 2} fontSize={font * 0.8} head={head * 0.6} />}
              {t.actualForce && <Arrow from={t.position} vec={{ x: t.actualForce.x * fScale, y: t.actualForce.y * fScale }} color="#f59e0b" width={lw * 3} fontSize={font * 0.8} head={head * 0.6} />}
            </g>
          );
        })}
      </g>
    </svg>
    <div className="pointer-events-none absolute bottom-2 left-3 max-w-[60%] rounded-sm border border-mil-border bg-mil-panel/85 p-2 text-[10px] text-mil-text">
      <div className="flex flex-wrap gap-x-3 gap-y-0.5">
        {drawnForces.map((f) => (
          <span key={f.key} style={{ color: FORCE_COLOR[f.key] }}>■ {f.label}</span>
        ))}
        <span style={{ color: '#f59e0b' }}>■ Tug push</span>
        <span style={{ color: '#e2e8f0' }}>■ Tug velocity</span>
        <span style={{ color: '#fb7185' }}>■ Tug acceleration</span>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-3">
        <span style={{ color: STATUS_COLOR.GREEN }}>— taut line</span>
        <span style={{ color: DIM }}>- - slack or unknown</span>
        <span style={{ color: STATUS_COLOR.RED }}>— overloaded</span>
      </div>
      <p className="mt-0.5 text-mil-dim">
        {drawnForces.length || frame?.tugs.some((t) => t.actualForce) ? `Force arrows share one scale: the longest is ${fmt.lbf(maxForce)}.` : 'No force vectors in this frame.'}
      </p>
    </div>
    </div>
  );
}

/** Wind, current and wave glyphs. Screen-space, berth-oriented, so the arrows read against the plan view. */
export function EnvironmentGlyph({ frame, faceBearingDeg }: { frame: ViewFrame | null; faceBearingDeg: number }) {
  const env = frame?.environment;
  const north = { x: Math.cos((faceBearingDeg * Math.PI) / 180), y: Math.sin((faceBearingDeg * Math.PI) / 180) };
  const c = 70;
  const r = 52;
  const draw = (v: Vec2, color: string, key: string) => {
    // SVG y runs down; berth y runs up.
    const ex = c + v.x * r;
    const ey = c - v.y * r;
    return (
      <g key={key}>
        <line x1={c} y1={c} x2={ex} y2={ey} stroke={color} strokeWidth={3} strokeLinecap="round" />
        <circle cx={ex} cy={ey} r={4} fill={color} />
      </g>
    );
  };
  return (
    <section className="border-b border-mil-border px-3 py-2 text-[11px] text-mil-text">
      <h3 className="mil-label mb-1 text-[10px]">Environment</h3>
      <svg width="140" height="140" viewBox="0 0 140 140" role="img" aria-label="Wind, current and north directions in the plan view" className="mx-auto">
        <circle cx={c} cy={c} r={r + 8} fill="none" stroke="#1e3a5f" />
        {/* north tick */}
        <line x1={c} y1={c} x2={c + north.x * (r + 8)} y2={c - north.y * (r + 8)} stroke="#4a6a8a" strokeDasharray="3 3" />
        <text x={c + north.x * (r + 18)} y={c - north.y * (r + 18) + 3} fill="#8ba4c4" fontSize="9" textAnchor="middle">N</text>
        {env?.wind.available && env.wind.fromTrueDeg != null && draw(windArrow(env.wind.fromTrueDeg, faceBearingDeg), FORCE_COLOR.wind, 'wind')}
        {env?.current.available && env.current.setTrueDeg != null && draw(currentArrow(env.current.setTrueDeg, faceBearingDeg), FORCE_COLOR.current, 'cur')}
      </svg>
      {!env && <p className="text-mil-dim">No environment in this frame.</p>}
      {env && (
        <ul className="space-y-0.5">
          <li style={{ color: FORCE_COLOR.wind }}>
            Wind: {env.wind.available && env.wind.speedKt != null ? `${env.wind.speedKt.toFixed(0)} kt${env.wind.gustKt != null ? `, gust ${env.wind.gustKt.toFixed(0)}` : ''}, from ${Math.round(env.wind.fromTrueDeg ?? 0)}°` : 'unavailable'}
          </li>
          <li style={{ color: FORCE_COLOR.current }}>
            Current: {env.current.available && env.current.speedKt != null ? `${env.current.speedKt.toFixed(1)} kt toward ${Math.round(env.current.setTrueDeg ?? 0)}°` : 'unavailable'}
          </li>
          <li>Water: {env.water.available && env.water.levelMllwFt != null ? `${fmt.ft(env.water.levelMllwFt, 1)} MLLW` : 'unavailable'}</li>
          {env.waves.map((w) => (
            <li key={w.key} className={w.part.available ? '' : 'text-mil-dim'} style={w.part.available ? { color: FORCE_COLOR.wave } : undefined}>
              {w.label}: {w.part.available && w.heightFt != null ? `${fmt.ft(w.heightFt, 1)}${w.periodS != null ? ` @ ${w.periodS.toFixed(0)} s` : ''}` : w.part.availability === 'not_simulated' ? 'not simulated' : 'unavailable'}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-[9px] text-mil-dim">Arrows point the way the wind blows and the water flows; N is true north.</p>
    </section>
  );
}
