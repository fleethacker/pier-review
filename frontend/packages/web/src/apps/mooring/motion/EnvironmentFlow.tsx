import { currentArrow, windArrow } from './frames';
import type { ViewFrame } from './frames';
import type { MapBounds } from './basemap';

export interface FlowDisplay { wind: boolean; current: boolean; animate: boolean }

/** A visual texture, never a force or trajectory calculation. Phase uses simulation time, so pausing freezes it. */
export function EnvironmentFlow({ frame, bounds, faceBearingDeg, display }: { frame: ViewFrame | null; bounds: MapBounds; faceBearingDeg: number; display: FlowDisplay }) {
  const env = frame?.environment;
  if (!env || !frame) return null;
  const fields = [
    { id: 'wind', part: env.wind, enabled: display.wind, speed: env.wind.speedKt, direction: env.wind.fromTrueDeg, vector: windArrow, color: '#7dd3fc' },
    { id: 'current', part: env.current, enabled: display.current, speed: env.current.speedKt, direction: env.current.setTrueDeg, vector: currentArrow, color: '#7dffb2' },
  ];
  const cell = Math.max(bounds.w, bounds.h) / 10;
  return <g aria-label="Environment flow visualization" pointerEvents="none">
    {fields.map((f, index) => {
      if (!f.enabled || !f.part.available || f.speed == null || f.direction == null || f.speed <= 0) return null;
      const v = f.vector(f.direction, faceBearingDeg);
      const phase = display.animate ? (((frame.tS + frame.forcingTimeOffsetS) * Math.min(f.speed, 40) / 40) % 1) : 0;
      return <g key={f.id} stroke={f.color} strokeWidth={cell / 65} opacity={0.24} data-flow={f.id} data-sim-time={display.animate ? frame.tS : 'static'}>
        {Array.from({ length: 120 }, (_, n) => {
          const col = n % 12, row = Math.floor(n / 12);
          const x = bounds.x + (col - 1 + index * 0.5 + v.x * phase) * cell;
          const y = bounds.y + (row - 1 + index * 0.5 + v.y * phase) * cell;
          const length = cell * (index ? 0.35 : 0.55);
          const tip = { x: x + v.x * length, y: y + v.y * length };
          return <path key={n} d={`M ${x} ${y} L ${tip.x} ${tip.y} m ${(-v.x + v.y * 0.7) * cell * 0.08} ${(-v.y - v.x * 0.7) * cell * 0.08} L ${tip.x} ${tip.y} l ${(-v.x - v.y * 0.7) * cell * 0.08} ${(-v.y + v.x * 0.7) * cell * 0.08}`} fill="none" />;
        })}
      </g>;
    })}
  </g>;
}
