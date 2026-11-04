import type { SceneStore } from '../scene/store';
import { useScene } from '../scene/store';
import { Panel, StatusChip } from './ui';

export function Inspector({ store }: { store: SceneStore }) {
  const item = useScene(store, (s) => {
    const sel = s.selection;
    if (!sel) return null;
    return sel.type === 'entity' ? s.entities[sel.id] : s.links[sel.id];
  });
  if (!item) return null;
  const title = ('label' in item && item.label) || item.id;
  return (
    <Panel title={String(title)} className="w-72 p-4">
      <div className="space-y-2 font-mono text-xs">
        <div className="flex items-center justify-between">
          <span className="text-mil-dim">{item.kind}</span>
          {item.status && item.status !== 'NONE' && <StatusChip status={item.status} />}
        </div>
        {(item.props ?? []).map((row) => (
          <div key={row.label} className="flex justify-between gap-3">
            <span className="text-mil-dim">{row.label}</span>
            <span className="text-right text-white">{row.value}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
