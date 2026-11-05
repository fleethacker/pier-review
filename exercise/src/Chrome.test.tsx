// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chrome, tabFromUrl, tabsOf } from './Chrome';
import type { AppDefinition, AppInstance } from './lib/app';

afterEach(cleanup);

const slots = (): AppInstance => ({
  Canvas: () => <div data-testid="canvas" />,
  Sidebar: () => <div data-testid="sidebar" />,
  Side: () => <div data-testid="side" />,
  Bottom: () => <div data-testid="bottom" />,
  Banner: () => <div data-testid="banner" />,
  Overlay: () => <div data-testid="overlay" />,
  dispose: () => {},
});

const def = (patch: Partial<AppDefinition> = {}): AppDefinition => ({
  id: 'exercise',
  title: 'Exercise simulator',
  description: 'A simulator',
  tabs: [
    { id: 'scenario', label: 'Scenario' },
    { id: 'forces', label: 'Forces' },
  ],
  start: () => slots(),
  ...patch,
});

describe('which view is open', () => {
  it('reads it from the address bar and falls back to the first tab', () => {
    expect(tabFromUrl('?tab=forces', def())).toBe('forces');
    expect(tabFromUrl('?tab=nonsense', def())).toBe('scenario');
    expect(tabFromUrl('', def())).toBe('scenario');
  });

  it('gives an app with no tabs of its own one named after it', () => {
    expect(tabsOf(def({ tabs: [] }))).toEqual([{ id: 'main', label: 'Exercise simulator' }]);
  });
});

describe('the page frame', () => {
  it('starts the app once and puts every panel it offers on the page', async () => {
    const start = vi.fn(() => slots());
    render(<Chrome def={def({ start })} />);
    await waitFor(() => expect(screen.getByTestId('canvas')).toBeTruthy());
    for (const slot of ['sidebar', 'side', 'bottom', 'banner', 'overlay']) expect(screen.getByTestId(slot)).toBeTruthy();
    expect(start).toHaveBeenCalledTimes(1);
  });

  it('tells the app which tab is showing, and again when one is picked', async () => {
    const setTab = vi.fn();
    render(<Chrome def={def({ start: () => ({ ...slots(), setTab }) })} />);
    await waitFor(() => expect(setTab).toHaveBeenCalledWith('scenario'));
    act(() => screen.getByRole('tab', { name: 'Forces' }).click());
    expect(setTab).toHaveBeenLastCalledWith('forces');
    expect(screen.getByRole('tab', { name: 'Forces' }).getAttribute('aria-selected')).toBe('true');
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('forces');
  });

  it('says so on the page when the app will not start', async () => {
    render(<Chrome def={def({ start: () => Promise.reject(new Error('no WebGL')) })} />);
    await waitFor(() => expect(screen.getByText(/Could not start the simulator: no WebGL/)).toBeTruthy());
  });

  it('shuts the app down when the page goes', async () => {
    const dispose = vi.fn();
    const { unmount } = render(<Chrome def={def({ start: () => ({ ...slots(), dispose }) })} />);
    await waitFor(() => expect(screen.getByTestId('canvas')).toBeTruthy());
    unmount();
    expect(dispose).toHaveBeenCalled();
  });
});
