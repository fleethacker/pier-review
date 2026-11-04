import { STATUS_COLOR } from '../../../shell/theme';

const W = 520;
const AXIS = '#4a6a8a';
const GRID = '#1a3a5c';
const TEXT = '#8ba4c4';

export interface Series {
  name: string;
  color: string;
  points: { x: number; y: number }[];
}

function extent(values: number[], pad = 0): [number, number] {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return lo === hi ? [lo - 1, hi + 1] : [lo - pad, hi + pad];
}

/** Small multi-series line chart. x is any number (ms epoch or hours); `xTicks` supplies labelled positions. */
export function LineChart({
  series,
  height = 150,
  xTicks,
  unit,
  thresholds = [],
  label,
}: {
  series: Series[];
  height?: number;
  xTicks: { x: number; label: string }[];
  unit: string;
  thresholds?: { y: number; label: string; color: string }[];
  label: string;
}) {
  const all = series.flatMap((s) => s.points);
  if (all.length < 2) {
    return <div className="flex h-full items-center justify-center text-[11px] text-mil-dim">No data yet.</div>;
  }
  const [x0, x1] = extent(all.map((p) => p.x));
  const [, yMax] = extent([...all.map((p) => p.y), ...thresholds.map((t) => t.y)]);
  const top = Math.max(yMax * 1.1, 5);
  const m = { l: 34, r: 8, t: 8, b: 20 };
  const sx = (x: number) => m.l + ((x - x0) / (x1 - x0)) * (W - m.l - m.r);
  const sy = (y: number) => height - m.b - (y / top) * (height - m.t - m.b);
  const yTicks = [0, top / 2, top].map((v) => Math.round(v));
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="h-full w-full" role="img" aria-label={label}>
      {yTicks.map((v) => (
        <g key={v}>
          <line x1={m.l} x2={W - m.r} y1={sy(v)} y2={sy(v)} stroke={GRID} />
          <text x={m.l - 4} y={sy(v) + 3} textAnchor="end" fontSize="9" fill={TEXT}>
            {v}
          </text>
        </g>
      ))}
      <text x={4} y={10} fontSize="9" fill={TEXT}>
        {unit}
      </text>
      {xTicks.map((t) => (
        <text key={t.x} x={sx(t.x)} y={height - 6} textAnchor="middle" fontSize="9" fill={TEXT}>
          {t.label}
        </text>
      ))}
      {thresholds.map((t) => (
        <g key={t.label}>
          <line x1={m.l} x2={W - m.r} y1={sy(t.y)} y2={sy(t.y)} stroke={t.color} strokeDasharray="4 3" />
          <text x={W - m.r} y={sy(t.y) - 3} textAnchor="end" fontSize="9" fill={t.color}>
            {t.label}
          </text>
        </g>
      ))}
      {series.map((s) => (
        <polyline
          key={s.name}
          fill="none"
          stroke={s.color}
          strokeWidth="1.8"
          points={s.points.map((p) => `${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ')}
        />
      ))}
      <g fontSize="9">
        {series.map((s, i) => (
          <g key={s.name} transform={`translate(${m.l + 8 + i * 70}, ${m.t + 4})`}>
            <rect width="10" height="3" y="-3" fill={s.color} />
            <text x="14" y="0" fill={TEXT}>
              {s.name}
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
}

/** Probability bars for the forecast, colored by the step's status. */
export function ProbabilityBars({
  steps,
  height = 70,
}: {
  steps: { label: string; p: number | null; status: 'GREEN' | 'AMBER' | 'RED' }[];
  height?: number;
}) {
  if (steps.length === 0) return null;
  const m = { l: 34, r: 8, t: 4, b: 4 };
  const bw = (W - m.l - m.r) / steps.length;
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="h-full w-full" role="img" aria-label="Chance that any line exceeds its working load, per forecast hour">
      <text x={4} y={10} fontSize="9" fill={TEXT}>
        P(any line &gt; WLL)
      </text>
      {steps.map((s, i) => {
        if (s.p == null) return <text key={i} x={m.l + i * bw} y={height / 2} fontSize="8" fill={TEXT}><title>{s.label}: probability unavailable</title>?</text>;
        const h = Math.max(s.p, 0.01) * (height - m.t - m.b);
        return (
          <rect
            key={i}
            x={m.l + i * bw + 1}
            y={height - m.b - h}
            width={Math.max(bw - 2, 1)}
            height={h}
            fill={STATUS_COLOR[s.status]}
            opacity={0.85}
          >
            <title>{`${s.label}: ${(s.p * 100).toFixed(0)}%`}</title>
          </rect>
        );
      })}
      <line x1={m.l} x2={W - m.r} y1={height - m.b} y2={height - m.b} stroke={AXIS} />
    </svg>
  );
}

/** Polar plot of the wind speed that first overloads the plan, by wind angle. */
export function PolarEnvelope({
  points,
  currentWindKt,
  worstAngle,
  size = 160,
}: {
  points: { angle: number; limit: number | null }[];
  currentWindKt?: number;
  worstAngle?: number;
  size?: number;
}) {
  const finite = points.filter((p) => p.limit != null) as { angle: number; limit: number }[];
  if (finite.length === 0) return <div className="text-[11px] text-mil-dim">No limiting wind found.</div>;
  const max = Math.max(...finite.map((p) => p.limit), currentWindKt ?? 0) * 1.1;
  const c = size / 2;
  const r = size / 2 - 14;
  const pt = (angle: number, v: number): [number, number] => {
    const a = ((angle - 90) * Math.PI) / 180; // 0 deg at the top, clockwise
    return [c + Math.cos(a) * (v / max) * r, c + Math.sin(a) * (v / max) * r];
  };
  const rings = [0.33, 0.66, 1].map((f) => Math.round(max * f));
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full" role="img" aria-label="Limiting wind speed by wind angle">
      {rings.map((v) => (
        <g key={v}>
          <circle cx={c} cy={c} r={(v / max) * r} fill="none" stroke={GRID} />
          <text x={c + 2} y={c - (v / max) * r + 9} fontSize="8" fill={TEXT}>
            {v} kt
          </text>
        </g>
      ))}
      {[0, 90, 180, 270].map((a) => {
        const [x, y] = pt(a, max);
        return (
          <g key={a}>
            <line x1={c} y1={c} x2={x} y2={y} stroke={GRID} />
            <text x={pt(a, max * 1.08)[0]} y={pt(a, max * 1.08)[1] + 3} textAnchor="middle" fontSize="8" fill={TEXT}>
              {a}°
            </text>
          </g>
        );
      })}
      <polygon
        points={finite.map((p) => pt(p.angle, p.limit).join(',')).join(' ')}
        fill="#00e5ff"
        fillOpacity="0.15"
        stroke="#00e5ff"
        strokeWidth="1.5"
      />
      {currentWindKt != null && <circle cx={c} cy={c} r={(currentWindKt / max) * r} fill="none" stroke="#ffc107" strokeDasharray="3 3" />}
      {worstAngle != null && (() => {
        const w = finite.find((p) => p.angle === worstAngle);
        if (!w) return null;
        const [x, y] = pt(w.angle, w.limit);
        return <circle cx={x} cy={y} r="4" fill="#ff1744" />;
      })()}
    </svg>
  );
}
