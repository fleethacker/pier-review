import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

import { MooringController } from './controller';
import { agents } from './api';
import type { AgentPlan, MooringLine, TugAssignment } from './types';

const line = (n: number): MooringLine => ({
  line_number: n,
  spec_id: 'S',
  parts: 1,
  ship_fitting_id: `B${n}`,
  pier_fitting_id: `P${n}`,
});
const tug: TugAssignment = { tug_id: 'T1', push_point_id: 'PP', mode: 'push', force_lbf: 100, direction_true_deg: 195 };
const plan = {
  plan_id: 'p1',
  scenario_id: 's1',
  state: 'succeeded',
  status: 'GREEN',
  config: { side_to: 'starboard', ship_x_ft: 650, lines: [line(7), line(8)] },
  tug_plan: { assignments: [{ ...tug, tug_id: 'BERTHING_ONLY' }] },
  holding_tugs: [tug],
} as unknown as AgentPlan;

let c: MooringController;
beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  c = new MooringController({ store: new SceneStore() });
  c.state.set({ lines: [line(1)], tugAssignments: [] });
});

afterEach(() => {
  c.dispose();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it('does not apply a plan computed before an environment edit', async () => {
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} });
  vi.spyOn(c, 'ensureScenario').mockResolvedValue('s1');
  vi.mocked(agents.POST).mockResolvedValue({ data: { plan_id: 'p1', events_url: '/api/v1/agent/plans/p1/events' } } as never);
  await c.agent.run();
  c.state.set({ env: { wind_gust_kt: 64 } as never });
  c.agent.applyPlan(plan);
  expect(c.state.get().lines.map((l) => l.line_number)).toEqual([1]);
  expect(c.agent.state.get().error).toMatch(/environment changed/);
});

describe('applying and undoing an agent plan', () => {
  it('puts the agent lines and tugs on the canvas and remembers what was there', () => {
    c.agent.applyPlan(plan);
    expect(c.state.get().lines.map((l) => l.line_number)).toEqual([7, 8]);
    expect(c.state.get().tugAssignments).toEqual([tug]);
    expect(c.agent.state.get().undo?.lines.map((l) => l.line_number)).toEqual([1]);
  });

  it('keeps the original undo point when a second plan is applied', () => {
    c.agent.applyPlan(plan);
    c.agent.applyPlan({ ...plan, config: { ...plan.config!, lines: [line(9)] } });
    c.agent.undo();
    expect(c.state.get().lines.map((l) => l.line_number)).toEqual([1]);
    expect(c.state.get().tugAssignments).toEqual([]);
    expect(c.agent.state.get().undo).toBeNull();
  });

  it('honors an explicit empty holding fleet even when berthing tugs were planned', () => {
    c.state.set({ tugAssignments: [tug] });
    c.agent.applyPlan({ ...plan, holding_tugs: [] });
    expect(c.state.get().tugAssignments).toEqual([]);
    c.agent.undo();
    expect(c.state.get().tugAssignments).toEqual([tug]);
  });

  it('does nothing for a plan without a config', () => {
    c.agent.applyPlan({ ...plan, config: null });
    expect(c.state.get().lines.map((l) => l.line_number)).toEqual([1]);
    expect(c.agent.state.get().undo).toBeNull();
  });
});


describe('safety sheet image provenance', () => {
  it('does not attach the current edited map to an immutable plan sheet', async () => {
    // A sheet is only built from an explicit independent review of this plan.
    c.agent.state.set({ planId: plan.plan_id, plan, phase: 'done',
      review: { state: 'ready', progress: 1, error: null, review: { review_id: 'rev-1', plan_id: plan.plan_id } as never } });
    c.state.set({ lines: [line(99)], shipXFt: 900 });
    const capture = vi.fn(() => 'data:image/jpeg;base64,unreviewed-map');
    c.host.store.capture = capture;
    vi.mocked(agents.POST).mockResolvedValueOnce({ data: { sheet_id: 'sheet-1' } } as never);
    vi.mocked(agents.GET)
      .mockResolvedValueOnce({ data: { sheet_id: 'sheet-1', plan_id: plan.plan_id } } as never)
      .mockResolvedValueOnce({ data: '<html>Immutable reviewed sheet</html>' } as never);
    await c.agent.createSheet();
    expect(c.agent.state.get().sheet.state).toBe('ready');
    expect(c.agent.state.get().sheet.image).toBeNull();
    expect(capture).not.toHaveBeenCalled();
    expect(c.agent.state.get().sheet.html).toContain('Immutable reviewed sheet');
  });

  it('does not reuse an unbound image after loading an approval', async () => {
    c.agent.state.set({ sheet: { state: 'ready', error: null, html: 'old',
      image: 'data:image/jpeg;base64,unbound-map',
      sheet: { sheet_id: 'sheet-1' } as never } });
    vi.mocked(agents.POST).mockResolvedValueOnce({ data: {} } as never);
    vi.mocked(agents.GET)
      .mockResolvedValueOnce({ data: { sheet_id: 'sheet-1', approvals: [{ decision: 'approve' }] } } as never)
      .mockResolvedValueOnce({ data: '<html>Approved sheet</html>' } as never);
    await c.agent.approve('pilot', 'Test', 'approve', '');
    expect(c.agent.state.get().sheet.state).toBe('ready');
    expect(c.agent.state.get().sheet.image).toBeNull();
    expect(c.agent.state.get().sheet.html).toContain('Approved sheet');
  });
});


it('does not reopen an old sheet when a new planning run starts during its fetch', async () => {
  c.agent.state.set({ planId: plan.plan_id, plan });
  let release!: (value: unknown) => void;
  const pending = new Promise((resolve) => { release = resolve; });
  vi.mocked(agents.POST).mockResolvedValueOnce({ data: { sheet_id: 'old-sheet' } } as never);
  vi.mocked(agents.GET)
    .mockReturnValueOnce(pending as never)
    .mockResolvedValueOnce({ data: '<html>Old sheet</html>' } as never);
  const creating = c.agent.createSheet();
  await Promise.resolve();
  vi.spyOn(c, 'saveScenario').mockResolvedValueOnce(null);
  await c.agent.run();
  release({ data: { sheet_id: 'old-sheet', plan_id: plan.plan_id } });
  await creating;
  expect(c.agent.state.get().sheet.state).toBe('idle');
  expect(c.agent.state.get().sheet.sheet).toBeNull();
  expect(c.state.get().overlay).toBeNull();
});


it.each(['resolve', 'reject'])('ignores a late approval %s after a new planning run', async (outcome) => {
  c.agent.state.set({ planId: plan.plan_id, sheet: { state: 'ready', error: null, html: 'old', image: null,
    sheet: { sheet_id: 'old-sheet' } as never } });
  let resolve!: (value: unknown) => void;
  let reject!: (reason: Error) => void;
  const pending = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  vi.mocked(agents.POST).mockReturnValueOnce(pending as never);
  const approving = c.agent.approve('pilot', 'Test', 'approve', '');
  vi.spyOn(c, 'saveScenario').mockResolvedValueOnce(null);
  await c.agent.run();
  if (outcome === 'resolve') resolve({ data: {} });
  else reject(new Error('Old approval request failed'));
  await approving;
  expect(agents.GET).not.toHaveBeenCalled();
  expect(c.agent.state.get().sheet).toEqual({ state: 'idle', error: null, sheet: null, html: null, image: null });
});
