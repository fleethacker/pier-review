import { useEffect, useRef, useState } from 'react';
import { cn } from '../../lib/cn';
import { Button, Field, Panel, Select, inputClass } from '../../shell/ui';
import { useController, useExercise } from './context';
import { NumField } from './NumField';
import { PRESET_SCENARIOS } from './scenarios';
import { seaStateFromWind } from './sim';
import { CLASS_IDS, SENSORS, SHIP_CLASSES, SIDE_COLORS, isMissile, isPlatform } from './ships';
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
      <div className="grid grid-cols-[1fr_auto] items-end gap-3">
        <NumField label="Chance seed" value={scenario.seed ?? 1} min={0} step={1} onCommit={(v) => v !== undefined && c.patchScenario({ seed: Math.round(v) })} />
        <Button size="sm" variant="secondary" title="Roll the dice again: a different run of the same scenario" onClick={() => c.patchScenario({ seed: Math.floor(Math.random() * 100_000) })}>
          Re-roll
        </Button>
      </div>
      <p className="text-[10px] leading-snug text-mil-dim">Missile hits, defensive shots and mines are chances. The seed fixes how they fall, so a run repeats exactly.</p>
      <fieldset className="space-y-1.5">
        <legend className="mil-label mb-1">Realism</legend>
        <label className="flex items-center gap-2 text-[11px] text-mil-text">
          <input type="checkbox" checked={!!scenario.detection} onChange={(e) => c.patchScenario({ detection: e.target.checked })} />
          Sensors and detection
        </label>
        <p className="pl-6 text-[10px] leading-snug text-mil-dim">Radar is limited by the horizon and the sea, sonar hears what is under the water. Missiles are only fired at targets the side has found, and ships only shoot at missiles they are tracking. Off, everyone sees everything.</p>
        <label className="flex items-center gap-2 text-[11px] text-mil-text">
          <input type="checkbox" checked={!!scenario.seaState} onChange={(e) => c.patchScenario({ seaState: e.target.checked })} />
          Rough seas slow small ships
        </label>
      </fieldset>
      <JsonEditor />
    </Panel>
  );
}

function EnvironmentPanel() {
  const c = useController();
  const env = useExercise((s) => s.scenario.environment);
  const seaOn = useExercise((s) => !!s.scenario.seaState);
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
        {seaOn && ` Sea state ${seaStateFromWind(env.windKt)} (0 calm, 8 very rough).`}
      </p>
    </Panel>
  );
}

const BEHAVIOR_LABELS: Record<Behavior['type'], string> = {
  route: 'Follow a route',
  escort: 'Keep station on a unit',
  pursue: 'Pursue a unit',
  loiter: 'Circle a point',
  strike: 'Strike a unit',
  hold: 'Hold and drift',
};

/** The behaviors that make sense for a class, always including the one it has. */
function behaviorOptions(unit: UnitConfig): { value: Behavior['type']; label: string }[] {
  const cls = SHIP_CLASSES[unit.classId];
  const types: Behavior['type'][] =
    cls.domain === 'static' ? ['hold'] : isMissile(cls) ? ['strike', 'route'] : cls.domain === 'air' ? ['route', 'escort', 'pursue', 'loiter', 'hold'] : ['route', 'escort', 'pursue', 'hold'];
  if (!types.includes(unit.behavior.type)) types.push(unit.behavior.type);
  return types.map((value) => ({ value, label: value === 'hold' && cls.domain === 'air' && !cls.canHover ? 'Circle where it is' : BEHAVIOR_LABELS[value] }));
}

function RouteEditor({ unit }: { unit: UnitConfig }) {
  const c = useController();
  const placing = useExercise((s) => s.placing);
  const b = unit.behavior;
  if (b.type !== 'route') return null;
  const air = SHIP_CLASSES[unit.classId].domain === 'air';
  const cols = air ? 'grid-cols-[1.2rem_1fr_1fr_2.6rem_3.2rem_1.2rem]' : 'grid-cols-[1.2rem_1fr_1fr_3.2rem_1.2rem]';
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
        <div className={cn('grid gap-1 text-[9px] uppercase tracking-wider text-mil-dim', cols)}>
          <span>#</span>
          <span>Lon</span>
          <span>Lat</span>
          <span>Kt</span>
          {air && <span>Alt m</span>}
          <span />
        </div>
        {b.waypoints.map((w, i) => (
          <div key={i} className={cn('grid items-center gap-1', cols)}>
            <span className="text-[10px] text-mil-text">{i + 1}</span>
            <NumField compact label={`Waypoint ${i + 1} longitude`} value={w.lon} step={0.001} decimals={5} onCommit={(v) => v !== undefined && c.patchWaypoint(unit.id, i, { lon: v })} />
            <NumField compact label={`Waypoint ${i + 1} latitude`} value={w.lat} step={0.001} decimals={5} onCommit={(v) => v !== undefined && c.patchWaypoint(unit.id, i, { lat: v })} />
            <NumField compact optional label={`Waypoint ${i + 1} speed`} placeholder="–" value={w.speedKt} min={0} onCommit={(v) => c.patchWaypoint(unit.id, i, { speedKt: v })} />
            {air && <NumField compact optional label={`Waypoint ${i + 1} altitude`} placeholder="–" value={w.altitudeM} min={0} onCommit={(v) => c.patchWaypoint(unit.id, i, { altitudeM: v })} />}
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
  const air = cls.domain === 'air';
  const fixed = cls.domain === 'static';
  const weapon = !!cls.weapon;
  const otherOptions = others.map((u) => ({ value: u.id, label: u.name }));
  const num = (key: 'hp' | 'damage' | 'pHit' | 'pKill' | 'magazine' | 'altitudeM' | 'signature' | 'radarRangeM' | 'decoys' | 'pDecoy') => (v: number | undefined) => c.patchUnit(unit.id, { [key]: v });
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
        {!fixed && (
          <>
            <NumField label="Heading (°T)" value={unit.headingDeg} min={0} max={360} step={5} onCommit={(v) => v !== undefined && c.patchUnit(unit.id, { headingDeg: v })} />
            <NumField label={`Speed (kt, max ${cls.maxSpeedKt})`} value={unit.speedKt} min={0} max={cls.maxSpeedKt} step={1} onCommit={(v) => v !== undefined && c.patchUnit(unit.id, { speedKt: v })} />
            <NumField optional label="Turn limit (°/s)" placeholder={`${cls.turnRateDegPerS} (class)`} value={unit.maxTurnRateDegPerS} min={0.01} step={0.05} decimals={2} onCommit={(v) => c.patchUnit(unit.id, { maxTurnRateDegPerS: v })} />
          </>
        )}
        {air && !weapon && <NumField optional label="Altitude (m)" placeholder={`${cls.cruiseAltM} (class)`} value={unit.altitudeM} min={0} step={100} onCommit={num('altitudeM')} />}
      </div>
      {!fixed && (
        <Field label="Behavior">
          <Select value={b.type} onChange={(v) => c.setBehaviorType(unit.id, v as Behavior['type'])} options={behaviorOptions(unit)} />
        </Field>
      )}
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
      {b.type === 'loiter' && (
        <div className="grid grid-cols-2 gap-3">
          <NumField label="Center lon" value={b.center.lon} step={0.001} decimals={5} onCommit={(v) => v !== undefined && c.patchBehavior(unit.id, { center: { ...b.center, lon: v } })} />
          <NumField label="Center lat" value={b.center.lat} step={0.001} decimals={5} onCommit={(v) => v !== undefined && c.patchBehavior(unit.id, { center: { ...b.center, lat: v } })} />
          <NumField label="Radius (m)" value={b.radiusM} min={100} step={500} onCommit={(v) => v !== undefined && c.patchBehavior(unit.id, { radiusM: v })} />
        </div>
      )}
      {b.type === 'strike' && (
        <Field label="Strike">
          <Select value={b.targetId} onChange={(v) => c.patchBehavior(unit.id, { targetId: v })} options={otherOptions} />
        </Field>
      )}
      {b.type === 'hold' && !fixed && <p className="text-[10px] text-mil-dim">{air && !cls.canHover ? 'Circles where it started.' : 'Stops and drifts with the current and wind.'}</p>}
      {fixed && <p className="text-[10px] text-mil-dim">Stays where it is. Goes off, with a chance, under any ship of another side that passes within {cls.weapon?.fuzeM} m.</p>}

      <details className="space-y-2" open={!!unit.launch}>
        <summary className="mil-label cursor-pointer">Launch</summary>
        <div className="grid grid-cols-2 gap-3 pt-2">
          <Field label="Launched by">
            <Select
              value={unit.launch?.byId ?? ''}
              onChange={(v) => c.patchLaunch(unit.id, v ? { byId: v, atS: unit.launch?.atS ?? 60 } : null)}
              options={[{ value: '', label: 'Present from the start' }, ...otherOptions]}
            />
          </Field>
          {unit.launch && <NumField label="Launch at (s)" value={unit.launch.atS} min={0} step={10} onCommit={(v) => v !== undefined && c.patchLaunch(unit.id, { byId: unit.launch!.byId, atS: v })} />}
          <p className="col-span-2 text-[10px] text-mil-dim">A launched unit appears at its launcher. If the launcher has been destroyed by then, the launch does not happen.</p>
        </div>
      </details>

      <details className="space-y-2">
        <summary className="mil-label cursor-pointer">Damage and defences</summary>
        <div className="grid grid-cols-2 gap-3 pt-2">
          {!weapon && !fixed && <NumField optional label="Hit points" placeholder={`${cls.hp} (class)`} value={unit.hp} min={1} step={10} onCommit={num('hp')} />}
          {cls.weapon && <NumField optional label="Damage" placeholder={`${cls.weapon.damage} (class)`} value={unit.damage} min={0} step={5} onCommit={num('damage')} />}
          {cls.weapon && <NumField optional label="Hit chance (0–1)" placeholder={`${cls.weapon.pHit} (class)`} value={unit.pHit} min={0} max={1} step={0.05} decimals={2} onCommit={num('pHit')} />}
          {cls.defence && <NumField optional label="Defence kill chance (0–1)" placeholder={`${cls.defence.pKill} (class)`} value={unit.pKill} min={0} max={1} step={0.05} decimals={2} onCommit={num('pKill')} />}
          {cls.defence && <NumField optional label="Defensive shots" placeholder={`${cls.defence.magazine} (class)`} value={unit.magazine} min={0} step={2} onCommit={num('magazine')} />}
          <label className="col-span-2 flex items-center gap-2 text-[11px] text-mil-text">
            <input type="checkbox" checked={!!unit.disabled} onChange={(e) => c.patchUnit(unit.id, { disabled: e.target.checked || undefined })} />
            Leave this unit out of the run
          </label>
          <p className="col-span-2 text-[10px] leading-snug text-mil-dim">
            {weapon ? 'A missile or mine does its damage, with the hit chance, when it reaches its target.' : 'Anything that does at least this much damage in one hit destroys it. Below half strength a ship slows to half speed.'}
          </p>
        </div>
      </details>

      {!weapon && !fixed && (
        <details className="space-y-2">
          <summary className="mil-label cursor-pointer">Sensors and countermeasures</summary>
          <div className="grid grid-cols-2 gap-3 pt-2">
            <NumField optional label="Radar signature (1 = normal)" placeholder="1" value={unit.signature} min={0.001} step={0.1} decimals={3} onCommit={num('signature')} />
            {SENSORS[unit.classId]?.radarRangeM !== undefined && (
              <NumField optional label="Radar range vs 1 m² (m)" placeholder={`${SENSORS[unit.classId]!.radarRangeM} (class)`} value={unit.radarRangeM} min={0} step={5000} onCommit={num('radarRangeM')} />
            )}
            <NumField optional label="Decoys" placeholder="0" value={unit.decoys} min={0} step={1} onCommit={num('decoys')} />
            <NumField optional label="Decoy chance (0–1)" placeholder="0.3" value={unit.pDecoy} min={0} max={1} step={0.05} decimals={2} onCommit={num('pDecoy')} />
            <p className="col-span-2 text-[10px] leading-snug text-mil-dim">
              A low signature shrinks the range at which radar picks the unit up (range scales with the fourth root, so a tenth of the signature is about 56% of the range). Each missile or torpedo that gets close uses up one decoy and may be led away. Only matters when sensors and detection are on.
            </p>
          </div>
        </details>
      )}

      <Button size="sm" variant="ghost" className="text-mil-red" onClick={() => c.removeUnit(unit.id)}>
        Remove {unit.name}
      </Button>
    </div>
  );
}

function SalvoForm({ onDone }: { onDone: () => void }) {
  const c = useController();
  const units = useExercise((s) => s.scenario.units);
  const platforms = units.filter((u) => isPlatform(SHIP_CLASSES[u.classId]));
  const [launcher, setLauncher] = useState(platforms.find((u) => u.side === 'RED')?.id ?? platforms[0]?.id ?? '');
  const [target, setTarget] = useState(platforms.find((u) => u.side === 'BLUE')?.id ?? platforms[1]?.id ?? '');
  const [kind, setKind] = useState<ClassId>('ASM');
  const [count, setCount] = useState(4);
  const [first, setFirst] = useState(60);
  const [gap, setGap] = useState(4);
  const opts = platforms.map((u) => ({ value: u.id, label: u.name }));
  return (
    <div className="space-y-3 border border-mil-border p-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Fired from">
          <Select value={launcher} onChange={setLauncher} options={opts} />
        </Field>
        <Field label="At">
          <Select value={target} onChange={setTarget} options={opts} />
        </Field>
        <Field label="Missile">
          <Select value={kind} onChange={(v) => setKind(v as ClassId)} options={CLASS_IDS.filter((id) => isMissile(SHIP_CLASSES[id])).map((id) => ({ value: id, label: SHIP_CLASSES[id].name }))} />
        </Field>
        <NumField label="How many" value={count} min={1} max={40} onCommit={(v) => v !== undefined && setCount(v)} />
        <NumField label="First at (s)" value={first} min={0} step={10} onCommit={(v) => v !== undefined && setFirst(v)} />
        <NumField label="Gap (s)" value={gap} min={0} step={1} onCommit={(v) => v !== undefined && setGap(v)} />
      </div>
      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={() => {
            c.addSalvo(launcher, target, kind, count, first, gap);
            onDone();
          }}
        >
          Fire salvo
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function ForcesPanel() {
  const c = useController();
  const units = useExercise((s) => s.scenario.units);
  const selectedId = useExercise((s) => s.selectedId);
  const selected = units.find((u) => u.id === selectedId);
  const editor = useRef<HTMLDivElement>(null);
  const [salvo, setSalvo] = useState(false);
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
              <span className={cn('flex-1 truncate', u.disabled && 'line-through opacity-50')}>{u.name}</span>
              <span className="text-[10px] text-mil-dim">{u.classId}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => c.addUnit()}>
          + Add ship
        </Button>
        <div className="min-w-0 flex-1">
          <Select
            value=""
            onChange={(v) => v && c.addUnit(v as ClassId)}
            options={[
              { value: '', label: 'Add aircraft, submarine, missile or mine…' },
              ...(['FIGHTER', 'HELO', 'SSN', 'ASM', 'SAM', 'TORP', 'MINE'] as ClassId[]).map((id) => ({ value: id, label: SHIP_CLASSES[id].name })),
            ]}
          />
        </div>
      </div>
      {salvo ? (
        <SalvoForm onDone={() => setSalvo(false)} />
      ) : (
        <Button size="sm" variant="secondary" onClick={() => setSalvo(true)}>
          + Add salvo
        </Button>
      )}
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
