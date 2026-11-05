import { useState } from 'react';
import { Button, Field, Panel, Select, StatusChip, inputClass } from '../../../shell/ui';
import type { Objective } from '../agent';
import { fmt, useUnitSystem } from '../units';
import { useAgent, useController, useMooring } from './context';
import { ResultLink } from './ResultLink';

const OBJECTIVES: { value: Objective; label: string }[] = [
  { value: 'moor_for_forecast', label: 'Moor for the forecast' },
  { value: 'storm_prep', label: 'Storm preparation' },
  { value: 'berthing', label: 'Berthing' },
];

export function AgentPanel() {
  useUnitSystem();
  const c = useController();
  const a = useAgent((s) => s);
  const canRun = useMooring((s) => (s.ship?.fittings?.length ?? 0) > 0);
  const [question, setQuestion] = useState('');
  const busy = a.phase === 'saving' || a.phase === 'running';

  return (
    <Panel title="Planning agent" className="space-y-3 p-4">
      <div className="grid grid-cols-[1fr_90px] gap-2">
        <Field label="Objective">
          <Select value={a.objective} onChange={(v) => c.agent.setObjective(v as Objective)} options={OBJECTIVES} />
        </Field>
        <Field label="Target % WLL">
          <input
            type="number"
            className={inputClass}
            min={10}
            max={100}
            value={a.targetMarginPct}
            onChange={(e) => c.agent.setTarget(Number(e.target.value))}
          />
        </Field>
      </div>
      <div className="flex gap-2">
        <Button size="sm" disabled={!canRun || busy} onClick={() => void c.agent.run()}>
          {a.phase === 'saving' ? 'Saving scenario…' : a.phase === 'running' ? 'Agent working…' : 'Ask the agent to plan'}
        </Button>
        {a.undo && (
          <Button size="sm" variant="secondary" onClick={() => c.agent.undo()}>
            Undo agent changes
          </Button>
        )}
      </div>
      {a.error && <p className="text-[11px] text-mil-red">{a.error}</p>}

      {a.steps.length > 0 && (
        <ol className="space-y-1.5" aria-label="Agent steps">
          {a.steps.map((s) => (
            <li key={`${s.iteration}-${s.tool}`} className="rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-mil-cyan">
                  {s.iteration}. {s.tool}
                </span>
                {s.resultId && <ResultLink id={s.resultId} />}
              </div>
              <div className="mt-0.5 text-white">{s.summary}</div>
            </li>
          ))}
        </ol>
      )}

      {a.proposal && a.phase === 'running' && (
        <div className="rounded-sm border border-mil-cyan/40 bg-mil-cyan/10 p-2 text-[11px] text-mil-cyan">
          Proposal: {a.proposal.config.lines.length} lines.
          <Button size="sm" variant="ghost" className="ml-2" onClick={() => c.agent.previewProposal()}>
            Preview on canvas
          </Button>
        </div>
      )}

      {a.plan && (
        <div className="space-y-2 border-t border-mil-border pt-3">
          <div className="flex items-center justify-between">
            <StatusChip status={a.plan.status ?? 'NONE'} label={`Plan ${a.plan.status ?? ''}`} />
            <div className="flex gap-1.5 text-[10px]">
              {a.plan.analysis_result_id && <ResultLink id={a.plan.analysis_result_id} />}
              {a.plan.risk_result_id && <ResultLink id={a.plan.risk_result_id} />}
            </div>
          </div>

          {a.plan.tug_plan && (
            <div className="rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]">
              <div className="mil-label !text-mil-amber">Tug assist</div>
              <div className="mt-1 text-white">
                {a.plan.tug_plan.recommended_tug_count} tugs · {fmt.hp(a.plan.tug_plan.total_power_hp)} ·{' '}
                {fmt.lbf(a.plan.tug_plan.required_lateral_lbf)} lateral
                {!a.plan.tug_plan.feasible && <span className="text-mil-red"> · not feasible</span>}
              </div>
              <ul className="mt-1 space-y-0.5 text-mil-text">
                {a.plan.tug_plan.assignments.map((t) => (
                  <li key={`${t.tug_id}-${t.push_point_id}`}>
                    {t.tug_id} {t.mode} at {t.push_point_id}: {fmt.lbf(t.force_lbf)}
                  </li>
                ))}
              </ul>
              {a.plan.tug_plan.rationale.map((r) => (
                <p key={r} className="mt-1 text-[10px] text-mil-dim">
                  {r}
                </p>
              ))}
            </div>
          )}

          <div>
            <div className="mil-label">Rationale</div>
            <ul className="mt-1 space-y-1.5">
              {(a.plan.rationale ?? []).map((r) => (
                <li key={r.text} className="text-[11px] text-white">
                  {r.text}
                  <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
                    {r.cites.map((id) => (
                      <ResultLink key={id} id={id} />
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {(a.plan.open_questions ?? []).length > 0 && (
            <div className="text-[11px] text-mil-amber">
              Open questions: {(a.plan.open_questions ?? []).join('; ')}
            </div>
          )}
          <details className="text-[10px] text-mil-dim">
            <summary className="cursor-pointer">Agent assumptions</summary>
            <ul className="mt-1 list-disc pl-4">
              {(a.plan.assumptions ?? []).map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </details>

          <Button size="sm" onClick={() => void c.agent.createSheet()} disabled={a.sheet.state === 'creating'}>
            {a.sheet.state === 'creating' ? 'Building sheet…' : a.sheet.sheet ? 'Rebuild safety sheet' : 'Create safety sheet'}
          </Button>
          {a.sheet.sheet && (
            <Button
              size="sm"
              variant="secondary"
              className="ml-2"
              onClick={() => c.openOverlay({ kind: 'sheet', id: a.sheet.sheet!.sheet_id })}
            >
              Open sheet
            </Button>
          )}
          {a.sheet.error && <p className="text-[11px] text-mil-red">{a.sheet.error}</p>}

          <div className="space-y-1.5 border-t border-mil-border pt-2">
            <div className="mil-label">Ask a follow-up</div>
            {a.chat.map((m, i) => (
              <p key={i} className={m.role === 'user' ? 'text-[11px] text-mil-cyan' : 'text-[11px] text-white'}>
                {m.role === 'user' ? 'You: ' : 'Agent: '}
                {m.text}
                {m.cites.map((id) => (
                  <span key={id} className="ml-1">
                    <ResultLink id={id} />
                  </span>
                ))}
              </p>
            ))}
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void c.agent.ask(question);
                setQuestion('');
              }}
            >
              <input
                className={inputClass}
                placeholder="What if the wind backs to NW at 35 kt?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                aria-label="Follow-up question"
              />
              <Button size="sm" type="submit" disabled={!question.trim() || busy}>
                Ask
              </Button>
            </form>
          </div>
        </div>
      )}
    </Panel>
  );
}
