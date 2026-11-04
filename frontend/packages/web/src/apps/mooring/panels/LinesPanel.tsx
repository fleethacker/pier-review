import { cn } from '../../../lib/cn';
import { Button, Panel, Select, StatusChip } from '../../../shell/ui';
import { IDS } from '../mapping';
import { fmt } from '../units';
import { useController, useMooring } from './context';

export function LinesPanel() {
  const c = useController();
  const s = useMooring((x) => x);
  const canEdit = (s.ship?.fittings?.length ?? 0) > 0;
  const results = new Map((s.analysis.response?.result.lines ?? []).map((l) => [l.line_number, l]));
  const specs = s.lineSpecs.map((l) => ({ value: l.spec_id, label: l.spec_id }));

  return (
    <Panel title="Mooring lines" className="space-y-3 p-4">
      <div className="space-y-2">
        <div className="grid grid-cols-[1fr_72px] gap-2">
          <Select
            value={s.addLine.specId}
            onChange={(v) => c.setNewLineSpec(v, s.addLine.parts)}
            options={specs}
            disabled={!canEdit}
          />
          <Select
            value={String(s.addLine.parts)}
            onChange={(v) => c.setNewLineSpec(s.addLine.specId, Number(v) as 1 | 2 | 3)}
            options={[1, 2, 3].map((n) => ({ value: String(n), label: `${n} part${n > 1 ? 's' : ''}` }))}
            disabled={!canEdit}
          />
        </div>
        {s.addLine.active ? (
          <div className="rounded-sm border border-mil-cyan/40 bg-mil-cyan/10 p-2 text-[11px] text-mil-cyan">
            {s.addLine.shipFittingId
              ? `Ship fitting ${s.addLine.shipFittingId} chosen. Click a pier fitting to finish the line.`
              : 'Click a ship bitt, then a pier fitting.'}
            <Button size="sm" variant="ghost" className="ml-2" onClick={() => c.cancelAddLine()}>
              Done
            </Button>
          </div>
        ) : (
          <Button size="sm" disabled={!canEdit} onClick={() => c.startAddLine()}>
            Add line on canvas
          </Button>
        )}
      </div>

      {s.lines.length === 0 ? (
        <p className="text-[11px] text-mil-dim">
          {s.recommend.state === 'running' ? 'Recommending a layout…' : 'No lines yet.'}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {s.lines.map((l) => {
            const r = results.get(l.line_number);
            return (
              <li
                key={l.line_number}
                className="rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]"
                onClick={() => c.host.store.select({ type: 'link', id: IDS.line(l.line_number) })}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-white">
                    #{l.line_number} {l.role ?? ''}
                  </span>
                  <span className="truncate text-mil-dim">
                    {l.ship_fitting_id} → {l.pier_fitting_id}
                  </span>
                  <button
                    className="text-mil-dim hover:text-mil-red"
                    aria-label={`Remove line ${l.line_number}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      c.removeLine(l.line_number);
                    }}
                  >
                    ✕
                  </button>
                </div>
                <div className="mt-1.5 grid grid-cols-[1fr_64px] gap-2" onClick={(e) => e.stopPropagation()}>
                  <Select value={l.spec_id} options={specs} onChange={(v) => c.updateLine(l.line_number, { spec_id: v })} />
                  <Select
                    value={String(l.parts)}
                    options={[1, 2, 3].map((n) => ({ value: String(n), label: `×${n}` }))}
                    onChange={(v) => c.updateLine(l.line_number, { parts: Number(v) as 1 | 2 | 3 })}
                  />
                </div>
                {r && (
                  <div className="mt-1.5 flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-sm bg-mil-border">
                      <div
                        className={cn(
                          'h-full',
                          r.status === 'RED' ? 'bg-mil-red' : r.status === 'AMBER' ? 'bg-mil-amber' : 'bg-mil-green',
                        )}
                        style={{ width: `${Math.min(r.pct_wll, 100)}%` }}
                      />
                    </div>
                    <span className="w-10 text-right text-mil-text">{fmt.pct(r.pct_wll)}</span>
                    <StatusChip status={r.status} label="" />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
