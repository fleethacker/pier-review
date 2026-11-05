// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControllerContext } from './context';
import { LinesPanel } from './LinesPanel';

afterEach(cleanup);

function setup(lines = [
  { line_number: 1, role: 'bow', spec_id: 'NYLON', parts: 1, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P-1' },
  { line_number: 2, role: 'stern', spec_id: 'NYLON', parts: 3, ship_fitting_id: 'BITT-6S', pier_fitting_id: 'P-2' },
]) {
  const c = { setAllParts: vi.fn(), updateLine: vi.fn(), setNewLineSpec: vi.fn(), startAddLine: vi.fn(), cancelAddLine: vi.fn(), removeLine: vi.fn(), host: { store: { select: vi.fn() } } };
  const state = {
    ship: { fittings: [{}] }, lines, lineSpecs: [{ spec_id: 'NYLON' }], analysis: { response: null },
    addLine: { active: false, shipFittingId: null, specId: 'NYLON', parts: 1 }, recommend: { state: 'idle' },
  };
  render(
    <ControllerContext.Provider value={{ ...c, state: { use: (sel: (s: typeof state) => unknown) => sel(state) } } as never}>
      <LinesPanel />
    </ControllerContext.Provider>,
  );
  return c;
}

describe('LinesPanel doubling up', () => {
  it('shows each line as single, tanker or doubled, with the current choice pressed', () => {
    setup();
    const one = screen.getByRole('group', { name: 'Line 1: single or doubled up' });
    const two = screen.getByRole('group', { name: 'Line 2: single or doubled up' });
    expect(one.querySelector('[aria-pressed="true"]')?.textContent).toBe('Single');
    expect(two.querySelector('[aria-pressed="true"]')?.textContent).toBe('Doubled');
  });

  it('doubles up one line without touching the others', () => {
    const c = setup();
    const one = screen.getByRole('group', { name: 'Line 1: single or doubled up' });
    fireEvent.click(one.querySelectorAll('button')[2]);
    expect(c.updateLine).toHaveBeenCalledWith(1, { parts: 3 });
    expect(c.setAllParts).not.toHaveBeenCalled();
  });

  it('singles up one line', () => {
    const c = setup();
    const two = screen.getByRole('group', { name: 'Line 2: single or doubled up' });
    fireEvent.click(two.querySelectorAll('button')[0]);
    expect(c.updateLine).toHaveBeenCalledWith(2, { parts: 1 });
  });

  it('doubles up or singles up every line at once', () => {
    const c = setup();
    fireEvent.click(screen.getByRole('button', { name: 'Double up all' }));
    expect(c.setAllParts).toHaveBeenLastCalledWith(3);
    fireEvent.click(screen.getByRole('button', { name: 'Single up all' }));
    expect(c.setAllParts).toHaveBeenLastCalledWith(1);
  });

  it('lets a new line start single or doubled', () => {
    const c = setup();
    const group = screen.getByRole('group', { name: 'New line: single or doubled up' });
    fireEvent.click(group.querySelectorAll('button')[2]);
    expect(c.setNewLineSpec).toHaveBeenCalledWith('NYLON', 3);
  });
});
