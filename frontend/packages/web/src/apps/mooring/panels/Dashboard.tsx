import { useState } from 'react';
import { cn } from '../../../lib/cn';
import { BackendBadge, Button, Citation, Field, Select, StatusChip, inputClass, toStatus } from '../../../shell/ui';
import type { EnvMode } from '../controller';
import { fmt, useUnitSystem } from '../units';
import { LineChart, PolarEnvelope, ProbabilityBars } from './charts';
import { useController, useMooring } from './context';

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
            <Reading label="Current" value={`${env.current_speed_kt.toFixed(1)} kt toward ${fmt.deg(env.current_set_true_deg)}`} />
            <Reading label="Water level" value={`${env.water_level_mllw_ft.toFixed(1)} ft MLLW${env.tide_stage ? ` · ${env.tide_stage}` : ''}`} />
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

function LimitsTab() {
  const env = useMooring((s) => s.risk.envelope);
  const current = useMooring((s) => s.env?.wind_gust_kt);
  return (
    <div>
      <RunBar kind="envelope" label="Compute wind limits" />
      {env && (
        <div className="grid grid-cols-[160px_1fr] gap-4">
          <div className="h-36">
            <PolarEnvelope
              points={env.result.points.map((p) => ({ angle: p.wind_rel_deg, limit: p.limit_wind_kt }))}
              currentWindKt={current}
              worstAngle={env.result.worst?.wind_rel_deg}
            />
          </div>
          <div className="space-y-1 text-[11px]">
            <div className="flex items-center justify-between">
              <StatusChip status={env.status} />
              <BackendBadge backend={env.backend} />
            </div>
            {env.result.worst && (
              <p className="text-white">
                Weakest direction: wind at {fmt.deg(env.result.worst.wind_rel_deg)} limits at{' '}
                {env.result.worst.limit_wind_kt != null ? fmt.kt(env.result.worst.limit_wind_kt) : 'n/a'}, first failing{' '}
                {env.result.worst.first_failure_element ?? 'n/a'} ({env.result.worst.failure_mode}).
              </p>
            )}
            <p className="text-mil-dim">The dashed ring is the current gust speed. Inside the cyan shape the plan holds.</p>
            <p className="text-mil-dim">Angles are as reported by the modeling service (wind direction relative to the ship). Result {env.result_id}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function ExceedanceTab() {
  const ex = useMooring((s) => s.risk.exceedance);
  const usable = ex && (ex.validity?.state === 'valid' || ex.validity?.state === 'limited') && (ex.result.n_valid ?? 0) > 0;
  return (
    <div>
      <RunBar kind="exceedance" label="Run pointwise gust scenario" />
      {ex && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-4 text-[11px]">
            <StatusChip status={ex.status} />
            {usable ? <>
              <span className="text-white">Any modeled element exceeds its limit: {(ex.result.p_any_exceeds_wll * 100).toFixed(1)}%</span>
              <span className="text-mil-text">Line MBS exceedance: {(ex.result.p_any_exceeds_mbs * 100).toFixed(1)}%</span>
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
        </div>
      )}
    </div>
  );
}
