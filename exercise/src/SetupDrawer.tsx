import { cn } from './lib/cn';
import { Button } from './ui';
import { Contacts } from './Contacts';
import type { SetupTab } from './controller';
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

const TABS: { id: SetupTab; label: string }[] = [
  { id: 'scenario', label: 'Scenario' },
  { id: 'environment', label: 'Conditions' },
  { id: 'forces', label: 'Forces' },
  { id: 'simulation', label: 'Simulation' },
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

/** What the simulation underneath the story can be asked to do, as opposed to how the exercise is set up. */
function SimulationTab() {
  const c = useController();
  const canRecord = useExercise((s) => s.canRecord);
  const recording = useExercise((s) => s.recording);
  const units = useExercise((s) => s.active.scenario.units.length);
  const events = useExercise((s) => s.active.trajectory.events.length);
  const detection = useExercise((s) => s.active.scenario.detection ?? false);
  const seed = useExercise((s) => s.active.scenario.seed ?? 1);
  return (
    <div className="space-y-4 p-3">
      <section className="space-y-2">
        <h3 className="mil-label">This run</h3>
        <dl className="space-y-1 text-[11px]">
          {([
            ['Units', `${units}`],
            ['Events', `${events}`],
            ['Sensors and detection', detection ? 'on' : 'off'],
            ['Chance seed', `${seed}`],
          ] as [string, string][]).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3">
              <dt className="text-mil-dim">{k}</dt>
              <dd className="text-right text-white">{v}</dd>
            </div>
          ))}
        </dl>
        <p className="text-[10px] leading-snug text-mil-dim">
          One run is one roll of the dice. Everything below asks the model for more than that.
        </p>
      </section>

      <section className="space-y-2 border-t border-mil-border pt-3">
        <h3 className="mil-label">Red team</h3>
        <p className="text-[11px] leading-snug text-mil-text">
          Run the scenario many times with the conditions and the chances varied, and measure how often each outcome
          happens, with an interval on the answer. Sweep a setting to see where the answer turns.
        </p>
        <Button size="sm" variant="secondary" className="w-full" onClick={() => c.toggleRedTeam(true)}>
          Open the red team
        </Button>
      </section>

      <section className="space-y-2 border-t border-mil-border pt-3">
        <h3 className="mil-label">Record the map</h3>
        <p className="text-[11px] leading-snug text-mil-text">
          Play the run from here and save the map as a video. The panels are not in the picture, only the map itself.
        </p>
        <Button size="sm" variant="secondary" className="w-full" disabled={!canRecord} onClick={() => c.toggleRecord()}>
          {recording ? '● Stop recording' : 'Record the run'}
        </Button>
        {!canRecord && <p className="text-[10px] text-mil-dim">The map is not up yet.</p>}
      </section>
    </div>
  );
}

export function SetupDrawer() {
  const c = useController();
  const open = useExercise((s) => s.setupOpen);
  const presenting = useExercise((s) => s.presenting);
  const tab = useExercise((s) => s.setupTab);
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
            onClick={() => c.setSetupTab(t.id)}
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
        ) : tab === 'simulation' ? (
          <SimulationTab />
        ) : (
          <div className="p-3">
            <Sidebar tab={tab} />
          </div>
        )}
      </div>
    </aside>
  );
}
