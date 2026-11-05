import { Citation, Panel, StatusChip } from '../../../shell/ui';
import { IDS, standoffFt } from '../mapping';
import { sequenceEvidence, sequenceLayoutMatches, stepEvidence } from '../sequence/evidence';
import { fmt, useUnitSystem } from '../units';
import { useAgent, useController, useMooring } from './context';
import { ResultLink } from './ResultLink';

const ACTION_LABEL: Record<string, string> = {
  pass: 'Pass line', secure_pier: 'Secure ashore', hold: 'Hold',
  take_to_power: 'Take to power', double_up: 'Double up', tend: 'Tend',
};

export function SequencePanel() {
  useUnitSystem();
  const c = useController();
  const plan = useAgent((s) => s.plan);
  const planId = useAgent((s) => s.planId);
  const phase = useAgent((s) => s.phase);
  const live = useMooring((s) => s);
  const seq = plan?.sequence;
  if (!seq || !plan) return null;

  const evidence = sequenceEvidence(seq);
  const scenario = live.scenarios.find((s) => s.scenario_id === plan.scenario_id);
  const identityMatches = scenario != null && scenario.ship_class_id === live.shipClassId
    && scenario.berth_id === live.berthId && scenario.loading === live.loading;
  const layoutMatches = sequenceLayoutMatches(plan, {
    side: live.side, shipXFt: live.shipXFt,
    standoffFt: live.berth ? standoffFt(live.berth, live.standoffOverrideFt) : live.standoffOverrideFt,
    lines: live.lines, tugs: live.tugAssignments,
  }, live.berth ? standoffFt(live.berth, plan.config?.standoff_ft) : plan.config?.standoff_ft ?? null);
  const currentLayout = phase === 'done' && plan.state === 'succeeded' && planId === plan.plan_id && identityMatches && layoutMatches;
  const stale = !currentLayout;
  const label = evidence.blocked ? 'Blocked by reported issues' : evidence.indeterminate ? 'Feasibility indeterminate' : 'Reported static checks passed';

  return (
    <Panel title={`Line sequence · ${seq.steps.length} steps · ${seq.crews_required} crews`} className="space-y-2 p-4">
      <div className="space-y-1 text-[11px]">
        <div className="flex flex-wrap gap-2">
          <StatusChip status={evidence.blocked ? 'RED' : evidence.indeterminate ? 'AMBER' : 'NONE'} label={label} />
          <span className={seq.review_status === 'reviewed' ? 'text-mil-text' : 'text-mil-amber'}>
            {seq.review_status === 'reviewed' ? 'Procedure review recorded' : 'Draft · unreviewed'}
          </span>
        </div>
        <p className="text-mil-dim">{evidence.failed} failed · {evidence.unknown} unevaluated static states. Static checks do not establish safe transient execution.</p>
        <p className="break-words text-mil-dim">Saved plan {plan.plan_id} · scenario {plan.scenario_id}</p>
        {plan.sequence_result_id && <ResultLink id={plan.sequence_result_id} />}
        {stale ? (
          <p role="status" className="border-l-2 border-mil-amber pl-2 text-mil-amber">
            Saved sequence is not bound to the current canvas. Inputs changed, a new plan is running, or its source scenario is unavailable. Run a new plan before using these steps.
          </p>
        ) : <p className="text-mil-text">Line layout and holding-tug assignments match this saved plan.</p>}
        <p className="text-mil-amber">Environment and forecast revision binding is not available in this sequence response. Reassess after conditions change.</p>
        {plan.installed_at_water_level_mllw_ft != null && <p className="text-mil-text">Assessed installation water level: {fmt.ft(plan.installed_at_water_level_mllw_ft, 1)} MLLW.</p>}
        {seq.total_duration_min != null && <p className="text-mil-text">Planning duration: {seq.total_duration_min} min · unreviewed estimate.</p>}
      </div>
      {(seq.issues ?? []).length > 0 && (
        <ul aria-label="Sequence issues" className="space-y-1 text-[11px]">
          {seq.issues!.map((issue, i) => (
            <li key={`${issue.code}-${i}`} className={issue.severity === 'RED' ? 'text-mil-red' : 'text-mil-amber'}>
              <span className="font-mono">{issue.severity} · {issue.code}</span>
              {issue.step != null && ` · step ${issue.step}`}{issue.line_number != null && ` · line ${issue.line_number}`}: {issue.message}
            </li>
          ))}
        </ul>
      )}
      {(seq.limitations ?? []).length > 0 && (
        <div className="text-[11px] text-mil-amber">
          <p className="mil-label">Limitations</p>
          <ul className="list-inside list-disc">{seq.limitations!.map((text, i) => <li key={i}>{text}</li>)}</ul>
        </div>
      )}
      {(seq.timing_assumptions ?? []).length > 0 && (
        <details className="text-[11px] text-mil-dim">
          <summary className="cursor-pointer">Timing assumptions · planning estimates</summary>
          <ul className="list-inside list-disc">{seq.timing_assumptions!.map((text, i) => <li key={i}>{text}</li>)}</ul>
        </details>
      )}
      <ol className="space-y-1" aria-label="Line-handling steps">
        {seq.steps.map((step) => {
          const state = stepEvidence(step, seq.issues);
          return (
            <li key={step.step} className="rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]">
              <div className="flex items-start justify-between gap-2">
                <span className="text-white">{step.step}. {ACTION_LABEL[step.action] ?? step.action}{step.line_number != null ? ` · line ${step.line_number}` : ''}</span>
                <span className="text-mil-dim">{step.station} · {step.crews} crews</span>
              </div>
              <StatusChip status={state.status} label={state.label} />
              <p className="text-mil-text">{step.trigger}</p>
              {step.state_note && <p className="text-mil-text">{step.state_note}</p>}
              {step.state_ok != null && step.state_max_pct != null && <p className="text-mil-text">Reported peak utilization: {fmt.pct(step.state_max_pct)}</p>}
              {!!step.depends_on?.length && <p className="text-mil-dim">After steps {step.depends_on.join(', ')}.</p>}
              {step.duration_min != null && <p className="text-mil-dim">Estimate: {step.duration_min} min · unreviewed.</p>}
              {!!step.tug_ids?.length && <p className="text-mil-amber">Relies on tugs: {step.tug_ids.join(', ')}. Verify their availability for this step.</p>}
              {step.caution && <p className="text-mil-amber">{step.caution}</p>}
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <Citation reference={step.reference} />
                {step.line_number != null && (
                  <button type="button" disabled={stale} className="rounded-sm border border-mil-border px-1.5 py-0.5 text-mil-cyan hover:border-mil-cyan/60 disabled:cursor-not-allowed disabled:opacity-40"
                    aria-label={`Select line ${step.line_number} for step ${step.step}`}
                    onClick={() => c.host.store.select({ type: 'link', id: IDS.line(step.line_number!) })}>
                    Select line {step.line_number}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}
