// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
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
});
