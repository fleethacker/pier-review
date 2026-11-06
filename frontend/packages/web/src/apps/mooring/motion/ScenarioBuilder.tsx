import { useRef, useState } from 'react';
import { Button, inputClass } from '../../../shell/ui';
import type { MotionController, MotionState } from './controller';
import type { WorkspaceSpec } from './workspace';
import { motionRequest } from './workspace';

const field = 'grid gap-1 text-[10px] text-mil-dim';

export function ScenarioSelector({ c, s }: { c: MotionController; s: MotionState }) {
  const [builderOpen, setBuilderOpen] = useState(false);
  const [draft, setDraft] = useState<WorkspaceSpec | null>(null);
  const [resolving, setResolving] = useState(false);
  const [parameterError, setParameterError] = useState<string | null>(null);
  const draftVersion = useRef(0);
  const catalog = s.catalog;
  const openBuilder = () => {
    const configuration = s.workspace?.scenario.configuration ?? catalog?.presets[0]?.configuration;
    if (!configuration) return;
    draftVersion.current += 1;
    setResolving(false); setParameterError(null);
    setDraft(structuredClone({ ...configuration, environment: configuration.environment ?? (configuration.environment_mode === 'synthetic' ? s.workspace?.environment : null) ?? null }));
    setBuilderOpen(true);
    void c.loadSavedScenarios();
  };
  const ship = catalog?.ships.find((x) => x.class_id === draft?.ship_class_id);
  const update = (patch: Partial<WorkspaceSpec>) => { draftVersion.current += 1; setResolving(false); setParameterError(null); setDraft((d) => d ? { ...d, ...patch } : d); };
  const selectSaved = (configuration: WorkspaceSpec) => { draftVersion.current += 1; setResolving(false); setParameterError(null); setDraft(structuredClone(configuration)); };
  const closeBuilder = () => { draftVersion.current += 1; setBuilderOpen(false); setResolving(false); };
  const resolveParameters = async () => {
    if (!draft || resolving) return;
    const version = draftVersion.current;
    setResolving(true); setParameterError(null);
    try {
      const resolved = await motionRequest<WorkspaceSpec>('/configuration', draft);
      if (draftVersion.current === version) setDraft(resolved);
    } catch (e) {
      if (draftVersion.current === version) setParameterError(e instanceof Error ? e.message : String(e));
    } finally { if (draftVersion.current === version) setResolving(false); }
  };
  return <>
    <label className="grid gap-0.5 text-[9px] uppercase tracking-wider text-mil-dim">
      Maneuver
      <select className={`${inputClass} h-9 min-w-44 max-w-72 text-[11px] normal-case tracking-normal`} aria-label="Demo maneuver" disabled={s.busy || !catalog} value="" onChange={(e) => {
        const preset = catalog?.presets.find((p) => p.preset_id === e.target.value);
        const saved = s.savedScenarios.find((entry) => `saved:${entry.motion_scenario_id}` === e.target.value);
        if (preset || saved) void c.loadWorkspace((preset ?? saved)!.configuration);
      }}>
        <option value="">{s.workspace?.scenario.configuration.name ?? (s.catalogBusy ? 'Loading maneuvers…' : 'Select a Norfolk demonstration')}</option>
        <optgroup label="Norfolk demonstrations">{catalog?.presets.map((p) => <option key={p.preset_id} value={p.preset_id}>{p.title}</option>)}</optgroup>
        {s.savedScenarios.length > 0 && <optgroup label="Saved scenarios">{s.savedScenarios.map((entry) => <option key={entry.motion_scenario_id} value={`saved:${entry.motion_scenario_id}`}>{entry.configuration.name} · {entry.created_at_utc.slice(0, 16).replace('T', ' ')}Z</option>)}</optgroup>}
      </select>
    </label>
    <Button size="sm" variant="secondary" disabled={!catalog || s.busy} onClick={openBuilder}>Build scenario</Button>
    {s.catalogError && <span role="alert" className="text-[10px] text-mil-amber">{s.catalogError} <button className="underline" onClick={() => void c.initializeWorkspace()}>Retry catalog</button></span>}
    {builderOpen && draft && catalog && <div style={{ top: 'var(--motion-top, 40px)' }} className="fixed inset-x-0 bottom-0 z-50 flex items-start justify-center overflow-y-auto bg-mil-bg/90 p-4" role="dialog" aria-modal="true" aria-label="Scenario builder">
      <form className="my-4 w-full max-w-3xl border border-mil-border bg-mil-panel p-5 shadow-2xl" onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); closeBuilder(); } if (e.key === 'Tab') { const nodes = [...e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), summary')]; const first = nodes[0], last = nodes[nodes.length - 1]; if (e.shiftKey && e.target === first) { e.preventDefault(); last?.focus(); } else if (!e.shiftKey && e.target === last) { e.preventDefault(); first?.focus(); } } }} onSubmit={(e) => { e.preventDefault(); closeBuilder(); void c.loadWorkspace(draft); }}>
        <div className="mb-4 flex items-start justify-between gap-3"><div><h2 className="mil-label text-base text-mil-text">Build a maneuver</h2><p className="mt-1 text-xs text-mil-dim">New scenarios load paused. Engineering parameters remain synthetic and unqualified.</p></div><Button type="button" size="sm" variant="ghost" onClick={closeBuilder}>Close builder</Button></div>
        <div className="mb-4 flex flex-wrap items-end gap-2 border-b border-mil-border pb-3"><label className={`${field} min-w-48 flex-1`}>Saved scenarios<select className={inputClass} value="" onChange={(e) => { const saved = s.savedScenarios.find((entry) => entry.motion_scenario_id === e.target.value); if (saved) selectSaved(saved.configuration); }}><option value="">{s.savedScenariosBusy ? 'Loading saved scenarios…' : s.savedScenarios.length ? 'Choose a saved scenario to edit' : 'No saved scenarios'}</option>{s.savedScenarios.map((entry) => <option key={entry.motion_scenario_id} value={entry.motion_scenario_id}>{entry.configuration.name} · {entry.created_at_utc.slice(0, 16).replace('T', ' ')}Z</option>)}</select></label><Button type="button" size="sm" variant="secondary" disabled={s.savedScenariosBusy} onClick={() => void c.loadSavedScenarios()}>Refresh saved</Button>{s.savedScenariosError && <p role="alert" className="w-full text-[10px] text-mil-red">Saved scenarios unavailable: {s.savedScenariosError}</p>}</div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className={`${field} sm:col-span-2 lg:col-span-3`}>Scenario name<input autoFocus required maxLength={120} className={inputClass} value={draft.name} onChange={(e) => update({ name: e.target.value })} /></label>
          <label className={field}>Vessel class<select className={inputClass} value={draft.ship_class_id} onChange={(e) => {
            const next = catalog.ships.find((x) => x.class_id === e.target.value);
            update({ ship_class_id: e.target.value, loading: next?.loading_conditions[0]?.name ?? 'full_load', controls: null, initial_state: null });
          }}>{catalog.ships.map((x) => <option key={x.class_id} value={x.class_id}>{x.name} · {x.loa_ft.toFixed(0)} ft</option>)}</select></label>
          <label className={field}>Loading condition<select className={inputClass} value={draft.loading} onChange={(e) => update({ loading: e.target.value, controls: null })}>{ship?.loading_conditions.map((l) => <option key={l.name}>{l.name}</option>)}</select></label>
          <label className={field}>Berth<select className={inputClass} value={draft.berth_id} onChange={(e) => update({ berth_id: e.target.value, initial_state: null, controls: null })}>{catalog.berths.map((b) => <option key={b.berth_id} value={b.berth_id}>{b.name}</option>)}</select></label>
          <label className={field}>Starting area<select className={inputClass} value={draft.start} onChange={(e) => update({ start: e.target.value as WorkspaceSpec['start'], initial_state: null, controls: null, initial_lines_attached: false })}><option value="berth">Alongside the berth</option><option value="approach">Berth approach</option><option value="channel">Channel demonstration</option></select></label>
          <label className={field}>Side to berth<select className={inputClass} value={draft.side_to} onChange={(e) => update({ side_to: e.target.value as WorkspaceSpec['side_to'], initial_state: null, controls: null })}><option value="starboard">Starboard</option><option value="port">Port</option></select></label>
          <label className={field}>Environment source<select className={inputClass} value={draft.environment_mode} onChange={(e) => update({ environment_mode: e.target.value as WorkspaceSpec['environment_mode'], environment: e.target.value === 'synthetic' ? s.workspace?.environment ?? null : null, forcing: null })}><option value="synthetic">Synthetic demonstration</option><option value="live">Acquire current conditions (held snapshot)</option>{draft.environment_mode === 'snapshot' && <option value="snapshot">Supplied snapshot</option>}</select></label>
          <label className={field}>Demonstration route<select className={inputClass} value={draft.route_id ?? ''} onChange={(e) => update({ route_id: e.target.value || null, route_follow: e.target.value ? draft.route_follow : false })}><option value="">Manual maneuvering</option>{catalog.routes.map((r) => <option key={r.route_id} value={r.route_id}>{r.title}</option>)}</select></label>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.route_follow ?? false} disabled={!draft.route_id} onChange={(e) => update({ route_follow: e.target.checked })} />Backend route following</label>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.initial_lines_attached ?? false} disabled={draft.start !== 'berth'} onChange={(e) => update({ initial_lines_attached: e.target.checked })} />Start with lines attached</label>
          <label className={field}>Simulation duration (s)<input type="number" required className={inputClass} min={1} max={14400} step={1} value={draft.duration_s} onChange={(e) => update({ duration_s: Number(e.target.value) })} /></label>
        </div>
        {draft.environment_mode === 'synthetic' && draft.environment && <fieldset className="mt-4 border-t border-mil-border pt-3"><legend className="mil-label px-1">Authored demonstration conditions</legend><div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {([['wind_speed_kt', 'Wind speed (kt)', 0, 100], ['wind_gust_kt', 'Wind gust (kt)', 0, 130], ['wind_from_true_deg', 'Wind from (° true)', 0, 359], ['current_speed_kt', 'Current speed (kt)', 0, 10], ['current_set_true_deg', 'Current toward (° true)', 0, 359], ['water_level_mllw_ft', 'Water level (ft MLLW)', -20, 30]] as const).map(([key, label, min, max]) => <label key={key} className={field}>{label}<input type="number" required className={inputClass} min={min} max={max} step={0.1} value={draft.environment![key]} onChange={(e) => update({ environment: { ...draft.environment!, [key]: Number(e.target.value) } })} /></label>)}
        </div></fieldset>}
        <details className="mt-4 border-t border-mil-border pt-3"><summary className="cursor-pointer text-[11px] text-mil-cyan">Engine, rudder and thruster parameters</summary><p className="my-2 text-[10px] text-mil-amber">Explicit synthetic training parameters, not verified vessel performance. Changes take effect in the new paused scenario.</p>{draft.controls ? <><div className="grid grid-cols-2 gap-3 sm:grid-cols-3">{([
          ['max_ahead_thrust_lbf', 'Ahead thrust per shaft (lbf)', 1, undefined, 1000], ['max_astern_thrust_lbf', 'Astern thrust per shaft (lbf)', 0, undefined, 1000],
          ['bow_thruster_max_lbf', 'Bow thruster capacity (lbf)', 0, undefined, 1000], ['stern_thruster_max_lbf', 'Stern thruster capacity (lbf)', 0, undefined, 1000],
          ['engine_slew_per_s', 'Engine slew (fraction/s)', 0.001, undefined, 0.001], ['rudder_max_deg', 'Rudder limit (°)', 0.1, 45, 0.1],
          ['rudder_slew_degps', 'Rudder slew (°/s)', 0.001, undefined, 0.001], ['thruster_slew_per_s', 'Thruster slew (fraction/s)', 0.001, undefined, 0.001],
        ] as const).map(([key, label, min, max]) => <label key={key} className={field}>{label}<input type="number" required className={inputClass} min={min} max={max} step="any" value={draft.controls!.propulsion[key]} onChange={(e) => update({ controls: { ...draft.controls!, propulsion: { ...draft.controls!.propulsion, [key]: Number(e.target.value), basis: 'synthetic', source: 'User-authored Motion propulsion parameters; unverified synthetic training' } } })} /></label>)}</div><p className="mt-2 text-[9px] text-mil-dim">Basis: {draft.controls.propulsion.basis} · {draft.controls.propulsion.source}</p></> : <><p className="my-2 text-[10px] text-mil-dim">Resolve the selected vessel and tug parameters from the backend before editing. This does not save a scenario, acquire live weather, or create a simulation.</p><Button type="button" size="sm" variant="secondary" disabled={resolving} onClick={() => void resolveParameters()}>{resolving ? 'Resolving parameters…' : 'Resolve training parameters'}</Button></>}{parameterError && <p role="alert" className="mt-2 text-[10px] text-mil-red">{parameterError}</p>}</details>
        <fieldset className="mt-4 border-t border-mil-border pt-3"><legend className="mil-label px-1">Assigned tugs</legend><div className="flex flex-wrap gap-4">{catalog.tugs.map((t) => <label key={t.tug_id} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.tug_ids?.includes(t.tug_id) ?? false} onChange={(e) => update({ controls: null, tug_ids: e.target.checked ? [...(draft.tug_ids ?? []), t.tug_id] : (draft.tug_ids ?? []).filter((id) => id !== t.tug_id) })} />{t.name}</label>)}</div></fieldset>
        <p className="mt-3 text-[10px] text-mil-dim">Use the workspace simulation-speed control to accelerate elapsed simulation time. Long channel demonstrations can run for up to four simulated hours.</p>
        {draft.route_id && <p className="mt-3 text-[10px] text-mil-amber">{catalog.routes.find((r) => r.route_id === draft.route_id)?.limitations.join(' ')}</p>}
        <div className="mt-5 flex items-center justify-between gap-4 border-t border-mil-border pt-4"><p className="text-[10px] text-mil-dim">Loading saves an immutable copy for later use. Unknown coastline, traffic and depth remain unknown.</p><Button type="submit" disabled={s.busy || resolving || !draft.name.trim()}>Load paused scenario</Button></div>
      </form>
    </div>}
  </>;
}
