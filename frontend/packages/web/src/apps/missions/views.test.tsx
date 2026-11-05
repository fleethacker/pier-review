// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SceneStore } from '../../scene/store';
import { Banner, Bottom, Side, Sidebar } from './Chrome';
import { ControllerContext } from './context';
import { MissionsController } from './controller';
import { missionsApp } from './index';

const json = (status: number, body: unknown) => ({ ok: status < 400, status, statusText: 'x', json: async () => body });

beforeEach(() => vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(501, {}))));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function mount() {
  const c = new MissionsController({ store: new SceneStore() });
  await c.init();
  render(
    <ControllerContext.Provider value={c}>
      <Banner />
      <Sidebar />
      <Side />
      <Bottom />
    </ControllerContext.Provider>,
  );
  return c;
}

describe('storyboard tab', () => {
  it('renders the sample storyboard with a sample banner, warnings and a keyboard scrubber', async () => {
    const c = await mount();
    expect(screen.getAllByText(/Sample data/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/MOCK sample sortie/).length).toBeGreaterThan(0);
    expect(screen.getByRole('slider', { name: 'Mission time' })).toBeTruthy();
    // unlocated events say so in the list
    expect(screen.getAllByText(/position not established/).length).toBeGreaterThanOrEqual(4);
    fireEvent.click(screen.getByRole('button', { name: /buoy abeam/ }));
    expect(c.state.selectedEventId).toBe('rep-2');
    expect(screen.getAllByText(/differs from the track by 180 m/).length).toBeGreaterThan(0);
    expect((screen.getAllByRole('button', { name: 'Download GeoJSON' })[0] as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole('form', { name: 'Upload track file' })).toBeTruthy();
    expect(screen.getByRole('form', { name: 'Upload image' })).toBeTruthy();
    expect(screen.getByRole('form', { name: 'Add report' })).toBeTruthy();
    c.dispose();
  });
});

describe('transit tab', () => {
  it('runs the sample, shows limits, vessel table and events', async () => {
    const c = await mount();
    // The shell's tab bar selects the tab now; it calls the controller the same way.
    act(() => c.setTab('transit'));
    expect(screen.getAllByText(/Surrogate maneuvering model; propulsion assumed; not navigational advice/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    await waitFor(() => expect(screen.getByRole('table', { name: 'Vessels' })).toBeTruthy());
    expect(screen.getAllByText(/SURROGATE_MANEUVERING_MODEL/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Propulsion \(speed, thrust lag/)).toBeTruthy();
    expect(screen.getByRole('list', { name: 'Transit events' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Play' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '30x' }));
    expect(c.state.clock.speed).toBe(30);
    c.dispose();
  });
});

describe('app definition', () => {
  it('starts and exposes shell slots', async () => {
    const inst = await missionsApp.start({ store: new SceneStore() });
    expect(inst.Sidebar && inst.Bottom && inst.Side && inst.Banner).toBeTruthy();
    inst.dispose();
  });
});
