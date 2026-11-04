import { cn } from '../lib/cn';
import type { SceneStore } from '../scene/store';
import { useScene } from '../scene/store';

export function ViewControls({ store, upBearingDeg }: { store: SceneStore; upBearingDeg: number }) {
  const mode = useScene(store, (s) => s.viewMode);
  const btn = (active: boolean) =>
    cn(
      'h-8 px-3 font-mono text-[11px] uppercase tracking-wider border transition-colors',
      active
        ? 'border-mil-cyan/60 bg-mil-cyan/20 text-mil-cyan'
        : 'border-mil-border bg-mil-panel/80 text-mil-text hover:text-white',
    );
  return (
    <>
      <div className="pointer-events-auto absolute left-3 top-3 flex">
        <button className={btn(mode === '2d')} onClick={() => store.setViewMode('2d')} aria-pressed={mode === '2d'}>
          2D
        </button>
        <button className={btn(mode === '3d')} onClick={() => store.setViewMode('3d')} aria-pressed={mode === '3d'}>
          3D
        </button>
        <button className={cn(btn(false), 'ml-2')} onClick={() => store.requestFit()} title="Fit scene to window">
          Fit
        </button>
      </div>
      <Compass bearingDeg={upBearingDeg} />
    </>
  );
}

/** North arrow: rotates opposite to the screen-up bearing so it always points at true north. */
function Compass({ bearingDeg }: { bearingDeg: number }) {
  return (
    <div
      className="pointer-events-none absolute right-3 top-3 h-12 w-12 rounded-full border border-mil-border bg-mil-panel/80"
      aria-label={`North is ${Math.round(bearingDeg)} degrees from screen up`}
    >
      <svg viewBox="-24 -24 48 48" className="h-full w-full" style={{ transform: `rotate(${-bearingDeg}deg)` }}>
        <polygon points="0,-18 5,2 0,-2 -5,2" fill="#00e5ff" />
        <polygon points="0,18 5,-2 0,2 -5,-2" fill="#4a6a8a" />
        <text x="0" y="-19.5" textAnchor="middle" fontSize="8" fill="#ffffff" fontFamily="monospace" transform="translate(0,-2)">
          N
        </text>
      </svg>
    </div>
  );
}
