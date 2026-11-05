// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Store } from '../../../lib/store';
import type { AgentState } from '../agent';
import type { MooringState } from '../controller';
import type { AgentPlan, AgentSchemas, MooringLine } from '../types';
import { setUnitSystem } from '../units';
import { ControllerContext } from './context';
import { SequencePanel } from './SequencePanel';

afterEach(() => { cleanup(); setUnitSystem('navy'); });
const line: MooringLine = { line_number: 1, spec_id: 'fixture-line', parts: 3, ship_fitting_id: 'S1', pier_fitting_id: 'P1', paid_out_unstretched_length_ft: 100 };
const step: AgentSchemas['SequenceStep'] = { step: 1, line_number: 1, action: 'secure_pier', station: 'forecastle', crews: 2,
  trigger: 'When the pier crew is ready.', reference: 'Authored UI fixture', state_ok: true };
const basePlan: AgentPlan = { plan_id: 'plan-fixture', scenario_id: 'scenario-fixture', state: 'succeeded',
  config: { side_to: 'starboard', ship_x_ft: 10, lines: [line] }, sequence_result_id: 'sequence-result-fixture',
  sequence: { steps: [step], crews_required: 2, review_status: 'draft_unreviewed' } };
function setup(sequence: Partial<AgentSchemas['SequenceResult']> = {}, planChanges: Partial<AgentPlan> = {}, stateChanges: Partial<MooringState> = {}) {
  const plan = { ...basePlan, sequence: { ...basePlan.sequence!, ...sequence }, ...planChanges };
  const state = new Store({ side: 'starboard', shipXFt: 10, standoffOverrideFt: null, berth: null, lines: [line], tugAssignments: [],
    berthId: 'berth-fixture', shipClassId: 'ship-fixture', loading: 'full_load',
    scenarios: [{ scenario_id: 'scenario-fixture', berth_id: 'berth-fixture', ship_class_id: 'ship-fixture', loading: 'full_load' }],
    ...stateChanges } as MooringState);
  const agent = new Store({ plan, planId: 'plan-fixture', phase: 'done' } as AgentState);
  const select = vi.fn();
  const openOverlay = vi.fn();
  const view = render(<ControllerContext.Provider value={{ state, agent: { state: agent }, host: { store: { select } }, openOverlay } as never}>
    <SequencePanel />
  </ControllerContext.Provider>);
  return { state, agent, select, openOverlay, ...view };
}

it.each([null, undefined])('treats a %s static state as indeterminate, never passed', (state_ok) => {
  setup({ steps: [{ ...step, state_ok, state_max_pct: 0 }] });
  expect(screen.getByText('Feasibility indeterminate')).toBeTruthy();
  expect(screen.getByText('Static state not established')).toBeTruthy();
  expect(screen.queryByText('Static check passed')).toBeNull();
  expect(screen.queryByText(/Reported peak utilization/)).toBeNull();
  expect(screen.getByText('Draft · unreviewed')).toBeTruthy();
});

it('keeps false distinct from missing and shows the blocking issue and limitation', () => {
  setup({ steps: [{ ...step, state_ok: false, state_max_pct: 120, state_note: 'Line overload at this intermediate state.' }],
    issues: [{ code: 'STATE_FAILED', severity: 'RED', step: 1, line_number: 1, message: 'A restraint limit was exceeded.' }],
    limitations: ['No transient handling model.'] });
  expect(screen.getByText('Blocked by reported issues')).toBeTruthy();
  expect(screen.getByText('Static check failed')).toBeTruthy();
  expect(screen.getByText(/Reported peak utilization: 120%/)).toBeTruthy();
  expect(within(screen.getByRole('list', { name: 'Sequence issues' })).getByText(/RED · STATE_FAILED/)).toBeTruthy();
  expect(screen.getByText('No transient handling model.')).toBeTruthy();
});

it('does not call partial restraint feasible even if a legacy step says true', () => {
  setup({ issues: [{ code: 'PARTIAL_RESTRAINT', severity: 'AMBER', step: 1, message: 'Assistance has not been established.' }] });
  expect(screen.getByText('Feasibility indeterminate')).toBeTruthy();
  expect(screen.queryByText('Reported static checks passed')).toBeNull();
});

it('never infers feasibility from an empty sequence', () => {
  setup({ steps: [] });
  expect(screen.getByText('Feasibility indeterminate')).toBeTruthy();
});

it('shows review status separately from reported static checks and preserves source links', () => {
  const { select, openOverlay } = setup({ review_status: 'reviewed', steps: [{ ...step, duration_min: 0, depends_on: [0], tug_ids: ['tug-fixture'], state_max_pct: 0 }] });
  expect(screen.getByText('Procedure review recorded')).toBeTruthy();
  expect(screen.getByText('Reported static checks passed')).toBeTruthy();
  expect(screen.getByText('Authored UI fixture')).toBeTruthy();
  expect(screen.getByText(/Environment and forecast revision binding is not available/)).toBeTruthy();
  expect(screen.getByText(/Reported peak utilization: 0%/)).toBeTruthy();
  const button = screen.getByRole('button', { name: 'Select line 1 for step 1' });
  button.focus();
  expect(document.activeElement).toBe(button);
  fireEvent.click(button);
  expect(select).toHaveBeenCalledWith({ type: 'link', id: 'line-1' });
  fireEvent.click(screen.getByRole('button', { name: 'sequence-result-fixture' }));
  expect(openOverlay).toHaveBeenCalledWith({ kind: 'result', id: 'sequence-result-fixture' });
});

it.each([
  { shipXFt: 20 }, { side: 'port' }, { shipClassId: 'other' }, { berthId: 'other' }, { loading: 'light' },
  { standoffOverrideFt: 8 }, { scenarios: [] },
  { lines: [{ ...line, parts: 1 }] }, { lines: [{ ...line, paid_out_unstretched_length_ft: 99 }] },
  { lines: [{ ...line, pier_fitting_id: 'P2' }] },
] satisfies Partial<MooringState>[])('does not select a saved sequence against changed or unverified inputs %j', (patch) => {
  const { select } = setup({}, {}, patch);
  expect(screen.getByText(/Saved sequence is not bound to the current canvas/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Select line 1 for step 1' }));
  expect(select).not.toHaveBeenCalled();
});

it.each(['running', 'failed', 'cancelled'] as const)('withholds line selection for a %s plan', (state) => {
  setup({}, { state });
  expect((screen.getByRole('button', { name: 'Select line 1 for step 1' }) as HTMLButtonElement).disabled).toBe(true);
});

it('identifies an old result retained during a new plan request', () => {
  const { agent, select } = setup();
  act(() => agent.set({ planId: 'new-plan', phase: 'running' }));
  expect(screen.getByText(/Saved sequence is not bound to the current canvas/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Select line 1 for step 1' }));
  expect(select).not.toHaveBeenCalled();
});

it('invalidates canvas selection immediately when a line is edited after the result is displayed', () => {
  const { state, select } = setup();
  act(() => state.set({ lines: [{ ...line, paid_out_unstretched_length_ft: 75 }] }));
  expect(screen.getByText(/Saved sequence is not bound to the current canvas/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Select line 1 for step 1' }));
  expect(select).not.toHaveBeenCalled();
});

it('requires the continuous holding-tug assignments to match the saved plan', () => {
  const { select } = setup({}, { holding_tugs: [{ tug_id: 'tug-fixture', push_point_id: 'push-fixture', force_lbf: 1000, mode: 'push', direction_true_deg: 90 }] });
  expect(screen.getByText(/Saved sequence is not bound to the current canvas/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Select line 1 for step 1' }));
  expect(select).not.toHaveBeenCalled();
});

it('converts installation water level for metric display without changing source values', () => {
  setUnitSystem('metric');
  setup({}, { installed_at_water_level_mllw_ft: 10 });
  expect(screen.getByText(/Assessed installation water level: 3.0 m MLLW/)).toBeTruthy();
});
