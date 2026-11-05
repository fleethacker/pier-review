import { BackendBadge, Button, StatusChip, toStatus } from '../../../shell/ui';
import { useAgent, useController } from './context';
import { ResultLink } from './ResultLink';

export const VERDICT_LABEL: Record<string, string> = {
  ready_for_signature: 'Ready for signature',
  revise: 'Revise',
  reject: 'Reject',
};

/** Explicit, independent Safety review of the finished plan. The sheet is built from this review and no other. */
export function ReviewSection() {
  const c = useController();
  const phase = useAgent((s) => s.phase);
  const intakeReportId = useAgent((s) => s.intakeReportId);
  const { state, progress, error, review } = useAgent((s) => s.review);

  return (
    <div className="space-y-1.5 rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]" aria-label="Independent safety review">
      <div className="flex items-center justify-between">
        <div className="mil-label">Independent safety review</div>
        {review && <BackendBadge backend={review.backend} />}
      </div>
      <p className="text-[10px] text-mil-dim">
        A separate Safety agent re-checks the finished plan against the thresholds
        {intakeReportId ? ' and the same Intake report the Planner used' : '; no Intake report was attached to this plan'}.
        Completing the review does not approve the plan.
      </p>
      <Button size="sm" disabled={phase !== 'done' || state === 'running'} onClick={() => void c.agent.review()}>
        {state === 'running' ? `Reviewing… ${Math.round(progress * 100)}%` : review ? 'Review again' : 'Run independent review'}
      </Button>
      {error && (
        <p role="alert" className="text-mil-red">
          {error}
        </p>
      )}
      {review && state === 'ready' && (
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip status={review.status} label={`Review ${review.status}`} />
            <span className={review.verdict === 'ready_for_signature' ? 'text-white' : 'text-mil-amber'}>
              {VERDICT_LABEL[review.verdict] ?? review.verdict}
            </span>
            {review.validity && <span className="text-mil-dim">validity {review.validity.state}</span>}
          </div>
          <p className="text-[10px] text-mil-dim">
            Review <span className="font-mono text-mil-text">{review.review_id}</span> · {review.created_at_utc}
            {review.intake_report_id && (
              <>
                {' '}
                · Intake <span className="font-mono text-mil-text">{review.intake_report_id}</span>
              </>
            )}
          </p>
          <p className="text-white">{review.summary}</p>
          <p className="text-[10px] text-mil-dim">
            {review.summary_source === 'llm'
              ? 'Narrated by a language model; the checks come from stored results.'
              : `Deterministic summary${review.narration_note ? ` (${review.narration_note})` : ''}.`}
          </p>
          <ul className="space-y-0.5" aria-label="Review checks">
            {review.checks.map((k) => (
              <li key={k.check_id} className="flex items-start gap-2">
                <StatusChip status={k.passed ? 'GREEN' : k.severity === 'INFO' ? 'NONE' : toStatus(k.severity)} label="" className="mt-0.5" />
                <span className={k.passed ? 'text-mil-text' : 'text-white'}>
                  {k.title}
                  {!k.passed && <span className="text-mil-dim">: {k.detail}</span>}
                  {(k.cites ?? []).map((id) => (
                    <span key={id} className="ml-1">
                      <ResultLink id={id} />
                    </span>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
