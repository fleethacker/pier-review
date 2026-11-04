import { BackendBadge, Citation, Panel, StatusChip, toStatus } from '../../../shell/ui';
import { fmt } from '../units';
import { useMooring } from './context';

export function ResultPanel() {
  const analysis = useMooring((s) => s.analysis);
  const lines = useMooring((s) => s.lines);
  const res = analysis.response;
  if (lines.length === 0) return null;

  return (
    <Panel title="Analysis" className="space-y-3 p-4">
      {analysis.state === 'pending' && <p className="text-[11px] text-mil-cyan">Analyzing…</p>}
      {analysis.state === 'error' && <p className="text-[11px] text-mil-red">{analysis.error}</p>}
      {res && (
        <>
          <div className="flex items-center justify-between">
            <StatusChip status={res.status} label={`Overall ${res.status}`} />
            <BackendBadge backend={res.backend} />
          </div>
          <p className="text-xs text-mil-amber">Validity: {res.validity?.state ?? 'unknown'}. {res.validity?.reasons?.map((r) => r.message).join(' ')}</p>
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <Metric label="Tightest line" value={`${res.result.min_margin.element_id} · ${fmt.pct(res.result.min_margin.pct_wll)} WLL`} />
            <Metric
              label="Ship drift"
              value={`${res.result.offset.sway_ft.toFixed(1)} ft sway · ${res.result.offset.surge_ft.toFixed(1)} ft surge`}
            />
          </div>
          <ul className="space-y-1.5">
            {[...(res.warnings ?? []), ...res.result.findings].map((f, i) => (
              <li key={`${f.rule_id}-${i}`} className="rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]">
                <div className="flex items-start gap-2">
                  <StatusChip status={toStatus(f.severity)} label="" className="mt-0.5" />
                  <span className="flex-1 text-white">{f.message}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 pl-4">
                  <span className="text-mil-dim">{f.rule_id}</span>
                  <Citation reference={f.reference} />
                </div>
              </li>
            ))}
          </ul>
          <details className="text-[10px] text-mil-dim">
            <summary className="cursor-pointer">Assumptions and provenance</summary>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {(res.assumptions ?? []).map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
            <div className="mt-1">
              {res.model} {res.model_version} · result {res.result_id}
            </div>
          </details>
        </>
      )}
    </Panel>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mil-label !text-mil-dim">{label}</div>
      <div className="text-white">{value}</div>
    </div>
  );
}
