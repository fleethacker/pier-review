import { Store } from '../../../lib/store';
import { agents, AGENTS_BASE, awaitJob, describeError, unwrap } from '../api';
import type { MooringController } from '../controller';
import type { IntakeReport } from './logic';

interface IntakeState {
  phase: 'idle' | 'running' | 'done' | 'error';
  progress: number;
  error: string | null;
  report: IntakeReport | null;
}

const INITIAL: IntakeState = { phase: 'idle', progress: 0, error: null, report: null };

/** Keeps the displayed assessment and Planner bound to the same immutable scenario. */
export class IntakeSession {
  readonly state = new Store<IntakeState>(INITIAL);
  private abort: AbortController | null = null;
  private context: string | null = null;
  private unsubscribe: () => void;

  constructor(private readonly parent: MooringController) {
    this.unsubscribe = parent.state.subscribe(() => {
      if (this.context !== null && this.context !== parent.planningKey()) this.clear();
    });
  }

  private clear(): void {
    this.abort?.abort();
    this.abort = null;
    this.context = null;
    this.state.set(INITIAL);
  }

  dispose(): void {
    this.unsubscribe();
    this.clear();
  }

  reportId(): string | null {
    return this.context === this.parent.planningKey() ? this.state.get().report?.report_id ?? null : null;
  }

  async run(): Promise<void> {
    this.clear();
    const request = new AbortController();
    this.abort = request;
    this.context = this.parent.planningKey();
    const current = () => this.abort === request && !request.signal.aborted && this.context === this.parent.planningKey();
    this.state.set({ phase: 'running' });
    try {
      const scenarioId = await this.parent.ensureScenario('Environment intake');
      if (!current()) return;
      if (!scenarioId) throw new Error('Choose a ship, berth and environment first.');
      const forecast = this.parent.forecastSelection;
      const horizon = forecast ? (Date.parse(forecast.to_utc) - Date.parse(forecast.from_utc)) / 3_600_000 : 24;
      const accepted = unwrap(await agents.POST('/api/v1/intake/reports', {
        body: { scenario_id: scenarioId, horizon_hours: horizon, ...(forecast ? { forecast_request: forecast } : {}) },
        signal: request.signal,
      }));
      if (!current()) return;
      const report = await awaitJob<IntakeReport>(AGENTS_BASE, accepted,
        (progress) => { if (current()) this.state.set({ progress }); }, request.signal);
      if (current()) this.state.set({ phase: 'done', report });
    } catch (e) {
      if (current()) this.state.set({ phase: 'error', error: describeError(e) });
    }
  }
}
