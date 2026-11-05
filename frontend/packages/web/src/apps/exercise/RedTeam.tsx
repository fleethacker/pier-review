import { useEffect, useState } from 'react';
import { cn } from '../../lib/cn';
import { Button, Field, Panel, Select, inputClass } from '../../shell/ui';
import { useController, useExercise } from './context';
import { formatClock } from './geo';
import { downloadText, fileSafe, openReport, reportHtml, resultCsv, resultJson } from './exportResults';
import { compareResults, defaultRedTeam, ENV_FIELDS, UNIT_FIELDS } from './montecarlo';
import type { McGroup, OutcomeDelta, OutcomeStat, TracePoint } from './montecarlo';
import { NumField } from './NumField';
import { parseRedTeam } from './scenarioJson';
import { SHIP_CLASSES, isMissile } from './ships';
import type { Dist, EnvField, OutcomeSpec, PerturbTarget, Perturbation, RedTeamSpec, ScenarioConfig, UnitField } from './types';

const ENV_LABEL: Record<EnvField, string> = {
  windKt: 'Wind speed (kt)',
  windFromDeg: 'Wind from (°)',
  currentKt: 'Current speed (kt)',
  currentToDeg: 'Current toward (°)',
};

const UNIT_LABEL: Record<UnitField, string> = {
  speedKt: 'Speed (kt)',
  headingDeg: 'Heading (°)',
  startEastM: 'Start position east (m)',
  startNorthM: 'Start position north (m)',
  routeEastM: 'Route shifted east (m)',
  routeNorthM: 'Route shifted north (m)',
  launchAtS: 'Launch time (s)',
  altitudeM: 'Altitude (m)',
  hp: 'Hit points',
  damage: 'Damage',
  pHit: 'Hit chance (0–1)',
  pKill: 'Defence kill chance (0–1)',
  magazine: 'Defensive shots',
  disabled: 'Left out (1) or in (0)',
};

const OFFSET = new Set<UnitField>(['startEastM', 'startNorthM', 'routeEastM', 'routeNorthM']);

const OUTCOME_TYPES: { value: OutcomeSpec['type']; label: string }[] = [
  { value: 'hit', label: 'A unit is hit' },
  { value: 'destroyed', label: 'A unit is destroyed' },
  { value: 'hp_below', label: 'A unit falls below a strength' },
  { value: 'side_losses', label: 'A side loses units' },
  { value: 'mine_strike', label: 'A mine goes off' },
  { value: 'intercepts', label: 'Missiles are shot down' },
  { value: 'closest_approach', label: 'Two units come close' },
  { value: 'all', label: 'All of several outcomes' },
  { value: 'any', label: 'Any of several outcomes' },
  { value: 'not', label: 'An outcome does not happen' },
];

const DIST_TYPES: { value: Dist['type']; label: string }[] = [
  { value: 'uniform', label: 'Uniform (min to max)' },
  { value: 'normal', label: 'Normal (mean, spread)' },
  { value: 'triangular', label: 'Triangular (min, likeliest, max)' },
  { value: 'choice', label: 'One of a list' },
];

const pct = (p: number, digits = 0) => `${(p * 100).toFixed(digits)}%`;
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const nextId = (prefix: string, taken: string[]) => {
  let n = taken.length + 1;
  while (taken.includes(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
};

/** A box holding a comma-separated list of numbers, committed on blur. */
function ListField({ label, value, onCommit, optional }: { label: string; value: number[] | undefined; onCommit: (v: number[] | undefined) => void; optional?: boolean }) {
  const show = (v: number[] | undefined) => (v ? v.join(', ') : '');
  const [text, setText] = useState(show(value));
  useEffect(() => setText(show(value)), [value]);
  const commit = () => {
    const t = text.trim();
    if (!t) return optional ? onCommit(undefined) : setText(show(value));
    const nums = t.split(/[,\s]+/).map(Number);
    if (nums.some((n) => !Number.isFinite(n))) return setText(show(value));
    onCommit(nums);
  };
  return (
    <Field label={label}>
      <input className={inputClass} value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} aria-label={label} />
    </Field>
  );
}

function useUnits() {
  const units = useExercise((s) => s.scenario.units);
  return { units, options: units.map((u) => ({ value: u.id, label: u.name })) };
}

function TargetPicker({ target, onChange, label }: { target: PerturbTarget; onChange: (t: PerturbTarget) => void; label: string }) {
  const { options } = useUnits();
  return (
    <div className="grid grid-cols-2 gap-2">
      <Field label={`${label}: what`}>
        <Select
          value={target.kind === 'environment' ? 'environment' : target.unitId}
          onChange={(v) => onChange(v === 'environment' ? { kind: 'environment', field: 'windKt' } : { kind: 'unit', unitId: v, field: target.kind === 'unit' ? target.field : 'pHit' })}
          options={[{ value: 'environment', label: 'The weather' }, ...options]}
        />
      </Field>
      <Field label={`${label}: setting`}>
        <Select
          value={target.field}
          onChange={(v) => onChange(target.kind === 'environment' ? { kind: 'environment', field: v as EnvField } : { ...target, field: v as UnitField })}
          options={target.kind === 'environment' ? ENV_FIELDS.map((f) => ({ value: f, label: ENV_LABEL[f] })) : UNIT_FIELDS.map((f) => ({ value: f, label: UNIT_LABEL[f] }))}
        />
      </Field>
    </div>
  );
}

function defaultDist(type: Dist['type']): Dist {
  switch (type) {
    case 'uniform':
      return { type, min: 0, max: 1 };
    case 'normal':
      return { type, mean: 0, sd: 1 };
    case 'triangular':
      return { type, min: 0, mode: 0.5, max: 1 };
    case 'choice':
      return { type, values: [0, 1] };
  }
}

function DistEditor({ dist, onChange }: { dist: Dist; onChange: (d: Dist) => void }) {
  const n = (key: string, label: string, value: number, patch: (v: number) => Dist) => (
    <NumField key={key} label={label} value={value} step={0.1} decimals={3} onCommit={(v) => v !== undefined && onChange(patch(v))} />
  );
  return (
    <div className="space-y-2">
      <Field label="How it varies">
        <Select value={dist.type} onChange={(v) => onChange(defaultDist(v as Dist['type']))} options={DIST_TYPES} />
      </Field>
      <div className="grid grid-cols-3 gap-2">
        {dist.type === 'uniform' && [n('a', 'Min', dist.min, (v) => ({ ...dist, min: v })), n('b', 'Max', dist.max, (v) => ({ ...dist, max: v }))]}
        {dist.type === 'normal' && [n('a', 'Mean', dist.mean, (v) => ({ ...dist, mean: v })), n('b', 'Spread (sd)', dist.sd, (v) => ({ ...dist, sd: v }))]}
        {dist.type === 'triangular' && [n('a', 'Min', dist.min, (v) => ({ ...dist, min: v })), n('b', 'Likeliest', dist.mode, (v) => ({ ...dist, mode: v })), n('c', 'Max', dist.max, (v) => ({ ...dist, max: v }))]}
      </div>
      {dist.type === 'choice' && (
        <div className="grid grid-cols-2 gap-2">
          <ListField label="Values" value={dist.values} onCommit={(v) => v && onChange({ ...dist, values: v })} />
          <ListField optional label="Weights (optional)" value={dist.weights} onCommit={(w) => onChange(w ? { ...dist, weights: w } : { type: 'choice', values: dist.values })} />
        </div>
      )}
    </div>
  );
}

function VariationRow({ p, onChange, onRemove }: { p: Perturbation; onChange: (p: Perturbation) => void; onRemove: () => void }) {
  const offset = p.target.kind === 'unit' && OFFSET.has(p.target.field);
  return (
    <details className="border border-mil-border p-2">
      <summary className="flex cursor-pointer items-center justify-between gap-2 text-[11px] text-white">
        <span className="truncate">{p.label ?? p.id}</span>
        <button
          aria-label={`Remove variation ${p.label ?? p.id}`}
          className="text-mil-dim hover:text-mil-red"
          onClick={(e) => {
            e.preventDefault();
            onRemove();
          }}
        >
          ✕
        </button>
      </summary>
      <div className="space-y-2 pt-2">
        <Field label="Name">
          <input className={inputClass} value={p.label ?? ''} placeholder={p.id} onChange={(e) => onChange({ ...p, label: e.target.value || undefined })} />
        </Field>
        <TargetPicker label="Vary" target={p.target} onChange={(target) => onChange({ ...p, target })} />
        {offset ? (
          <p className="text-[10px] text-mil-dim">The draw is a distance in meters added to the position.</p>
        ) : (
          <Field label="Applied to the scenario's value">
            <Select
              value={p.mode}
              onChange={(v) => onChange({ ...p, mode: v as Perturbation['mode'] })}
              options={[
                { value: 'set', label: 'Replace it' },
                { value: 'add', label: 'Add to it' },
                { value: 'scale', label: 'Multiply it' },
              ]}
            />
          </Field>
        )}
        <DistEditor dist={p.dist} onChange={(dist) => onChange({ ...p, dist })} />
      </div>
    </details>
  );
}

function makeOutcome(type: OutcomeSpec['type'], id: string, label: string | undefined, units: ScenarioConfig['units'], earlier: string[] = []): OutcomeSpec {
  const unitId = units[0]?.id ?? '';
  const base = { id, ...(label ? { label } : {}) };
  switch (type) {
    case 'hit':
    case 'destroyed':
      return { ...base, type, unitId };
    case 'hp_below':
      return { ...base, type, unitId, frac: 0.5 };
    case 'side_losses':
      return { ...base, type, side: 'BLUE', atLeast: 1 };
    case 'mine_strike':
      return { ...base, type };
    case 'intercepts':
      return { ...base, type, atLeast: 1 };
    case 'closest_approach':
      return { ...base, type, aId: unitId, bId: units[1]?.id ?? unitId, withinM: 2000 };
    case 'all':
    case 'any':
      return { ...base, type, of: earlier.slice(0, 2) };
    case 'not':
      return { ...base, type, of: earlier[0] ?? '' };
  }
}

function OutcomeRow({ o, earlier, onChange, onRemove }: { o: OutcomeSpec; earlier: { id: string; label: string }[]; onChange: (o: OutcomeSpec) => void; onRemove: () => void }) {
  const { units, options } = useUnits();
  return (
    <div className="space-y-2 border border-mil-border p-2">
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <Field label="Measure how often">
            <Select value={o.type} onChange={(v) => onChange({ ...makeOutcome(v as OutcomeSpec['type'], o.id, o.label, units, earlier.map((e) => e.id)), ...(o.beforeS !== undefined ? { beforeS: o.beforeS } : {}) } as OutcomeSpec)} options={OUTCOME_TYPES} />
          </Field>
        </div>
        <button aria-label={`Remove outcome ${o.label ?? o.id}`} className="pb-2 text-mil-dim hover:text-mil-red" onClick={onRemove}>
          ✕
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {(o.type === 'hit' || o.type === 'destroyed' || o.type === 'hp_below') && (
          <Field label="Unit">
            <Select value={o.unitId} onChange={(v) => onChange({ ...o, unitId: v })} options={options} />
          </Field>
        )}
        {o.type === 'hp_below' && <NumField label="Strength below (0–1)" value={o.frac} min={0.01} max={1} step={0.05} decimals={2} onCommit={(v) => v !== undefined && onChange({ ...o, frac: v })} />}
        {o.type === 'side_losses' && (
          <>
            <Field label="Side">
              <Select value={o.side} onChange={(v) => onChange({ ...o, side: v as 'BLUE' | 'RED' | 'NEUTRAL' })} options={['BLUE', 'RED', 'NEUTRAL'].map((s) => ({ value: s, label: s }))} />
            </Field>
            <NumField label="At least" value={o.atLeast} min={1} step={1} onCommit={(v) => v !== undefined && onChange({ ...o, atLeast: Math.round(v) })} />
          </>
        )}
        {o.type === 'mine_strike' && (
          <Field label="Ship">
            <Select value={o.unitId ?? ''} onChange={(v) => onChange(v ? { ...o, unitId: v } : { id: o.id, ...(o.label ? { label: o.label } : {}), type: 'mine_strike' })} options={[{ value: '', label: 'Any ship' }, ...options]} />
          </Field>
        )}
        {o.type === 'intercepts' && <NumField label="At least" value={o.atLeast} min={1} step={1} onCommit={(v) => v !== undefined && onChange({ ...o, atLeast: Math.round(v) })} />}
        {o.type === 'closest_approach' && (
          <>
            <Field label="Unit">
              <Select value={o.aId} onChange={(v) => onChange({ ...o, aId: v })} options={options} />
            </Field>
            <Field label="And">
              <Select value={o.bId} onChange={(v) => onChange({ ...o, bId: v })} options={options} />
            </Field>
            <NumField label="Within (m)" value={o.withinM} min={1} step={100} onCommit={(v) => v !== undefined && onChange({ ...o, withinM: v })} />
          </>
        )}
        <NumField optional label="Only if by this time (s)" value={o.beforeS} min={1} step={60} placeholder="any time" onCommit={(v) => onChange({ ...o, beforeS: v })} />
        <Field label="Name for the results">
          <input className={inputClass} value={o.label ?? ''} placeholder="(automatic)" onChange={(e) => onChange({ ...o, label: e.target.value || undefined })} />
        </Field>
      </div>
      {(o.type === 'all' || o.type === 'any') && (
        <fieldset className="space-y-1">
          <legend className="mil-label mb-1">Outcomes to combine (must be listed above this one)</legend>
          {earlier.length === 0 && <p className="text-[10px] text-mil-dim">Add an outcome above this one first.</p>}
          <div className="flex flex-col gap-1">
            {earlier.map((e) => (
              <label key={e.id} className="flex items-center gap-1.5 text-[11px] text-mil-text">
                <input
                  type="checkbox"
                  checked={o.of.includes(e.id)}
                  onChange={(ev) => onChange({ ...o, of: ev.target.checked ? [...o.of, e.id] : o.of.filter((x) => x !== e.id) })}
                />
                {e.label}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      {o.type === 'not' && (
        <Field label="The outcome that does not happen">
          <Select value={o.of} onChange={(v) => onChange({ ...o, of: v })} options={[{ value: '', label: 'Choose…' }, ...earlier.map((e) => ({ value: e.id, label: e.label }))]} />
        </Field>
      )}
    </div>
  );
}

function SweepEditor({ spec, update }: { spec: RedTeamSpec; update: (fn: (s: RedTeamSpec) => void) => void }) {
  const { units } = useUnits();
  const missiles = units.filter((u) => isMissile(SHIP_CLASSES[u.classId]));
  const sw = spec.sweep;
  if (!sw) {
    return (
      <div className="space-y-2">
        <p className="text-[10px] leading-snug text-mil-dim">A sweep repeats the whole batch at each of several values, to draw a curve: for example, how the chance of a hit changes as the salvo grows from 1 to 8 missiles.</p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={missiles.length === 0}
            onClick={() => update((s) => (s.sweep = { target: { kind: 'salvo', unitIds: missiles.map((m) => m.id) }, values: [1, Math.max(1, Math.ceil(missiles.length / 2)), missiles.length].filter((v, i, a) => a.indexOf(v) === i) }))}
          >
            Sweep the salvo size
          </Button>
          <Button size="sm" variant="secondary" onClick={() => update((s) => (s.sweep = { target: { kind: 'environment', field: 'windKt' }, values: [0, 10, 20, 30] }))}>
            Sweep a setting
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {sw.target.kind === 'salvo' ? (
        <>
          <fieldset className="space-y-1">
            <legend className="mil-label mb-1">Missiles in the salvo, in the order they are switched on</legend>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              {missiles.map((m) => (
                <label key={m.id} className="flex items-center gap-1.5 text-[11px] text-mil-text">
                  <input
                    type="checkbox"
                    checked={sw.target.kind === 'salvo' && sw.target.unitIds.includes(m.id)}
                    onChange={(e) =>
                      update((s) => {
                        if (s.sweep?.target.kind !== 'salvo') return;
                        const on = new Set(s.sweep.target.unitIds);
                        if (e.target.checked) on.add(m.id);
                        else on.delete(m.id);
                        s.sweep.target.unitIds = missiles.map((x) => x.id).filter((id) => on.has(id));
                      })
                    }
                  />
                  {m.name}
                </label>
              ))}
            </div>
          </fieldset>
          <ListField label="Salvo sizes to try" value={sw.values} onCommit={(v) => v && update((s) => (s.sweep!.values = v.map((x) => Math.max(0, Math.round(x)))))} />
        </>
      ) : (
        <>
          <TargetPicker label="Sweep" target={sw.target} onChange={(t) => update((s) => (s.sweep!.target = t))} />
          <ListField label="Values to try" value={sw.values} onCommit={(v) => v && update((s) => (s.sweep!.values = v))} />
        </>
      )}
      <Button size="sm" variant="ghost" onClick={() => update((s) => delete s.sweep)}>
        Remove the sweep
      </Button>
    </div>
  );
}

function SpecJson({ spec }: { spec: RedTeamSpec }) {
  const c = useController();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-2">
      <Button
        size="sm"
        variant="secondary"
        onClick={() => {
          setText(JSON.stringify(spec, null, 2));
          setError(null);
          setOpen(!open);
        }}
      >
        {open ? 'Hide JSON' : 'Edit all as JSON'}
      </Button>
      {open && (
        <>
          <textarea aria-label="Red-team JSON" className={cn(inputClass, 'h-52 resize-y text-[10px] leading-snug')} spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} />
          {error && <p className="text-[11px] text-mil-red">{error}</p>}
          <Button
            size="sm"
            onClick={() => {
              try {
                c.setRedTeam(parseRedTeam(JSON.parse(text)));
                setOpen(false);
              } catch (e) {
                setError(e instanceof SyntaxError ? 'That is not valid JSON.' : e instanceof Error ? e.message : String(e));
              }
            }}
          >
            Apply
          </Button>
        </>
      )}
    </div>
  );
}

function Setup() {
  const c = useController();
  const spec = useExercise((s) => s.scenario.redTeam)!;
  const scenario = useExercise((s) => s.scenario);
  const update = (fn: (s: RedTeamSpec) => void) => {
    const next = clone(spec);
    fn(next);
    c.setRedTeam(next);
  };
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <NumField label={spec.sweep ? 'Runs at each value' : 'Runs'} value={spec.runs} min={1} max={20000} step={50} onCommit={(v) => v !== undefined && update((s) => (s.runs = Math.round(v)))} />
        <NumField label="Seed" value={spec.seed} step={1} onCommit={(v) => v !== undefined && update((s) => (s.seed = Math.round(v)))} />
      </div>
      <p className="text-[10px] leading-snug text-mil-dim">The same seed repeats the same batch exactly, and every run in it can be replayed on the map.</p>
      <div className="grid grid-cols-2 items-end gap-3">
        <label className="flex items-center gap-2 pb-2 text-[11px] text-mil-text">
          <input type="checkbox" checked={spec.targetHalfWidth !== undefined} onChange={(e) => update((s) => (e.target.checked ? (s.targetHalfWidth = 0.02) : delete s.targetHalfWidth))} />
          Stop early when sure enough
        </label>
        {spec.targetHalfWidth !== undefined && (
          <NumField label="Sure to within ± (points)" value={Number((spec.targetHalfWidth * 100).toFixed(2))} min={0.1} max={50} step={0.5} decimals={2} onCommit={(v) => v !== undefined && update((s) => (s.targetHalfWidth = v / 100))} />
        )}
      </div>

      <Panel title="Outcomes to measure" className="space-y-2 p-3">
        {spec.outcomes.map((o, i) => (
          <OutcomeRow key={o.id} o={o} earlier={spec.outcomes.slice(0, i).map((x) => ({ id: x.id, label: x.label ?? x.id }))} onChange={(next) => update((s) => (s.outcomes[i] = next))} onRemove={() => update((s) => s.outcomes.splice(i, 1))} />
        ))}
        <Button size="sm" variant="secondary" onClick={() => update((s) => s.outcomes.push(makeOutcome('hit', nextId('o', s.outcomes.map((x) => x.id)), undefined, scenario.units)))}>
          + Add outcome
        </Button>
      </Panel>

      <Panel title="What varies from run to run" className="space-y-2 p-3">
        {spec.perturbations.map((p, i) => (
          <VariationRow key={p.id} p={p} onChange={(next) => update((s) => (s.perturbations[i] = next))} onRemove={() => update((s) => s.perturbations.splice(i, 1))} />
        ))}
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            update((s) =>
              s.perturbations.push({ id: nextId('v', s.perturbations.map((x) => x.id)), target: { kind: 'environment', field: 'windKt' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 4 } }),
            )
          }
        >
          + Add variation
        </Button>
      </Panel>

      <Panel title="Sweep (optional)" className="p-3">
        <SweepEditor spec={spec} update={update} />
      </Panel>

      <div className="flex flex-wrap gap-2">
        <SpecJson spec={spec} />
        <Button size="sm" variant="ghost" onClick={() => c.setRedTeam(defaultRedTeam(scenario))}>
          Reset to suggested setup
        </Button>
      </div>
    </div>
  );
}

function Interval({ o }: { o: OutcomeStat }) {
  return (
    <div className="relative h-3 w-full bg-mil-bg" role="img" aria-label={`${pct(o.p, 1)}, 95% interval ${pct(o.lo)} to ${pct(o.hi)}`}>
      <div className="absolute inset-y-0 left-0 bg-mil-cyan/50" style={{ width: pct(o.p) }} />
      <div className="absolute top-1/2 h-px -translate-y-1/2 bg-white" style={{ left: pct(o.lo), width: `${(o.hi - o.lo) * 100}%` }} />
      <div className="absolute inset-y-0.5 w-px bg-white" style={{ left: pct(o.lo) }} />
      <div className="absolute inset-y-0.5 w-px bg-white" style={{ left: pct(o.hi) }} />
    </div>
  );
}

const CURVE_COLORS = ['#00e5ff', '#ffc107', '#ff4a4a', '#00e676', '#b388ff', '#ff8a65'];

function SweepChart({ groups, outcomes }: { groups: McGroup[]; outcomes: { id: string; label: string }[] }) {
  const W = 480;
  const H = 150;
  const pad = { l: 34, r: 10, t: 10, b: 24 };
  const x = (i: number) => pad.l + (groups.length === 1 ? (W - pad.l - pad.r) / 2 : (i / (groups.length - 1)) * (W - pad.l - pad.r));
  const y = (p: number) => pad.t + (1 - p) * (H - pad.t - pad.b);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Chance of each outcome at each sweep value">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="#1a3a5c" strokeWidth={0.6} />
            <text x={pad.l - 4} y={y(t) + 3} textAnchor="end" fontSize={8} fill="#8ba4c4">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        {groups.map((g, i) => (
          <text key={i} x={x(i)} y={H - 8} textAnchor="middle" fontSize={8} fill="#8ba4c4">
            {g.sweepValue}
          </text>
        ))}
        {outcomes.map((o, oi) => {
          const color = CURVE_COLORS[oi % CURVE_COLORS.length];
          const stats = groups.map((g) => g.outcomes.find((s) => s.id === o.id)!);
          return (
            <g key={o.id}>
              <polyline fill="none" stroke={color} strokeWidth={1.5} points={stats.map((s, i) => `${x(i)},${y(s.p)}`).join(' ')} />
              {stats.map((s, i) => (
                <g key={i}>
                  <line x1={x(i)} x2={x(i)} y1={y(s.lo)} y2={y(s.hi)} stroke={color} strokeWidth={1} opacity={0.6} />
                  <circle cx={x(i)} cy={y(s.p)} r={2.5} fill={color} />
                </g>
              ))}
            </g>
          );
        })}
      </svg>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-mil-text">
        {outcomes.map((o, oi) => (
          <li key={o.id} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-3" style={{ background: CURVE_COLORS[oi % CURVE_COLORS.length] }} />
            {o.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Histogram({ o, durationS }: { o: OutcomeStat; durationS: number }) {
  const max = Math.max(1, ...o.timeHist);
  return (
    <div>
      <div className="flex h-12 items-end gap-px" role="img" aria-label="When it happened">
        {o.timeHist.map((n, i) => (
          <div key={i} className="flex-1 bg-mil-amber/70" style={{ height: `${(n / max) * 100}%`, minHeight: n ? 2 : 0 }} title={`${n} runs`} />
        ))}
      </div>
      <div className="flex justify-between text-[9px] text-mil-dim">
        <span>T+0</span>
        <span>T+{formatClock(durationS)}</span>
      </div>
    </div>
  );
}

/** The chance as runs accumulated, with its 95% band narrowing around it. */
function Convergence({ points, target }: { points: TracePoint[]; target: number }) {
  if (points.length < 2) return null;
  const W = 480;
  const H = 70;
  const pad = { l: 34, r: 8, t: 6, b: 14 };
  const maxN = points[points.length - 1].n;
  const x = (n: number) => pad.l + (n / maxN) * (W - pad.l - pad.r);
  const lo = Math.max(0, Math.min(...points.map((p) => p.lo)) - 0.02);
  const hi = Math.min(1, Math.max(...points.map((p) => p.hi)) + 0.02);
  const y = (p: number) => pad.t + (1 - (p - lo) / Math.max(hi - lo, 1e-6)) * (H - pad.t - pad.b);
  const band = [...points.map((p) => `${x(p.n)},${y(p.hi)}`), ...[...points].reverse().map((p) => `${x(p.n)},${y(p.lo)}`)].join(' ');
  const last = points[points.length - 1];
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`The chance settling at ${pct(last.p, 1)} after ${last.n} runs`}>
        <polygon points={band} fill="#00e5ff" opacity={0.18} />
        <polyline fill="none" stroke="#00e5ff" strokeWidth={1.5} points={points.map((p) => `${x(p.n)},${y(p.p)}`).join(' ')} />
        <text x={pad.l - 4} y={y(hi) + 8} textAnchor="end" fontSize={8} fill="#8ba4c4">
          {pct(hi)}
        </text>
        <text x={pad.l - 4} y={y(lo)} textAnchor="end" fontSize={8} fill="#8ba4c4">
          {pct(lo)}
        </text>
        <text x={pad.l} y={H - 2} fontSize={8} fill="#8ba4c4">
          0
        </text>
        <text x={W - pad.r} y={H - 2} textAnchor="end" fontSize={8} fill="#8ba4c4">
          {maxN} runs
        </text>
      </svg>
      <p className="text-[10px] text-mil-dim">
        {(Math.round((last.hi - last.lo) * 500) / 10).toFixed(1)} points either side now.
        {(last.hi - last.lo) / 2 <= target ? ` Within the ±${(target * 100).toFixed(0)} point target.` : ' Still settling: more runs would narrow it.'}
      </p>
    </div>
  );
}

function Detail({ group, groupIndex, outcome, durationS, target }: { group: McGroup; groupIndex: number; outcome: OutcomeStat; durationS: number; target: number }) {
  const c = useController();
  const rows = group.sensitivity
    .filter((r) => r.outcomeId === outcome.id)
    .sort((a, b) => Math.abs(b.corr) - Math.abs(a.corr))
    .slice(0, 6);
  const replay = (run: number) => {
    c.replayRun(groupIndex, run, outcome.label);
    c.toggleRedTeam(false);
  };
  const chips = (runs: number[]) =>
    runs.map((k) => (
      <button key={k} className="border border-mil-border px-1.5 py-0.5 text-[10px] text-mil-text hover:border-mil-cyan/60 hover:text-white" onClick={() => replay(k)}>
        Run {k + 1}
      </button>
    ));
  return (
    <div className="space-y-3 border-t border-mil-border pt-3">
      <p className="text-[11px] text-white">
        {outcome.label}: {outcome.hits} of {outcome.n} runs ({pct(outcome.p, 1)}, 95% interval {pct(outcome.lo, 1)} to {pct(outcome.hi, 1)}).
        {outcome.meanTimeS !== null && ` On average it happens at T+${formatClock(outcome.meanTimeS)}.`}
      </p>
      <div>
        <p className="mil-label mb-1">How sure the number is</p>
        <Convergence points={group.trace[outcome.id] ?? []} target={target} />
        {outcome.halfWidth > target && <p className="text-[10px] text-mil-dim">About {outcome.runsNeeded.toLocaleString('en-US')} runs in all would get within ±{(target * 100).toFixed(0)} points.</p>}
      </div>
      {outcome.hits > 0 && (
        <div>
          <p className="mil-label mb-1">When it happens</p>
          <Histogram o={outcome} durationS={durationS} />
        </div>
      )}
      <div>
        <p className="mil-label mb-1">What drives it</p>
        {rows.length === 0 ? (
          <p className="text-[10px] text-mil-dim">Nothing is varied, or every run came out the same way, so there is nothing to rank.</p>
        ) : (
          <table className="w-full text-[10px]">
            <thead>
              <tr className="text-left text-mil-dim">
                <th className="py-0.5 font-normal">Variation</th>
                <th className="py-0.5 font-normal">Effect</th>
                <th className="py-0.5 text-right font-normal">When it happens / when not</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.perturbationId} className="border-t border-mil-border/50 text-mil-text">
                  <td className="py-1 pr-2">{r.label}</td>
                  <td className="py-1 pr-2">
                    <div className="relative h-2 w-24 bg-mil-bg" role="img" aria-label={`correlation ${r.corr.toFixed(2)}`}>
                      <div className="absolute inset-y-0 left-1/2 w-px bg-mil-border" />
                      <div className={cn('absolute inset-y-0', r.corr >= 0 ? 'left-1/2 bg-mil-red/70' : 'right-1/2 bg-mil-green/70')} style={{ width: `${Math.min(1, Math.abs(r.corr)) * 50}%` }} />
                    </div>
                  </td>
                  <td className="py-1 text-right tabular-nums">
                    {r.meanWhenHit === null ? '–' : r.meanWhenHit.toFixed(2)} / {r.meanWhenNot === null ? '–' : r.meanWhenNot.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="mt-1 text-[9px] leading-snug text-mil-dim">Red to the right: higher values make it more likely. Green to the left: higher values make it less likely.</p>
      </div>
      <div className="space-y-1">
        <p className="mil-label">Watch a run</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] text-mil-dim">Where it happened:</span>
          {group.hitRuns[outcome.id]?.length ? chips(group.hitRuns[outcome.id]) : <span className="text-[10px] text-mil-dim">none</span>}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] text-mil-dim">Where it did not:</span>
          {group.missRuns[outcome.id]?.length ? chips(group.missRuns[outcome.id]) : <span className="text-[10px] text-mil-dim">none</span>}
        </div>
      </div>
    </div>
  );
}

function DeltaChip({ d }: { d: OutcomeDelta }) {
  const pts = d.delta * 100;
  const color = !d.significant ? 'text-mil-dim' : pts > 0 ? 'text-mil-red' : 'text-mil-green';
  return (
    <span className={cn('tabular-nums', color)} title={`${pct(d.before, 1)} before; the change is ${pts >= 0 ? '+' : ''}${pts.toFixed(1)} points (95% interval ${(d.lo * 100).toFixed(1)} to ${(d.hi * 100).toFixed(1)})${d.significant ? '' : ', which could be chance'}`}>
      {pts >= 0 ? '▲' : '▼'} {Math.abs(pts).toFixed(1)} pts{d.significant ? '' : ' (within noise)'}
    </span>
  );
}

function ExportBar() {
  const c = useController();
  const mc = useExercise((s) => s.mc);
  const baseline = useExercise((s) => s.baseline);
  const [blocked, setBlocked] = useState(false);
  if (!mc.result || !mc.spec || !mc.base) return null;
  const { result, spec, base } = mc;
  const stem = `red-team-${fileSafe(base.name)}`;
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => downloadText(`${stem}.csv`, 'text/csv', resultCsv(result))}>
          Download CSV
        </Button>
        <Button size="sm" variant="secondary" onClick={() => downloadText(`${stem}.json`, 'application/json', resultJson(base, spec, result))}>
          Download JSON
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setBlocked(!openReport(reportHtml(base, spec, result, baseline?.result)))}>
          Report to print
        </Button>
        <Button size="sm" variant="secondary" onClick={() => c.pinBaseline()}>
          Keep as baseline
        </Button>
      </div>
      {blocked && <p role="alert" className="text-[10px] text-mil-amber">The browser blocked the report window. Allow pop-ups for this page and try again.</p>}
    </div>
  );
}

function Results() {
  const mc = useExercise((s) => s.mc);
  const baseline = useExercise((s) => s.baseline);
  const c = useController();
  const scenario = useExercise((s) => s.scenario);
  const [outcomeId, setOutcomeId] = useState<string | null>(null);
  const [groupIndex, setGroupIndex] = useState<number | null>(null);
  const result = mc.result;
  if (!result || !mc.spec || !mc.base) return null;
  const gi = Math.min(groupIndex ?? result.groups.length - 1, result.groups.length - 1);
  const group = result.groups[gi];
  const outcome = group.outcomes.find((o) => o.id === outcomeId) ?? group.outcomes[0];
  const sweep = result.groups.length > 1;
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
  const deltas = baseline && baseline.result !== result ? compareResults(baseline.result, result) : [];
  const groupDeltas = deltas.find((d) => d.label === group.label);
  const stale = !same({ ...scenario, redTeam: undefined }, { ...mc.base, redTeam: undefined }) || !same(scenario.redTeam, mc.spec);
  return (
    <div className="space-y-3">
      {stale && <p role="status" className="border border-mil-amber/40 bg-mil-amber/10 p-2 text-[10px] text-mil-amber">The scenario or the settings have changed since this batch ran. Run it again to measure the new setup. Replays still show the setup that was measured.</p>}
      <p className="text-[10px] text-mil-dim">
        {result.totalRuns.toLocaleString('en-US')} runs in {(result.elapsedMs / 1000).toFixed(1)} s{result.stopped ? ', stopped early' : ''}
        {result.converged ? ', stopped once every chance was pinned down to the target' : ''}. Bars show the chance; the line is the 95% interval.
      </p>
      <ExportBar />
      {baseline && (
        <div className="flex items-start justify-between gap-2 border border-mil-border p-2 text-[10px] text-mil-text">
          <span>
            {baseline.result === result ? 'This batch is the baseline: ' : 'Comparing with the baseline: '}
            {baseline.label}.{baseline.result !== result && ' Arrows show how each chance moved; grey means the move could be chance.'}
          </span>
          <button className="shrink-0 text-mil-dim hover:text-white" onClick={() => c.clearBaseline()}>
            Clear
          </button>
        </div>
      )}
      {sweep && (
        <div className="space-y-2">
          <p className="mil-label">Chance against {mc.spec.sweep && mc.spec.sweep.target.kind === 'salvo' ? 'salvo size' : 'the swept setting'}</p>
          <SweepChart groups={result.groups} outcomes={group.outcomes.map((o) => ({ id: o.id, label: o.label }))} />
          <Field label="Look in detail at">
            <Select value={String(gi)} onChange={(v) => setGroupIndex(Number(v))} options={result.groups.map((g, i) => ({ value: String(i), label: g.label }))} />
          </Field>
        </div>
      )}
      <ul className="space-y-1" aria-label="Outcome chances">
        {group.outcomes.map((o) => (
          <li key={o.id}>
            <button
              aria-pressed={o.id === outcome.id}
              onClick={() => setOutcomeId(o.id)}
              className={cn('w-full space-y-1 border p-2 text-left', o.id === outcome.id ? 'border-mil-cyan/60 bg-mil-cyan/5' : 'border-mil-border hover:border-mil-text')}
            >
              <div className="flex items-baseline justify-between gap-2 text-[11px]">
                <span className="truncate text-white">{o.label}</span>
                <span className="tabular-nums text-mil-cyan">
                  {pct(o.p, o.n >= 1000 ? 1 : 0)} <span className="text-mil-dim">±{(o.halfWidth * 100).toFixed(1)} ({pct(o.lo)}–{pct(o.hi)})</span>
                </span>
              </div>
              <Interval o={o} />
              {groupDeltas?.rows.find((r) => r.id === o.id) && (
                <div className="text-[10px]">
                  <DeltaChip d={groupDeltas.rows.find((r) => r.id === o.id)!} />
                </div>
              )}
            </button>
          </li>
        ))}
      </ul>
      <Detail group={group} groupIndex={gi} outcome={outcome} durationS={mc.base.durationS} target={mc.spec.targetHalfWidth ?? 0.02} />
      <div>
        <p className="mil-label mb-1">Average per run{sweep ? `, ${group.label}` : ''}</p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px]">
          {group.metrics.map((m) => (
            <div key={m.label} className="flex justify-between">
              <dt className="text-mil-dim">{m.label.replace(' per run', '')}</dt>
              <dd className="tabular-nums text-white">{m.mean.toFixed(2)}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

export function RedTeamPanel() {
  const c = useController();
  const open = useExercise((s) => s.redTeamOpen);
  const spec = useExercise((s) => s.scenario.redTeam);
  const mc = useExercise((s) => s.mc);
  const scenario = useExercise((s) => s.scenario);
  const errors = useExercise((s) => s.errors);
  if (!open || !spec) return null;
  const problems = c.redTeamProblems();
  const running = mc.status === 'running';
  const blocked = problems.length > 0 || errors.length > 0;
  const total = mc.total || spec.runs * (spec.sweep?.values.length ?? 1);
  return (
    <div role="dialog" aria-label="Red team" className="pointer-events-auto absolute bottom-3 right-3 top-14 z-20 flex w-[560px] max-w-[calc(100%-1.5rem)] flex-col border border-mil-border bg-mil-panel/95 shadow-glass backdrop-blur">
      <div className="flex items-start justify-between gap-3 border-b border-mil-border p-4">
        <div>
          <h2 className="mil-label text-[11px]">Red team</h2>
          <p className="mt-1 text-[11px] leading-snug text-mil-text">
            Run “{scenario.name}” over and over with random variation, and measure how often things happen. Chance rolls and the variations below differ from run to run; everything else is the same.
          </p>
        </div>
        <button aria-label="Close red team" className="text-mil-dim hover:text-white" onClick={() => c.toggleRedTeam(false)}>
          ✕
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <details open={mc.status === 'idle' || mc.status === 'error'}>
          <summary className="mil-label cursor-pointer">Setup</summary>
          <div className="pt-3">
            <Setup />
          </div>
        </details>

        {(problems.length > 0 || errors.length > 0) && (
          <div role="alert" className="space-y-1 border border-mil-red/50 bg-mil-red/10 p-2 text-[11px] text-mil-red">
            {errors.length > 0 && <p>The scenario has a problem to fix first: {errors[0]}</p>}
            {problems.slice(0, 4).map((p) => (
              <p key={p}>{p}</p>
            ))}
            {problems.length > 4 && <p className="text-mil-dim">{problems.length - 4} more.</p>}
          </div>
        )}

        <div className="space-y-2">
          <div className="flex items-center gap-3">
            {running ? (
              <Button size="sm" variant="secondary" onClick={() => c.stopRedTeam()}>
                Stop
              </Button>
            ) : (
              <Button size="sm" disabled={blocked} onClick={() => void c.runRedTeam()}>
                {mc.status === 'done' ? 'Run again' : 'Run'} {(spec.runs * (spec.sweep?.values.length ?? 1)).toLocaleString('en-US')} runs
              </Button>
            )}
            {running && (
              <span className="tabular-nums text-[11px] text-mil-cyan">
                {mc.done.toLocaleString('en-US')} / {total.toLocaleString('en-US')}
              </span>
            )}
          </div>
          {running && (
            <div className="h-1.5 w-full bg-mil-bg" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={mc.done} aria-label="Progress">
              <div className="h-full bg-mil-cyan" style={{ width: `${Math.min(100, (mc.done / Math.max(1, total)) * 100)}%` }} />
            </div>
          )}
          {mc.status === 'error' && <p role="alert" className="text-[11px] text-mil-red">{mc.error}</p>}
        </div>

        <Results />
      </div>
    </div>
  );
}
