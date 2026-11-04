import { BackendBadge } from '../../shell/ui';
import { useMooring } from './panels/context';

export function Banner() {
  const backend = useMooring((s) => s.backend);
  const confidence = useMooring((s) => s.berth?.provenance.confidence);
  return (
    <div className="flex items-center gap-3">
      {backend === 'mock' && (
        <span className="text-[10px] text-mil-amber">Placeholder numbers: not validated physics. Do not use operationally.</span>
      )}
      <BackendBadge backend={backend} />
      {confidence && <span className="text-[10px] uppercase tracking-wider text-mil-dim">berth data: {confidence}</span>}
    </div>
  );
}
