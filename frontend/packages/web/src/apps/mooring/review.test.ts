import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SceneStore } from '../../scene/store';

vi.mock('./api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling',
  AGENTS_BASE: 'http://localhost/api/agents',
  modeling: { GET: vi.fn(), POST: vi.fn() },
  agents: { GET: vi.fn(), POST: vi.fn() },
  unwrap: <T,>(r: { data: T }) => r.data,
  awaitJob: vi.fn(),
  describeError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

import { agents, awaitJob } from './api';
import { MooringController } from './controller';
import type { SafetyReview } from './types';

const review = {
  review_id: 'rev-1',
  plan_id: 'p1',
  created_at_utc: '2026-11-05T12:00:00Z',
  verdict: 'ready_for_signature',
  status: 'AMBER',
  checks: [],
  thresholds: {},
  summary: 'Within limits on seed data.',
  backend: 'real',
} as unknown as SafetyReview;

let c: MooringController;

/** Put the agent session in the state it reaches after a finished plan bound to an Intake report. */
function finishedPlan(planId = 'p1', intakeReportId: string | null = 'intake-1') {
  c.agent.state.set({ phase: 'done', planId, intakeReportId, plan: { plan_id: planId } as never });
}

beforeEach(() => {
  vi.resetAllMocks();
  c = new MooringController({ store: new SceneStore() });
  vi.mocked(agents.POST).mockResolvedValue({ data: { job_id: 'j1', status_url: '/api/v1/jobs/j1' } } as never);
  vi.mocked(awaitJob).mockResolvedValue(review);
});
afterEach(() => {
  c.dispose();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it('reviews the finished plan with the Intake report the Planner used', async () => {
  finishedPlan();
  await c.agent.review();
  expect(agents.POST).toHaveBeenCalledWith('/api/v1/safety/reviews', {
    body: { plan_id: 'p1', target_margin_pct_wll: 80, intake_report_id: 'intake-1' },
  });
  expect(c.agent.state.get().review).toMatchObject({ state: 'ready', review });
});

it('omits the Intake report when the plan had none', async () => {
  finishedPlan('p1', null);
  await c.agent.review();
  expect(agents.POST).toHaveBeenCalledWith('/api/v1/safety/reviews', { body: { plan_id: 'p1', target_margin_pct_wll: 80 } });
});

it('does not review a plan that is still running', async () => {
  c.agent.state.set({ phase: 'running', planId: 'p1' });
  await c.agent.review();
  expect(agents.POST).not.toHaveBeenCalled();
});

it('rejects a review that belongs to another plan', async () => {
  finishedPlan();
  vi.mocked(awaitJob).mockResolvedValue({ ...review, plan_id: 'other' });
  await c.agent.review();
  expect(c.agent.state.get().review).toMatchObject({ state: 'error', review: null });
  expect(c.agent.state.get().review.error).toMatch(/different plan/);
});

it('refuses to build a sheet without an explicit review', async () => {
  finishedPlan();
  await c.agent.createSheet();
  expect(agents.POST).not.toHaveBeenCalledWith('/api/v1/safety-sheets', expect.anything());
  expect(c.agent.state.get().sheet).toMatchObject({ state: 'error', error: expect.stringMatching(/review/) });
});

it('builds the sheet from the reviewed plan and that review id', async () => {
  finishedPlan();
  await c.agent.review();
  vi.mocked(agents.POST).mockResolvedValue({ data: { sheet_id: 's1', version: 1 } } as never);
  vi.mocked(agents.GET).mockResolvedValue({ data: { sheet_id: 's1', plan_id: 'p1', review_id: 'rev-1' } } as never);
  await c.agent.createSheet();
  expect(agents.POST).toHaveBeenLastCalledWith('/api/v1/safety-sheets', { body: { plan_id: 'p1', review_id: 'rev-1' } });
  expect(c.agent.state.get().sheet.state).toBe('ready');
});

it('drops a late review after a new plan run starts', async () => {
  finishedPlan();
  let resolve!: (r: SafetyReview) => void;
  vi.mocked(awaitJob).mockReturnValue(new Promise((ok) => { resolve = ok; }));
  const pending = c.agent.review();
  await Promise.resolve();
  await Promise.resolve();
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} });
  vi.spyOn(c, 'ensureScenario').mockResolvedValue('s2');
  vi.mocked(agents.POST).mockResolvedValue({ data: { plan_id: 'p2', events_url: '/api/v1/agent/plans/p2/events' } } as never);
  await c.agent.run();
  resolve(review);
  await pending;
  expect(c.agent.state.get().review).toMatchObject({ state: 'idle', review: null });
  expect(c.agent.state.get().planId).toBe('p2');
});

it('clears the review and sheet when a follow-up question can change the plan', async () => {
  finishedPlan();
  await c.agent.review();
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} });
  vi.mocked(agents.POST).mockResolvedValue({ data: { accepted: true } } as never);
  await c.agent.ask('What if the wind backs NW?');
  expect(c.agent.state.get().review).toMatchObject({ state: 'idle', review: null });
});
