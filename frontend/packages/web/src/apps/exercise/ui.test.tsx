// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
import { PRESET_SCENARIOS } from './scenarios';
import { Side } from './Side';
import { Sidebar } from './Sidebar';

function withController(ui: ReactNode, controller = new ExerciseController(undefined, PRESET_SCENARIOS[0])) {
  return { controller, ...render(<ControllerContext.Provider value={controller}>{ui}</ControllerContext.Provider>) };
}

beforeEach(() => {
  view.created.length = 0;
  localStorage.clear();
});
afterEach(() => {
  cleanup();
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
