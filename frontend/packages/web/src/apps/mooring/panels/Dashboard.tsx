import { useState } from 'react';
import { cn } from '../../../lib/cn';
import { BackendBadge, Button, Citation, Field, Select, StatusChip, inputClass, toStatus } from '../../../shell/ui';
import type { EnvMode, EnvelopePoint } from '../controller';
import type { ModelingSchemas } from '../types';
import { fmt, useUnitSystem } from '../units';
import { LineChart, PolarEnvelope, ProbabilityBars } from './charts';
import { useController, useMooring } from './context';
import { ResultLink } from './ResultLink';

type Tab = 'live' | 'alerts' | 'forecast' | 'limits' | 'exceedance';
const TABS: { id: Tab; label: string }[] = [
  { id: 'live', label: 'Live' },
  { id: 'alerts', label: 'Alerts' },
  { id: 'forecast', label: 'Timeline' },
  { id: 'limits', label: 'Wind limits' },
  { id: 'exceedance', label: 'Gust risk' },
];

export function Dashboard() {
  useUnitSystem();
  const [tab, setTab] = useState<Tab>('live');
  const alertCount = useMooring((s) => s.alerts.filter((a) => a.severity !== 'INFO').length);
  return (
    <div className="flex h-full flex-col">
      <div role="tablist" className="flex shrink-0 gap-1 border-b border-mil-border px-3 pt-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              'border border-b-0 px-3 py-1 font-mono text-[11px] uppercase tracking-wider',
              tab === t.id ? 'border-mil-border bg-mil-bg text-mil-cyan' : 'border-transparent text-mil-text hover:text-white',
            )}
          >
            {t.label}
            {t.id === 'alerts' && alertCount > 0 && (
              <span className="ml-1.5 rounded-sm bg-mil-amber/20 px-1 text-mil-amber">{alertCount}</span>
            )}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === 'live' && <LiveTab />}
        {tab === 'alerts' && <AlertsTab />}
        {tab === 'forecast' && <ForecastTab />}
        {tab === 'limits' && <LimitsTab />}
        {tab === 'exceedance' && <ExceedanceTab />}
      </div>
    </div>
  );
}

function LiveTab() {
  const c = useController();
  const env = useMooring((s) => s.env);
  const mode = useMooring((s) => s.envMode);
  const history = useMooring((s) => s.windHistory);
  const [replayStart, setReplayStart] = useState('2026-11-03T00:00:00Z');
  const [speed, setSpeed] = useState(3600);
  const [rampTo, setRampTo] = useState(50);
  const [rampMin, setRampMin] = useState(3);
  const t0 = history[0]?.t ?? 0;
  const tN = history[history.length - 1]?.t ?? 0;
  const xs = (pick: 'wind' | 'gust') => history.map((h) => ({ x: (h.t - t0) / 1000, y: h[pick] }));

  return (
    <div className="grid grid-cols-[300px_1fr] gap-4">
      <div className="space-y-2">
        <Field label="Environment source">
          <Select
            value={mode.kind}
            onChange={(v) => void c.setEnvMode(v as EnvMode, { replayStartUtc: replayStart, speed, rampToKt: rampTo, rampMinutes: rampMin })}
            options={[
              { value: 'manual', label: 'Manual (edit values)' },
              { value: 'live', label: 'Live feed' },
              { value: 'replay', label: 'Historical replay' },
              { value: 'storm', label: 'Storm ramp (what-if)' },
            ]}
          />
        </Field>
        {mode.kind === 'replay' && (
          <div className="grid grid-cols-2 gap-2">
            <Field label="Start (UTC)">
              <input className={inputClass} value={replayStart} onChange={(e) => setReplayStart(e.target.value)} />
            </Field>
            <Field label="Speed (×)">
              <input type="number" className={inputClass} value={speed} min={1} onChange={(e) => setSpeed(Number(e.target.value))} />
            </Field>
          </div>
        )}
        {mode.kind === 'storm' && (
          <div className="grid grid-cols-2 gap-2">
            <Field label="Ramp to (kt)">
              <input type="number" className={inputClass} value={rampTo} min={1} onChange={(e) => setRampTo(Number(e.target.value))} />
            </Field>
            <Field label="Over (min)">
              <input type="number" className={inputClass} value={rampMin} min={1} onChange={(e) => setRampMin(Number(e.target.value))} />
            </Field>
          </div>
        )}
        {mode.kind !== 'manual' && (
          <div className="flex items-center justify-between text-[10px] text-mil-dim">
            <span>Stream: {mode.status}</span>
            <Button size="sm" variant="ghost" onClick={() => void c.setEnvMode('manual')}>
              Stop
            </Button>
          </div>
        )}
        {env && (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
            <Reading label="Wind" value={`${fmt.kt(env.wind_speed_kt)} from ${fmt.deg(env.wind_from_true_deg)}`} />
            <Reading label="Gust" value={fmt.kt(env.wind_gust_kt)} />
            <Reading label="Current" value={`${fmt.kt(env.current_speed_kt, 1)} toward ${fmt.deg(env.current_set_true_deg)}`} />
            <Reading label="Water level" value={`${fmt.ft(env.water_level_mllw_ft, 1)} MLLW${env.tide_stage ? ` · ${env.tide_stage}` : ''}`} />
          </dl>
        )}
      </div>
      <div className="h-40">
        {history.length > 1 ? (
          <LineChart
            label="Wind and gust speed over time"
            unit="kt"
            series={[
              { name: 'wind', color: '#7fd1ff', points: xs('wind') },
              { name: 'gust', color: '#ffc107', points: xs('gust') },
            ]}
            xTicks={[
              { x: 0, label: '0 s' },
              { x: (tN - t0) / 1000, label: `${Math.round((tN - t0) / 1000)} s` },
            ]}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-[11px] text-mil-dim">
            Choose Live feed, Historical replay or Storm ramp to watch wind and gusts here.
          </div>
        )}
      </div>
    </div>
  );
}

function Reading({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-mil-dim">{label}</dt>
      <dd className="text-white">{value}</dd>
    </>
  );
}

function AlertsTab() {
  const alerts = useMooring((s) => s.alerts);
  const status = useMooring((s) => s.alertsStatus);
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] text-mil-dim">Alert stream: {status}</div>
      {alerts.length === 0 && <p className="text-[11px] text-mil-dim">No alerts yet.</p>}
      {alerts.map((a) => (
        <div key={a.id} className="flex items-start gap-2 rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]">
          <StatusChip status={toStatus(a.severity)} label={a.severity} className="w-14 shrink-0" />
          <div className="flex-1">
            <div className="text-white">{a.message}</div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-mil-dim">
              <span>{a.source === 'service' ? 'modeling service' : 'plan analysis'}</span>
              {a.windKt != null && (
                <span>
                  wind {fmt.kt(a.windKt)} G{fmt.kt(a.gustKt ?? a.windKt)}
                </span>
              )}
              <Citation reference={a.reference} />
            </div>
          </div>
          <time className="text-mil-dim">{a.at.slice(11, 19)}Z</time>
        </div>
      ))}
    </div>
  );
}

function RunBar({ kind, label }: { kind: 'timeline' | 'envelope' | 'exceedance'; label: string }) {
  const c = useController();
  const risk = useMooring((s) => s.risk);
  const lines = useMooring((s) => s.lines.length);
  return (
    <div className="mb-2 flex items-center gap-3">
      <Button size="sm" disabled={risk.running !== null || lines === 0} onClick={() => void c.runRisk(kind)}>
        {risk.running === kind ? 'Running…' : label}
      </Button>
      {lines === 0 && <span className="text-[11px] text-mil-dim">Add lines to run this.</span>}
      {risk.error && <span className="text-[11px] text-mil-red">{risk.error}</span>}
    </div>
  );
}

function ForecastTab() {
  const tl = useMooring((s) => s.risk.timeline);
  const steps = tl?.result.steps ?? [];
  const t0 = steps[0] ? Date.parse(steps[0].valid_at_utc) : 0;
  const hours = (iso: string) => (Date.parse(iso) - t0) / 3.6e6;
  const ticks = steps.filter((_, i) => i % 6 === 0).map((s) => ({ x: hours(s.valid_at_utc), label: s.valid_at_utc.slice(11, 16) + 'Z' }));
  return (
    <div>
      <RunBar kind="timeline" label="Run 24 h training timeline" />
      {tl && (
        <div className="grid grid-cols-[1fr_220px] gap-4">
          <div>
            <div className="h-28">
              <LineChart
                label="Wind and gust speed"
                unit="kt"
                height={110}
                xTicks={ticks}
                series={[
                  { name: 'wind', color: '#7fd1ff', points: steps.map((s) => ({ x: hours(s.valid_at_utc), y: s.wind_speed_kt })) },
                  { name: 'gust', color: '#ffc107', points: steps.map((s) => ({ x: hours(s.valid_at_utc), y: s.wind_gust_kt })) },
                ]}
              />
            </div>
            <div className="h-14">
              <ProbabilityBars steps={steps.map((s) => ({ label: s.valid_at_utc.slice(11, 16) + 'Z', p: s.p_any_exceeds_wll, status: s.status }))} />
            </div>
          </div>
          <div className="space-y-1 text-[11px]">
            <div className="flex items-center justify-between">
              <StatusChip status={tl.status} label={`Overall ${tl.status}`} />
              <BackendBadge backend={tl.backend} />
            </div>
            <div className="text-mil-text">First amber: {tl.result.first_amber_utc?.slice(11, 16) ?? 'none'}{tl.result.first_amber_utc ? 'Z' : ''}</div>
            <div className="text-mil-text">First red: {tl.result.first_red_utc?.slice(11, 16) ?? 'none'}{tl.result.first_red_utc ? 'Z' : ''}</div>
            <div className="text-mil-text">{tl.result.forcing_source === 'synthetic_training'
              ? 'Synthetic training timeline; not a weather forecast.'
              : tl.result.forcing_source === 'supplied' ? 'Supplied snapshots; inspect their source and validity.' : 'Forcing source not recorded.'}</div>
            <div className="text-mil-text">Validity: {tl.validity?.state ?? 'unknown'}</div>
            <div className="text-mil-dim">Result {tl.result_id}</div>
          </div>
        </div>
      )}
    </div>
  );
}

// These additive wire fields exist in the generated contract; older responses may omit them.
type LimitPoint = EnvelopePoint & Pick<ModelingSchemas['LimitEnvelopePoint'],
  'limit_gust_kt' | 'advisory_gust_kt' | 'outcome' | 'search_max_kt' | 'undetermined_at_kt'>;

function limitOutcome(point: LimitPoint): string {
  switch (point.outcome) {
    case 'fails_at_zero_wind': return 'Fails with no wind; other assessed loads remain.';
    case 'no_failure_in_range': return `No limit established${point.search_max_kt != null ? ` through ${fmt.kt(point.search_max_kt)}` : ' within the search range'}. Capacity above that range is unknown.`;
    case 'undetermined': return `Indeterminate solve${point.undetermined_at_kt != null ? ` at ${fmt.kt(point.undetermined_at_kt)}` : ''}; no usable limit.`;
    case 'invalid_inputs': return 'Invalid inputs; no usable limit.';
    case 'limit_found': return 'Conservative verified edge of the search bracket.';
    default: return 'Search outcome not recorded in this response.';
  }
}

function UltimateLimitUnavailable() {
  return (
    <div className="border-l-2 border-mil-amber bg-mil-amber/5 p-2 text-[11px]">
      <p className="text-mil-amber">Ultimate-load / breaking gust: unavailable</p>
      <p className="text-mil-dim">No supported ultimate-capacity gust assessment is available here. A working-load limit or sampled MBS exceedance does not predict line rupture.</p>
    </div>
  );
}

function LimitsTab() {
  const env = useMooring((s) => s.risk.envelope);
  const current = useMooring((s) => s.env?.wind_speed_kt);
  const usable = env && (env.validity?.state === 'valid' || env.validity?.state === 'limited');
  const worst: LimitPoint | null = env?.result.worst ?? null;
  return (
    <div className="space-y-2">
      <RunBar kind="envelope" label="Compute working-load wind limits" />
      <p className="text-[11px] text-mil-text">Working-load and element limits apply to the assessed line layout, assistance and conditions. They are not ultimate-capacity thresholds.</p>
      <UltimateLimitUnavailable />
      {env && (
        <div className="grid grid-cols-[160px_1fr] gap-4">
          <div className="h-36">
            {usable ? <PolarEnvelope
              points={env.result.points.map((p) => ({ angle: p.wind_rel_deg, limit: p.limit_wind_kt }))}
              currentWindKt={current}
              worstAngle={env.result.worst?.wind_rel_deg}
            /> : <p className="text-mil-red">Wind limits unavailable for this validity state.</p>}
          </div>
          <div className="space-y-1 text-[11px]">
            <div className="flex items-center justify-between">
              <StatusChip status={env.status} />
              <BackendBadge backend={env.backend} />
            </div>
            {usable && worst && <>
              <p className="text-white">Governing relative wind-from direction: {fmt.deg(worst.wind_rel_deg)} · element {worst.first_failure_element ?? 'not established'} · {worst.failure_mode === 'none' ? 'failure mode not established' : worst.failure_mode}.</p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                <Reading label="Sustained wind limit" value={worst.limit_wind_kt != null ? fmt.kt(worst.limit_wind_kt, 1) : 'Unavailable'} />
                <Reading label="Corresponding working-limit gust" value={worst.limit_gust_kt != null ? fmt.kt(worst.limit_gust_kt, 1) : 'Unavailable'} />
                <Reading label="Application gust advisory" value={worst.advisory_gust_kt != null ? fmt.kt(worst.advisory_gust_kt, 1) : 'Unavailable'} />
              </dl>
              <p className="text-mil-text">{limitOutcome(worst)}</p>
            </>}
            <p className="text-mil-text">Validity: {env.validity?.state ?? 'unknown'}</p>
            {env.result.points.some((p) => p.limit_wind_kt == null) && <p className="text-mil-text">Limits are unavailable for some bearings; gaps are not connected.</p>}
            <p className="text-mil-dim">{current != null ? 'The dashed ring is the current sustained wind speed.' : 'Current sustained wind unavailable; no comparison ring.'} Sampled limits apply only to the assessed conditions.</p>
            <p className="text-mil-dim">Gust values use the service's held gust-to-sustained ratio. The application advisory is 80% of that gust limit, not 80% line utilization or a physical failure threshold. Omitted values remain unavailable.</p>
            <p className="text-mil-dim">Angles are wind FROM relative to the bow, clockwise. Speeds are in knots in both display unit systems.</p>
            {env.assumptions?.length ? <details className="text-mil-dim">
              <summary className="cursor-pointer">Model assumptions and wind basis</summary>
              <ul className="list-inside list-disc">{env.assumptions.map((text, i) => <li key={i}>{text}</li>)}</ul>
            </details> : <p className="text-mil-amber">Averaging time and reference-height basis were not supplied in this response.</p>}
            <ResultLink id={env.result_id} />
          </div>
        </div>
      )}
    </div>
  );
}

function ExceedanceTab() {
  const ex = useMooring((s) => s.risk.exceedance);
  const usable = ex && (ex.validity?.state === 'valid' || ex.validity?.state === 'limited') && (ex.result.n_valid ?? 0) > 0;
  const hasMbsSamples = ex?.result.elements.some((element) => element.p_exceed_mbs != null);
  return (
    <div>
      <RunBar kind="exceedance" label="Run pointwise gust scenario" />
      <UltimateLimitUnavailable />
      {ex && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-4 text-[11px]">
            <StatusChip status={ex.status} />
            {usable ? <>
              <span className="text-white">Any modeled element exceeds its working limit: {(ex.result.p_any_exceeds_wll * 100).toFixed(1)}%</span>
              <span className="text-mil-text">Sampled line strength (MBS) exceedance: {hasMbsSamples ? `${(ex.result.p_any_exceeds_mbs * 100).toFixed(1)}%` : 'unavailable; no line MBS samples'}.</span>
            </> : <span className="text-mil-red">Probability unavailable: input validity or successful samples are not established.</span>}
            <span className="text-mil-dim">{ex.result.n_samples} samples · governing {ex.result.governing_element ?? 'n/a'}</span>
            <BackendBadge backend={ex.backend} />
          </div>
          <p className="text-[11px] text-mil-text">Validity: {ex.validity?.state ?? 'unknown'}. {ex.result.n_valid ?? 'Unknown'} successful / {ex.result.n_samples} requested samples.</p>
          <p className="text-[11px] text-mil-dim">{ex.result.uncertainty_model?.qualification === 'qualified'
            ? 'Sample estimates; apply the stated validity limits.' : 'Scenario sample statistics; not an operational risk estimate.'}
            {' '}Instantaneous samples; these percentages are not a horizon event probability. Fender limits compare energy; force columns show reaction.</p>
          {usable && <table className="w-full text-left text-[11px]">
            <thead className="text-mil-dim">
              <tr>
                <th className="py-1">Element</th>
                <th>P(&gt;limit)</th>
                <th>P(&gt;MBS)</th>
                <th>Force p50</th>
                <th>Force p95</th>
              </tr>
            </thead>
            <tbody>
              {ex.result.elements.map((e) => (
                <tr key={e.element_id} className="border-t border-mil-border text-white">
                  <td className="py-1">{e.element_id}</td>
                  <td>{(e.p_exceed_wll * 100).toFixed(1)}%</td>
                  <td>{e.p_exceed_mbs == null ? 'n/a' : `${(e.p_exceed_mbs * 100).toFixed(1)}%`}</td>
                  <td>{fmt.lbf(e.tension_p50_lbf)}</td>
                  <td>{fmt.lbf(e.tension_p95_lbf)}</td>
                </tr>
              ))}
            </tbody>
          </table>}
          <ResultLink id={ex.result_id} />
        </div>
      )}
    </div>
  );
}
