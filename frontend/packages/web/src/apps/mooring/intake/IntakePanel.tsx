import { useEffect, useRef, useState } from 'react';
import { Button, BackendBadge, Panel, StatusChip, toStatus } from '../../../shell/ui';
import { agents, AGENTS_BASE, awaitJob, describeError, unwrap } from '../api';
import { useController, useMooring } from '../panels/context';
import { dataQualityLine, formatSpan, summaryProvenance, worstSeverity } from './logic';
import type { IntakeReport } from './logic';

type Phase = 'idle' | 'running' | 'done' | 'error';

/** Asks the intake agent to assess the environment for the chosen berth, ship and side over the next day. */
export function IntakePanel() {
  useController();
  const berth = useMooring((s) => s.berth);
  const shipClassId = useMooring((s) => s.shipClassId);
  const side = useMooring((s) => s.side);
  const [phase, setPhase] = useState<Phase>('idle');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<IntakeReport | null>(null);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  // A report describes one berth, ship and side; drop it when they change so it is never shown against the wrong one.
  const key = `${berth?.berth_id}|${shipClassId}|${side}`;
  const shownFor = useRef(key);
  useEffect(() => {
    if (shownFor.current !== key) {
      shownFor.current = key;
      abort.current?.abort();
      setReport(null);
      setPhase('idle');
      setError(null);
    }
  }, [key]);

  const run = async () => {
    if (!berth) return;
    abort.current?.abort();
    abort.current = new AbortController();
    setPhase('running');
    setError(null);
    setProgress(0);
    try {
      const accepted = unwrap(
        await agents.POST('/api/v1/intake/reports', {
          body: { berth_id: berth.berth_id, ship_class_id: shipClassId || null, side_to: side, horizon_hours: 24 },
        }),
      );
      const result = await awaitJob<IntakeReport>(AGENTS_BASE, accepted, setProgress, abort.current.signal);
      setReport(result);
      setPhase('done');
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      setError(describeError(e));
      setPhase('error');
    }
  };

  return (
    <Panel title="Environment intake" className="space-y-2 p-4">
      <p className="text-[11px] text-mil-dim">Assess the next 24 hours at this berth: wind and current limits, windows of concern, and data quality.</p>
      <Button size="sm" disabled={!berth || phase === 'running'} onClick={() => void run()}>
        {phase === 'running' ? `Assessing… ${Math.round(progress * 100)}%` : report ? 'Assess again' : 'Assess conditions'}
      </Button>

      {error && (
        <div role="alert" className="rounded-sm border border-mil-red/40 bg-mil-red/10 p-2 text-[11px] text-mil-red">
          {error}
        </div>
      )}

      {report && phase !== 'running' && (
        <div className="space-y-2 text-[11px]">
          <div className="flex flex-wrap items-center gap-2">
            <BackendBadge backend={report.backend} />
            <StatusChip status={toStatus(worstSeverity(report))} label={`worst: ${worstSeverity(report)}`} />
          </div>
          <p className="text-white">{report.summary}</p>
          <p className="text-[10px] text-mil-dim">{summaryProvenance(report)}</p>

          <div>
            <div className="mil-label mb-1">Mooring condition</div>
            <p className={report.mst.exceeds_ship_mst ? 'text-mil-red' : 'text-mil-text'}>
              MST {String(report.mst.mst_required)} required{report.mst.ship_mst ? `, ship rated ${report.mst.ship_mst}` : ''}
              {report.mst.exceeds_ship_mst ? ': exceeds the ship rating' : ''}.
            </p>
            <p className="text-[10px] text-mil-dim">{report.mst.reason}</p>
          </div>

          <div>
            <div className="mil-label mb-1">Windows of concern ({report.windows.length})</div>
            {report.windows.length === 0 ? (
              <p className="text-mil-dim">None in the next {report.horizon_hours} h.</p>
            ) : (
              <ul className="space-y-1">
                {report.windows.map((w, i) => (
                  <li key={`${i}-${w.start_utc}`}>
                    <StatusChip status={toStatus(w.severity)} label={`${w.kind.replace('_', ' ')} · ${w.severity}`} />{' '}
                    <span className="text-mil-dim">{formatSpan(w.start_utc, w.end_utc)} · peak {w.peak_value} {w.unit}</span>
                    <div className="text-[10px] text-mil-dim">{w.reason}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {report.berthing_windows.length > 0 && (
            <div>
              <div className="mil-label mb-1">Berthing windows ({report.berthing_windows.length})</div>
              <ul>
                {report.berthing_windows.map((w, i) => (
                  <li key={`${i}-${w.start_utc}`} className="text-mil-dim">
                    {formatSpan(w.start_utc, w.end_utc)} · gust {w.max_gust_kt} kt · current {w.max_current_kt} kt · {Math.round(w.required_power_hp)} hp of tugs
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report.data_quality.length > 0 && (
            <details>
              <summary className="cursor-pointer text-mil-dim">Data quality ({report.data_quality.length})</summary>
              <ul className="mt-1 space-y-0.5 text-[10px] text-mil-dim">
                {report.data_quality.map((d, i) => (
                  <li key={`${i}-${d.station_id}`} className={d.severity === 'RED' ? 'text-mil-red' : d.severity === 'AMBER' ? 'text-mil-amber' : undefined}>
                    {dataQualityLine(d)}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </Panel>
  );
}
