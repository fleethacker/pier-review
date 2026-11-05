import { BackendBadge, Button, Field, Panel, StatusChip, inputClass, toStatus } from '../../../shell/ui';
import { useController } from '../panels/context';
import { ResultLink } from '../panels/ResultLink';
import { OUTCOME_LABEL, coverage, fromLocalInput, outcomeStatus, shortUtc, toLocalInput } from './logic';

const num = (v: string) => (v === '' ? NaN : Number(v));

/** Advance arrival planning: arrival >= 24 h ahead, holding duration, bound forecast series, alternatives and the selected plan. */
export function AdvancePanel() {
  const c = useController();
  const a = c.advance.state.use((s) => s);
  const lines = c.state.use((s) => s.lines.length);
  const i = a.inputs;
  const cov = a.series ? coverage(a.series.series, i) : null;
  const problems = c.advance.problems();
  const result = a.response?.result;
  const manifest = result?.forecast_manifest;
  const selected = result?.selected_arrival_utc ?? null;

  return (
    <Panel title="Advance planning (24 h+)" className="space-y-3 p-4">
      <p className="text-[11px] text-mil-dim">
        Assess arrivals at least 24 hours ahead against a bound forecast series, through docking and holding. Static, sampled
        planning: results stay limited and never approve a plan.
      </p>

      <div className="grid grid-cols-2 gap-2">
        <Field label="As of (UTC)">
          <input type="datetime-local" className={inputClass} aria-label="As of (UTC)" value={toLocalInput(i.asOfUtc)}
            onChange={(e) => c.advance.setInputs({ asOfUtc: fromLocalInput(e.target.value) })} />
        </Field>
        <Field label="Target % WLL">
          <input type="number" className={inputClass} aria-label="Target % WLL" min={10} max={100} value={i.targetPctWll}
            onChange={(e) => c.advance.setInputs({ targetPctWll: num(e.target.value) })} />
        </Field>
        <Field label="Earliest arrival (UTC)">
          <input type="datetime-local" className={inputClass} aria-label="Earliest arrival (UTC)" value={toLocalInput(i.arrivalFromUtc)}
            onChange={(e) => c.advance.setInputs({ arrivalFromUtc: fromLocalInput(e.target.value) })} />
        </Field>
        <Field label="Latest arrival (UTC)">
          <input type="datetime-local" className={inputClass} aria-label="Latest arrival (UTC)" value={toLocalInput(i.arrivalToUtc)}
            onChange={(e) => c.advance.setInputs({ arrivalToUtc: fromLocalInput(e.target.value) })} />
        </Field>
        <Field label="Docking (h)">
          <input type="number" className={inputClass} aria-label="Docking hours" min={0.5} step={0.5} value={i.operationHours}
            onChange={(e) => c.advance.setInputs({ operationHours: num(e.target.value) })} />
        </Field>
        <Field label="Holding (h)">
          <input type="number" className={inputClass} aria-label="Holding hours" min={0} step={1} value={i.holdingHours}
            onChange={(e) => c.advance.setInputs({ holdingHours: num(e.target.value) })} />
        </Field>
      </div>
      <label className="flex items-center gap-2 text-[11px] text-mil-text">
        <input type="checkbox" checked={i.optimizeLines} onChange={(e) => c.advance.setInputs({ optimizeLines: e.target.checked })} />
        Search a common line plan across the forecast (slower)
      </label>

      <div className="space-y-1.5 rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]" aria-label="Forecast source">
        <div className="mil-label">Forecast source</div>
        <p className="text-mil-dim">
          Public forecast (NWS + CO-OPS): <span className="text-mil-amber">unavailable</span>. The composed public forecast is not
          connected yet; use a labeled training scenario.
        </p>
        <div className="grid grid-cols-4 gap-2">
          <Field label="Seed">
            <input type="number" className={inputClass} aria-label="Training seed" value={a.training.seed}
              onChange={(e) => c.advance.setTraining({ seed: Math.trunc(num(e.target.value)) })} />
          </Field>
          <Field label="Gust kt">
            <input type="number" className={inputClass} aria-label="Gust peak kt" min={0} value={a.training.gustPeakKt}
              onChange={(e) => c.advance.setTraining({ gustPeakKt: num(e.target.value) })} />
          </Field>
          <Field label="Tide ±ft">
            <input type="number" className={inputClass} aria-label="Water level amplitude ft" min={0} step={0.5} value={a.training.waterLevelAmplitudeFt}
              onChange={(e) => c.advance.setTraining({ waterLevelAmplitudeFt: num(e.target.value) })} />
          </Field>
          <Field label="Hours">
            <input type="number" className={inputClass} aria-label="Series hours" min={24} max={168} value={a.training.durationHours}
              onChange={(e) => c.advance.setTraining({ durationHours: Math.trunc(num(e.target.value)) })} />
          </Field>
        </div>
        <Button size="sm" variant="secondary" disabled={a.seriesState === 'loading'} onClick={() => void c.advance.generateTrainingSeries()}>
          {a.seriesState === 'loading' ? 'Generating…' : a.series ? 'Regenerate training scenario' : 'Use training scenario'}
        </Button>
        {a.seriesError && <p className="text-mil-red">{a.seriesError}</p>}
        {a.series && (
          <div className="space-y-0.5" aria-label="Series coverage">
            <p className="text-mil-amber">{a.series.label}</p>
            {cov && (
              <>
                <p className="text-mil-text">
                  {cov.count} snapshots, {shortUtc(cov.startUtc)} to {shortUtc(cov.endUtc)}, every {a.series.stepMin} min (largest gap {cov.maxGapMin} min).
                </p>
                <p className={cov.covered ? 'text-mil-text' : 'text-mil-red'}>
                  Needs {shortUtc(cov.neededFromUtc)} to {shortUtc(cov.neededToUtc)}: {cov.covered ? 'covered' : 'not covered'}.
                </p>
              </>
            )}
            <p className="text-[10px] text-mil-dim">Revision {a.series.revision}</p>
          </div>
        )}
      </div>

      {problems.length > 0 && (
        <ul className="list-disc pl-4 text-[11px] text-mil-amber" aria-label="Before you can assess">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
      <Button size="sm" disabled={problems.length > 0 || a.phase === 'running' || lines === 0} onClick={() => void c.advance.run()}>
        {a.phase === 'running' ? `Assessing arrivals… ${Math.round(a.progress * 100)}%` : 'Assess arrivals'}
      </Button>
      {a.error && <p role="alert" className="text-[11px] text-mil-red">{a.error}</p>}

      {a.response && result && (
        <div className="space-y-2 border-t border-mil-border pt-2 text-[11px]" aria-label="Advance planning result">
          {a.recheckReason && (
            <div role="alert" className="rounded-sm border border-mil-amber/40 bg-mil-amber/10 p-2 text-mil-amber">
              Recheck required. {a.recheckReason}
              <div className="mt-1 flex gap-2">
                <Button size="sm" onClick={() => void c.advance.run()} disabled={problems.length > 0}>Assess again</Button>
                <Button size="sm" variant="secondary" onClick={() => void c.advance.recheck()} disabled={a.recheck.state === 'running'}>
                  Compare with the current series
                </Button>
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip status={a.response.status} label={`Overall ${a.response.status}`} />
            <span className="text-mil-text">validity {a.response.validity?.state ?? 'not reported (unknown)'}</span>
            <BackendBadge backend={a.response.backend} />
            <ResultLink id={a.response.result_id} />
          </div>
          <p className="text-white">
            {selected ? <>Selected arrival <span className="text-mil-cyan">{shortUtc(selected)}</span>.</> : 'No arrival meets the target through docking and holding.'}{' '}
            {result.evaluations} conditions evaluated{result.complete ? '' : ' (incomplete: budget exhausted)'}.
          </p>
          {manifest && (
            <p className="text-[10px] text-mil-dim">
              Forecast {manifest.source}{manifest.source_id ? ` · ${manifest.source_id}` : ''} · revision {manifest.revision} · content{' '}
              <span className="font-mono">{manifest.content_hash.slice(0, 12)}</span> · as of {shortUtc(manifest.as_of_utc)}
            </p>
          )}

          <table className="w-full text-left text-[10px]" aria-label="Arrival alternatives">
            <thead className="text-mil-dim">
              <tr><th>Arrival</th><th>Outcome</th><th>Max % WLL</th><th>Governing</th></tr>
            </thead>
            <tbody>
              {result.windows.map((w) => (
                <tr key={w.arrival_utc} className={w.arrival_utc === selected ? 'text-mil-cyan' : 'text-mil-text'}>
                  <td>{shortUtc(w.arrival_utc)}{w.arrival_utc === selected ? ' ★' : ''}</td>
                  <td><StatusChip status={outcomeStatus(w.outcome)} label={OUTCOME_LABEL[w.outcome] ?? w.outcome} /></td>
                  <td>{w.max_pct_wll == null ? 'unavailable' : `${Math.round(w.max_pct_wll)}%`}</td>
                  <td>{w.governing_element ?? 'n/a'}{w.governing_at_utc ? ` @ ${shortUtc(w.governing_at_utc)}` : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {result.selected_config ? (
            <div className="space-y-1">
              <Button size="sm" onClick={() => c.advance.applySelected()} disabled={!!a.recheckReason}>
                Apply selected configuration
              </Button>
              <p className="text-[10px] text-mil-dim">
                Lines keep their modeled paid-out lengths and the installation tide
                {result.installed_at_water_level_mllw_ft != null ? ` (${result.installed_at_water_level_mllw_ft.toFixed(1)} ft MLLW)` : ''}; these reproduce
                the calculation and are not cutting lengths or handling instructions.
              </p>
              {a.applied && (
                <p className="text-mil-cyan" role="status">
                  Applied the configuration for {shortUtc(a.applied.arrivalUtc)}. Run the planning agent and the independent review to carry it forward.
                </p>
              )}
            </div>
          ) : (
            <p className="text-mil-dim">No configuration is published because no arrival is supported.</p>
          )}

          {a.recheck.state !== 'idle' && (
            <div className="rounded-sm border border-mil-border p-2" aria-label="Recheck">
              {a.recheck.state === 'running' && <p className="text-mil-dim">Comparing…</p>}
              {a.recheck.error && <p className="text-mil-red">{a.recheck.error}</p>}
              {a.recheck.response && (
                <>
                  <StatusChip status={toStatus(a.recheck.response.result.state === 'unchanged' ? 'GREEN' : 'AMBER')}
                    label={a.recheck.response.result.state.replace('_', ' ')} />
                  {a.recheck.response.result.reasons.map((r, k) => <p key={k} className="text-mil-text">{r}</p>)}
                  <p className="text-[10px] text-mil-dim">A comparison never changes or approves the plan; assess again for new results.</p>
                </>
              )}
            </div>
          )}

          {(result.limitations.length > 0 || result.recheck_triggers.length > 0) && (
            <details className="text-[10px] text-mil-dim">
              <summary className="cursor-pointer">Limitations and recheck triggers</summary>
              <ul className="mt-1 list-disc pl-4">
                {result.limitations.map((l, k) => <li key={`l${k}`}>{l}</li>)}
                {result.recheck_triggers.map((l, k) => <li key={`r${k}`}>Recheck if: {l}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
    </Panel>
  );
}
