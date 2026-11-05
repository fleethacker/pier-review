// @vitest-environment jsdom
import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The map loads through dynamic imports, which are slow when the whole suite runs at once.
configure({ asyncUtilTimeout: 8000 });

const view = vi.hoisted(() => ({
  created: [] as { container: HTMLElement; token: string; onProblem: (p: { kind: 'token' | 'quota'; message: string }) => void; disposed: boolean }[],
}));

vi.mock('mapbox-gl', () => ({ default: { fake: true } }));
vi.mock('./mapView', () => ({
  ExerciseMapView: class {
    map = {};
    record: (typeof view.created)[number];
    constructor(container: HTMLElement, _mapbox: unknown, token: string, _c: unknown, onProblem: (p: { kind: 'token' | 'quota'; message: string }) => void) {
      this.record = { container, token, onProblem, disposed: false };
      view.created.push(this.record);
    }
    dispose() {
      this.record.disposed = true;
    }
  },
}));

import { Bottom } from './Bottom';
import { ControllerContext } from './context';
import { ExerciseController } from './controller';
import { MapCanvas } from './MapCanvas';
import { NumField } from './NumField';
import { RedTeamPanel } from './RedTeam';
import { PRESET_SCENARIOS } from './scenarios';
import { Side } from './Side';
import { Sidebar } from './Sidebar';

function withController(ui: ReactNode, controller = new ExerciseController(undefined, PRESET_SCENARIOS[0])) {
  return { controller, ...render(<ControllerContext.Provider value={controller}>{ui}</ControllerContext.Provider>) };
}

beforeEach(() => {
  view.created.length = 0;
  localStorage.clear();
  // There is no server in these tests: anything that asks one gets a refusal.
  vi.stubGlobal('fetch', () => Promise.reject(new TypeError('no server')));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('NumField', () => {
  function setup(props: Partial<React.ComponentProps<typeof NumField>> = {}) {
    const onCommit = vi.fn();
    const utils = render(<NumField label="Speed" value={10} onCommit={onCommit} {...props} />);
    return { onCommit, input: screen.getByLabelText('Speed') as HTMLInputElement, ...utils };
  }
  const type = (input: HTMLInputElement, value: string) => {
    act(() => input.focus());
    fireEvent.change(input, { target: { value } });
  };

  it('commits a typed value on blur but not while typing', () => {
    const { input, onCommit } = setup();
    type(input, '15');
    expect(onCommit).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(15);
  });

  it('commits on Enter', () => {
    const { input, onCommit } = setup();
    type(input, '22');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onCommit).toHaveBeenCalledWith(22);
  });

  it('puts the old value back on Escape, without committing', () => {
    const { input, onCommit } = setup();
    type(input, '99');
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onCommit).not.toHaveBeenCalled();
    expect(input.value).toBe('10');
  });

  it('reverts values that are out of range or not numbers, and blanks unless optional', () => {
    const { input, onCommit } = setup({ min: 0, max: 30 });
    for (const bad of ['31', '-1', '', 'abc']) {
      type(input, bad);
      fireEvent.blur(input);
      expect(input.value).toBe('10');
    }
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('commits undefined for a blank optional field', () => {
    const { input, onCommit } = setup({ optional: true });
    type(input, '');
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(undefined);
  });

  it('does not commit when nothing changed, and follows the value from outside', () => {
    const { input, onCommit, rerender } = setup();
    type(input, '10');
    fireEvent.blur(input);
    expect(onCommit).not.toHaveBeenCalled();
    rerender(<NumField label="Speed" value={18} onCommit={onCommit} />);
    expect(input.value).toBe('18');
  });

  it('uses the label as the accessible name when compact', () => {
    render(<NumField compact label="Waypoint 1 longitude" value={-61.5} onCommit={() => {}} />);
    expect(screen.getByLabelText('Waypoint 1 longitude')).toBeTruthy();
    expect(screen.queryByText('Waypoint 1 longitude')).toBeNull();
  });
});

describe('Sidebar', () => {
  it('edits the environment and re-runs the scenario', () => {
    const { controller } = withController(<Sidebar />);
    const before = controller.state.get().active;
    const wind = screen.getByLabelText('Wind (kt)');
    fireEvent.change(wind, { target: { value: '35' } });
    fireEvent.blur(wind);
    expect(controller.state.get().scenario.environment.windKt).toBe(35);
    expect(controller.state.get().active).not.toBe(before);
  });

  it('lists the ships, selects one for editing, and changes its behavior', () => {
    const { controller } = withController(<Sidebar />);
    const list = within(screen.getByRole('list', { name: 'Ships' }));
    expect(list.getAllByRole('button')).toHaveLength(5);
    fireEvent.click(list.getByRole('button', { name: /Cruiser 1/ }));
    expect(controller.state.get().selectedId).toBe('cg1');
    expect(screen.getByDisplayValue('Cruiser 1')).toBeTruthy();
    expect(screen.getByText('Escort of')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Behavior'), { target: { value: 'hold' } });
    expect(controller.state.get().scenario.units.find((u) => u.id === 'cg1')!.behavior.type).toBe('hold');
    expect(screen.queryByText('Escort of')).toBeNull();
    expect(screen.getByText(/Stops and drifts/)).toBeTruthy();
  });

  it('edits a ship and its waypoints', () => {
    const { controller } = withController(<Sidebar />);
    act(() => controller.select('cvn1'));
    const name = screen.getByDisplayValue('Carrier 1');
    fireEvent.change(name, { target: { value: 'Big Deck' } });
    fireEvent.blur(name);
    expect(controller.state.get().scenario.units[0].name).toBe('Big Deck');

    const speed = screen.getByLabelText(/Speed \(kt, max 30\)/);
    fireEvent.change(speed, { target: { value: '25' } });
    fireEvent.blur(speed);
    expect(controller.state.get().scenario.units[0].speedKt).toBe(25);

    const tooFast = screen.getByLabelText(/Speed \(kt, max 30\)/);
    fireEvent.change(tooFast, { target: { value: '60' } });
    fireEvent.blur(tooFast);
    expect(controller.state.get().scenario.units[0].speedKt).toBe(25);

    const wpSpeed = screen.getByLabelText('Waypoint 2 speed');
    fireEvent.change(wpSpeed, { target: { value: '12' } });
    fireEvent.blur(wpSpeed);
    const b = controller.state.get().scenario.units[0].behavior;
    expect(b.type === 'route' && b.waypoints[1].speedKt).toBe(12);

    fireEvent.click(screen.getByRole('button', { name: 'Remove waypoint 3' }));
    const after = controller.state.get().scenario.units[0].behavior;
    expect(after.type === 'route' && after.waypoints).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: 'Add on map' }));
    expect(controller.state.get().placing).toBe(true);
  });

  it('adds and removes ships', () => {
    const { controller } = withController(<Sidebar />);
    fireEvent.click(screen.getByRole('button', { name: '+ Add ship' }));
    expect(controller.state.get().scenario.units).toHaveLength(6);
    expect(controller.state.get().selectedId).toBe('u6');
    fireEvent.click(screen.getByRole('button', { name: /^Remove Destroyer 6/ }));
    expect(controller.state.get().scenario.units).toHaveLength(5);
  });

  it('says so when a change cannot run, and why', () => {
    const { controller } = withController(<Sidebar />);
    act(() => controller.patchScenario({ durationS: 5 }));
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('not applied');
    expect(alert.textContent).toContain('Duration');
    act(() => controller.patchScenario({ durationS: 900 }));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('asks before replacing an edited scenario, and loads without asking when nothing was edited', () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { controller } = withController(<Sidebar />);
    fireEvent.change(screen.getByLabelText('Load'), { target: { value: 'formation-drill' } });
    expect(confirm).not.toHaveBeenCalled();
    expect(controller.state.get().scenario.id).toBe('formation-drill');

    act(() => controller.patchEnvironment({ windKt: 40 }));
    fireEvent.change(screen.getByLabelText('Load'), { target: { value: 'csg-transit' } });
    expect(confirm).toHaveBeenCalledOnce();
    expect(controller.state.get().scenario.id).toBe('formation-drill');

    confirm.mockReturnValue(true);
    fireEvent.change(screen.getByLabelText('Load'), { target: { value: 'csg-transit' } });
    expect(controller.state.get().scenario.id).toBe('csg-transit');
  });

  it('edits the scenario as JSON and reports what is wrong with bad JSON', () => {
    const { controller } = withController(<Sidebar />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit as JSON' }));
    const box = screen.getByLabelText('Scenario JSON') as HTMLTextAreaElement;
    expect(JSON.parse(box.value).id).toBe('csg-transit');

    fireEvent.change(box, { target: { value: '{broken' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(screen.getByRole('status').textContent).toContain('not valid JSON');

    const edited = JSON.parse(JSON.stringify(PRESET_SCENARIOS[0]));
    edited.name = 'Edited in JSON';
    fireEvent.change(box, { target: { value: JSON.stringify(edited) } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(controller.state.get().scenario.name).toBe('Edited in JSON');
    expect(screen.queryByLabelText('Scenario JSON')).toBeNull();
  });
});

describe('Side', () => {
  it('changes the view options and the map style', () => {
    const { controller } = withController(<Side />);
    fireEvent.change(screen.getByLabelText('Ship size'), { target: { value: '8' } });
    expect(controller.state.get().view.shipScale).toBe(8);
    fireEvent.change(screen.getByLabelText('Wake length'), { target: { value: '0' } });
    expect(screen.getByText('off')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Ship names'));
    expect(controller.state.get().view.showLabels).toBe(false);
    fireEvent.click(screen.getByLabelText('Sensor range of selected ship'));
    expect(controller.state.get().view.showRange).toBe(true);
    fireEvent.change(screen.getByDisplayValue('Standard (3D lighting)'), { target: { value: 'dark' } });
    expect(controller.state.get().mapStyle).toBe('dark');
  });

  it('shows a readout for the selected ship', () => {
    const { controller } = withController(<Side />);
    expect(screen.getByText(/Click a ship on the map/)).toBeTruthy();
    act(() => controller.select('cvn1'));
    expect(screen.getByText('Carrier 1')).toBeTruthy();
    expect(screen.getByText('Aircraft carrier (CVN)')).toBeTruthy();
    expect(screen.getByText('Speed through water').nextElementSibling!.textContent).toBe('18.0 kt');
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }));
    expect(controller.state.get().selectedId).toBeNull();
  });
});

describe('Bottom', () => {
  it('plays, pauses, restarts and changes speed', () => {
    const { controller } = withController(<Bottom />);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    expect(controller.clock.playing).toBe(true);
    expect(screen.getByRole('button', { name: 'Pause' })).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Playback speed'), { target: { value: '120' } });
    expect(controller.clock.rate).toBe(120);
    act(() => controller.clock.tick(1));
    expect(screen.getByLabelText('Elapsed time').textContent).toBe('T+00:02:00');
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(controller.clock.playing).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Restart' }));
    expect(controller.clock.timeS).toBe(0);
  });

  it('scrubs with the slider', () => {
    const { controller } = withController(<Bottom />);
    fireEvent.change(screen.getByLabelText('Time'), { target: { value: '1800' } });
    expect(controller.clock.timeS).toBe(1800);
    expect(screen.getByLabelText('Elapsed time').textContent).toBe('T+00:30:00');
  });

  it('lists every ship and, once one is selected, its range and bearing to the others', () => {
    const { controller } = withController(<Bottom />);
    expect(screen.getAllByRole('row')).toHaveLength(6);
    fireEvent.click(screen.getByRole('row', { name: /Carrier 1/ }));
    expect(controller.state.get().selectedId).toBe('cvn1');
    const cruiser = screen.getByRole('row', { name: /Cruiser 1/ });
    expect(cruiser.textContent).toMatch(/\d+\.\d\d \/ \d{3}°/);
    expect(screen.getByRole('row', { name: /Carrier 1/ }).textContent).toContain('–');
    fireEvent.click(screen.getByRole('row', { name: /Carrier 1/ }));
    expect(controller.state.get().selectedId).toBeNull();
  });
});

describe('MapCanvas', () => {
  const VALID = 'pk.eyJ1IjoidGVzdCJ9.abc-DEF_123';

  it('asks for a token when there is none, and refuses things that are not tokens', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', '');
    withController(<MapCanvas />);
    const box = screen.getByLabelText('Mapbox access token');
    const submit = screen.getByRole('button', { name: 'Use this token' }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(box, { target: { value: 'sk.secret.token' } });
    expect(submit.disabled).toBe(true);
    fireEvent.change(box, { target: { value: VALID } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => expect(view.created).toHaveLength(1));
    expect(view.created[0].token).toBe(VALID);
    expect(localStorage.getItem('exercise.mapboxToken')).toBe(VALID);
    expect(screen.queryByLabelText('Mapbox access token')).toBeNull();
  });

  it('uses the built-in token without asking, and disposes the map on unmount', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', 'pk.built.in');
    const { unmount } = withController(<MapCanvas />);
    await waitFor(() => expect(view.created).toHaveLength(1));
    expect(view.created[0].token).toBe('pk.built.in');
    expect(screen.queryByLabelText('Mapbox access token')).toBeNull();
    expect(view.created[0].container.getAttribute('data-testid')).toBe('exercise-map');
    unmount();
    expect(view.created[0].disposed).toBe(true);
  });

  it('asks the server for a token when neither the build nor this browser has one', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', '');
    const asked: string[] = [];
    vi.stubGlobal('fetch', async (url: string) => {
      asked.push(url.replace(/^https?:\/\/[^/]+/, ''));
      return new Response(JSON.stringify({ mapboxToken: VALID }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    withController(<MapCanvas />);
    await waitFor(() => expect(view.created[0]?.token).toBe(VALID));
    expect(asked).toEqual(['/api/modeling/api/v1/exercise/config']);
    expect(localStorage.getItem('exercise.mapboxToken')).toBeNull();
  });

  it('shows the prompt when the server has no token, asking only once', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', '');
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify({ mapboxToken: null }), { status: 200 }));
    vi.stubGlobal('fetch', fetchSpy);
    withController(<MapCanvas />);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText('Mapbox access token')).toBeTruthy();
    expect(screen.getAllByText('MAPBOX_TOKEN').length).toBe(1);
    expect(view.created).toHaveLength(0);
  });

  it('does not ask the server again after Mapbox rejects the token it gave, and tells the server', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', '');
    const urls: string[] = [];
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
      urls.push(`${init?.method ?? 'GET'} ${url.replace(/^https?:\/\/[^/]+/, '')}`);
      return url.endsWith('/config') ? new Response(JSON.stringify({ mapboxToken: 'pk.server.token' })) : new Response(null, { status: 204 });
    });
    withController(<MapCanvas />);
    await waitFor(() => expect(view.created).toHaveLength(1));
    act(() => view.created[0].onProblem({ kind: 'token', message: 'Mapbox rejected the access token pk.server.token.' }));
    await waitFor(() => expect(screen.getByLabelText('Mapbox access token')).toBeTruthy());
    await new Promise((r) => setTimeout(r, 20));
    expect(urls.filter((u) => u.endsWith('/config'))).toHaveLength(1);
    const report = urls.find((u) => u.startsWith('POST'));
    expect(report).toContain('/exercise/client-errors');
    expect(view.created).toHaveLength(1);
  });

  it('falls back to the token saved in this browser', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', '');
    localStorage.setItem('exercise.mapboxToken', VALID);
    withController(<MapCanvas />);
    await waitFor(() => expect(view.created[0]?.token).toBe(VALID));
  });

  it('goes back to the prompt, with the reason, when Mapbox rejects the token', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', 'pk.bad.token');
    withController(<MapCanvas />);
    await waitFor(() => expect(view.created).toHaveLength(1));
    act(() => view.created[0].onProblem({ kind: 'token', message: 'Mapbox rejected the access token.' }));
    expect(screen.getByText('Mapbox rejected the access token.')).toBeTruthy();
    expect(screen.getByLabelText('Mapbox access token')).toBeTruthy();
    expect(view.created[0].disposed).toBe(true);
  });

  it('keeps the map and shows a notice when Mapbox only refuses some requests', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', 'pk.built.in');
    withController(<MapCanvas />);
    await waitFor(() => expect(view.created).toHaveLength(1));
    act(() => view.created[0].onProblem({ kind: 'quota', message: 'Mapbox is refusing some map requests.' }));
    expect(screen.getByRole('alert').textContent).toContain('refusing some map requests');
    expect(view.created[0].disposed).toBe(false);
  });

  it('orbits from the toolbar without a selection', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', 'pk.built.in');
    const { controller } = withController(<MapCanvas />);
    await waitFor(() => expect(view.created).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: 'Orbit' }));
    expect(controller.state.get().follow).toBe('orbit');
    expect(screen.getByRole('button', { name: 'Orbit' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Orbit' }));
    expect(controller.state.get().follow).toBe('off');
  });

  it('fills the screen in presentation mode with a minimal HUD, and gives the page back on Exit or Escape', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', 'pk.built.in');
    const { controller } = withController(<MapCanvas />);
    await waitFor(() => expect(view.created).toHaveLength(1));
    const frame = () => screen.getByTestId('exercise-map').parentElement!;
    expect(frame().className).toContain('absolute');
    expect(screen.queryByRole('group', { name: 'Presentation controls' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Present' }));
    expect(controller.state.get().presenting).toBe(true);
    expect(frame().className).toContain('fixed');
    const hud = within(screen.getByRole('group', { name: 'Presentation controls' }));
    expect(screen.getByText('Carrier group transit')).toBeTruthy();
    expect(screen.getByText('T+00:00:00')).toBeTruthy();

    fireEvent.click(hud.getByRole('button', { name: 'Play' }));
    expect(controller.clock.playing).toBe(true);
    fireEvent.change(hud.getByLabelText('Time'), { target: { value: '120' } });
    expect(controller.clock.timeS).toBe(120);
    fireEvent.change(hud.getByLabelText('Playback speed'), { target: { value: '300' } });
    expect(controller.clock.rate).toBe(300);

    fireEvent.click(hud.getByRole('button', { name: 'Exit' }));
    expect(controller.state.get().presenting).toBe(false);
    expect(frame().className).toContain('absolute');

    act(() => controller.setPresenting(true));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(controller.state.get().presenting).toBe(false);
  });

  it('drives the camera and waypoint tools from the toolbar', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', 'pk.built.in');
    const { controller } = withController(<MapCanvas />);
    await waitFor(() => expect(view.created).toHaveLength(1));

    fireEvent.click(screen.getByRole('button', { name: 'Fit all' }));
    expect(controller.state.get().fitRevision).toBe(1);

    fireEvent.click(screen.getByRole('button', { name: 'Follow' }));
    expect(controller.state.get().follow).toBe('off');
    expect(controller.state.get().notice).toContain('Select a ship');

    act(() => controller.select('cvn1'));
    fireEvent.click(screen.getByRole('button', { name: 'Chase' }));
    expect(controller.state.get().follow).toBe('chase');
    expect(screen.getByRole('button', { name: 'Chase' }).getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: 'Add waypoints' }));
    expect(controller.state.get().placing).toBe(true);
    expect(screen.getByRole('status').textContent).toContain('Carrier 1');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(controller.state.get().placing).toBe(false);
  });
});

const salvoScenario = () => PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!;
const salvoController = () => new ExerciseController(undefined, salvoScenario());

describe('Sidebar for aircraft, missiles and mines', () => {
  it('offers only behaviors that make sense for the selected unit', () => {
    const { controller } = withController(<Sidebar />, salvoController());
    const options = () => within(screen.getByLabelText('Behavior')).getAllByRole('option').map((o) => o.textContent);
    act(() => controller.select('cvn1'));
    expect(options()).toEqual(['Follow a route', 'Keep station on a unit', 'Pursue a unit', 'Hold and drift']);
    act(() => controller.select('rf1'));
    expect(options()).toContain('Circle a point');
    expect(options()).toContain('Circle where it is');
    act(() => controller.select('m1'));
    expect(options()).toEqual(['Strike a unit', 'Follow a route']);
    act(() => controller.select('bh1'));
    expect(options()).toContain('Hold and drift');
  });

  it('shows altitude for aircraft, with a waypoint altitude column, and a strike target for missiles', () => {
    const { controller } = withController(<Sidebar />, salvoController());
    act(() => controller.select('rf1'));
    const alt = screen.getByLabelText('Altitude (m)');
    fireEvent.change(alt, { target: { value: '4000' } });
    fireEvent.blur(alt);
    expect(controller.state.get().scenario.units.find((u) => u.id === 'rf1')!.altitudeM).toBe(4000);
    const wpAlt = screen.getByLabelText('Waypoint 1 altitude');
    fireEvent.change(wpAlt, { target: { value: '800' } });
    fireEvent.blur(wpAlt);
    const b = controller.state.get().scenario.units.find((u) => u.id === 'rf1')!.behavior;
    expect(b.type === 'route' && b.waypoints[0].altitudeM).toBe(800);

    act(() => controller.select('m1'));
    expect(screen.queryByLabelText('Altitude (m)')).toBeNull();
    fireEvent.change(screen.getByLabelText('Strike'), { target: { value: 'cg1' } });
    expect(controller.state.get().scenario.units.find((u) => u.id === 'm1')!.behavior).toMatchObject({ type: 'strike', targetId: 'cg1' });
  });

  it('edits who launches a unit and when, and lets it be present from the start again', () => {
    const { controller } = withController(<Sidebar />, salvoController());
    act(() => controller.select('m1'));
    const time = screen.getByLabelText('Launch at (s)');
    fireEvent.change(time, { target: { value: '450' } });
    fireEvent.blur(time);
    expect(controller.state.get().scenario.units.find((u) => u.id === 'm1')!.launch).toEqual({ byId: 'rdd1', atS: 450 });
    fireEvent.change(screen.getByLabelText('Launched by'), { target: { value: '' } });
    expect(controller.state.get().scenario.units.find((u) => u.id === 'm1')!.launch).toBeUndefined();
    expect(screen.queryByLabelText('Launch at (s)')).toBeNull();
    fireEvent.change(screen.getByLabelText('Launched by'), { target: { value: 'cg1' } });
    expect(controller.state.get().scenario.units.find((u) => u.id === 'm1')!.launch).toEqual({ byId: 'cg1', atS: 60 });
  });

  it('edits hit points, damage, hit chance, defence and leaving a unit out, showing class values as hints', () => {
    const { controller } = withController(<Sidebar />, salvoController());
    const unit = (id: string) => controller.state.get().scenario.units.find((u) => u.id === id)!;
    const set = (label: string, value: string) => {
      const box = screen.getByLabelText(label);
      fireEvent.change(box, { target: { value } });
      fireEvent.blur(box);
    };
    act(() => controller.select('cvn1'));
    expect(screen.getByLabelText('Hit points').getAttribute('placeholder')).toBe('400 (class)');
    set('Hit points', '250');
    expect(unit('cvn1').hp).toBe(250);
    set('Defence kill chance (0–1)', '0.9');
    expect(unit('cvn1').pKill).toBe(0.9);
    set('Defensive shots', '3');
    expect(unit('cvn1').magazine).toBe(3);
    set('Hit points', '');
    expect('hp' in JSON.parse(JSON.stringify(unit('cvn1')))).toBe(false);

    act(() => controller.select('m1'));
    expect(screen.queryByLabelText('Hit points')).toBeNull();
    set('Damage', '90');
    set('Hit chance (0–1)', '0.5');
    expect(unit('m1')).toMatchObject({ damage: 90, pHit: 0.5 });
    set('Hit chance (0–1)', '1.5');
    expect(unit('m1').pHit).toBe(0.5);
    fireEvent.click(screen.getByLabelText('Leave this unit out of the run'));
    expect(unit('m1').disabled).toBe(true);
    fireEvent.click(screen.getByLabelText('Leave this unit out of the run'));
    expect(unit('m1').disabled).toBeFalsy();
  });

  it('describes a mine, and hides what does not apply to it', () => {
    const { controller } = withController(<Sidebar />, new ExerciseController(undefined, PRESET_SCENARIOS.find((p) => p.id === 'minefield-transit')!));
    act(() => controller.select('mine01'));
    expect(screen.queryByLabelText('Behavior')).toBeNull();
    expect(screen.queryByLabelText(/^Speed/)).toBeNull();
    expect(screen.getByText(/Stays where it is/).textContent).toContain('45 m');
  });

  it('adds an aircraft, a missile or a mine from the menu', () => {
    const { controller } = withController(<Sidebar />, salvoController());
    const menu = screen.getByDisplayValue('Add aircraft, submarine, missile or mine…');
    fireEvent.change(menu, { target: { value: 'MINE' } });
    expect(controller.state.get().scenario.units.at(-1)!.classId).toBe('MINE');
    fireEvent.change(screen.getByDisplayValue('Add aircraft, submarine, missile or mine…'), { target: { value: 'FIGHTER' } });
    expect(controller.state.get().scenario.units.at(-1)!.classId).toBe('FIGHTER');
    expect(controller.state.get().selectedId).toBe(controller.state.get().scenario.units.at(-1)!.id);
  });

  it('fires a salvo from a form, and cancels out of it', () => {
    const { controller } = withController(<Sidebar />, salvoController());
    const before = controller.state.get().scenario.units.length;
    fireEvent.click(screen.getByRole('button', { name: '+ Add salvo' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('button', { name: 'Fire salvo' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '+ Add salvo' }));
    const count = screen.getByLabelText('How many');
    fireEvent.change(count, { target: { value: '3' } });
    fireEvent.blur(count);
    fireEvent.click(screen.getByRole('button', { name: 'Fire salvo' }));
    const added = controller.state.get().scenario.units.slice(before);
    expect(added).toHaveLength(3);
    expect(added[0]).toMatchObject({ classId: 'ASM', side: 'RED' });
    expect(added[0].launch).toEqual({ byId: 'rdd1', atS: 60 });
    expect(screen.getByRole('button', { name: '+ Add salvo' })).toBeTruthy();
  });

  it('shows and changes the chance seed, and re-rolls it', () => {
    const { controller } = withController(<Sidebar />, salvoController());
    const seed = screen.getByLabelText('Chance seed');
    expect((seed as HTMLInputElement).value).toBe('4');
    fireEvent.change(seed, { target: { value: '9' } });
    fireEvent.blur(seed);
    expect(controller.state.get().scenario.seed).toBe(9);
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
    fireEvent.click(screen.getByRole('button', { name: 'Re-roll' }));
    expect(controller.state.get().scenario.seed).toBe(50_000);
  });

  it('shows a unit that is left out struck through in the list', () => {
    const { controller } = withController(<Sidebar />, salvoController());
    act(() => controller.patchUnit('m1', { disabled: true }));
    const list = within(screen.getByRole('list', { name: 'Ships' }));
    expect(list.getByText('Missile 1').className).toContain('line-through');
    expect(list.getByText('Missile 2').className).not.toContain('line-through');
  });
});

describe('Side readout for the new kinds of unit', () => {
  it('shows altitude and hit points for an aircraft, and status', () => {
    const { controller } = withController(<Side />, salvoController());
    act(() => controller.select('rf1'));
    expect(screen.getByText('Altitude').nextElementSibling!.textContent).toBe('1,500 m');
    expect(screen.getByText('Hit points').nextElementSibling!.textContent).toBe('30 / 30');
    expect(screen.getByText('Status').nextElementSibling!.textContent).toBe('Active');
  });

  it('shows what a missile will do and that it is waiting, and what a ship can defend with', () => {
    const { controller } = withController(<Side />, salvoController());
    act(() => controller.select('m1'));
    expect(screen.getByText('Status').nextElementSibling!.textContent).toBe('Waiting');
    expect(screen.getByText('Damage').nextElementSibling!.textContent).toBe('60');
    expect(screen.getByText('Hit chance').nextElementSibling!.textContent).toBe('85%');
    expect(screen.queryByText('Hit points')).toBeNull();
    act(() => controller.select('cg1'));
    expect(screen.getByText('Defence').nextElementSibling!.textContent).toBe('50% per shot, 9 km');
    expect(screen.queryByText('Altitude')).toBeNull();
  });

  it('shows hit points falling and the unit destroyed as the run goes on', () => {
    const c = salvoController();
    c.setRedTeam({ ...c.redTeamSpec() });
    withController(<Side />, c);
    act(() => c.select('cvn1'));
    expect(screen.getByText('Hit points').nextElementSibling!.textContent).toBe('400 / 400');
    act(() => c.seek(560));
    expect(screen.getByText('Hit points').nextElementSibling!.textContent).toBe('340 / 400');
    expect(screen.getByText('Status').nextElementSibling!.textContent).toBe('Damaged');
  });
});

describe('Bottom: contacts and events', () => {
  it('shows status, hit points and altitude, and dashes for units that do not exist yet', () => {
    const { controller } = withController(<Bottom />, salvoController());
    const row = (name: string) => screen.getByRole('row', { name: new RegExp(name) });
    expect(row('Carrier 1').textContent).toContain('Active');
    expect(row('Carrier 1').textContent).toContain('400/400');
    expect(row('Raider 1').textContent).toContain('1,500');
    expect(row('Missile 1').textContent).toContain('Waiting');
    expect(row('Missile 1').textContent).not.toContain('090°');
    act(() => controller.seek(520));
    expect(row('Missile 7').textContent).toContain('Active');
    act(() => controller.seek(560));
    expect(row('Missile 1').textContent).toContain('Spent');
    expect(row('Carrier 1').textContent).toContain('Damaged');
    expect(row('Carrier 1').textContent).toContain('340/400');
  });

  it('lists events in words, and jumps to one and selects the ship involved', () => {
    const { controller } = withController(<Bottom />, salvoController());
    fireEvent.click(screen.getByRole('tab', { name: /Events/ }));
    const list = within(screen.getByRole('list', { name: 'Events' }));
    expect(list.getAllByRole('button').length).toBe(controller.state.get().active.trajectory.events.length);
    const hit = list.getByRole('button', { name: /Missile 7 hit Carrier 1 \(340 HP left\)/ });
    fireEvent.click(hit);
    expect(controller.clock.timeS).toBe(546 - 8);
    expect(controller.state.get().selectedId).toBe('cvn1');
    fireEvent.click(list.getByRole('button', { name: /Destroyer 1 shot down Missile 1/ }));
    expect(controller.state.get().selectedId).toBe('ddg1');
    fireEvent.click(list.getByRole('button', { name: /Hostile destroyer launched Missile 1/ }));
    expect(controller.clock.timeS).toBe(292);
  });

  it('counts events in the tab, and says when there are none', () => {
    const quiet = withController(<Bottom />);
    expect(screen.getByRole('tab', { name: 'Events (0)' })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /Events/ }));
    expect(screen.getByText(/Nothing happens in this run/)).toBeTruthy();
    quiet.unmount();
  });

  it('marks hits, interceptions and losses on the timeline', () => {
    const { container, controller } = withController(<Bottom />, salvoController());
    const ticks = container.querySelectorAll('[aria-hidden="true"] span');
    const wanted = controller.state.get().active.trajectory.events.filter((e) => ['hit', 'mine', 'destroyed', 'intercept'].includes(e.type));
    expect(ticks).toHaveLength(wanted.length);
    expect((ticks[0] as HTMLElement).style.left).toMatch(/%$/);
  });

  it('switches between the tabs', () => {
    withController(<Bottom />, salvoController());
    expect(screen.getByRole('tab', { name: 'Contacts' }).getAttribute('aria-selected')).toBe('true');
    fireEvent.click(screen.getByRole('tab', { name: /Events/ }));
    expect(screen.queryByRole('row', { name: /Carrier 1/ })).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: 'Contacts' }));
    expect(screen.getByRole('row', { name: /Carrier 1/ })).toBeTruthy();
  });
});

describe('MapCanvas red team and replay controls', () => {
  it('opens and closes the red-team panel from the toolbar', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', 'pk.built.in');
    const { controller } = withController(<MapCanvas />, salvoController());
    await waitFor(() => expect(view.created).toHaveLength(1));
    const button = screen.getByRole('button', { name: 'Red team' });
    fireEvent.click(button);
    expect(controller.state.get().redTeamOpen).toBe(true);
    expect(button.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(button);
    expect(controller.state.get().redTeamOpen).toBe(false);
  });

  it('says a replay is running, lists its random draws, and offers the way back', async () => {
    vi.stubEnv('VITE_MAPBOX_TOKEN', 'pk.built.in');
    const c = salvoController();
    c.setRedTeam({ ...c.redTeamSpec(), runs: 3, sweep: undefined });
    await c.runRedTeam();
    const { controller } = withController(<MapCanvas />, c);
    await waitFor(() => expect(view.created).toHaveLength(1));
    act(() => controller.replayRun(0, 1, 'Carrier is hit'));
    expect(screen.getByRole('status').textContent).toContain('Replaying run 2');
    expect(screen.getByRole('status').textContent).toContain('chosen for: Carrier is hit');
    expect(within(screen.getByRole('status')).getByText('Wind speed')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Back to red team' }));
    expect(controller.state.get().redTeamOpen).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Exit replay' }));
    expect(controller.state.get().replay).toBeNull();
    expect(screen.queryByText(/Replaying run/)).toBeNull();
  });
});

describe('RedTeamPanel', () => {
  const small = () => {
    const c = salvoController();
    c.setRedTeam({ ...c.redTeamSpec(), runs: 5, sweep: undefined });
    c.toggleRedTeam(true);
    return c;
  };
  const dialog = () => within(screen.getByRole('dialog', { name: 'Red team' }));

  it('is not there until opened, and closes from its own button', () => {
    const c = salvoController();
    withController(<RedTeamPanel />, c);
    expect(screen.queryByRole('dialog')).toBeNull();
    act(() => c.toggleRedTeam(true));
    expect(screen.getByRole('dialog', { name: 'Red team' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Close red team' }));
    expect(c.state.get().redTeamOpen).toBe(false);
  });

  it('shows the setup, and editing it saves to the scenario without re-running the one you watch', () => {
    const c = small();
    const before = c.state.get().active;
    withController(<RedTeamPanel />, c);
    const runs = dialog().getByLabelText('Runs');
    fireEvent.change(runs, { target: { value: '25' } });
    fireEvent.blur(runs);
    const seed = dialog().getByLabelText('Seed');
    fireEvent.change(seed, { target: { value: '77' } });
    fireEvent.blur(seed);
    expect(c.state.get().scenario.redTeam).toMatchObject({ runs: 25, seed: 77 });
    expect(c.state.get().active).toBe(before);
    expect(dialog().getByRole('button', { name: 'Run 25 runs' })).toBeTruthy();
  });

  it('adds, edits and removes outcomes', () => {
    const c = small();
    withController(<RedTeamPanel />, c);
    const outcomes = () => c.state.get().scenario.redTeam!.outcomes;
    const n = outcomes().length;
    fireEvent.click(dialog().getByRole('button', { name: '+ Add outcome' }));
    expect(outcomes()).toHaveLength(n + 1);
    expect(outcomes().at(-1)!.type).toBe('hit');
    const kinds = dialog().getAllByLabelText('Measure how often');
    fireEvent.change(kinds.at(-1)!, { target: { value: 'closest_approach' } });
    expect(outcomes().at(-1)).toMatchObject({ type: 'closest_approach', withinM: 2000 });
    const within = dialog().getByLabelText('Within (m)');
    fireEvent.change(within, { target: { value: '800' } });
    fireEvent.blur(within);
    expect(outcomes().at(-1)).toMatchObject({ withinM: 800 });
    fireEvent.change(dialog().getAllByLabelText('Measure how often').at(-1)!, { target: { value: 'side_losses' } });
    expect(outcomes().at(-1)).toMatchObject({ type: 'side_losses', side: 'BLUE', atLeast: 1 });
    fireEvent.change(dialog().getAllByLabelText('Measure how often').at(-1)!, { target: { value: 'mine_strike' } });
    expect(outcomes().at(-1)).toMatchObject({ type: 'mine_strike' });
    fireEvent.change(dialog().getAllByLabelText('Measure how often').at(-1)!, { target: { value: 'intercepts' } });
    expect(outcomes().at(-1)).toMatchObject({ type: 'intercepts', atLeast: 1 });
    fireEvent.change(dialog().getAllByLabelText('Measure how often').at(-1)!, { target: { value: 'hp_below' } });
    expect(outcomes().at(-1)).toMatchObject({ type: 'hp_below', frac: 0.5 });
    fireEvent.click(dialog().getByRole('button', { name: new RegExp(`Remove outcome ${outcomes().at(-1)!.id}`) }));
    expect(outcomes()).toHaveLength(n);
    fireEvent.click(dialog().getByRole('button', { name: 'Remove outcome Carrier is hit' }));
    expect(outcomes().some((o) => o.label === 'Carrier is hit')).toBe(false);
  });

  it('adds, edits and removes variations, whatever the distribution', () => {
    const c = small();
    withController(<RedTeamPanel />, c);
    const vars = () => c.state.get().scenario.redTeam!.perturbations;
    const n = vars().length;
    fireEvent.click(dialog().getByRole('button', { name: '+ Add variation' }));
    expect(vars()).toHaveLength(n + 1);
    const added = vars().at(-1)!;
    expect(added).toMatchObject({ target: { kind: 'environment', field: 'windKt' }, mode: 'add', dist: { type: 'normal' } });

    const row = dialog().getAllByText(added.id)[0].closest('details')!;
    const r = within(row);
    fireEvent.change(r.getByLabelText('Vary: what'), { target: { value: 'cg1' } });
    expect(vars().at(-1)!.target).toMatchObject({ kind: 'unit', unitId: 'cg1' });
    fireEvent.change(r.getByLabelText('Vary: setting'), { target: { value: 'startEastM' } });
    expect(vars().at(-1)!.target).toMatchObject({ field: 'startEastM' });
    expect(r.getByText(/distance in meters/)).toBeTruthy();
    expect(r.queryByLabelText('Applied to the scenario\'s value')).toBeNull();
    fireEvent.change(r.getByLabelText('Vary: setting'), { target: { value: 'pKill' } });
    fireEvent.change(r.getByLabelText('Applied to the scenario\'s value'), { target: { value: 'scale' } });
    expect(vars().at(-1)!.mode).toBe('scale');

    const how = r.getByLabelText('How it varies');
    for (const [type, text] of [['uniform', 'Max'], ['triangular', 'Likeliest'], ['normal', 'Spread (sd)']] as const) {
      fireEvent.change(how, { target: { value: type } });
      expect(vars().at(-1)!.dist.type).toBe(type);
      expect(r.getByLabelText(text)).toBeTruthy();
    }
    const sd = r.getByLabelText('Spread (sd)');
    fireEvent.change(sd, { target: { value: '2.5' } });
    fireEvent.blur(sd);
    expect(vars().at(-1)!.dist).toMatchObject({ type: 'normal', sd: 2.5 });
    fireEvent.change(how, { target: { value: 'choice' } });
    const values = r.getByLabelText('Values');
    fireEvent.change(values, { target: { value: '1, 2, 3' } });
    fireEvent.blur(values);
    const weights = r.getByLabelText('Weights (optional)');
    fireEvent.change(weights, { target: { value: '5, 1, 1' } });
    fireEvent.blur(weights);
    expect(vars().at(-1)!.dist).toEqual({ type: 'choice', values: [1, 2, 3], weights: [5, 1, 1] });
    fireEvent.change(weights, { target: { value: '' } });
    fireEvent.blur(weights);
    expect(vars().at(-1)!.dist).toEqual({ type: 'choice', values: [1, 2, 3] });
    fireEvent.change(values, { target: { value: 'one, two' } });
    fireEvent.blur(values);
    expect(vars().at(-1)!.dist).toEqual({ type: 'choice', values: [1, 2, 3] });

    const name = r.getByLabelText('Name');
    fireEvent.change(name, { target: { value: 'My variation' } });
    expect(vars().at(-1)!.label).toBe('My variation');
    fireEvent.click(dialog().getByRole('button', { name: 'Remove variation My variation' }));
    expect(vars()).toHaveLength(n);
  });

  it('adds, edits and removes a sweep, over the salvo or over a setting', () => {
    const c = small();
    withController(<RedTeamPanel />, c);
    const sweep = () => c.state.get().scenario.redTeam!.sweep;
    expect(sweep()).toBeUndefined();
    fireEvent.click(dialog().getByRole('button', { name: 'Sweep the salvo size' }));
    expect(sweep()!.target).toMatchObject({ kind: 'salvo' });
    expect((sweep()!.target as { unitIds: string[] }).unitIds).toHaveLength(10);
    expect(dialog().getByRole('button', { name: /Run 15 runs/ })).toBeTruthy();
    fireEvent.click(dialog().getByLabelText('Missile 8'));
    expect((sweep()!.target as { unitIds: string[] }).unitIds).toHaveLength(9);
    fireEvent.click(dialog().getByLabelText('Missile 8'));
    expect((sweep()!.target as { unitIds: string[] }).unitIds).toHaveLength(10);
    const sizes = dialog().getByLabelText('Salvo sizes to try');
    fireEvent.change(sizes, { target: { value: '2, 4, 6' } });
    fireEvent.blur(sizes);
    expect(sweep()!.values).toEqual([2, 4, 6]);
    fireEvent.click(dialog().getByRole('button', { name: 'Remove the sweep' }));
    expect(sweep()).toBeUndefined();

    fireEvent.click(dialog().getByRole('button', { name: 'Sweep a setting' }));
    expect(sweep()!.target).toEqual({ kind: 'environment', field: 'windKt' });
    fireEvent.change(dialog().getByLabelText('Sweep: setting'), { target: { value: 'currentKt' } });
    expect(sweep()!.target).toEqual({ kind: 'environment', field: 'currentKt' });
    const vals = dialog().getByLabelText('Values to try');
    fireEvent.change(vals, { target: { value: '0, 3' } });
    fireEvent.blur(vals);
    expect(sweep()!.values).toEqual([0, 3]);
  });

  it('edits everything as JSON, and says what is wrong with bad JSON', () => {
    const c = small();
    withController(<RedTeamPanel />, c);
    fireEvent.click(dialog().getByRole('button', { name: 'Edit all as JSON' }));
    const box = dialog().getByLabelText('Red-team JSON') as HTMLTextAreaElement;
    expect(JSON.parse(box.value).runs).toBe(5);
    fireEvent.change(box, { target: { value: '{nope' } });
    fireEvent.click(dialog().getByRole('button', { name: 'Apply' }));
    expect(dialog().getByText('That is not valid JSON.')).toBeTruthy();
    fireEvent.change(box, { target: { value: JSON.stringify({ ...JSON.parse(JSON.stringify(c.state.get().scenario.redTeam)), runs: 'lots' }) } });
    fireEvent.click(dialog().getByRole('button', { name: 'Apply' }));
    expect(dialog().getByText(/redTeam.runs must be a number/)).toBeTruthy();
    fireEvent.change(box, { target: { value: JSON.stringify({ ...JSON.parse(JSON.stringify(c.state.get().scenario.redTeam)), runs: 9 }) } });
    fireEvent.click(dialog().getByRole('button', { name: 'Apply' }));
    expect(c.state.get().scenario.redTeam!.runs).toBe(9);
    expect(dialog().queryByLabelText('Red-team JSON')).toBeNull();
  });

  it('resets to a suggested setup', () => {
    const c = small();
    withController(<RedTeamPanel />, c);
    fireEvent.click(dialog().getByRole('button', { name: 'Reset to suggested setup' }));
    expect(c.state.get().scenario.redTeam!.runs).toBe(100);
    expect(c.state.get().scenario.redTeam!.sweep).toBeUndefined();
  });

  it('names what is wrong and will not run until it is fixed', () => {
    const c = small();
    c.setRedTeam({ ...c.state.get().scenario.redTeam!, outcomes: [{ id: 'x', type: 'destroyed', unitId: 'ghost' }] });
    withController(<RedTeamPanel />, c);
    expect(dialog().getByRole('alert').textContent).toContain('"ghost"');
    expect((dialog().getByRole('button', { name: /Run 5 runs/ }) as HTMLButtonElement).disabled).toBe(true);
    act(() => c.patchEnvironment({ windKt: 5 }));
    act(() => c.patchScenario({ durationS: 5 }));
    expect(dialog().getByRole('alert').textContent).toContain('scenario has a problem');
  });

  it('runs a batch with progress, then shows each outcome with its chance and interval', async () => {
    const c = small();
    c.setRedTeam({ ...c.state.get().scenario.redTeam!, runs: 12 });
    withController(<RedTeamPanel />, c);
    fireEvent.click(dialog().getByRole('button', { name: 'Run 12 runs' }));
    expect(dialog().getByRole('button', { name: 'Stop' })).toBeTruthy();
    expect(dialog().getByRole('progressbar', { name: 'Progress' })).toBeTruthy();
    const list = await waitFor(() => dialog().getByRole('list', { name: 'Outcome chances' }), { timeout: 30_000 });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(c.state.get().scenario.redTeam!.outcomes.length);
    expect(items[0].textContent).toMatch(/Carrier is hit\d+%\s*±[\d.]+\s*\(\d+%–\d+%\)/);
    expect(within(items[0]).getByRole('img').getAttribute('aria-label')).toMatch(/95% interval/);
    expect(dialog().getByText(/12 runs in/)).toBeTruthy();
    expect(dialog().getByRole('button', { name: 'Run again 12 runs' })).toBeTruthy();
    expect(dialog().queryByRole('progressbar')).toBeNull();
    expect(dialog().getByText('Average per run')).toBeTruthy();
    expect(dialog().getByText('Hits on ships')).toBeTruthy();
  }, 60_000);

  it('can be stopped part way', async () => {
    const c = small();
    c.setRedTeam({ ...c.state.get().scenario.redTeam!, runs: 5000 });
    withController(<RedTeamPanel />, c);
    fireEvent.click(dialog().getByRole('button', { name: /Run 5,000 runs/ }));
    fireEvent.click(dialog().getByRole('button', { name: 'Stop' }));
    await waitFor(() => expect(dialog().getByText(/stopped early/)).toBeTruthy(), { timeout: 30_000 });
  }, 60_000);

  it('draws a curve when sweeping, lets you choose which batch to look at, and picks an outcome for detail', async () => {
    const c = small();
    c.setRedTeam({
      ...c.state.get().scenario.redTeam!,
      runs: 10,
      sweep: { target: { kind: 'salvo', unitIds: ['m1', 'm2', 'm3', 'm4'] }, values: [1, 4] },
    });
    withController(<RedTeamPanel />, c);
    fireEvent.click(dialog().getByRole('button', { name: /Run 20 runs/ }));
    await waitFor(() => expect(dialog().getByRole('img', { name: 'Chance of each outcome at each sweep value' })).toBeTruthy(), { timeout: 30_000 });
    expect(dialog().getByText(/Chance against salvo size/)).toBeTruthy();
    const pick = dialog().getByLabelText('Look in detail at');
    expect(within(pick).getAllByRole('option').map((o) => o.textContent)).toEqual(['1 of 4 enabled', '4 of 4 enabled']);
    fireEvent.change(pick, { target: { value: '0' } });
    fireEvent.click(within(dialog().getByRole('list', { name: 'Outcome chances' })).getByRole('button', { name: /Carrier loses 15%/ }));
    expect(dialog().getByText(/Carrier loses 15%\+ of its strength: \d+ of 10 runs/)).toBeTruthy();
  }, 60_000);

  it('shows what drives an outcome and what time it happens, and replays a run that did or did not', async () => {
    const c = salvoController();
    c.setRedTeam({
      ...salvoScenario().redTeam!,
      runs: 40,
      sweep: undefined,
      perturbations: [{ id: 'p', label: 'Missile 1 hit chance', target: { kind: 'unit', unitId: 'm1', field: 'pHit' }, mode: 'set', dist: { type: 'uniform', min: 0, max: 1 } }],
      outcomes: [{ id: 'm1hit', label: 'Missile 1 hits', type: 'hit', unitId: 'cvn1' }],
    });
    c.toggleRedTeam(true);
    const spy = vi.spyOn(c, 'replayRun');
    withController(<RedTeamPanel />, c);
    fireEvent.click(dialog().getByRole('button', { name: /Run 40 runs/ }));
    await waitFor(() => expect(dialog().getByText(/What drives it/)).toBeTruthy(), { timeout: 30_000 });
    const result = c.state.get().mc.result!;
    const stat = result.groups[0].outcomes[0];
    expect(stat.hits).toBeGreaterThan(0);
    expect(dialog().getByText(new RegExp(`${stat.hits} of 40 runs`))).toBeTruthy();
    expect(dialog().getByRole('img', { name: 'When it happened' })).toBeTruthy();
    expect(dialog().getAllByText('Missile 1 hit chance').length).toBeGreaterThan(1);
    expect(dialog().getByRole('img', { name: /correlation/ })).toBeTruthy();
    const chips = dialog().getAllByRole('button', { name: /^Run \d+$/ });
    fireEvent.click(chips[0]);
    expect(spy).toHaveBeenCalledWith(0, result.groups[0].hitRuns.m1hit[0], 'Missile 1 hits');
    expect(c.state.get().redTeamOpen).toBe(false);
    expect(c.state.get().replay).not.toBeNull();
  }, 60_000);

  it('warns when the scenario has changed since the batch ran', async () => {
    const c = small();
    c.setRedTeam({ ...c.state.get().scenario.redTeam!, runs: 3 });
    withController(<RedTeamPanel />, c);
    fireEvent.click(dialog().getByRole('button', { name: /Run 3 runs/ }));
    await waitFor(() => dialog().getByRole('list', { name: 'Outcome chances' }), { timeout: 30_000 });
    expect(dialog().queryByRole('status')).toBeNull();
    act(() => c.patchEnvironment({ windKt: 30 }));
    expect(dialog().getByRole('status').textContent).toContain('changed since this batch ran');
  }, 60_000);

  it('shows an error when the batch cannot run', async () => {
    const c = salvoController();
    c.toggleRedTeam(true);
    withController(<RedTeamPanel />, c);
    act(() => c.setRedTeam({ ...c.state.get().scenario.redTeam!, perturbations: [{ id: 'bad', target: { kind: 'environment', field: 'windKt' }, mode: 'add', dist: { type: 'uniform', min: 5, max: 1 } }] }));
    expect(dialog().getByRole('alert').textContent).toContain('minimum is above the maximum');
  });
});
