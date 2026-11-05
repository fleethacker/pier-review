import type { AgentPlan, AgentSchemas, MooringLine, TugAssignment } from '../types';

type Sequence = AgentSchemas['SequenceResult'];
type Step = AgentSchemas['SequenceStep'];

/** Summarize reported evidence only. An absent check never becomes a passing check. */
export function sequenceEvidence(sequence: Sequence) {
  const failed = sequence.steps.filter((step) => step.state_ok === false).length;
  const unknown = sequence.steps.filter((step) => stepEvidence(step, sequence.issues).status === 'AMBER').length;
  const partial = (sequence.issues ?? []).some((issue) => issue.code === 'PARTIAL_RESTRAINT');
  const blocked = failed > 0 || (sequence.issues ?? []).some((issue) => issue.severity === 'RED');
  const indeterminate = unknown > 0 || partial || sequence.steps.length === 0;
  return { failed, unknown, blocked, indeterminate };
}

export function stepEvidence(step: Step, issues: Sequence['issues'] = []): { label: string; status: 'RED' | 'AMBER' | 'NONE' } {
  if (step.state_ok === false) return { label: 'Static check failed', status: 'RED' };
  if ((issues ?? []).some((issue) => issue.code === 'PARTIAL_RESTRAINT' && (issue.step == null || issue.step === step.step))) {
    return { label: 'Partial restraint · static state not established', status: 'AMBER' };
  }
  if (step.state_ok === true) return { label: 'Static check passed', status: 'NONE' };
  return { label: 'Static state not established', status: 'AMBER' };
}

/** Ignore JSON property order and omitted/null defaults, but keep zero and all material line/tug fields. */
function canonical(value: unknown): string {
  function normalized(v: unknown): unknown {
    if (Array.isArray(v)) return v.map(normalized);
    if (v !== null && typeof v === 'object') return Object.fromEntries(
      Object.entries(v).filter(([, item]) => item != null).sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, normalized(item)]),
    );
    return v;
  }
  return JSON.stringify(normalized(value));
}

/** Geometry binding only: the AgentPlan contract does not contain a forecast/source revision to compare. */
export function sequenceLayoutMatches(
  plan: AgentPlan,
  live: { side: string; shipXFt: number; standoffFt: number | null; lines: MooringLine[]; tugs: TugAssignment[] },
  planStandoffFt: number | null,
): boolean {
  const config = plan.config;
  if (!config || config.side_to !== live.side || config.ship_x_ft !== live.shipXFt || planStandoffFt !== live.standoffFt) return false;
  const lines = (items: MooringLine[]) => [...items].sort((a, b) => a.line_number - b.line_number);
  const tugs = (items: TugAssignment[]) => [...items].sort((a, b) => canonical(a).localeCompare(canonical(b)));
  return canonical(lines(config.lines)) === canonical(lines(live.lines)) && canonical(tugs(plan.holding_tugs ?? [])) === canonical(tugs(live.tugs));
}
