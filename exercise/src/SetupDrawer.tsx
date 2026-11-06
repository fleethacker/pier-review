import { useState } from 'react';
import { cn } from './lib/cn';
import { Button } from './ui';
import { Contacts } from './Contacts';
import { useController, useExercise } from './context';
import { MAP_STYLES } from './mapStyles';
import type { MapStyleId } from './mapStyles';
import { Field, Select } from './ui';
import { Sidebar } from './Sidebar';
import { SIDE_COLORS } from './ships';

/**
 * Everything that is not the storyboard, out of the way until it is wanted: the scenario, the conditions, the forces,
 * the contact table, what the map draws, and the red team. The storyboard view keeps the map and the feed; this is where
 * the simulation underneath it is set up.
 */

type Tab = 'scenario' | 'environment' | 'forces' | 'contacts' | 'view';

const TABS: { id: Tab; label: string }[] = [
  { id: 'scenario', label: 'Scenario' },
  { id: 'environment', label: 'Conditions' },
  { id: 'forces', label: 'Forces' },
  { id: 'contacts', label: 'Contacts' },
  { id: 'view', label: 'Map' },
];

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-[11px] text-mil-text">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function ViewTab() {
  const c = useController();
  const view = useExercise((s) => s.view);
  const mapStyle = useExercise((s) => s.mapStyle);
  return (
    <div className="space-y-3 p-3">
      <Field label="Map">
        <Select value={mapStyle} onChange={(v) => c.setMapStyle(v as MapStyleId)} options={MAP_STYLES.map((m) => ({ value: m.id, label: m.label }))} />
      </Field>
      <label className="block">
        <span className="mil-label mb-1 flex justify-between">
          <span>Ship size</span>
          <span className="text-white">{view.shipScale}×</span>
        </span>
        <input type="range" className="w-full" aria-label="Ship size" min={1} max={20} step={1} value={view.shipScale} onChange={(e) => c.setView({ shipScale: Number(e.target.value) })} />
        <span className="text-[10px] text-mil-dim">1× is true scale. Raise it to see ships when zoomed out.</span>
      </label>
      <label className="block">
        <span className="mil-label mb-1 flex justify-between">
          <span>Wake length</span>
          <span className="text-white">{view.trailS === 0 ? 'off' : `${view.trailS} s`}</span>
        </span>
        <input type="range" className="w-full" aria-label="Wake length" min={0} max={900} step={30} value={view.trailS} onChange={(e) => c.setView({ trailS: Number(e.target.value) })} />
      </label>
      <div className="space-y-1.5">
        <Toggle label="Ship names" checked={view.showLabels} onChange={(showLabels) => c.setView({ showLabels })} />
        <Toggle label="Routes and waypoints" checked={view.showRoutes} onChange={(showRoutes) => c.setView({ showRoutes })} />
        <Toggle label="Sensor range of selected ship" checked={view.showRange} onChange={(showRange) => c.setView({ showRange })} />
        <Toggle label="Storyboard bubbles" checked={view.showStory} onChange={(showStory) => c.setView({ showStory })} />
      </div>
      <div className="space-y-2 border-t border-mil-border pt-3">
        <h3 className="mil-label">Key</h3>
        {(['BLUE', 'RED', 'NEUTRAL'] as const).map((side) => (
          <div key={side} className="flex items-center gap-2 text-[11px] text-mil-text">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: SIDE_COLORS[side] }} />
            {side === 'BLUE' ? 'Blue force' : side === 'RED' ? 'Opposing force' : 'Neutral / merchant'}
          </div>
        ))}
        <p className="text-[10px] leading-snug text-mil-dim">
          Dashed lines are planned routes; numbered dots are waypoints. Faint dotted lines join a missile to its target,
          and thin rings mark where a mine would go off. The white trail is the wake or ground track. Orange flashes are
          hits, white-blue ones shot-down missiles. A dark, burning ship is destroyed. Dimensions, handling and weapons
          are illustrative, not for operational use.
        </p>
      </div>
    </div>
  );
}

export function SetupDrawer() {
  const c = useController();
  const open = useExercise((s) => s.setupOpen);
  const presenting = useExercise((s) => s.presenting);
  const [tab, setTab] = useState<Tab>('scenario');
  if (!open || presenting) return null;
  return (
    <aside
      role="dialog"
      aria-label="Setup"
      className="pointer-events-auto absolute inset-y-0 left-0 z-30 flex w-[26rem] max-w-[90vw] flex-col border-r border-mil-border bg-mil-panel/95 backdrop-blur"
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-mil-border px-3 py-2">
        <h2 className="mil-label text-mil-cyan">Setup</h2>
        <Button size="sm" variant="ghost" aria-label="Close setup" onClick={() => c.toggleSetup(false)}>
          Close
        </Button>
      </div>
      <div role="tablist" aria-label="Setup sections" className="flex shrink-0 flex-wrap gap-3 border-b border-mil-border px-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              'border-b-2 py-1.5 font-mono text-[10px] uppercase tracking-wider',
              tab === t.id ? 'border-mil-cyan text-mil-cyan' : 'border-transparent text-mil-text hover:text-white',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === 'contacts' ? (
          <Contacts />
        ) : tab === 'view' ? (
          <ViewTab />
        ) : (
          <div className="p-3">
            <Sidebar tab={tab} />
          </div>
        )}
      </div>
      <div className="shrink-0 border-t border-mil-border p-3">
        <Button size="sm" variant="secondary" className="w-full" onClick={() => c.toggleRedTeam(true)}>
          Red team: run it many times
        </Button>
      </div>
    </aside>
  );
}
