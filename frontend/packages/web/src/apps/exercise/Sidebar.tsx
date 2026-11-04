import { useEffect, useRef, useState } from 'react';
import { cn } from '../../lib/cn';
import { Button, Field, Panel, Select, inputClass } from '../../shell/ui';
import { useController, useExercise } from './context';
import { NumField } from './NumField';
import { PRESET_SCENARIOS } from './scenarios';
import { CLASS_IDS, SHIP_CLASSES, SIDE_COLORS } from './ships';
import type { Behavior, ClassId, LightPreset, Side, UnitConfig } from './types';

/** A text box that commits on blur or Enter. */
function TextField({ label, value, onCommit }: { label: string; value: string; onCommit: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <Field label={label}>
      <input
        className={inputClass}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => (text.trim() ? text !== value && onCommit(text) : setText(value))}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      />
    </Field>
  );
}

const LIGHT_OPTIONS: { value: LightPreset; label: string }[] = [
  { value: 'dawn', label: 'Dawn' },
  { value: 'day', label: 'Day' },
  { value: 'dusk', label: 'Dusk' },
  { value: 'night', label: 'Night' },
];

function JsonEditor() {
  const c = useController();
  const [text, setText] = useState('');
  const [open, setOpen] = useState(false);
  const name = useExercise((s) => s.scenario.name);

  const download = () => {
    const url = URL.createObjectURL(new Blob([c.exportJson()], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name.replace(/[^\w-]+/g, '-').toLowerCase() || 'scenario'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setText(c.exportJson());
            setOpen(!open);
          }}
        >
          {open ? 'Hide JSON' : 'Edit as JSON'}
        </Button>
        <Button size="sm" variant="secondary" onClick={download}>
          Download
        </Button>
      </div>
      {open && (
        <>
          <textarea
            aria-label="Scenario JSON"
            className={cn(inputClass, 'h-48 resize-y font-mono text-[10px] leading-snug')}
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={() => c.importJson(text) && setOpen(false)}>
              Apply
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setText(c.exportJson())}>
              Revert
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

function ScenarioPanel() {
  const c = useController();
  const scenario = useExercise((s) => s.scenario);
  const isPreset = PRESET_SCENARIOS.some((p) => p.id === scenario.id);
  const dirty = (id: string) => {
    const original = PRESET_SCENARIOS.find((p) => p.id === id);
    return !original || JSON.stringify(original) !== JSON.stringify(scenario);
  };
  return (
    <Panel title="Scenario" className="space-y-3 p-4">
      <Field label="Load">
        <Select
          value={isPreset ? scenario.id : ''}
          onChange={(id) => {
            if (dirty(scenario.id) && !window.confirm('Loading another scenario discards your changes to this one. Download it first if you want to keep it. Continue?')) return;
            c.loadPreset(id);
          }}
          options={[
            ...(isPreset ? [] : [{ value: '', label: `${scenario.name} (edited)`, disabled: true }]),
            ...PRESET_SCENARIOS.map((p) => ({ value: p.id, label: p.name })),
            { value: 'blank', label: 'New blank scenario' },
          ]}
        />
      </Field>
      {scenario.description && <p className="text-[11px] leading-snug text-mil-text">{scenario.description}</p>}
      <TextField label="Name" value={scenario.name} onCommit={(name) => c.patchScenario({ name })} />
      <div className="grid grid-cols-2 gap-3">
        <NumField label="Length (min)" value={scenario.durationS / 60} min={1} max={1440} step={5} decimals={1} onCommit={(m) => m !== undefined && c.patchScenario({ durationS: Math.round(m * 60) })} />
        <Field label="Light">
          <Select value={scenario.lightPreset} onChange={(v) => c.patchScenario({ lightPreset: v as LightPreset })} options={LIGHT_OPTIONS} />
        </Field>
      </div>
      <JsonEditor />
    </Panel>
  );
}

function EnvironmentPanel() {
  const c = useController();
  const env = useExercise((s) => s.scenario.environment);
  const set = (key: keyof typeof env) => (v: number | undefined) => v !== undefined && c.patchEnvironment({ [key]: v });
  return (
    <Panel title="Environment" className="space-y-3 p-4">
      <div className="grid grid-cols-2 gap-3">
        <NumField label="Wind (kt)" value={env.windKt} min={0} step={1} onCommit={set('windKt')} />
        <NumField label="Wind from (°T)" value={env.windFromDeg} min={0} max={360} step={5} onCommit={set('windFromDeg')} />
        <NumField label="Current (kt)" value={env.currentKt} min={0} step={0.1} decimals={2} onCommit={set('currentKt')} />
        <NumField label="Current toward (°T)" value={env.currentToDeg} min={0} max={360} step={5} onCommit={set('currentToDeg')} />
      </div>
      <p className="text-[10px] leading-snug text-mil-dim">
        Current sets every ship over the ground. Wind pushes ships downwind a little, small craft more than big ships.
      </p>
    </Panel>
  );
}

const BEHAVIOR_OPTIONS: { value: Behavior['type']; label: string }[] = [
  { value: 'route', label: 'Follow a route' },
  { value: 'escort', label: 'Keep station on a ship' },
  { value: 'pursue', label: 'Pursue a ship' },
  { value: 'hold', label: 'Hold and drift' },
];

function RouteEditor({ unit }: { unit: UnitConfig }) {
  const c = useController();
  const placing = useExercise((s) => s.placing);
  const b = unit.behavior;
  if (b.type !== 'route') return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-[11px] text-mil-text">
          <input type="checkbox" checked={!!b.loop} onChange={(e) => c.patchBehavior(unit.id, { loop: e.target.checked })} />
          Loop back to the first waypoint
        </label>
        <Button size="sm" variant={placing ? 'primary' : 'secondary'} aria-pressed={placing} onClick={() => c.setPlacing(!placing)}>
          {placing ? 'Done' : 'Add on map'}
        </Button>
      </div>
      <div className="space-y-1">
        <div className="grid grid-cols-[1.2rem_1fr_1fr_3.2rem_1.2rem] gap-1 text-[9px] uppercase tracking-wider text-mil-dim">
          <span>#</span>
          <span>Lon</span>
          <span>Lat</span>
          <span>Kt</span>
          <span />
        </div>
        {b.waypoints.map((w, i) => (
          <div key={i} className="grid grid-cols-[1.2rem_1fr_1fr_3.2rem_1.2rem] items-center gap-1">
            <span className="text-[10px] text-mil-text">{i + 1}</span>
            <NumField compact label={`Waypoint ${i + 1} longitude`} value={w.lon} step={0.001} decimals={5} onCommit={(v) => v !== undefined && c.patchWaypoint(unit.id, i, { lon: v })} />
            <NumField compact label={`Waypoint ${i + 1} latitude`} value={w.lat} step={0.001} decimals={5} onCommit={(v) => v !== undefined && c.patchWaypoint(unit.id, i, { lat: v })} />
            <NumField compact optional label={`Waypoint ${i + 1} speed`} placeholder="–" value={w.speedKt} min={0} onCommit={(v) => c.patchWaypoint(unit.id, i, { speedKt: v })} />
            <button aria-label={`Remove waypoint ${i + 1}`} className="text-mil-dim hover:text-mil-red" onClick={() => c.removeWaypoint(unit.id, i)}>
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function UnitEditor({ unit }: { unit: UnitConfig }) {
  const c = useController();
  const others = useExercise((s) => s.scenario.units).filter((u) => u.id !== unit.id);
  const cls = SHIP_CLASSES[unit.classId];
  const b = unit.behavior;
  const otherOptions = others.map((u) => ({ value: u.id, label: u.name }));
  return (
    <div className="space-y-3 border-t border-mil-border pt-3">
      <TextField label="Name" value={unit.name} onCommit={(name) => c.patchUnit(unit.id, { name })} />
      <div className="grid grid-cols-2 gap-3">
        <Field label="Class">
          <Select value={unit.classId} onChange={(v) => c.patchUnit(unit.id, { classId: v as ClassId })} options={CLASS_IDS.map((id) => ({ value: id, label: SHIP_CLASSES[id].name }))} />
        </Field>
        <Field label="Side">
          <Select value={unit.side} onChange={(v) => c.patchUnit(unit.id, { side: v as Side })} options={(['BLUE', 'RED', 'NEUTRAL'] as Side[]).map((s) => ({ value: s, label: s }))} />
        </Field>
        <NumField label="Start lon" value={unit.start.lon} step={0.001} decimals={5} onCommit={(v) => v !== undefined && c.patchUnit(unit.id, { start: { ...unit.start, lon: v } })} />
        <NumField label="Start lat" value={unit.start.lat} step={0.001} decimals={5} onCommit={(v) => v !== undefined && c.patchUnit(unit.id, { start: { ...unit.start, lat: v } })} />
        <NumField label="Heading (°T)" value={unit.headingDeg} min={0} max={360} step={5} onCommit={(v) => v !== undefined && c.patchUnit(unit.id, { headingDeg: v })} />
        <NumField label={`Speed (kt, max ${cls.maxSpeedKt})`} value={unit.speedKt} min={0} max={cls.maxSpeedKt} step={1} onCommit={(v) => v !== undefined && c.patchUnit(unit.id, { speedKt: v })} />
        <NumField optional label="Turn limit (°/s)" placeholder={`${cls.turnRateDegPerS} (class)`} value={unit.maxTurnRateDegPerS} min={0.01} step={0.05} decimals={2} onCommit={(v) => c.patchUnit(unit.id, { maxTurnRateDegPerS: v })} />
      </div>
      <Field label="Behavior">
        <Select value={b.type} onChange={(v) => c.setBehaviorType(unit.id, v as Behavior['type'])} options={BEHAVIOR_OPTIONS} />
      </Field>
      <RouteEditor unit={unit} />
      {b.type === 'escort' && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Escort of">
            <Select value={b.leaderId} onChange={(v) => c.patchBehavior(unit.id, { leaderId: v })} options={otherOptions} />
          </Field>
          <span />
          <NumField label="Ahead (m)" value={b.aheadM} step={100} onCommit={(v) => v !== undefined && c.patchBehavior(unit.id, { aheadM: v })} />
          <NumField label="Abeam to starboard (m)" value={b.abeamM} step={100} onCommit={(v) => v !== undefined && c.patchBehavior(unit.id, { abeamM: v })} />
          <p className="col-span-2 text-[10px] text-mil-dim">Negative values put the station astern or to port.</p>
        </div>
      )}
      {b.type === 'pursue' && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Pursue">
            <Select value={b.targetId} onChange={(v) => c.patchBehavior(unit.id, { targetId: v })} options={otherOptions} />
          </Field>
          <NumField label="Shadow within (m)" value={b.standoffM} min={0} step={100} onCommit={(v) => v !== undefined && c.patchBehavior(unit.id, { standoffM: v })} />
        </div>
      )}
      {b.type === 'hold' && <p className="text-[10px] text-mil-dim">Stops and drifts with the current and wind.</p>}
      <Button size="sm" variant="ghost" className="text-mil-red" onClick={() => c.removeUnit(unit.id)}>
        Remove {unit.name}
      </Button>
    </div>
  );
}

function ForcesPanel() {
  const c = useController();
  const units = useExercise((s) => s.scenario.units);
  const selectedId = useExercise((s) => s.selectedId);
  const selected = units.find((u) => u.id === selectedId);
  const editor = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selectedId) editor.current?.scrollIntoView?.({ block: 'nearest' });
  }, [selectedId]);
  return (
    <Panel title="Ships" className="space-y-3 p-4">
      <ul className="space-y-1" aria-label="Ships">
        {units.map((u) => (
          <li key={u.id}>
            <button
              aria-pressed={u.id === selectedId}
              onClick={() => c.select(u.id === selectedId ? null : u.id)}
              className={cn(
                'flex w-full items-center gap-2 border px-2 py-1.5 text-left text-xs',
                u.id === selectedId ? 'border-mil-cyan/60 bg-mil-cyan/10 text-white' : 'border-mil-border text-mil-text hover:text-white',
              )}
            >
              <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SIDE_COLORS[u.side] }} />
              <span className="flex-1 truncate">{u.name}</span>
              <span className="text-[10px] text-mil-dim">{u.classId}</span>
            </button>
          </li>
        ))}
      </ul>
      <Button size="sm" variant="secondary" onClick={() => c.addUnit()}>
        + Add ship
      </Button>
      <div ref={editor}>{selected && <UnitEditor key={selected.id} unit={selected} />}</div>
    </Panel>
  );
}

export function Sidebar() {
  const c = useController();
  const errors = useExercise((s) => s.errors);
  const notice = useExercise((s) => s.notice);
  return (
    <div className="space-y-3">
      {errors.length > 0 && (
        <div role="alert" className="rounded-sm border border-mil-red/50 bg-mil-red/10 p-2 text-[11px] text-mil-red">
          <p>Your last change is not applied yet, and the map still shows the last version that ran. {errors[0]}</p>
          {errors.length > 1 && <p className="mt-1 text-mil-dim">{errors.length - 1} more problem{errors.length > 2 ? 's' : ''} after it.</p>}
        </div>
      )}
      {notice && (
        <div role="status" className="flex items-start justify-between gap-2 rounded-sm border border-mil-amber/40 bg-mil-amber/10 p-2 text-[11px] text-mil-amber">
          <span>{notice}</span>
          <button aria-label="Dismiss message" className="text-mil-dim hover:text-white" onClick={() => c.notify(null)}>
            ✕
          </button>
        </div>
      )}
      <ScenarioPanel />
      <EnvironmentPanel />
      <ForcesPanel />
    </div>
  );
}
