import { Button, BackendBadge, Panel, StatusChip, toStatus } from '../../../shell/ui';
import { useController, useMooring } from '../panels/context';
import { dataQualityLine, formatSpan, summaryProvenance, worstSeverity } from './logic';

/** Asks the intake agent to assess the environment for the chosen berth, ship and side over the next day. */
export function IntakePanel() {
  const controller = useController();
  const berth = useMooring((s) => s.berth);
  const { phase, progress, error, report } = controller.intake.state.use((s) => s);

  return (
    <Panel title="Environment intake" className="space-y-2 p-4">
      <p className="text-[11px] text-mil-dim">Assess the selected scenario over 24 hours: wind and current limits, windows of concern, and data quality. Saved manual conditions stay steady; they are not a weather forecast.</p>
      <Button size="sm" disabled={!berth || phase === 'running'} onClick={() => void controller.intake.run()}>
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
          <p className="text-[10px] text-mil-dim">The next planning run uses this assessment. Editing the inputs clears it.</p>

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
