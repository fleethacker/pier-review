import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SceneStore } from '../../../scene/store';

vi.mock('../api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling',
  AGENTS_BASE: 'http://localhost/api/agents',
  modeling: { GET: vi.fn(), POST: vi.fn() },
  agents: { GET: vi.fn(), POST: vi.fn() },
  unwrap: <T,>(r: { data: T }) => r.data,
  awaitJob: vi.fn(),
  describeError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

import { modeling } from '../api';
import { MooringController } from '../controller';
import { finalOutcome, type DockingDemoCase } from './cases';

const demo = {
  case_id: 'ddg-undetermined',
  name: 'DDG incomplete line plan — undetermined',
  expected_outcome: 'undetermined',
  explanation: 'Only one line is supplied.',
  environment_request: { name: 'env', kind: 'steady', wind_speed_kt: 4 },
  scenario_request: {
    name: 'sc',
    ship_class_id: 'DDG',
    berth_id: 'B',
    side_to: 'starboard',
    env_source: { mode: 'scenario', env_scenario_id: '<id returned by POST /env/scenarios>' },
    config: { side_to: 'starboard', ship_x_ft: 650, lines: [] },
  },
  analysis_request: { ship_class_id: 'DDG', berth_id: 'B' },
} as unknown as DockingDemoCase;

let c: MooringController;
beforeEach(() => {
  vi.resetAllMocks();
  c = new MooringController({ store: new SceneStore() });
  vi.mocked(modeling.GET).mockResolvedValue({ data: [demo] } as never);
  vi.mocked(modeling.POST).mockImplementation((async (path: string) => {
    if (path === '/api/v1/env/scenarios') return { data: { env_scenario_id: 'env-9' } };
    if (path === '/api/v1/scenarios') return { data: { scenario_id: 'sc-9' } };
    if (path === '/api/v1/mooring/analyze') {
      return {
        data: {
          result_id: 'res-1',
          status: 'RED',
          validity: { state: 'invalid', reasons: [{ code: 'underconstrained', message: 'No equilibrium.' }] },
        },
      };
    }
    throw new Error(`unexpected ${path}`);
  }) as never);
  vi.spyOn(c, 'loadScenario').mockImplementation(async (id: string) => {
    c.state.set({ scenarioId: id });
  });
});
afterEach(() => {
  c.dispose();
  vi.restoreAllMocks();
});

it('lists the named cases', async () => {
  await c.demo.list();
  expect(modeling.GET).toHaveBeenCalledWith('/api/v1/demo/docking-cases');
  expect(c.demo.state.get()).toMatchObject({ phase: 'ready', cases: [demo] });
});

it('saves the case unchanged except for its new environment id, selects it and records the initial outcome', async () => {
  await c.demo.list();
  await c.demo.load('ddg-undetermined');
  expect(modeling.POST).toHaveBeenCalledWith('/api/v1/env/scenarios', { body: demo.environment_request });
  expect(modeling.POST).toHaveBeenCalledWith('/api/v1/scenarios', {
    body: { ...demo.scenario_request, env_source: { mode: 'scenario', env_scenario_id: 'env-9' } },
  });
  expect(c.loadScenario).toHaveBeenCalledWith('sc-9');
  expect(modeling.POST).toHaveBeenCalledWith('/api/v1/mooring/analyze', { body: demo.analysis_request });
  expect(c.demo.state.get().active).toEqual({
    caseId: 'ddg-undetermined',
    scenarioId: 'sc-9',
    initial: { status: 'RED', validity: 'invalid', reasons: ['No equilibrium.'], resultId: 'res-1' },
    initialError: null,
  });
  expect(c.demo.state.get().loadingCaseId).toBeNull();
});

it('reports a case that could not be selected instead of claiming it is loaded', async () => {
  vi.mocked(c.loadScenario).mockResolvedValue(undefined);
  await c.demo.list();
  await c.demo.load('ddg-undetermined');
  expect(c.demo.state.get().active).toBeNull();
  expect(c.demo.state.get().error).toMatch(/could not be selected/);
});

it('keeps the case loaded but shows the analysis error when the initial outcome fails', async () => {
  const post = vi.mocked(modeling.POST).getMockImplementation()!;
  vi.mocked(modeling.POST).mockImplementation((async (path: string, init: unknown) => {
    if (path === '/api/v1/mooring/analyze') throw new Error('503 down');
    return post(path as never, init as never);
  }) as never);
  await c.demo.list();
  await c.demo.load('ddg-undetermined');
  expect(c.demo.state.get().active).toMatchObject({ scenarioId: 'sc-9', initial: null, initialError: '503 down' });
});

it('shows a final outcome only for a plan made on the loaded case', () => {
  const active = { caseId: 'x', scenarioId: 'sc-9', initial: null, initialError: null };
  expect(finalOutcome(active, { scenario_id: 'other', status: 'GREEN' }, null)).toBeNull();
  expect(finalOutcome(active, { scenario_id: 'sc-9', status: 'AMBER' }, null)).toEqual({ planStatus: 'AMBER', review: null });
  expect(finalOutcome(null, { scenario_id: 'sc-9', status: 'AMBER' }, null)).toBeNull();
});
