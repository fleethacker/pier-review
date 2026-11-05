import { Store } from '../../lib/store';
import { agents, AGENTS_BASE, modeling, unwrap, describeError } from './api';
import type { MooringController } from './controller';
import type {
  AgentPlan,
  AgentSchemas,
  Approval,
  MooringConfig,
  MooringLine,
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

export interface AgentState {
  phase: 'idle' | 'saving' | 'running' | 'done' | 'error';
  error: string | null;
  planId: string | null;
  objective: Objective;
  targetMarginPct: number;
  steps: AgentStep[];
  proposal: { config: MooringConfig; status: 'GREEN' | 'AMBER' | 'RED' } | null;
  plan: AgentPlan | null;
  chat: ChatItem[];
  undo: { lines: MooringLine[]; tugs: TugAssignment[] } | null;
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
  objective: 'moor_for_forecast',
  targetMarginPct: 70,
  steps: [],
  proposal: null,
  plan: null,
  chat: [],
  undo: null,
  sheet: { state: 'idle', error: null, sheet: null, html: null, image: null },
};

const message = describeError;

/** The planning agent and safety sheet flow. Reads and writes the mooring plan through the controller. */
export class AgentSession {
  readonly state = new Store<AgentState>(INITIAL);
  private source: EventSource | null = null;
  private disposed = false;
  private context: string | null = null;
  private sheetRequest = 0;

  constructor(private readonly parent: MooringController) {}

  private get s(): AgentState {
    return this.state.get();
  }

  dispose(): void {
    this.disposed = true;
    this.sheetRequest++;
    this.source?.close();
  }

  setObjective(objective: Objective): void {
    this.state.set({ objective });
  }

  setTarget(targetMarginPct: number): void {
    this.state.set({ targetMarginPct });
  }

  async run(): Promise<void> {
    if (this.s.phase === 'running' || this.s.phase === 'saving') return;
    this.sheetRequest++;
    this.source?.close();
    this.context = this.parent.contextKey();
    this.state.set({
      undo: null,
      phase: 'saving',
      error: null,
      steps: [],
      proposal: null,
      plan: null,
      chat: [],
      planId: null,
      sheet: INITIAL.sheet,
    });
    try {
      const scenarioId = await this.parent.saveScenario(`Agent run ${new Date().toISOString().slice(11, 19)}Z`);
      if (!scenarioId) throw new Error('Choose a ship and berth first.');
      const accepted = unwrap(
        await agents.POST('/api/v1/agent/plans', {
          body: {
            scenario_id: scenarioId,
            objective: this.s.objective,
            target_margin_pct_wll: this.s.targetMarginPct,
            max_iterations: 8,
          },
        }),
      );
      this.state.set({ phase: 'running', planId: accepted.plan_id });
      this.listen(accepted.events_url, accepted.plan_id);
    } catch (e) {
      this.state.set({ phase: 'error', error: message(e) });
    }
  }

  private listen(eventsUrl: string, planId: string): void {
    this.source?.close();
    const source = new EventSource(`${AGENTS_BASE}${eventsUrl}`);
    this.source = source;
    const parse = <T,>(ev: Event): T => JSON.parse((ev as MessageEvent).data) as T;

    source.addEventListener('step', (ev) => {
      const d = parse<{ iteration: number; thought_summary: string; tool: string; result_id: string | null }>(ev);
      this.state.set({
        steps: [...this.s.steps, { iteration: d.iteration, tool: d.tool, summary: d.thought_summary, resultId: d.result_id }],
      });
    });
    source.addEventListener('proposal', (ev) => {
      this.state.set({ proposal: parse<NonNullable<AgentState['proposal']>>(ev) });
    });
    source.addEventListener('message', (ev) => {
      const d = parse<{ text: string; cites: string[] }>(ev);
      this.state.set({ chat: [...this.s.chat, { role: 'agent', text: d.text, cites: d.cites }] });
    });
    source.addEventListener('done', () => {
      source.close();
      void this.finish(planId);
    });
    source.onerror = () => {
      // EventSource retries by itself; only give up if the stream never produced anything.
      if (source.readyState === EventSource.CLOSED && this.s.phase === 'running') {
        this.state.set({ phase: 'error', error: 'The agent event stream closed unexpectedly.' });
      }
    };
  }

  private async finish(planId: string): Promise<void> {
    try {
      const plan = unwrap(await agents.GET('/api/v1/agent/plans/{plan_id}', { params: { path: { plan_id: planId } } }));
      if (this.disposed) return;
      this.state.set({ phase: 'done', plan });
      this.applyPlan(plan);
    } catch (e) {
      this.state.set({ phase: 'error', error: message(e) });
    }
  }

  /** Put the agent's lines and tugs on the canvas, keeping what was there so it can be undone. */
  applyPlan(plan: AgentPlan | null = this.s.plan): void {
    if (!plan?.config || !this.applicable()) return;
    const { lines, tugAssignments } = this.parent.state.get();
    if (!this.s.undo) this.state.set({ undo: { lines, tugs: tugAssignments } });
    this.parent.setTugAssignments(plan.holding_tugs ?? []);
    this.parent.replaceLines(plan.config.lines.map((l) => ({ ...l })));
  }

  private applicable(): boolean {
    if (this.context !== null && this.context !== this.parent.contextKey()) {
      this.state.set({ error: 'Ship, berth or geometry changed. Run a new plan before applying or undoing it.' });
      return false;
    }
    return true;
  }

  previewProposal(): void {
    const p = this.s.proposal;
    if (!p || !this.applicable()) return;
    const { lines, tugAssignments } = this.parent.state.get();
    if (!this.s.undo) this.state.set({ undo: { lines, tugs: tugAssignments } });
    this.parent.replaceLines(p.config.lines.map((l) => ({ ...l })));
  }

  undo(): void {
    const u = this.s.undo;
    if (!u || !this.applicable()) return;
    this.parent.setTugAssignments(u.tugs);
    this.parent.replaceLines(u.lines);
    this.state.set({ undo: null });
  }

  async ask(text: string): Promise<void> {
    const planId = this.s.planId;
    if (!planId || !text.trim()) return;
    this.state.set({ chat: [...this.s.chat, { role: 'user', text, cites: [] }] });
    try {
      unwrap(
        await agents.POST('/api/v1/agent/plans/{plan_id}/messages', {
          params: { path: { plan_id: planId } },
          body: { text },
        }),
      );
      this.state.set({ phase: 'running', steps: [] });
      this.listen(`/api/v1/agent/plans/${planId}/events`, planId);
    } catch (e) {
      this.state.set({ error: message(e) });
    }
  }

  // ---- safety sheet ----------------------------------------------------------------------------------------

  async createSheet(): Promise<void> {
    const planId = this.s.planId;
    if (!planId) return;
    const request = ++this.sheetRequest;
    this.setSheet({ state: 'creating', error: null });
    try {
      const created = unwrap(await agents.POST('/api/v1/safety-sheets', { body: { plan_id: planId } }));
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
    if (!sheet) return;
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
