// @vitest-environment jsdom
import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControllerContext } from './context';
import { ExerciseController } from './controller';
import { RedTeamPanel } from './RedTeam';
import { PRESET_SCENARIOS } from './scenarios';

configure({ asyncUtilTimeout: 20_000 });
vi.setConfig({ testTimeout: 60_000 });

const salvo = () => PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!;
function open(runs = 12) {
  const c = new ExerciseController(undefined, salvo());
  c.setRedTeam({ ...c.redTeamSpec(), runs, sweep: undefined });
  c.toggleRedTeam(true);
  const utils = render(
    <ControllerContext.Provider value={c}>
      <RedTeamPanel />
    </ControllerContext.Provider>,
  );
  return { c, ...utils };
}
const dialog = () => within(screen.getByRole('dialog', { name: 'Red team' }));
const commit = (label: string, value: string) => {
  const el = dialog().getAllByLabelText(label).at(-1)!;
  fireEvent.change(el, { target: { value } });
  fireEvent.blur(el);
};
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('red-team panel: combined outcomes and precision', () => {
  it('builds an "all of" outcome from earlier ones and a time limit', () => {
    const { c } = open();
    const outcomes = () => c.state.get().scenario.redTeam!.outcomes;
    fireEvent.click(dialog().getByRole('button', { name: '+ Add outcome' }));
    fireEvent.change(dialog().getAllByLabelText('Measure how often').at(-1)!, { target: { value: 'all' } });
    const added = outcomes().at(-1)!;
    expect(added).toMatchObject({ type: 'all' });
    const boxes = within(dialog().getByRole('group', { name: /Outcomes to combine/ })).getAllByRole('checkbox');
    expect(boxes.length).toBeGreaterThan(2);
    expect((added as { of: string[] }).of).toHaveLength(2);
    fireEvent.click(boxes[2]);
    expect((outcomes().at(-1) as { of: string[] }).of).toHaveLength(3);
    commit('Only if by this time (s)', '600');
    expect(outcomes().at(-1)).toMatchObject({ beforeS: 600 });
    commit('Only if by this time (s)', '');
    expect(outcomes().at(-1)!.beforeS).toBeUndefined();
    expect(c.redTeamProblems()).toEqual([]);
  });

  it('builds a "not" outcome and keeps the time limit when the type changes', () => {
    const { c } = open();
    fireEvent.click(dialog().getByRole('button', { name: '+ Add outcome' }));
    const last = () => c.state.get().scenario.redTeam!.outcomes.at(-1)!;
    commit('Only if by this time (s)', '900');
    fireEvent.change(dialog().getAllByLabelText('Measure how often').at(-1)!, { target: { value: 'not' } });
    expect(last()).toMatchObject({ type: 'not', beforeS: 900 });
    fireEvent.change(dialog().getByLabelText('The outcome that does not happen'), { target: { value: c.state.get().scenario.redTeam!.outcomes[1].id } });
    expect(last()).toMatchObject({ type: 'not', of: c.state.get().scenario.redTeam!.outcomes[1].id });
    expect(c.redTeamProblems()).toEqual([]);
  });

  it('turns on stopping early and sets the precision in points', () => {
    const { c } = open();
    expect(dialog().queryByLabelText('Sure to within ± (points)')).toBeNull();
    fireEvent.click(dialog().getByRole('checkbox', { name: 'Stop early when sure enough' }));
    expect(c.state.get().scenario.redTeam!.targetHalfWidth).toBe(0.02);
    commit('Sure to within ± (points)', '5');
    expect(c.state.get().scenario.redTeam!.targetHalfWidth).toBeCloseTo(0.05, 10);
    fireEvent.click(dialog().getByRole('checkbox', { name: 'Stop early when sure enough' }));
    expect(c.state.get().scenario.redTeam!.targetHalfWidth).toBeUndefined();
  });
});

describe('red-team panel: results, baseline and export', () => {
  async function ran(runs = 12) {
    const u = open(runs);
    fireEvent.click(dialog().getByRole('button', { name: /^Run / }));
    await waitFor(() => expect(u.c.state.get().mc.status).toBe('done'));
    return u;
  }

  it('shows how sure each number is, and how the chance settled', async () => {
    const { c } = await ran(48);
    const stats = c.state.get().mc.result!.groups[0].outcomes[0];
    expect(dialog().getAllByText(new RegExp(`±${(stats.halfWidth * 100).toFixed(1)}`)).length).toBeGreaterThan(0);
    expect(dialog().getByText('How sure the number is')).toBeTruthy();
    expect(dialog().getByRole('img', { name: /The chance settling at/ })).toBeTruthy();
  });

  it('says so when the batch stopped because it was sure enough', async () => {
    const u = open(400);
    act(() => u.c.setRedTeam({ ...u.c.redTeamSpec(), targetHalfWidth: 0.4 }));
    fireEvent.click(dialog().getByRole('button', { name: /^Run / }));
    await waitFor(() => expect(u.c.state.get().mc.status).toBe('done'));
    expect(u.c.state.get().mc.result!.converged).toBe(true);
    expect(dialog().getByText(/stopped once every chance was pinned down/)).toBeTruthy();
  });

  it('keeps a baseline, then shows the change against it on the next batch', async () => {
    const { c } = await ran(60);
    fireEvent.click(dialog().getByRole('button', { name: 'Keep as baseline' }));
    expect(c.state.get().baseline).not.toBeNull();
    expect(dialog().getByText(/This batch is the baseline/)).toBeTruthy();
    // Take the carrier's defences away and run again.
    act(() => c.state.get().scenario.units.forEach((u) => c.patchUnit(u.id, { magazine: 0 })));
    fireEvent.click(dialog().getByRole('button', { name: /^Run again/ }));
    await waitFor(() => expect(c.state.get().mc.result).not.toBe(c.state.get().baseline!.result));
    await waitFor(() => expect(c.state.get().mc.status).toBe('done'));
    expect(dialog().getByText(/Comparing with the baseline/)).toBeTruthy();
    expect(dialog().getAllByText(/pts/).length).toBeGreaterThan(0);
    fireEvent.click(dialog().getByRole('button', { name: 'Clear' }));
    expect(c.state.get().baseline).toBeNull();
  });

  it('downloads CSV and JSON files named for the scenario', async () => {
    const urls: Blob[] = [];
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => (urls.push(b), 'blob:x'), revokeObjectURL: () => undefined }));
    const clicks: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.download);
    });
    await ran(10);
    fireEvent.click(dialog().getByRole('button', { name: 'Download CSV' }));
    fireEvent.click(dialog().getByRole('button', { name: 'Download JSON' }));
    expect(clicks[0]).toMatch(/^red-team-.+\.csv$/);
    expect(clicks[1]).toMatch(/^red-team-.+\.json$/);
    const read = (b: Blob) =>
      new Promise<string>((resolve) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result));
        r.readAsText(b);
      });
    expect(await read(urls[0])).toContain('group,outcome,runs_with_outcome');
    expect(JSON.parse(await read(urls[1])).result.totalRuns).toBe(10);
  });

  it('opens the report in a new window, and says when the browser blocks it', async () => {
    await ran(10);
    const doc = { open: vi.fn(), write: vi.fn(), close: vi.fn() };
    vi.spyOn(window, 'open').mockReturnValueOnce({ document: doc } as unknown as Window);
    fireEvent.click(dialog().getByRole('button', { name: 'Report to print' }));
    expect(doc.write.mock.calls[0][0]).toContain('Red team report');
    vi.spyOn(window, 'open').mockReturnValueOnce(null);
    fireEvent.click(dialog().getByRole('button', { name: 'Report to print' }));
    expect(screen.getByRole('alert').textContent).toContain('blocked the report window');
  });
});
