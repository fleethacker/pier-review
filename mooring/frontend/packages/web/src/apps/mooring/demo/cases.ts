import { Store } from '../../../lib/store';
import { describeError, modeling, unwrap } from '../api';
import type { MooringController } from '../controller';
import type { AnalyzeResponse, ModelingSchemas, SafetyReview } from '../types';

export type DockingDemoCase = ModelingSchemas['DockingDemoCase'];
export type ExpectedOutcome = DockingDemoCase['expected_outcome'];

/** The outcome of the plan exactly as the case supplies it, before the Planner touches it. */
export interface InitialOutcome {
  status: AnalyzeResponse['status'];
  validity: NonNullable<AnalyzeResponse['validity']>['state'] | null;
  reasons: string[];
  resultId: string;
}

export interface ActiveCase {
  caseId: string;
  scenarioId: string;
  initial: InitialOutcome | null;
  initialError: string | null;
}

export interface DemoCasesState {
  phase: 'idle' | 'loading' | 'ready' | 'error';
  error: string | null;
  cases: DockingDemoCase[];
  /** Case being saved and loaded right now. */
  loadingCaseId: string | null;
  active: ActiveCase | null;
}

const INITIAL: DemoCasesState = { phase: 'idle', error: null, cases: [], loadingCaseId: null, active: null };

/** Plain-language name of the outcome the service says each case demonstrates. */
export const EXPECTED_LABEL: Record<ExpectedOutcome, string> = {
  supported_limited: 'Supported, limited (AMBER)',
  overloaded: 'Overloaded (RED)',
  invalid_data: 'Invalid input (RED, invalid)',
  undetermined: 'Undetermined: line plan underconstrained',
};

/** The final outcome after Planner and independent review, or null when they do not belong to this case. */
export function finalOutcome(
  active: ActiveCase | null,
  plan: { scenario_id?: string | null; status?: string | null } | null,
  review: SafetyReview | null,
): { planStatus: string | null; review: SafetyReview | null } | null {
  if (!active || !plan || plan.scenario_id !== active.scenarioId) return null;
  return { planStatus: plan.status ?? null, review: review && review.plan_id ? review : null };
}

/** The four named offline demo cases: load one as a saved scenario and record its initial outcome. */
export class DemoCaseSession {
  readonly state = new Store<DemoCasesState>(INITIAL);
  private request = 0;
  private disposed = false;

  constructor(private readonly parent: MooringController) {}

  dispose(): void {
    this.disposed = true;
    this.request++;
  }

  async list(): Promise<void> {
    if (this.state.get().phase === 'loading') return;
    this.state.set({ phase: 'loading', error: null });
    try {
      const cases = unwrap(await modeling.GET('/api/v1/demo/docking-cases'));
      if (!this.disposed) this.state.set({ phase: 'ready', cases });
    } catch (e) {
      if (!this.disposed) this.state.set({ phase: 'error', error: describeError(e) });
    }
  }

  /**
   * Save the case's environment and scenario exactly as published, select it in the UI, then analyze the supplied
   * plan for the initial outcome. Nothing in the case is altered; the Planner works on the saved scenario afterwards.
   */
  async load(caseId: string): Promise<void> {
    const demo = this.state.get().cases.find((c) => c.case_id === caseId);
    if (!demo) return;
    const request = ++this.request;
    const current = () => !this.disposed && request === this.request;
    this.state.set({ loadingCaseId: caseId, error: null, active: null });
    try {
      const env = unwrap(await modeling.POST('/api/v1/env/scenarios', { body: demo.environment_request }));
      if (!current()) return;
      const saved = unwrap(
        await modeling.POST('/api/v1/scenarios', {
          body: {
            ...demo.scenario_request,
            env_source: { ...demo.scenario_request.env_source, env_scenario_id: env.env_scenario_id },
          },
        }),
      );
      if (!current()) return;
      await this.parent.loadScenario(saved.scenario_id);
      if (!current()) return;
      if (this.parent.state.get().scenarioId !== saved.scenario_id) {
        throw new Error('The case was saved but could not be selected. See the message above the panels.');
      }
      this.state.set({ active: { caseId, scenarioId: saved.scenario_id, initial: null, initialError: null } });
      try {
        const analysis = unwrap(await modeling.POST('/api/v1/mooring/analyze', { body: demo.analysis_request }));
        if (!current()) return;
        this.setActive({
          initial: {
            status: analysis.status,
            validity: analysis.validity?.state ?? null,
            reasons: (analysis.validity?.reasons ?? []).map((r) => r.message),
            resultId: analysis.result_id,
          },
        });
      } catch (e) {
        if (current()) this.setActive({ initialError: describeError(e) });
      }
    } catch (e) {
      if (current()) this.state.set({ error: describeError(e) });
    } finally {
      if (current()) this.state.set({ loadingCaseId: null });
    }
  }

  private setActive(patch: Partial<ActiveCase>): void {
    const active = this.state.get().active;
    if (active) this.state.set({ active: { ...active, ...patch } });
  }
}
