// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearApps, registerApp } from '../scene/app';
import { SceneStore } from '../scene/store';

vi.mock('./cesium/SceneRenderer', () => ({
  SceneRenderer: class {
    view = { screenUpBearingDeg: 0 };
    dispose() {}
    screenPositionOf() {
      return null;
    }
    pickAtPage() {
      return null;
    }
    geometryReady = true;
  },
}));

import { Shell } from './Shell';

afterEach(() => {
  cleanup();
  clearApps();
});

function registerTestApp() {
  registerApp({
    id: 'test',
    title: 'Test app',
    description: '',
    start: () => ({
      Sidebar: () => <div>sidebar content</div>,
      Side: () => <div>side content</div>,
      Overlay: () => null,
      Banner: () => <span>banner content</span>,
      dispose() {},
    }),
  });
}

describe('Shell layout', () => {
  it('renders the app slots', async () => {
    registerTestApp();
    render(<Shell store={new SceneStore()} />);
    await waitFor(() => expect(screen.getByText('sidebar content')).toBeTruthy());
    expect(screen.getByText('banner content')).toBeTruthy();
    expect(screen.getByText('side content')).toBeTruthy();
  });

  it('keeps an empty overlay from covering the canvas, so clicks and drags reach it', async () => {
    registerTestApp();
    const { container } = render(<Shell store={new SceneStore()} />);
    await waitFor(() => expect(screen.getByText('sidebar content')).toBeTruthy());
    const wrapper = container.querySelector('.z-20');
    expect(wrapper).not.toBeNull();
    expect(wrapper!.className).toContain('pointer-events-none');
  });

  it('toggles the view mode through the store', async () => {
    registerTestApp();
    const store = new SceneStore();
    render(<Shell store={store} />);
    await waitFor(() => expect(screen.getByText('sidebar content')).toBeTruthy());
    screen.getByRole('button', { name: /^3d$/i }).click();
    await waitFor(() => expect(store.getState().viewMode).toBe('3d'));
    screen.getByRole('button', { name: /^2d$/i }).click();
    await waitFor(() => expect(store.getState().viewMode).toBe('2d'));
  });

  it('toggles night and day lighting through the store', async () => {
    registerTestApp();
    const store = new SceneStore();
    render(<Shell store={store} />);
    await waitFor(() => expect(screen.getByText('sidebar content')).toBeTruthy());
    expect(store.getState().lighting).toBe('night');
    fireEvent.click(screen.getByRole('button', { name: 'Day' }));
    expect(store.getState().lighting).toBe('day');
    expect(screen.getByRole('button', { name: 'Night' })).toBeTruthy();
  });
});

describe('landing page and tabs', () => {
  function registerTwo() {
    const started: string[] = [];
    const tabsSeen: string[] = [];
    const stores: SceneStore[] = [];
    for (const [id, title] of [['alpha', 'Alpha app'], ['beta', 'Beta app']] as const) {
      registerApp({
        id,
        title,
        description: `${title} does things`,
        physics: ['Line equilibrium'],
        tabs: [
          { id: 'one', label: `${title} one` },
          { id: 'two', label: `${title} two` },
        ],
        start: (host) => {
          started.push(id);
          stores.push(host.store);
          return { Sidebar: () => <div>{title} panels</div>, setTab: (t) => tabsSeen.push(`${id}:${t}`), dispose() {} };
        },
      });
    }
    return { started, tabsSeen, stores };
  }

  afterEach(() => window.history.replaceState(null, '', '/'));

  it('shows a box for every application and opens the one clicked', async () => {
    const { started } = registerTwo();
    render(<Shell />);
    expect(screen.getByText('Pier Review')).toBeTruthy();
    const list = screen.getByRole('list', { name: 'Applications' });
    expect(list.querySelectorAll('li')).toHaveLength(2);
    expect(screen.getByText('Beta app does things')).toBeTruthy();
    expect(started).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: 'Open Beta app' }));
    await waitFor(() => expect(screen.getByText('Beta app panels')).toBeTruthy());
    expect(started).toEqual(['beta']);
    expect(window.location.search).toBe('?app=beta&tab=one');
  });

  it('switches tabs through the app and keeps each app running with its own scene', async () => {
    const { started, tabsSeen, stores } = registerTwo();
    window.history.replaceState(null, '', '/?app=alpha&tab=two');
    render(<Shell />);
    await waitFor(() => expect(screen.getByText('Alpha app panels')).toBeTruthy());
    expect(screen.getByRole('tab', { name: 'Alpha app two' }).getAttribute('aria-selected')).toBe('true');
    await waitFor(() => expect(tabsSeen).toContain('alpha:two'));
    fireEvent.click(screen.getByRole('tab', { name: 'Alpha app one' }));
    await waitFor(() => expect(tabsSeen).toContain('alpha:one'));
    fireEvent.click(screen.getByRole('button', { name: 'All applications' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open Beta app' }));
    await waitFor(() => expect(screen.getByText('Beta app panels')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'All applications' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open Alpha app' }));
    await waitFor(() => expect(screen.getByText('Alpha app panels')).toBeTruthy());
    expect(started).toEqual(['alpha', 'beta']);
    expect(stores[0]).not.toBe(stores[1]);
  });

  it('moves between tabs with the arrow keys', async () => {
    registerTwo();
    window.history.replaceState(null, '', '/?app=alpha');
    render(<Shell />);
    await waitFor(() => expect(screen.getByText('Alpha app panels')).toBeTruthy());
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Alpha app one' }), { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: 'Alpha app two' }).getAttribute('aria-selected')).toBe('true');
  });

  it('follows a tab change the application makes by itself', async () => {
    let notify: ((id: string) => void) | null = null;
    registerApp({
      id: 'gamma', title: 'Gamma app', description: '',
      tabs: [{ id: 'a', label: 'Gamma A' }, { id: 'b', label: 'Gamma B' }],
      start: () => ({ Sidebar: () => <div>gamma</div>, onTabChange: (l) => ((notify = l), () => (notify = null)), dispose() {} }),
    });
    registerApp({ id: 'delta', title: 'Delta app', description: '', start: () => ({ dispose() {} }) });
    window.history.replaceState(null, '', '/?app=gamma');
    render(<Shell />);
    await waitFor(() => expect(notify).not.toBeNull());
    act(() => notify!('b'));
    expect(screen.getByRole('tab', { name: 'Gamma B' }).getAttribute('aria-selected')).toBe('true');
    expect(window.location.search).toBe('?app=gamma&tab=b');
  });
});
