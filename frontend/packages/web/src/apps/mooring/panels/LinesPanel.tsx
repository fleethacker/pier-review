import { useState } from 'react';
import { cn } from '../../../lib/cn';
import { Button, Field, Panel, Select, StatusChip } from '../../../shell/ui';
import { hasUsableAnalysis, IDS } from '../mapping';
import { fmt } from '../units';
import { useController, useMooring } from './context';
import { PartsControl } from './PartsControl';
import { classSupport } from '../classSupport';

export function LinesPanel() {
  const c = useController();
  const s = useMooring((x) => x);
  const canEdit = classSupport(s.ship, s.shipClassId, s.loading).canPlan;
  const analysis = s.analysis.response;
  const results = new Map((hasUsableAnalysis(analysis) ? analysis?.result.lines ?? [] : []).map((l) => [l.line_number, l]));
  const specs = s.lineSpecs.map((l) => ({ value: l.spec_id, label: l.spec_id }));
  const shipFittings = (s.ship?.fittings ?? []).filter((f) => f.kind === 'bitt' && f.side === s.side)
    .map((f) => ({ value: f.fitting_id, label: f.fitting_id }));
  const pierFittings = (s.berth?.fittings ?? []).map((f) => ({ value: f.fitting_id, label: f.fitting_id }));
  const [shipChoice, chooseShip] = useState('');
  const [pierChoice, choosePier] = useState('');
  const shipId = shipFittings.some((f) => f.value === shipChoice) ? shipChoice : shipFittings[0]?.value ?? '';
  const pierId = pierFittings.some((f) => f.value === pierChoice) ? pierChoice : pierFittings[0]?.value ?? '';

  return (
    <Panel title="Mooring lines" className="space-y-3 p-4">
      <div className="space-y-2">
        <Select
          value={s.addLine.specId}
          onChange={(v) => c.setNewLineSpec(v, s.addLine.parts)}
          options={specs}
          disabled={!canEdit}
        />
        <PartsControl
          label="New line: single or doubled up"
          value={s.addLine.parts}
          onChange={(n) => c.setNewLineSpec(s.addLine.specId, n)}
          disabled={!canEdit}
        />
        {s.addLine.active ? (
          <div className="rounded-sm border border-mil-cyan/40 bg-mil-cyan/10 p-2 text-[11px] text-mil-cyan">
            {s.addLine.shipFittingId
              ? `Ship fitting ${s.addLine.shipFittingId} chosen. Click a pier fitting to finish the line.`
              : 'Click a ship bitt, then a pier fitting, or drag between them.'}
            <Button size="sm" variant="ghost" className="ml-2" onClick={() => c.cancelAddLine()}>
              Done
            </Button>
          </div>
        ) : (
          <Button size="sm" disabled={!canEdit} onClick={() => c.startAddLine()}>
            Add line on canvas
          </Button>
        )}
        <p className="text-[11px] text-mil-dim">Drag between ship and pier fittings to add a line. Select a line, then drag either endpoint to reconnect it. Escape cancels. Installed lengths stay unchanged.</p>
        <details className="text-[11px] text-mil-dim">
          <summary className="cursor-pointer">Choose fittings without dragging</summary>
          <div className="mt-2 space-y-2">
            <Field label="New line ship fitting"><Select value={shipId} onChange={chooseShip} options={shipFittings} disabled={!canEdit} /></Field>
            <Field label="New line pier fitting"><Select value={pierId} onChange={choosePier} options={pierFittings} disabled={!canEdit} /></Field>
            <Button size="sm" disabled={!canEdit || !shipId || !pierId} onClick={() => c.addLine(shipId, pierId)}>Add selected fittings</Button>
          </div>
        </details>
      </div>

      {analysis && !hasUsableAnalysis(analysis) && (
        <p className="text-[11px] text-mil-amber">Line loads unavailable: analysis validity is {analysis.validity?.state ?? 'unknown'}. Inspect the analysis findings before rechecking.</p>
      )}
      {s.lines.length === 0 ? (
        <p className="text-[11px] text-mil-dim">
          {s.recommend.state === 'running' ? 'Recommending a layout…' : 'No lines yet.'}
        </p>
      ) : (
        <>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              className="flex-1"
              onClick={() => c.setAllParts(3)}
            >
              Double up all
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="flex-1"
              onClick={() => c.setAllParts(1)}
            >
              Single up all
            </Button>
          </div>
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
                  <div className="mt-1.5 space-y-1.5" onClick={(e) => e.stopPropagation()}>
                    <details className="text-mil-dim">
                      <summary className="cursor-pointer">Edit endpoints</summary>
                      <div className="mt-2 space-y-2">
                        <Field label={`Line ${l.line_number} ship fitting`}>
                          <Select value={l.ship_fitting_id} options={shipFittings}
                            onChange={(v) => c.updateLine(l.line_number, { ship_fitting_id: v })} disabled={!canEdit} />
                        </Field>
                        <Field label={`Line ${l.line_number} pier fitting`}>
                          <Select value={l.pier_fitting_id} options={pierFittings}
                            onChange={(v) => c.updateLine(l.line_number, { pier_fitting_id: v })} disabled={!canEdit} />
                        </Field>
                      </div>
                    </details>
                    <Select
                      value={l.spec_id}
                      options={specs}
                      onChange={(v) => c.updateLine(l.line_number, { spec_id: v })}
                    />
                    <PartsControl
                      label={`Line ${l.line_number}: single or doubled up`}
                      value={l.parts as 1 | 2 | 3}
                      onChange={(n) => c.updateLine(l.line_number, { parts: n })}
                    />
                    {l.paid_out_unstretched_length_ft != null && <p className="text-mil-dim">Installed unstretched length: {fmt.ft(l.paid_out_unstretched_length_ft, 1)} · preserved on reconnect</p>}
                  </div>
                  {r && (
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-sm bg-mil-border">
                        <div
                          className={cn(
                            'h-full',
                            r.status === 'RED'
                              ? 'bg-mil-red'
                              : r.status === 'AMBER'
                                ? 'bg-mil-amber'
                                : 'bg-mil-green',
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
        </>
      )}
    </Panel>
  );
}
