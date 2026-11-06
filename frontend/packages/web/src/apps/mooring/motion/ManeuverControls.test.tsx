// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MotionController } from './controller';
import { MotionView } from './MotionView';
import { adaptFrame, type SimFrame } from './frames';
import { controls, neutral, prediction, workspace } from './workspace.test-fixtures';
import type { HelmOrder } from './workspace';

const raw = JSON.parse(readFileSync(path.resolve(__dirname, '../../../../../../../contract/examples/modeling/sim_frame.json'), 'utf8')) as SimFrame;
const guidance = { source: 'synthetic' as const, active: true, route_id: 'carrier-route', waypoint_index: 1, waypoint_name: 'Channel', target_speed_kt: 10, cross_track_ft: 0, remaining_ft: 10000, completed: false };
afterEach(cleanup);

function mounted() {
  const c = new MotionController({ faceBearingDeg: () => 90, tugIds: () => [], lineNumbers: () => [], layoutKey: () => 'test', ensureScenario: async () => null, initialState: () => null });
  const frame = adaptFrame({ ...raw, t_s: 0, controls, guidance }, { faceBearingDeg: 90 });
  c.state.set({ open: true, source: 'live', workspace: { ...workspace, scenario: { ...workspace.scenario, configuration: { ...workspace.scenario.configuration, route_follow: true } } }, frame, sessionId: 'carrier-session', link: 'open', lifecycle: 'paused' });
  render(<MotionView controller={c} workspace />);
  return c;
}
function report(c: MotionController, commanded: HelmOrder, actual: HelmOrder, active = true) {
  act(() => c.state.set({ frame: { ...c.s.frame!, controls: { ...controls, commanded, actual }, guidance: { ...guidance, active } } }));
}
const lever = (name = 'Port engine') => screen.getByRole('slider', { name }) as HTMLInputElement;
const ahead: HelmOrder = { ...neutral, port_throttle: 1, starboard_throttle: 1, rudder_deg: 5, bow_thruster: .1, stern_thruster: -.1 };

describe('Live automatic helm and separate manual edits', () => {
  it('follows automatic commands after mounting paused at neutral, with separate actual response', () => {
    const c = mounted(); const send = vi.spyOn(c, 'helmCommand');
    expect(lever().value).toBe('0');
    report(c, ahead, { ...neutral, port_throttle: .2, starboard_throttle: .2 });
    expect(screen.getByLabelText('Helm control mode').textContent).toBe('AUTO · Route following');
    for (const name of ['Port engine', 'Starboard engine']) {
      expect(lever(name).value).toBe('100');
      expect(screen.getByLabelText(`${name} commanded`).textContent).toBe('Cmd 100%');
      expect(screen.getByLabelText(`${name} actual`).textContent).toBe('Actual 20%');
    }
    expect(lever('Rudder').value).toBe('5');
    expect(lever('Bow thruster').value).toBe('10');
    expect(lever('Stern thruster').value).toBe('-10');
    expect(send).not.toHaveBeenCalled();
  });

  it('preserves an unsent edit while live values change; preview does not take control', () => {
    const c = mounted(); const send = vi.spyOn(c, 'helmCommand');
    const preview = vi.spyOn(c, 'refreshPrediction').mockResolvedValue();
    report(c, ahead, neutral);
    fireEvent.change(lever(), { target: { value: 40 } });
    report(c, { ...ahead, port_throttle: .8, rudder_deg: 7 }, { ...ahead, port_throttle: .6 });
    expect(lever().value).toBe('40');
    expect(lever('Rudder').value).toBe('5');
    expect(screen.getByLabelText('Port engine commanded').textContent).toBe('Cmd 80%');
    expect(screen.getByLabelText('Port engine actual').textContent).toBe('Actual 60%');
    expect(screen.getByText(/Manual draft not sent/)).toBeTruthy();
    expect(lever().getAttribute('aria-valuetext')).toContain('40 draft; 80 percent commanded; 60 actual');
    fireEvent.click(screen.getByRole('button', { name: 'Preview order' }));
    expect(preview).toHaveBeenCalledWith({ ...ahead, port_throttle: .4 });
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Helm control mode').textContent).toContain('AUTO');
  });

  it('discards edits without a command and resumes following the latest automatic order', () => {
    const c = mounted(); const send = vi.spyOn(c, 'helmCommand');
    fireEvent.change(lever(), { target: { value: 40 } });
    report(c, ahead, ahead);
    act(() => c.state.set({ prediction, predictionWhatIf: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Discard edit' }));
    expect(lever().value).toBe('100');
    expect(screen.queryByText(/Manual draft not sent/)).toBeNull();
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByText(/What-if order preview/)).toBeTruthy();
    report(c, { ...ahead, port_throttle: .7 }, ahead);
    expect(lever().value).toBe('70');
  });

  it('retains failed sends and never announces manual takeover before backend confirmation', () => {
    const c = mounted(); const send = vi.spyOn(c, 'helmCommand').mockReturnValue(false);
    fireEvent.change(lever(), { target: { value: 40 } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply helm order' }));
    expect(send).toHaveBeenLastCalledWith({ ...neutral, port_throttle: .4 });
    expect(lever().value).toBe('40');
    expect(screen.getByText(/Manual draft not sent/)).toBeTruthy();
    send.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Apply helm order' }));
    expect(screen.queryByRole('button', { name: 'Discard edit' })).toBeNull();
    expect(screen.getByLabelText('Helm control mode').textContent).toContain('AUTO');
    expect(screen.getByLabelText('Port engine commanded').textContent).toBe('Cmd 0%');
    // A new edit must survive acknowledgement of an older sent order.
    fireEvent.change(lever(), { target: { value: 60 } });
    report(c, { ...neutral, port_throttle: .4 }, { ...neutral, port_throttle: .1 }, false);
    act(() => c.state.set({ command: { status: 'applied', message: 'Previous order acknowledged' } }));
    expect(screen.getByLabelText('Helm control mode').textContent).toBe('MANUAL');
    expect(lever().value).toBe('60');
    expect(screen.getByLabelText('Port engine commanded').textContent).toBe('Cmd 40%');
    expect(screen.getByLabelText('Port engine actual').textContent).toBe('Actual 10%');
  });

  it('orders neutral without claiming actual actuators have instantly stopped', () => {
    const c = mounted(); const send = vi.spyOn(c, 'helmCommand').mockReturnValue(true);
    report(c, ahead, ahead);
    fireEvent.change(lever(), { target: { value: 40 } });
    fireEvent.click(screen.getByRole('button', { name: 'Order neutral' }));
    expect(send).toHaveBeenCalledWith(neutral);
    report(c, neutral, { ...ahead, port_throttle: .8 }, false);
    expect(lever().value).toBe('0');
    expect(screen.getByLabelText('Port engine actual').textContent).toBe('Actual 80%');
    expect(screen.queryByRole('button', { name: 'Discard edit' })).toBeNull();
  });

  it('clears edits on a new run and follows the reset automatic controller', () => {
    const c = mounted(); report(c, ahead, ahead, false);
    fireEvent.change(lever(), { target: { value: 40 } });
    act(() => c.state.set({ frame: { ...c.s.frame!, runId: 'reset-run', controls, guidance } }));
    expect(lever().value).toBe('0');
    expect(screen.queryByRole('button', { name: 'Discard edit' })).toBeNull();
    report(c, ahead, neutral);
    expect(lever().value).toBe('100');
    expect(screen.getByLabelText('Helm control mode').textContent).toContain('AUTO');
  });

  it('shows holding and treats missing automatic-mode evidence as unknown', () => {
    const c = mounted();
    act(() => c.state.set({ frame: { ...c.s.frame!, guidance: { ...guidance, completed: true } } }));
    expect(screen.getByLabelText('Helm control mode').textContent).toBe('AUTO · Holding position');
    act(() => c.state.set({ frame: { ...c.s.frame!, guidance: null } }));
    expect(screen.getByLabelText('Helm control mode').textContent).toBe('Control mode unknown');
  });
});
