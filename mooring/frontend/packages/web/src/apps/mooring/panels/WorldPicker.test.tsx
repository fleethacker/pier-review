// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControllerContext } from './context';
import { WorldPicker } from './WorldPicker';

afterEach(cleanup);

// jsdom has no PointerEvent, so coordinates on pointer events would be dropped. A MouseEvent carries them.
if (typeof window.PointerEvent === 'undefined') {
  class PointerEventPolyfill extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  (window as unknown as { PointerEvent: unknown }).PointerEvent = PointerEventPolyfill;
}

const sites = [
  { berthId: 'N', name: 'Mock Pier 12 North face (NAVSTA Norfolk)', lat: 36.9585, lon: -76.3305 },
  { berthId: 'S', name: 'Mock Pier 12 South face (NAVSTA Norfolk)', lat: 36.9575, lon: -76.3305 },
  { berthId: 'Y', name: 'Notional berth, Yokosuka (Fleet Activities Yokosuka)', lat: 35.289, lon: 139.673 },
];

function setup(berthId = 'N') {
  const setBerth = vi.fn();
  const fakeState = { berthSites: sites, berthId, shipClassId: 'DDG-51-FIIA' };
  const controller = { setBerth, state: { use: (sel: (s: typeof fakeState) => unknown) => sel(fakeState) } };
  render(
    <ControllerContext.Provider value={controller as never}>
      <WorldPicker />
    </ControllerContext.Provider>,
  );
  // jsdom has no layout: give each marker a box at a known place.
  const place = (label: RegExp, x: number, y: number) => {
    const el = screen.getByRole('button', { name: label });
    el.getBoundingClientRect = () => ({ left: x - 7, top: y - 7, width: 14, height: 14, right: x + 7, bottom: y + 7, x: x - 7, y: y - 7, toJSON() {} });
    return el;
  };
  place(/Port NAVSTA Norfolk/, 100, 50);
  place(/Port Fleet Activities Yokosuka/, 300, 50);
  const chip = screen.getByRole('button', { name: /Ship\. Drag it/ });
  const drag = (to: { x: number; y: number }) => {
    fireEvent.pointerDown(chip, { clientX: 10, clientY: 200, pointerId: 1 });
    fireEvent.pointerMove(chip, { clientX: to.x, clientY: to.y, pointerId: 1 });
    fireEvent.pointerUp(chip, { clientX: to.x, clientY: to.y, pointerId: 1 });
  };
  return { setBerth, drag };
}

describe('WorldPicker', () => {
  it('shows one marker per port, not per berth, and says where the ship is docked', () => {
    setup();
    expect(screen.getAllByRole('button', { name: /^Port / })).toHaveLength(2);
    expect(screen.getByText('Docked: NAVSTA Norfolk')).toBeTruthy();
  });

  it('docks at a single-berth port when the ship is dropped on it', () => {
    const { setBerth, drag } = setup();
    drag({ x: 302, y: 52 });
    expect(setBerth).toHaveBeenCalledWith('Y');
  });

  it('asks which berth when the port has several, then docks at the chosen one', () => {
    const { setBerth, drag } = setup('Y');
    drag({ x: 100, y: 50 });
    expect(setBerth).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /Mock Pier 12 South face/ }));
    expect(setBerth).toHaveBeenCalledWith('S');
  });

  it('does nothing when dropped away from every port', () => {
    const { setBerth, drag } = setup();
    drag({ x: 200, y: 150 });
    expect(setBerth).not.toHaveBeenCalled();
  });

  it('does not re-dock at the berth the ship is already at', () => {
    const { setBerth, drag } = setup('Y');
    drag({ x: 300, y: 50 });
    expect(setBerth).not.toHaveBeenCalled();
  });

  it('also docks from a plain click on a port, for keyboard and touch users', () => {
    const { setBerth } = setup();
    fireEvent.click(screen.getByRole('button', { name: /Port Fleet Activities Yokosuka/ }));
    expect(setBerth).toHaveBeenCalledWith('Y');
  });
});
