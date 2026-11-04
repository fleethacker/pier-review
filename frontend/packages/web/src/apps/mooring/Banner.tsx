import { BackendBadge } from '../../shell/ui';
import { cn } from '../../lib/cn';
import { useMooring } from './panels/context';
import { setUnitSystem, useUnitSystem } from './units';
import type { UnitSystem } from './units';

export function Banner() {
  const units = useUnitSystem();
  const backend = useMooring((s) => s.backend);
  const confidence = useMooring((s) => s.berth?.provenance.confidence);
  return (
    <div className="flex items-center gap-3">
      {backend === 'mock' && (
        <span className="text-[10px] text-mil-amber">Placeholder numbers: not validated physics. Do not use operationally.</span>
      )}
      <BackendBadge backend={backend} />
      <div role="group" aria-label="Units" className="flex">
        {([['navy', 'Navy'], ['metric', 'Metric']] as [UnitSystem, string][]).map(([id, label]) => (
          <button
            key={id}
            aria-pressed={units === id}
            onClick={() => setUnitSystem(id)}
            className={cn(
              'border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider',
              units === id ? 'border-mil-cyan/60 bg-mil-cyan/20 text-mil-cyan' : 'border-mil-border text-mil-text hover:text-white',
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {confidence && <span className="text-[10px] uppercase tracking-wider text-mil-dim">berth data: {confidence}</span>}
    </div>
  );
}
