// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearApps, registerApp } from '../scene/app';
import { SceneStore } from '../scene/store';

const renderers = vi.hoisted(() => ({ constructed: 0 }));

vi.mock('./cesium/SceneRenderer', () => ({
  SceneRenderer: class {
    constructor() {
      renderers.constructed++;
    }
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
  renderers.constructed = 0;
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

describe('Shell tabs and custom canvases', () => {
  const plain = (id: string, title: string) => ({
    id,
    title,
    description: `${title} description`,
    start: () => ({ Sidebar: () => <div>{id} sidebar</div>, dispose() {} }),
  });

  it('shows no tabs for a single app and one tab per app otherwise, switching apps on click', async () => {
    registerApp(plain('a', 'App A'));
    const { unmount } = render(<Shell store={new SceneStore()} />);
    await waitFor(() => expect(screen.getByText('a sidebar')).toBeTruthy());
    expect(screen.queryByRole('tablist')).toBeNull();
    unmount();

    registerApp(plain('b', 'App B'));
    render(<Shell store={new SceneStore()} />);
    await waitFor(() => expect(screen.getByText('a sidebar')).toBeTruthy());
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual(['App A', 'App B']);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs[1].getAttribute('title')).toBe('App B description');

    fireEvent.click(tabs[1]);
    await waitFor(() => expect(screen.getByText('b sidebar')).toBeTruthy());
    expect(screen.queryByText('a sidebar')).toBeNull();
    expect(screen.getAllByRole('tab')[1].getAttribute('aria-selected')).toBe('true');
  });

  it('renders an app\'s own canvas in place of the scene canvas and its controls', async () => {
    registerApp({
      ...plain('map', 'Map app'),
      canvas: 'custom',
      start: () => ({ Canvas: () => <div>custom canvas</div>, dispose() {} }),
    });
    render(<Shell store={new SceneStore()} />);
    await waitFor(() => expect(screen.getByText('custom canvas')).toBeTruthy());
    expect(screen.queryByRole('button', { name: /^3d$/i })).toBeNull();
    await new Promise((r) => setTimeout(r, 50));
    expect(renderers.constructed).toBe(0);
  });

  it('does not start the scene renderer for a custom-canvas app while it is still starting', async () => {
    let finish: (() => void) | undefined;
    registerApp({
      ...plain('slow', 'Slow app'),
      canvas: 'custom',
      start: () =>
        new Promise((resolve) => {
          finish = () => resolve({ Canvas: () => <div>late canvas</div>, dispose() {} });
        }),
    });
    render(<Shell store={new SceneStore()} />);
    await new Promise((r) => setTimeout(r, 50));
    expect(renderers.constructed).toBe(0);
    expect(screen.queryByRole('button', { name: /^3d$/i })).toBeNull();
    finish!();
    await waitFor(() => expect(screen.getByText('late canvas')).toBeTruthy());
    expect(renderers.constructed).toBe(0);
  });

  it('still shows the scene canvas and its controls for apps without their own', async () => {
    registerApp(plain('scene', 'Scene app'));
    render(<Shell store={new SceneStore()} />);
    await waitFor(() => expect(screen.getByRole('button', { name: /^3d$/i })).toBeTruthy());
    await waitFor(() => expect(renderers.constructed).toBe(1));
  });

  it('reports an app that fails to start, even with a custom canvas', async () => {
    registerApp({ ...plain('bad', 'Bad app'), canvas: 'custom', start: () => Promise.reject(new Error('no map today')) });
    render(<Shell store={new SceneStore()} />);
    await waitFor(() => expect(screen.getByText(/no map today/)).toBeTruthy());
  });
});
