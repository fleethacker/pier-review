import { Button, Panel } from '../../../shell/ui';
import { useController, useMooring } from './context';
import { classSupport } from '../classSupport';

export function RecommendPanel() {
  const c = useController();
  const rec = useMooring((s) => s.recommend);
  const s = useMooring((state) => state);
  const support = classSupport(s.ship, s.shipClassId, s.loading);
  return (
    <Panel title="Recommended layouts" className="space-y-2 p-4">
      <Button size="sm" disabled={!support.canPlan || rec.state === 'running'} onClick={() => void c.recommend({ apply: false })}>
        {rec.state === 'running' ? `Working… ${Math.round(rec.progress * 100)}%` : 'Recommend layouts'}
      </Button>
      {support.reason && <p className="text-[11px] text-mil-amber">{support.reason}</p>}
      {rec.state === 'error' && <p className="text-[11px] text-mil-red">{rec.error}</p>}
      <ul className="space-y-1.5">
        {rec.candidates.map((cand, i) => (
          <li key={cand.analysis_result_id} className="rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-white">
                Option {i + 1} · {cand.line_count} lines
              </span>
              <Button size="sm" variant="secondary" onClick={() => c.applyCandidate(cand)}>
                Apply
              </Button>
            </div>
            <div className="mt-1 text-mil-text">
              Peak use {Math.round(cand.min_margin_pct_wll)}% WLL · limit wind {cand.limit_wind_kt_worst?.toFixed(0) ?? 'unavailable'} kt
            </div>
            <ul className="mt-1 list-disc pl-4 text-[10px] text-mil-dim">
              {cand.why.map((w, i) => (
                <li key={`${i}-${w}`}>{w}</li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
