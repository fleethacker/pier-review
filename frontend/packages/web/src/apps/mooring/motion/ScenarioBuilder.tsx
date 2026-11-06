import { useState } from 'react';
import { Button, inputClass } from '../../../shell/ui';
import type { MotionController, MotionState } from './controller';
import type { WorkspaceSpec } from './workspace';

const field = 'grid gap-1 text-[10px] text-mil-dim';

export function ScenarioSelector({ c, s }: { c: MotionController; s: MotionState }) {
  const [builderOpen, setBuilderOpen] = useState(false);
  const [draft, setDraft] = useState<WorkspaceSpec | null>(null);
  const catalog = s.catalog;
  const openBuilder = () => {
    const configuration = s.workspace?.scenario.configuration ?? catalog?.presets[0]?.configuration;
    if (!configuration) return;
    setDraft(structuredClone({ ...configuration, environment: configuration.environment ?? (configuration.environment_mode === 'synthetic' ? s.workspace?.environment : null) ?? null }));
    setBuilderOpen(true);
  };
  const ship = catalog?.ships.find((x) => x.class_id === draft?.ship_class_id);
  const update = (patch: Partial<WorkspaceSpec>) => setDraft((d) => d ? { ...d, ...patch } : d);
  return <>
    <label className="grid gap-0.5 text-[9px] uppercase tracking-wider text-mil-dim">
      Maneuver
      <select className={`${inputClass} h-9 min-w-44 max-w-72 text-[11px] normal-case tracking-normal`} aria-label="Demo maneuver" disabled={s.busy || !catalog} value="" onChange={(e) => {
        const preset = catalog?.presets.find((p) => p.preset_id === e.target.value);
        if (preset) void c.loadWorkspace(preset.configuration);
      }}>
        <option value="">{s.workspace?.scenario.configuration.name ?? (s.catalogBusy ? 'Loading maneuvers…' : 'Select a Norfolk demonstration')}</option>
        {catalog?.presets.map((p) => <option key={p.preset_id} value={p.preset_id}>{p.title}</option>)}
      </select>
    </label>
    <Button size="sm" variant="secondary" disabled={!catalog || s.busy} onClick={openBuilder}>Build scenario</Button>
    {s.catalogError && <span role="alert" className="text-[10px] text-mil-amber">{s.catalogError} <button className="underline" onClick={() => void c.initializeWorkspace()}>Retry catalog</button></span>}
    {builderOpen && draft && catalog && <div style={{ top: 'var(--motion-top, 40px)' }} className="fixed inset-x-0 bottom-0 z-50 flex items-start justify-center overflow-y-auto bg-mil-bg/90 p-4" role="dialog" aria-modal="true" aria-label="Scenario builder">
      <form className="my-4 w-full max-w-3xl border border-mil-border bg-mil-panel p-5 shadow-2xl" onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setBuilderOpen(false); } if (e.key === 'Tab') { const nodes = [...e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)')]; const first = nodes[0], last = nodes[nodes.length - 1]; if (e.shiftKey && e.target === first) { e.preventDefault(); last?.focus(); } else if (!e.shiftKey && e.target === last) { e.preventDefault(); first?.focus(); } } }} onSubmit={(e) => { e.preventDefault(); setBuilderOpen(false); void c.loadWorkspace(draft); }}>
        <div className="mb-4 flex items-start justify-between gap-3"><div><h2 className="mil-label text-base text-mil-text">Build a maneuver</h2><p className="mt-1 text-xs text-mil-dim">New scenarios load paused. Engineering parameters remain synthetic and unqualified.</p></div><Button type="button" size="sm" variant="ghost" onClick={() => setBuilderOpen(false)}>Close builder</Button></div>
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
        <fieldset className="mt-4 border-t border-mil-border pt-3"><legend className="mil-label px-1">Assigned tugs</legend><div className="flex flex-wrap gap-4">{catalog.tugs.map((t) => <label key={t.tug_id} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.tug_ids?.includes(t.tug_id) ?? false} onChange={(e) => update({ controls: null, tug_ids: e.target.checked ? [...(draft.tug_ids ?? []), t.tug_id] : (draft.tug_ids ?? []).filter((id) => id !== t.tug_id) })} />{t.name}</label>)}</div></fieldset>
        <p className="mt-3 text-[10px] text-mil-dim">Use the workspace simulation-speed control to accelerate elapsed simulation time. Long channel demonstrations can run for up to four simulated hours.</p>
        {draft.route_id && <p className="mt-3 text-[10px] text-mil-amber">{catalog.routes.find((r) => r.route_id === draft.route_id)?.limitations.join(' ')}</p>}
        <div className="mt-5 flex items-center justify-between gap-4 border-t border-mil-border pt-4"><p className="text-[10px] text-mil-dim">Unknown coastline, traffic and depth remain unknown. This is demonstrator decision support.</p><Button type="submit" disabled={s.busy || !draft.name.trim()}>Load paused scenario</Button></div>
      </form>
    </div>}
  </>;
}
