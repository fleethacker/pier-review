import { Field, Panel, Select } from '../../shell/ui';
import { useClockSecond, useController, useExercise } from './context';
import { formatLatLon } from './geo';
import { MAP_STYLES } from './mapStyles';
import type { MapStyleId } from './mapStyles';
import { SHIP_CLASSES, SIDE_COLORS } from './ships';
import { unitHp, unitStateAt } from './sim';
import { STATUS_LABEL, unitStatus } from './status';

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-[11px] text-mil-text">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function ViewPanel() {
  const c = useController();
  const view = useExercise((s) => s.view);
  const mapStyle = useExercise((s) => s.mapStyle);
  return (
    <Panel title="View" className="space-y-3 p-4">
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
      </div>
    </Panel>
  );
}

function SelectedPanel() {
  const second = useClockSecond();
  const c = useController();
  const unit = useExercise((s) => s.active.scenario.units.find((u) => u.id === s.selectedId) ?? null);
  const run = useExercise((s) => s.active);
  if (!unit) {
    return (
      <Panel title="Selected ship" className="p-4">
        <p className="text-[11px] text-mil-dim">Click a ship on the map or in the list to see its readout.</p>
      </Panel>
    );
  }
  const i = run.trajectory.unitIds.indexOf(unit.id);
  const st = unitStateAt(run.trajectory, i, second);
  const cls = SHIP_CLASSES[unit.classId];
  const status = unitStatus(unit, st, second, run.trajectory.events);
  const rows: [string, string][] = [
    ['Class', cls.name],
    ['Status', STATUS_LABEL[status]],
    ...(!cls.weapon && cls.domain !== 'static' ? ([['Hit points', `${Math.round(st.hp)} / ${unitHp(unit)}`]] as [string, string][]) : []),
    ['Length / beam', `${cls.loaM} / ${cls.beamM} m`],
    ['Position', formatLatLon(st)],
    ['Heading', `${Math.round(st.headingDeg).toString().padStart(3, '0')}°T`],
    ['Speed through water', `${st.speedKt.toFixed(1)} kt`],
    ['Course / speed over ground', `${Math.round(st.cogDeg).toString().padStart(3, '0')}°T / ${st.sogKt.toFixed(1)} kt`],
    ...(cls.domain === 'air' ? ([['Altitude', `${Math.round(st.altM).toLocaleString('en-US')} m`]] as [string, string][]) : []),
    ...(cls.sensorRangeNm > 0 ? ([['Sensor range', `${cls.sensorRangeNm} nm (illustrative)`]] as [string, string][]) : []),
    ...(cls.weapon
      ? ([
          ['Damage', `${unit.damage ?? cls.weapon.damage}`],
          ['Hit chance', `${Math.round((unit.pHit ?? cls.weapon.pHit) * 100)}%`],
        ] as [string, string][])
      : []),
    ...(cls.defence
      ? ([['Defence', `${Math.round((unit.pKill ?? cls.defence.pKill) * 100)}% per shot, ${(cls.defence.rangeM / 1000).toFixed(0)} km`]] as [string, string][])
      : []),
  ];
  return (
    <Panel title="Selected ship" className="space-y-2 p-4">
      <div className="flex items-center gap-2 text-sm text-white">
        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: SIDE_COLORS[unit.side] }} />
        {unit.name}
      </div>
      <dl className="space-y-1 text-[11px]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-mil-dim">{k}</dt>
            <dd className="text-right text-white">{v}</dd>
          </div>
        ))}
      </dl>
      <button className="text-[10px] uppercase tracking-wider text-mil-dim hover:text-white" onClick={() => c.select(null)}>
        Clear selection
      </button>
    </Panel>
  );
}

function Key() {
  return (
    <Panel title="Key" className="space-y-2 p-4">
      {(['BLUE', 'RED', 'NEUTRAL'] as const).map((side) => (
        <div key={side} className="flex items-center gap-2 text-[11px] text-mil-text">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: SIDE_COLORS[side] }} />
          {side === 'BLUE' ? 'Blue force' : side === 'RED' ? 'Opposing force' : 'Neutral / merchant'}
        </div>
      ))}
      <p className="text-[10px] leading-snug text-mil-dim">
        The colored glow under each unit is its side. Dashed lines are planned routes; numbered dots are waypoints. Faint
        dotted lines join a missile to its target, and thin rings mark where a mine would go off. The white trail is the
        wake or ground track. Orange flashes are hits, white-blue ones shot-down missiles. A dark, burning ship is destroyed.
        Dimensions, handling and weapons are illustrative, not for operational use.
      </p>
    </Panel>
  );
}

export function Side() {
  return (
    <div className="space-y-3">
      <ViewPanel />
      <SelectedPanel />
      <Key />
    </div>
  );
}
