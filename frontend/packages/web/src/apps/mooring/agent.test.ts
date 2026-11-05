import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SceneStore } from '../../scene/store';

vi.mock('./api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling',
  AGENTS_BASE: 'http://localhost/api/agents',
  modeling: { GET: vi.fn(), POST: vi.fn() },
  agents: { GET: vi.fn(), POST: vi.fn() },
  unwrap: <T,>(r: { data: T }) => r.data,
  awaitJob: vi.fn(),
}));

import { MooringController } from './controller';
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
  vi.useFakeTimers();
  c = new MooringController({ store: new SceneStore() });
  c.state.set({ lines: [line(1)], tugAssignments: [] });
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
