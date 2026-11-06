// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MotionController } from './controller';
import { adaptFrame } from './frames';
import type { SimFrame, SimScene } from './frames';
import { Badges, MotionView } from './MotionView';
import { catalog, controls, loading, prediction, workspace } from './workspace.test-fixtures';

vi.mock('../streams', () => ({ openJsonStream: () => ({ send: () => true, close: () => undefined }) }));
const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const raw = JSON.parse(readFileSync(path.join(dir, 'sim_frame.json'), 'utf8')) as SimFrame;
const scene = JSON.parse(readFileSync(path.join(dir, 'sim_scene.json'), 'utf8')) as SimScene;
afterEach(cleanup);

function controller() {
  const c = new MotionController({ faceBearingDeg: () => 90, tugIds: () => [], lineNumbers: () => [], layoutKey: () => 'test', ensureScenario: async () => null, initialState: () => null });
  c.state.set({ open: true, source: 'live', link: 'open', lifecycle: 'paused', workspace, catalog, scene, frame: adaptFrame({ ...raw, t_s: 0, controls, loading }, { faceBearingDeg: 90 }), forcingSynthetic: true, forcingRevision: 'demo-source-7', lifecycleReasons: ['TRAINING: Authored training configuration'] });
  return c;
}

describe('Motion demo information', () => {
  it('starts closed, identifies the synthetic source, and exposes full provenance on request', () => {
    const c = controller();
    render(<Badges frame={c.s.frame} state={c.s} />);
    const summary = screen.getByText('Demo information').closest('summary')!;
    const details = summary.parentElement as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(summary.textContent).toContain('simulation · synthetic forcing');
    expect(summary.textContent).toContain(`· ${c.s.frame!.badge.validity}`);
    expect(screen.getByText(/Development model, unqualified/).closest('details')).toBe(details);
    expect(screen.getByText('TRAINING: Authored training configuration').closest('details')).toBe(details);
    fireEvent.click(summary);
    expect(details.open).toBe(true);
    expect(within(details).getByText('forcing revision: demo-source-7')).toBeTruthy();
    expect(details.textContent).toContain(c.s.frame!.badge.provenanceSource);
    expect(details.textContent).toContain(c.s.frame!.environment!.wind.source);
    fireEvent.click(summary);
    expect(details.open).toBe(false);
  });

  it('opens for an invalid state and leaves its reasons exposed even if details are closed', () => {
    const c = controller();
    c.state.set({ lifecycleInvalid: true, lifecycleReasons: ['FORCING_UNCOVERED: forecast coverage ended'] });
    render(<Badges frame={null} state={c.s} />);
    const summary = screen.getByText('Demo information').closest('summary')!;
    expect((summary.parentElement as HTMLDetailsElement).open).toBe(true);
    fireEvent.click(summary);
    const reason = screen.getByText('FORCING_UNCOVERED: forecast coverage ended');
    expect(reason.closest('details')).toBeNull();
    expect(reason.closest('[role="alert"]')).toBeTruthy();
    expect(screen.getByText(/environment unavailable/).closest('details')).toBeNull();
  });

  it('keeps stale input and known contact alerts outside background details', () => {
    const c = controller();
    c.state.set({ lifecycleReasons: ['INPUT_STALE: wind sample is stale'], frame: { ...c.s.frame!, alerts: [{ code: 'PIER_CONTACT', severity: 'RED', message: 'Hull contact with supplied pier', elementIds: [] }] } });
    render(<Badges frame={c.s.frame} state={c.s} />);
    expect(screen.getByRole('alert').textContent).toBe('Hull contact with supplied pier');
    const warning = screen.getAllByText('INPUT_STALE: wind sample is stale').find((el) => !el.closest('details'))!;
    expect(warning.getAttribute('role')).toBe('status');
  });

  it('keeps unknown state validity and assumed map orientation outside collapsed details', () => {
    const c = controller();
    const frame = { ...c.s.frame!, badge: { ...c.s.frame!.badge, validity: 'unknown' as const }, assumedFaceBearing: true };
    render(<Badges frame={frame} state={c.s} />);
    expect(screen.getByText('State validity unavailable').closest('details')).toBeNull();
    expect(screen.getByText('Berth orientation assumed · no scene bearing supplied').closest('details')).toBeNull();
    expect((screen.getByText('Demo information').closest('details') as HTMLDetailsElement).open).toBe(false);
  });

  it('collapses forecast background while preserving truncation, contact and refresh warnings', () => {
    const c = controller();
    c.state.set({ prediction: { ...prediction, warnings: [{ code: 'PIER_CONTACT', severity: 'RED', message: 'Predicted hull reaches the pier', t_s: 5 }] } });
    render(<MotionView controller={c} workspace />);
    const coverage = screen.getByLabelText('Prediction coverage');
    const details = within(coverage).getByText('Forecast details').parentElement as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(within(coverage).getByText(/TRUNCATED prediction/).closest('details')).toBeNull();
    expect(within(coverage).getByRole('alert').textContent).toBe('Predicted hull reaches the pier');
    fireEvent.click(within(coverage).getByText('Forecast details'));
    expect(details.open).toBe(true);
    expect(details.textContent).toContain('Unchecked: coastline, traffic');
    expect(details.textContent).toContain('uncertainty unavailable');
    fireEvent.click(within(coverage).getByText('Forecast details'));
    act(() => c.state.set({ predictionError: 'Input snapshot expired' }));
    expect(within(coverage).getByText(/Refresh unavailable: Input snapshot expired/).closest('details')).toBeNull();
  });
});
