import { useEffect } from 'react';
import { Button, Panel, StatusChip, toStatus } from '../../../shell/ui';
import { useAgent, useController } from '../panels/context';
import { ResultLink } from '../panels/ResultLink';
import { EXPECTED_LABEL, finalOutcome } from './cases';

const VERDICT: Record<string, string> = {
  ready_for_signature: 'ready for signature',
  revise: 'revise',
  reject: 'reject',
};

/** The four named offline demo cases, with the initial (as supplied) and final (planned and reviewed) outcomes kept apart. */
export function DemoCasesPanel() {
  const c = useController();
  const { phase, error, cases, loadingCaseId, active } = c.demo.state.use((s) => s);
  const plan = useAgent((s) => s.plan);
  const review = useAgent((s) => (s.review.state === 'ready' ? s.review.review : null));

  useEffect(() => {
    if (c.demo.state.get().phase === 'idle') void c.demo.list();
  }, [c]);

  const activeCase = active ? cases.find((x) => x.case_id === active.caseId) : undefined;
  const final = finalOutcome(active, plan, review);

  return (
    <Panel title="Demo cases" className="space-y-2 p-4">
      <p className="text-[11px] text-mil-dim">
        Named offline cases built from seed data, not operational plans. Loading one saves its scenario and analyzes the line
        plan exactly as supplied.
      </p>
      {phase === 'loading' && <p className="text-[11px] text-mil-cyan">Loading cases…</p>}
      {error && (
        <div role="alert" className="rounded-sm border border-mil-red/40 bg-mil-red/10 p-2 text-[11px] text-mil-red">
          {error}
          {phase === 'error' && (
            <Button size="sm" variant="ghost" className="ml-2" onClick={() => void c.demo.list()}>
              Retry
            </Button>
          )}
        </div>
      )}
      {cases.length > 0 && (
        <ul className="space-y-1.5" aria-label="Demo cases">
          {cases.map((dc) => (
            <li key={dc.case_id} className="flex items-start justify-between gap-2 text-[11px]">
              <div>
                <div className={active?.caseId === dc.case_id ? 'text-mil-cyan' : 'text-white'}>{dc.name}</div>
                <div className="text-[10px] text-mil-dim">Demonstrates: {EXPECTED_LABEL[dc.expected_outcome]}</div>
              </div>
              <Button
                size="sm"
                variant={active?.caseId === dc.case_id ? 'secondary' : 'primary'}
                disabled={loadingCaseId !== null}
                onClick={() => void c.demo.load(dc.case_id)}
              >
                {loadingCaseId === dc.case_id ? 'Loading…' : active?.caseId === dc.case_id ? 'Reload' : 'Load'}
              </Button>
            </li>
          ))}
        </ul>
      )}

      {active && activeCase && (
        <div className="space-y-2 border-t border-mil-border pt-2 text-[11px]" aria-label="Case outcomes">
          <p className="text-[10px] text-mil-dim">{activeCase.explanation}</p>
          <div className="rounded-sm border border-mil-border bg-mil-bg/60 p-2">
            <div className="mil-label">Initial: plan as supplied</div>
            {active.initial ? (
              <div className="mt-1 space-y-0.5">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusChip status={active.initial.status} label={active.initial.status} />
                  <span className="text-mil-text">validity {active.initial.validity ?? 'not reported'}</span>
                  <ResultLink id={active.initial.resultId} />
                </div>
                {active.initial.reasons.map((r, i) => (
                  <p key={`${i}-${r}`} className="text-[10px] text-mil-dim">
                    {r}
                  </p>
                ))}
              </div>
            ) : active.initialError ? (
              <p className="mt-1 text-mil-red">Could not analyze the supplied plan: {active.initialError}</p>
            ) : (
              <p className="mt-1 text-mil-dim">Analyzing…</p>
            )}
          </div>
          <div className="rounded-sm border border-mil-border bg-mil-bg/60 p-2">
            <div className="mil-label">Final: after Planner and independent review</div>
            {!final ? (
              <p className="mt-1 text-mil-dim">Run the planning agent on this case, then the independent safety review.</p>
            ) : (
              <div className="mt-1 space-y-0.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-mil-dim">Planner</span>
                  {final.planStatus ? (
                    <StatusChip status={toStatus(final.planStatus)} label={final.planStatus} />
                  ) : (
                    <span className="text-mil-dim">no status</span>
                  )}
                </div>
                {final.review ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-mil-dim">Review</span>
                    <StatusChip status={final.review.status} label={final.review.status} />
                    <span className="text-white">{VERDICT[final.review.verdict] ?? final.review.verdict}</span>
                    {final.review.validity && <span className="text-mil-text">validity {final.review.validity.state}</span>}
                  </div>
                ) : (
                  <p className="text-mil-dim">Independent review not run yet.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
