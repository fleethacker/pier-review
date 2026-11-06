import { Store } from '../../lib/store';
import { openAgentEvents } from './events';
import { agents, AGENTS_BASE, awaitJob, modeling, unwrap, describeError } from './api';
import type { MooringController } from './controller';
import type {
  AgentPlan,
  AgentSchemas,
  Approval,
  MooringConfig,
  MooringLine,
  SafetyReview,
  SafetySheet,
  TugAssignment,
} from './types';

export type Objective = AgentSchemas['AgentPlanRequest']['objective'];
export type Role = AgentSchemas['ApprovalCreate']['role'];

export interface AgentStep {
  iteration: number;
  tool: string;
  summary: string;
  resultId: string | null;
}
export interface ChatItem {
  role: 'user' | 'agent';
  text: string;
  cites: string[];
}

export interface ReviewState {
  state: 'idle' | 'running' | 'ready' | 'error';
  progress: number;
  error: string | null;
  review: SafetyReview | null;
}

export interface AgentState {
  phase: 'idle' | 'saving' | 'running' | 'done' | 'error';
  error: string | null;
  planId: string | null;
  /** The Intake report the Planner was given; the independent review is bound to the same report. */
  intakeReportId: string | null;
  objective: Objective;
  targetMarginPct: number;
  steps: AgentStep[];
  proposal: { config: MooringConfig; status: 'GREEN' | 'AMBER' | 'RED' } | null;
  plan: AgentPlan | null;
  chat: ChatItem[];
  undo: { lines: MooringLine[]; tugs: TugAssignment[] } | null;
  /** Independent Safety review of the finished plan. A sheet is only built from an explicit, ready review. */
  review: ReviewState;
  sheet: {
    state: 'idle' | 'creating' | 'ready' | 'error';
    error: string | null;
    sheet: SafetySheet | null;
    html: string | null;
    image: string | null;
  };
}

const INITIAL: AgentState = {
  phase: 'idle',
  error: null,
  planId: null,
  intakeReportId: null,
  objective: 'moor_for_forecast',
  targetMarginPct: 70,
  steps: [],
  proposal: null,
  plan: null,
  chat: [],
  undo: null,
  review: { state: 'idle', progress: 0, error: null, review: null },
  sheet: { state: 'idle', error: null, sheet: null, html: null, image: null },
};

const message = describeError;

/** SafetyReviewRequest's documented default. The independent review does not inherit the Planner's target margin. */
export const REVIEW_TARGET_PCT_WLL = 80;

/** The planning agent and safety sheet flow. Reads and writes the mooring plan through the controller. */
export class AgentSession {
  readonly state = new Store<AgentState>(INITIAL);
  private source: ReturnType<typeof openAgentEvents> | null = null;
  private disposed = false;
  private context: string | null = null;
  private sheetRequest = 0;
  private reviewRequest = 0;
  private planRequest = 0;
  private applying = false;
  private invalidated = false;
  private unsubscribe: () => void;

  constructor(private readonly parent: MooringController) {
    this.unsubscribe = parent.state.subscribe(() => {
      if (this.applying || this.invalidated || this.context === null || this.context === parent.planningKey()) return;
      this.resetForSelection();
      this.invalidated = true;
      this.state.set({ error: 'Layout, assistance, forecast or environment changed. Run a new plan and safety review.' });
      if (parent.state.get().overlay?.kind === 'sheet') parent.openOverlay(null);
    });
  }

  private get s(): AgentState {
    return this.state.get();
  }

  dispose(): void {
    this.disposed = true;
    this.unsubscribe();
    this.planRequest++;
    this.sheetRequest++;
    this.reviewRequest++;
    this.source?.close();
  }

  /** A different ship, berth or side-to must not retain the previous selection's plan or late responses. */
  resetForSelection(): void {
    this.planRequest++;
    this.sheetRequest++;
    this.reviewRequest++;
    this.source?.close();
    this.source = null;
    this.context = null;
    this.invalidated = false;
    this.state.set({ ...INITIAL, objective: this.s.objective, targetMarginPct: this.s.targetMarginPct });
    if (this.parent.state.get().overlay?.kind === 'sheet') this.parent.openOverlay(null);
  }

  setObjective(objective: Objective): void {
    this.state.set({ objective });
  }

  setTarget(targetMarginPct: number): void {
    this.state.set({ targetMarginPct });
  }

  async run(): Promise<void> {
    if (this.s.phase === 'running' || this.s.phase === 'saving') return;
    const request = ++this.planRequest;
    const current = () => !this.disposed && request === this.planRequest;
    this.sheetRequest++;
    this.reviewRequest++;
    this.source?.close();
    this.context = this.parent.planningKey();
    this.invalidated = false;
    this.state.set({
      undo: null,
      phase: 'saving',
      error: null,
      steps: [],
      proposal: null,
      plan: null,
      chat: [],
      planId: null,
      intakeReportId: null,
      review: INITIAL.review,
      sheet: INITIAL.sheet,
    });
    try {
      const inputs = this.parent.planningKey();
      const intakeReportId = this.parent.intake.reportId();
      const scenarioId = await this.parent.ensureScenario(`Agent run ${new Date().toISOString().slice(11, 19)}Z`);
      if (!current()) return;
      if (inputs !== this.parent.planningKey()) throw new Error('Inputs changed while saving. Run a new plan.');
      if (!scenarioId) throw new Error('Choose a ship and berth first.');
      const accepted = unwrap(
        await agents.POST('/api/v1/agent/plans', {
          body: {
            scenario_id: scenarioId,
            objective: this.s.objective,
            target_margin_pct_wll: this.s.targetMarginPct,
            max_iterations: 8,
            ...(intakeReportId ? { intake_report_id: intakeReportId } : {}),
          },
        }),
      );
      if (!current()) return;
      this.state.set({ phase: 'running', planId: accepted.plan_id, intakeReportId });
      this.listen(accepted.events_url, accepted.plan_id);
    } catch (e) {
      if (current()) this.state.set({ phase: 'error', error: message(e) });
    }
  }

  private listen(eventsUrl: string, planId: string): void {
    this.source?.close();
    const source = openAgentEvents(`${AGENTS_BASE}${eventsUrl}`);
    this.source = source;
    const request = this.planRequest;
    const current = () => !this.disposed && this.source === source && request === this.planRequest;
    const parse = <T,>(ev: Event): T => JSON.parse((ev as MessageEvent).data) as T;

    source.addEventListener('step', (ev) => {
      if (!current()) return;
      const d = parse<{ iteration: number; thought_summary: string; tool: string; result_id: string | null }>(ev);
      this.state.set({
        steps: [...this.s.steps, { iteration: d.iteration, tool: d.tool, summary: d.thought_summary, resultId: d.result_id }],
      });
    });
    source.addEventListener('proposal', (ev) => {
      if (!current()) return;
      this.state.set({ proposal: parse<NonNullable<AgentState['proposal']>>(ev) });
    });
    source.addEventListener('message', (ev) => {
      if (!current()) return;
      const d = parse<{ text: string; cites: string[] }>(ev);
      this.state.set({ chat: [...this.s.chat, { role: 'agent', text: d.text, cites: d.cites }] });
    });
    source.addEventListener('done', () => {
      if (!current()) return;
      source.close();
      void this.finish(planId, request);
    });
    source.onerror = () => {
      // EventSource retries by itself; only give up if the stream never produced anything.
      if (current() && source.readyState === 2 && this.s.phase === 'running') {
        this.state.set({ phase: 'error', error: 'The agent event stream closed unexpectedly.' });
      }
    };
  }

  private async finish(planId: string, request: number): Promise<void> {
    const current = () => !this.disposed && request === this.planRequest && this.s.planId === planId;
    try {
      const plan = unwrap(await agents.GET('/api/v1/agent/plans/{plan_id}', { params: { path: { plan_id: planId } } }));
      if (!current()) return;
      this.state.set({ phase: 'done', plan });
      this.applyPlan(plan);
    } catch (e) {
      if (current()) this.state.set({ phase: 'error', error: message(e) });
    }
  }

  /** Put the agent's lines and tugs on the canvas, keeping what was there so it can be undone. */
  applyPlan(plan: AgentPlan | null = this.s.plan): void {
    if (!plan?.config || !this.applicable()) return;
    const config = plan.config;
    const { lines, tugAssignments } = this.parent.state.get();
    if (!this.s.undo) this.state.set({ undo: { lines, tugs: tugAssignments } });
    this.applyLayout(() => {
      this.parent.setTugAssignments(plan.holding_tugs ?? []);
      this.parent.replaceLines(config.lines.map((l) => ({ ...l })));
    });
  }

  private applyLayout(change: () => void): void {
    this.applying = true;
    try { change(); this.context = this.parent.planningKey(); }
    finally { this.applying = false; }
  }

  private applicable(): boolean {
    if (this.invalidated || (this.context !== null && this.context !== this.parent.planningKey())) {
      this.state.set({ error: 'Ship, berth, geometry or environment changed. Run a new plan before applying or undoing it.' });
      return false;
    }
    return true;
  }

  previewProposal(): void {
    const p = this.s.proposal;
    if (!p || !this.applicable()) return;
    const { lines, tugAssignments } = this.parent.state.get();
    if (!this.s.undo) this.state.set({ undo: { lines, tugs: tugAssignments } });
    this.applyLayout(() => this.parent.replaceLines(p.config.lines.map((l) => ({ ...l }))));
  }

  undo(): void {
    const u = this.s.undo;
    if (!u || !this.applicable()) return;
    this.applyLayout(() => { this.parent.setTugAssignments(u.tugs); this.parent.replaceLines(u.lines); });
    this.reviewRequest++;
    this.sheetRequest++;
    this.state.set({ review: INITIAL.review, sheet: INITIAL.sheet });
    this.resetForSelection();
    this.invalidated = true;
    this.state.set({ error: 'The plan was undone. Run a new plan and safety review for this layout.' });
  }

  async ask(text: string): Promise<void> {
    const planId = this.s.planId;
    if (!planId || !text.trim() || this.s.phase !== 'done' || !this.applicable()) return;
    const request = ++this.planRequest;
    const current = () => !this.disposed && request === this.planRequest && this.s.planId === planId;
    this.source?.close();
    this.source = null;
    this.sheetRequest++;
    this.reviewRequest++;
    this.state.set({ phase: 'saving', chat: [...this.s.chat, { role: 'user', text, cites: [] }],
      review: INITIAL.review, sheet: INITIAL.sheet });
    try {
      unwrap(
        await agents.POST('/api/v1/agent/plans/{plan_id}/messages', {
          params: { path: { plan_id: planId } },
          body: { text },
        }),
      );
      if (!current()) return;
      // A follow-up can change the plan: the old review and sheet no longer describe it.
      this.sheetRequest++;
      this.reviewRequest++;
      this.state.set({ phase: 'running', steps: [], review: INITIAL.review, sheet: INITIAL.sheet });
      this.listen(`/api/v1/agent/plans/${planId}/events`, planId);
    } catch (e) {
      if (current()) this.state.set({ phase: 'error', error: message(e) });
    }
  }

  // ---- independent safety review ---------------------------------------------------------------------------

  /** Ask the Safety agent to review the finished plan independently, with the Intake report the Planner used. */
  async review(): Promise<void> {
    const planId = this.s.planId;
    if (!planId || this.s.phase !== 'done' || this.s.review.state === 'running' || !this.applicable()) return;
    const request = ++this.reviewRequest;
    this.sheetRequest++;
    const current = () => !this.disposed && request === this.reviewRequest && this.s.planId === planId;
    this.state.set({ review: { state: 'running', progress: 0, error: null, review: null }, sheet: INITIAL.sheet });
    try {
      const intakeReportId = this.s.intakeReportId;
      const accepted = unwrap(
        await agents.POST('/api/v1/safety/reviews', {
          body: {
            plan_id: planId,
            // The reviewer's own threshold (the contract default), not the Planner's target.
            target_margin_pct_wll: REVIEW_TARGET_PCT_WLL,
            ...(intakeReportId ? { intake_report_id: intakeReportId } : {}),
          },
        }),
      );
      if (!current()) return;
      const review = await awaitJob<SafetyReview>(AGENTS_BASE, accepted, (progress) => {
        if (current()) this.setReview({ progress });
      });
      if (!current()) return;
      if (review.plan_id !== planId) throw new Error('The service returned a review of a different plan.');
      this.setReview({ state: 'ready', progress: 1, review });
    } catch (e) {
      if (current()) this.setReview({ state: 'error', error: message(e) });
    }
  }

  private setReview(patch: Partial<ReviewState>): void {
    this.state.set({ review: { ...this.s.review, ...patch } });
  }

  // ---- safety sheet ----------------------------------------------------------------------------------------

  /** Build the sheet from the plan and the explicit review shown in the UI, never an implicit one. */
  async createSheet(): Promise<void> {
    const planId = this.s.planId;
    const review = this.s.review.review;
    if (!planId || !this.applicable()) return;
    if (!review || this.s.review.state !== 'ready' || review.plan_id !== planId) {
      this.setSheet({ state: 'error', error: 'Run the independent safety review before building the sheet.' });
      return;
    }
    const request = ++this.sheetRequest;
    this.setSheet({ state: 'creating', error: null });
    try {
      const created = unwrap(
        await agents.POST('/api/v1/safety-sheets', { body: { plan_id: planId, review_id: review.review_id } }),
      );
      if (!this.currentSheetRequest(request)) return;
      await this.loadSheet(created.sheet_id, request);
      if (!this.currentSheetRequest(request)) return;
      this.parent.openOverlay({ kind: 'sheet', id: created.sheet_id });
    } catch (e) {
      if (this.currentSheetRequest(request)) this.setSheet({ state: 'error', error: message(e) });
    }
  }

  private currentSheetRequest(request: number): boolean {
    return !this.disposed && request === this.sheetRequest;
  }

  private async loadSheet(sheetId: string, request: number): Promise<void> {
    const sheet = unwrap(await agents.GET('/api/v1/safety-sheets/{sheet_id}', { params: { path: { sheet_id: sheetId } } }));
    if (!this.currentSheetRequest(request)) return;
    const html = unwrap(
      await agents.GET('/api/v1/safety-sheets/{sheet_id}/render', {
        params: { path: { sheet_id: sheetId }, query: { format: 'html' } },
        parseAs: 'text',
      }),
    ) as unknown as string;
    if (!this.currentSheetRequest(request)) return;
    // A live canvas capture is not bound to this immutable plan/review. It may
    // already contain edited geometry or lines; do not attach it as sheet evidence.
    this.setSheet({ state: 'ready', error: null, sheet, html, image: null });
  }

  async approve(role: Role, name: string, decision: Approval['decision'], comment: string): Promise<void> {
    const sheet = this.s.sheet.sheet;
    if (!sheet || !this.applicable()) return;
    const request = ++this.sheetRequest;
    try {
      unwrap(
        await agents.POST('/api/v1/safety-sheets/{sheet_id}/approvals', {
          params: { path: { sheet_id: sheet.sheet_id } },
          body: { role, name, decision, comment: comment || null },
        }),
      );
      if (!this.currentSheetRequest(request)) return;
      await this.loadSheet(sheet.sheet_id, request);
    } catch (e) {
      if (this.currentSheetRequest(request)) this.setSheet({ error: message(e) });
    }
  }

  private setSheet(patch: Partial<AgentState['sheet']>): void {
    this.state.set({ sheet: { ...this.s.sheet, ...patch } });
  }
}

/** Fetch one stored result so its numbers can be inspected from anywhere an id is cited. */
export async function fetchResult(resultId: string): Promise<unknown> {
  return unwrap(await modeling.GET('/api/v1/results/{result_id}', { params: { path: { result_id: resultId } } }));
}
