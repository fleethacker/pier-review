import { useState } from 'react';
import { Button, inputClass } from '../../../shell/ui';
import type { MotionController, MotionState } from './controller';
import type { HelmOrder, PayloadItem, TugOrder, TugDynamicsState, ControlsConfig } from './workspace';

// Empty numeric drafts are unknown, never an implicit zero. Only validated numbers enter commands.
const draftNumber = (value: string) => value.trim() ? Number(value) : Number.NaN;
const PAYLOAD_FIELDS = [
  ['weight_lbf', 'Weight (lbf)', 0, 1e9], ['x_ft', 'Forward x (ft)', -10000, 10000],
  ['y_ft', 'Port y (ft)', -10000, 10000], ['z_ft', 'Height z (ft)', -1000, 1000],
] as const;
type PayloadDraft = Omit<PayloadItem, typeof PAYLOAD_FIELDS[number][0]> & Record<typeof PAYLOAD_FIELDS[number][0], string>;
type TugDraft = { mode: TugOrder['mode'] } & Record<Exclude<keyof TugOrder, 'mode'>, string>;

function Lever({ label, value, actual, min = -100, max = 100, unit = '%', hint, onChange, disabled }: { label: string; value: number; actual: number; min?: number; max?: number; unit?: string; hint: string; onChange: (v: number) => void; disabled: boolean }) {
  return <label className="block min-w-0 border-r border-mil-border px-3 py-2 last:border-r-0">
    <span className="flex items-baseline justify-between gap-2 text-[10px]"><span className="uppercase tracking-wider text-mil-text">{label}</span><span className="text-mil-cyan">{value.toFixed(0)}{unit}</span></span>
    <input aria-label={label} className="my-2 block w-full accent-cyan-300" type="range" min={min} max={max} step={1} value={value} onChange={(e) => onChange(Number(e.target.value))} disabled={disabled} aria-valuetext={`${value.toFixed(0)} ${unit === '%' ? 'percent' : 'degrees'} ordered; ${actual.toFixed(0)} actual`} />
    <span className="flex justify-between gap-2 text-[9px] text-mil-dim"><span>{hint}</span><span className="whitespace-nowrap">Actual {actual.toFixed(0)}{unit}</span></span>
  </label>;
}

export function ManeuverControls({ c, s }: { c: MotionController; s: MotionState }) {
  const control = s.frame?.controls;
  const [draft, setDraft] = useState<HelmOrder | null>(() => control?.commanded ?? null);
  const [auxiliary, setAuxiliary] = useState<'tugs' | 'lines' | 'payloads' | null>(null);
  if (!control || !s.workspace) return <p className="px-3 py-2 text-[11px] text-mil-dim">Awaiting backend actuator state. Controls are available when this scenario supplies propulsion parameters.</p>;
  const order = draft ?? control.commanded;
  const actual = control.actual;
  const disabled = s.link !== 'open' || s.busy || s.stateImportBusy || s.lifecycleInvalid;
  const update = (k: keyof HelmOrder, v: number) => setDraft({ ...order, [k]: v });
  const spec = s.workspace.controls.propulsion;
  return <div className="bg-mil-panel">
    <div className="grid grid-cols-2 border-b border-mil-border sm:grid-cols-3 xl:grid-cols-5">
      <Lever label="Port engine" value={order.port_throttle * 100} actual={actual.port_throttle * 100} hint="Astern − / + Ahead" onChange={(v) => update('port_throttle', v / 100)} disabled={disabled} />
      <Lever label="Starboard engine" value={order.starboard_throttle * 100} actual={actual.starboard_throttle * 100} hint="Astern − / + Ahead" onChange={(v) => update('starboard_throttle', v / 100)} disabled={disabled} />
      <Lever label="Rudder" value={order.rudder_deg} actual={actual.rudder_deg} min={-spec.rudder_max_deg} max={spec.rudder_max_deg} unit="°" hint="Port − / + Starboard" onChange={(v) => update('rudder_deg', v)} disabled={disabled} />
      <Lever label="Bow thruster" value={order.bow_thruster * 100} actual={actual.bow_thruster * 100} hint="Starboard − / + Port" onChange={(v) => update('bow_thruster', v / 100)} disabled={disabled || spec.bow_thruster_max_lbf === 0} />
      <Lever label="Stern thruster" value={order.stern_thruster * 100} actual={actual.stern_thruster * 100} hint="Starboard − / + Port" onChange={(v) => update('stern_thruster', v / 100)} disabled={disabled || spec.stern_thruster_max_lbf === 0} />
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2"><Button size="sm" onClick={() => c.helmCommand(order)} disabled={disabled}>Apply helm order</Button><Button size="sm" variant="secondary" onClick={() => void c.refreshPrediction(order)} disabled={disabled || s.predictionBusy}>Preview order</Button><Button size="sm" variant="secondary" disabled={disabled} onClick={() => { const neutral = { port_throttle: 0, starboard_throttle: 0, rudder_deg: 0, bow_thruster: 0, stern_thruster: 0 }; setDraft(neutral); c.helmCommand(neutral); }}>Order neutral</Button></div>
      <div className="flex gap-1" role="group" aria-label="Auxiliary controls">{(['tugs', 'lines', 'payloads'] as const).map((tab) => <Button key={tab} size="sm" variant="secondary" aria-expanded={auxiliary === tab} aria-controls="motion-auxiliary" onClick={() => setAuxiliary(auxiliary === tab ? null : tab)}>{tab === 'tugs' ? 'Tugs' : tab === 'lines' ? 'Mooring lines' : 'Payload & loading'}</Button>)}</div>
    </div>
    <p className="px-3 pb-2 text-[9px] text-mil-dim">Orders apply when simulation advances. Neutral removes commanded thrust; vessel momentum remains. {control.basis} propulsion · rudder sign describes ahead flow.</p>
    {s.command && <p role="status" className={`border-t border-mil-border px-3 py-2 text-[10px] ${s.command.status === 'applied' ? 'text-mil-cyan' : 'text-mil-amber'}`}>{s.command.status.toUpperCase()} · {s.command.message}</p>}
    {auxiliary && <div id="motion-auxiliary" className="max-h-60 overflow-y-auto border-t border-mil-border px-3 py-3">
      {auxiliary === 'tugs' && <TugControls c={c} s={s} disabled={disabled} />}
      {auxiliary === 'lines' && <LineControls c={c} s={s} disabled={disabled} />}
      {auxiliary === 'payloads' && <PayloadControls key={s.sessionId} c={c} s={s} disabled={disabled} />}
    </div>}
  </div>;
}

function TugControls({ c, s, disabled }: { c: MotionController; s: MotionState; disabled: boolean }) {
  const [selected, setSelected] = useState('');
  const [forceDraft, setForceDraft] = useState('0');
  const force = draftNumber(forceDraft);
  const [direction, setDirection] = useState(90);
  const choices = s.frame?.tugs ?? [];
  const id = choices.some((t) => t.id === selected) ? selected : choices[0]?.id ?? '';
  const tug = choices.find((t) => t.id === id);
  const capacity = s.catalog?.tugs.find((t) => t.tug_id === id)?.bollard_pull_ahead_lbf;
  const config = s.workspace?.controls.tug_dynamics?.find((t) => t.tug_id === id);
  const dynamic = s.frame?.tugDynamics.find((t) => t.tug_id === id);
  if (config) return <div className="space-y-3"><label className="flex items-center gap-2 text-[10px] text-mil-dim">Tug<select aria-label="Workspace tug" className={`${inputClass} w-28`} value={id} onChange={(e) => setSelected(e.target.value)}>{choices.map((t) => <option key={t.id}>{t.id}</option>)}</select><span>Independent backend dynamics · {config.basis}</span></label>{dynamic ? <DynamicTugControls key={id} c={c} config={config} state={dynamic} disabled={disabled} /> : <p className="text-xs text-mil-dim">Waiting for the tug's backend command state.</p>}</div>;
  return <div className="flex flex-wrap items-end gap-3 text-[10px]">
    <label className="grid gap-1 text-mil-dim">Tug<select aria-label="Workspace tug" className={inputClass} value={id} onChange={(e) => { setSelected(e.target.value); setForceDraft('0'); }}>{!choices.length && <option value="">None assigned</option>}{choices.map((t) => <option key={t.id}>{t.id}</option>)}</select></label>
    <label className="grid gap-1 text-mil-dim">Tug force (lbf)<input className={`${inputClass} w-28`} type="number" min={0} max={capacity} step="any" value={forceDraft} onChange={(e) => setForceDraft(e.target.value)} /></label>
    <label className="grid gap-1 text-mil-dim">Force toward<select className={inputClass} value={direction} onChange={(e) => setDirection(Number(e.target.value))}><option value={90}>Starboard (90°)</option><option value={270}>Port (270°)</option></select></label>
    <Button size="sm" disabled={disabled || !id || !Number.isFinite(force) || force < 0 || (capacity != null && force > capacity)} onClick={() => c.tugCommand(id, force, direction)}>Apply tug command</Button>
    <p className="text-mil-dim">{tug?.actualForce ? `Reported force ${Math.hypot(tug.actualForce.x, tug.actualForce.y).toFixed(0)} lbf` : 'Reported force unavailable'} · {tug?.contactState.replace(/_/g, ' ') ?? 'No tug assigned'}</p>
  </div>;
}

function DynamicTugControls({ c, config, state, disabled }: { c: MotionController; config: NonNullable<ControlsConfig['tug_dynamics']>[number]; state: TugDynamicsState; disabled: boolean }) {
  const [draft, setDraft] = useState<TugDraft>(() => ({ mode: state.commanded.mode, target_velocity_x_fps: String(state.commanded.target_velocity_x_fps), target_velocity_y_fps: String(state.commanded.target_velocity_y_fps), target_heading_true_deg: String(state.commanded.target_heading_true_deg), tow_length_ft: String(state.commanded.tow_length_ft) }));
  const order: TugOrder = { mode: draft.mode, target_velocity_x_fps: draftNumber(draft.target_velocity_x_fps), target_velocity_y_fps: draftNumber(draft.target_velocity_y_fps), target_heading_true_deg: draftNumber(draft.target_heading_true_deg), tow_length_ft: draftNumber(draft.tow_length_ft) };
  const speed = Math.hypot(order.target_velocity_x_fps, order.target_velocity_y_fps);
  const valid = [order.target_velocity_x_fps, order.target_velocity_y_fps, order.target_heading_true_deg, order.tow_length_ft].every(Number.isFinite) && speed <= config.max_target_speed_fps && order.target_heading_true_deg >= 0 && order.target_heading_true_deg < 360 && order.tow_length_ft > 0 && order.tow_length_ft <= 10000;
  return <div className="space-y-2 text-[10px]"><div className="flex flex-wrap items-end gap-3"><label className="grid gap-1 text-mil-dim">Connection mode<select aria-label="Tug connection mode" className={inputClass} value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value as TugOrder['mode'] })}><option value="free">Free maneuvering</option><option value="push">Push on contact</option><option value="tow">Tow when taut</option></select></label>
    {([['target_velocity_x_fps', 'Along-pier target (ft/s)', -config.max_target_speed_fps, config.max_target_speed_fps], ['target_velocity_y_fps', 'Off-pier target (ft/s)', -config.max_target_speed_fps, config.max_target_speed_fps], ['target_heading_true_deg', 'Tug heading (° true)', 0, 360], ['tow_length_ft', 'Tow length (ft)', 0, 10000]] as const).map(([key, label, min, max]) => <label key={key} className="grid gap-1 text-mil-dim">{label}<input className={`${inputClass} w-28`} type="number" min={min} max={max} step="any" value={draft[key]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
    <Button size="sm" disabled={disabled || !valid} onClick={() => c.tugMotionCommand(config.tug_id, order)}>Apply tug maneuver</Button></div>
    <p className="text-mil-dim">Target speed limit {config.max_target_speed_fps.toFixed(1)} ft/s. Positive y is away from the pier. Orders use the tug's own inertia and propulsion; force transfers only at contact or with a taut tow.</p>
    <p className="text-mil-cyan">Reported: {state.connection_state.replace(/_/g, ' ')} · transferred force {Math.hypot(state.transferred_x_lbf, state.transferred_y_lbf).toFixed(0)} lbf · compression {state.contact_compression_ft.toFixed(2)} ft · tow tension {state.tow_tension_lbf.toFixed(0)} lbf</p>
  </div>;
}

function LineControls({ c, s, disabled }: { c: MotionController; s: MotionState; disabled: boolean }) {
  const lines = s.frame?.lineControls ?? [];
  return <div className="space-y-2"><p className="text-[10px] text-mil-dim">Attach or release each line, then set its paid-out length. Tension and extension come from the backend.</p>{!lines.length && <p className="text-xs text-mil-dim">No controllable lines in this scenario.</p>}{lines.map((l) => <LineRow key={l.line_number} line={l} c={c} disabled={disabled} />)}</div>;
}

function LineRow({ line, c, disabled }: { line: NonNullable<MotionState['frame']>['lineControls'][number]; c: MotionController; disabled: boolean }) {
  const [lengthDraft, setLengthDraft] = useState(String(line.paid_out_length_ft));
  const length = draftNumber(lengthDraft);
  return <div className="flex flex-wrap items-center gap-3 border-b border-mil-border pb-2 text-[10px]"><span className="w-28">Line {line.line_number} · {line.attached ? 'attached' : 'released'}</span><label className="flex items-center gap-2 text-mil-dim">Paid out (ft)<input aria-label={`Line ${line.line_number} paid out (ft)`} className={`${inputClass} w-24`} type="number" min={0} max={10000} step="any" value={lengthDraft} onChange={(e) => setLengthDraft(e.target.value)} /></label><Button size="sm" variant="secondary" disabled={disabled || !Number.isFinite(length) || length <= 0 || length > 10000} onClick={() => c.lineControl({ line_number: line.line_number, paid_out_length_ft: length })}>Set length</Button><Button size="sm" variant="secondary" disabled={disabled} onClick={() => c.lineControl({ line_number: line.line_number, attached: !line.attached })}>{line.attached ? 'Release' : 'Attach'}</Button><span className="text-mil-dim">Reported {line.paid_out_length_ft.toFixed(1)} ft · extension {line.extension_ft.toFixed(1)} ft · {line.tension_lbf == null ? 'tension unavailable' : `${line.tension_lbf.toFixed(0)} lbf`}</span></div>;
}

function PayloadControls({ c, s, disabled }: { c: MotionController; s: MotionState; disabled: boolean }) {
  const [payloads, setPayloads] = useState<PayloadDraft[]>(() => (s.frame?.loading?.payloads ?? []).map((p) => ({ ...p, weight_lbf: String(p.weight_lbf), x_ft: String(p.x_ft), y_ft: String(p.y_ft), z_ft: String(p.z_ft) })));
  const [nextId, setNextId] = useState(1);
  const atRest = (s.lifecycle === 'paused' || s.lifecycle === 'reset' || s.lifecycle === 'created') && s.frame?.ship.surgeFps != null && s.frame.ship.swayFps != null && s.frame.ship.yawDegps != null && Math.abs(s.frame.ship.surgeFps) < 1e-6 && Math.abs(s.frame.ship.swayFps) < 1e-6 && Math.abs(s.frame.ship.yawDegps) < 1e-6;
  const update = (i: number, patch: Partial<PayloadDraft>) => setPayloads(payloads.map((p, n) => n === i ? { ...p, ...patch } : p));
  const command: PayloadItem[] = payloads.map((p) => ({ ...p, weight_lbf: draftNumber(p.weight_lbf), x_ft: draftNumber(p.x_ft), y_ft: draftNumber(p.y_ft), z_ft: draftNumber(p.z_ft) }));
  const invalid = command.some((p) => !p.label.trim() || p.label.length > 120 || PAYLOAD_FIELDS.some(([key, , min, max]) => !Number.isFinite(p[key]) || p[key] < min || p[key] > max));
  return <div className="space-y-2"><p className="text-[10px] text-mil-dim">Change loading only while paused and at rest. Positions are feet from the reference waterline at midships: +x forward, +y port, +z up. Backend recalculates mass, CG, draft and static attitude.</p>
    {payloads.map((p, i) => <div key={p.payload_id} className="grid grid-cols-2 items-end gap-2 sm:grid-cols-6"><label className="text-[9px] text-mil-dim">Payload<input className={inputClass} value={p.label} maxLength={120} onChange={(e) => update(i, { label: e.target.value })} /></label>{PAYLOAD_FIELDS.map(([key, label, min, max]) => <label key={key} className="text-[9px] text-mil-dim">{label}<input aria-label={`${p.label} ${label}`} className={inputClass} type="number" min={min} max={max} step="any" value={p[key]} onChange={(e) => update(i, { [key]: e.target.value })} /></label>)}<Button size="sm" variant="secondary" onClick={() => setPayloads(payloads.filter((_, n) => n !== i))}>Remove {p.label}</Button></div>)}
    <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="secondary" disabled={payloads.length >= 64} onClick={() => { const id = `authored-${Date.now()}-${nextId}`; setNextId(nextId + 1); setPayloads([...payloads, { payload_id: id, label: `Payload ${nextId}`, weight_lbf: '0', x_ft: '0', y_ft: '0', z_ft: '0' }]); }}>Add payload</Button><Button size="sm" disabled={disabled || !atRest || invalid} onClick={() => c.loadingCommand(command)}>Apply loading</Button>{!atRest && <span className="text-[10px] text-mil-amber">Pause and reset to rest before changing loading.</span>}{invalid && <span className="text-[10px] text-mil-amber">Complete every payload field within its limits: weight 0–1,000,000,000 lbf; x/y ±10,000 ft; z ±1,000 ft.</span>}</div>
  </div>;
}
