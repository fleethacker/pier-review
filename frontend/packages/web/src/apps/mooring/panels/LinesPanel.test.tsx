// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControllerContext } from './context';
import { LinesPanel } from './LinesPanel';

afterEach(cleanup);

function setup(lines = [
  { line_number: 1, role: 'bow', spec_id: 'NYLON', parts: 1, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P-1' },
  { line_number: 2, role: 'stern', spec_id: 'NYLON', parts: 3, ship_fitting_id: 'BITT-6S', pier_fitting_id: 'P-2' },
], analysis: unknown = null) {
  const c = { addLine: vi.fn(), setAllParts: vi.fn(), updateLine: vi.fn(), setNewLineSpec: vi.fn(), startAddLine: vi.fn(), cancelAddLine: vi.fn(), removeLine: vi.fn(), host: { store: { select: vi.fn() } } };
  const state = {
    shipClassId: 'S1', loading: 'full_load',
    ship: { class_id: 'S1', loading_conditions: [{ name: 'full_load' }], fittings: [{ fitting_id: 'BITT-1S', kind: 'bitt', side: 'starboard' },
      { fitting_id: 'BITT-6S', kind: 'bitt', side: 'starboard' }] },
    berth: { fittings: [{ fitting_id: 'P-1' }, { fitting_id: 'P-2' }] }, side: 'starboard',
    lines, lineSpecs: [{ spec_id: 'NYLON' }], analysis: { response: analysis },
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

it('offers labelled keyboard alternatives for creating and reconnecting a line', () => {
  const c = setup();
  fireEvent.change(screen.getByLabelText('New line ship fitting'), { target: { value: 'BITT-6S' } });
  fireEvent.change(screen.getByLabelText('New line pier fitting'), { target: { value: 'P-2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add selected fittings', hidden: true }));
  expect(c.addLine).toHaveBeenCalledWith('BITT-6S', 'P-2');
  fireEvent.change(screen.getByLabelText('Line 1 pier fitting'), { target: { value: 'P-2' } });
  expect(c.updateLine).toHaveBeenCalledWith(1, { pier_fitting_id: 'P-2' });
  fireEvent.change(screen.getByLabelText('Line 2 ship fitting'), { target: { value: 'BITT-1S' } });
  expect(c.updateLine).toHaveBeenCalledWith(2, { ship_fitting_id: 'BITT-1S' });
});


it.each(['invalid', 'unknown', undefined])('withholds line percentages for %s analysis validity', (state) => {
  setup(undefined, { validity: state ? { state } : undefined,
    result: { lines: [{ line_number: 1, pct_wll: 12.3, status: 'GREEN' }] } });
  expect(screen.queryByText('12%')).toBeNull();
  expect(screen.getByText(/Line loads unavailable/)).toBeTruthy();
});

it.each(['valid', 'limited'])('retains line percentages for %s analysis', (state) => {
  setup(undefined, { validity: { state }, result: { lines: [{ line_number: 1, pct_wll: 12.3, status: 'GREEN' }] } });
  expect(screen.getByText('12%')).toBeTruthy();
});
