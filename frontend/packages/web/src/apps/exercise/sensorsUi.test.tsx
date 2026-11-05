// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { ControllerContext } from './context';
import { ExerciseController } from './controller';
import { RedTeamPanel } from './RedTeam';
import { PRESET_SCENARIOS } from './scenarios';
import { Side } from './Side';
import { Sidebar } from './Sidebar';

afterEach(cleanup);

const preset = (id: string) => PRESET_SCENARIOS.find((p) => p.id === id)!;
function mount(ui: ReactNode, id = 'salvo-defense') {
  const c = new ExerciseController(undefined, preset(id));
  return { c, ...render(<ControllerContext.Provider value={c}>{ui}</ControllerContext.Provider>) };
}
const commit = (el: HTMLElement, value: string) => {
  fireEvent.change(el, { target: { value } });
  fireEvent.blur(el);
};

describe('realism switches', () => {
  it('turns sensors and rough seas on and off, leaving them out of the scenario when off', () => {
    const { c } = mount(<Sidebar />);
    const sensors = screen.getByRole('checkbox', { name: 'Sensors and detection' }) as HTMLInputElement;
    const seas = screen.getByRole('checkbox', { name: 'Rough seas slow small ships' }) as HTMLInputElement;
    expect(sensors.checked).toBe(false);
    fireEvent.click(sensors);
    fireEvent.click(seas);
    expect(c.state.get().scenario).toMatchObject({ detection: true, seaState: true });
    expect(c.state.get().errors).toEqual([]);
    fireEvent.click(sensors);
    fireEvent.click(seas);
    expect('detection' in c.state.get().scenario).toBe(false);
    expect('seaState' in c.state.get().scenario).toBe(false);
  });

  it('shows the sea state next to the wind when rough seas are on', () => {
    const { c } = mount(<Sidebar />);
    expect(screen.queryByText(/Sea state/)).toBeNull();
    act(() => c.patchScenario({ seaState: true }));
    act(() => c.patchEnvironment({ windKt: 30 }));
    expect(screen.getByText(/Sea state 6/)).toBeTruthy();
  });

  it('starts the sensor presets with both switched on', () => {
    mount(<Sidebar />, 'over-the-horizon');
    expect((screen.getByRole('checkbox', { name: 'Sensors and detection' }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('checkbox', { name: 'Rough seas slow small ships' }) as HTMLInputElement).checked).toBe(true);
  });
});

describe('sensors and countermeasures on a unit', () => {
  it('edits signature, radar range, decoys and decoy chance, and leaves them off a missile', () => {
    const { c } = mount(<Sidebar />);
    act(() => c.select('cvn1'));
    fireEvent.click(screen.getByText('Sensors and countermeasures'));
    commit(screen.getByLabelText('Radar signature (1 = normal)'), '0.2');
    commit(screen.getByLabelText('Radar range vs 1 m² (m)'), '80000');
    commit(screen.getByLabelText('Decoys'), '6');
    commit(screen.getByLabelText('Decoy chance (0–1)'), '0.5');
    expect(c.state.get().scenario.units.find((u) => u.id === 'cvn1')).toMatchObject({ signature: 0.2, radarRangeM: 80_000, decoys: 6, pDecoy: 0.5 });
    // Clearing a box puts it back to the class's.
    commit(screen.getByLabelText('Decoys'), '');
    expect(c.state.get().scenario.units.find((u) => u.id === 'cvn1')!.decoys).toBeUndefined();
    act(() => c.select('m1'));
    expect(screen.queryByText('Sensors and countermeasures')).toBeNull();
  });

  it('has no radar range for a submarine, which has no radar', () => {
    const { c } = mount(<Sidebar />, 'sub-ambush');
    act(() => c.select('ssn1'));
    fireEvent.click(screen.getByText('Sensors and countermeasures'));
    expect(screen.queryByLabelText('Radar range vs 1 m² (m)')).toBeNull();
    expect(screen.getByLabelText('Decoys')).toBeTruthy();
  });
});

describe('submarines and torpedoes in the editor', () => {
  it('adds a submarine and a torpedo from the menu', () => {
    const { c } = mount(<Sidebar />, 'sub-ambush');
    const menu = () => screen.getByDisplayValue('Add aircraft, drone, submarine, missile or mine…');
    const before = c.state.get().scenario.units.length;
    fireEvent.change(menu(), { target: { value: 'SSN' } });
    expect(c.state.get().scenario.units).toHaveLength(before + 1);
    expect(c.state.get().scenario.units.at(-1)!.classId).toBe('SSN');
    fireEvent.change(menu(), { target: { value: 'TORP' } });
    const torp = c.state.get().scenario.units.at(-1)!;
    expect(torp).toMatchObject({ classId: 'TORP', behavior: { type: 'strike' } });
    expect(torp.launch).toBeTruthy();
    expect(c.state.get().errors).toEqual([]);
  });

  it('adds each new class from the menu with a sensible default, and the scenario still runs', () => {
    const { c } = mount(<Sidebar />, 'sub-ambush');
    const menu = () => screen.getByDisplayValue('Add aircraft, drone, submarine, missile or mine…');
    for (const id of ['AEW', 'UAV', 'DRONE', 'SSK']) {
      fireEvent.change(menu(), { target: { value: id } });
      expect(c.state.get().scenario.units.at(-1)!.classId).toBe(id);
      expect(c.state.get().errors, id).toEqual([]);
    }
    const [aew, uav, drone, ssk] = c.state.get().scenario.units.slice(-4);
    expect(aew.behavior.type).toBe('route');
    expect(uav.behavior.type).toBe('route');
    expect(drone).toMatchObject({ behavior: { type: 'strike' } });
    expect(drone.launch).toBeTruthy();
    expect(ssk.behavior.type).toBe('route');
  });

  it('shows depth, decoys and signature in the readout of a ship', () => {
    const { c } = mount(<Side />, 'sub-ambush');
    act(() => c.select('ssn1'));
    expect(screen.getByText('Depth').nextSibling?.textContent).toBe('30 m');
    act(() => c.select('cg1'));
    expect(screen.getByText('Decoys').nextSibling?.textContent).toBe('4');
    expect(screen.queryByText('Depth')).toBeNull();
    act(() => c.patchUnit('cg1', { signature: 0.5 }));
    expect(screen.getByText('Radar signature').nextSibling?.textContent).toBe('0.5× normal');
  });
});

describe('the detected outcome in the red-team panel', () => {
  const open = (id: string) => {
    const u = mount(<RedTeamPanel />, id);
    act(() => u.c.toggleRedTeam(true));
    return u;
  };
  const dialog = () => within(screen.getByRole('dialog', { name: 'Red team' }));

  it('adds one, picks who detects, and warns when sensors are off', () => {
    const { c } = open('salvo-defense');
    fireEvent.click(dialog().getByRole('button', { name: '+ Add outcome' }));
    fireEvent.change(dialog().getAllByLabelText('Measure how often').at(-1)!, { target: { value: 'detected' } });
    const last = () => c.state.get().scenario.redTeam!.outcomes.at(-1)!;
    expect(last()).toMatchObject({ type: 'detected' });
    fireEvent.change(dialog().getByLabelText('Detected by'), { target: { value: 'RED' } });
    expect(last()).toMatchObject({ type: 'detected', bySide: 'RED' });
    expect(screen.getByRole('alert').textContent).toContain('Sensors and detection');
    fireEvent.change(dialog().getByLabelText('Detected by'), { target: { value: '' } });
    expect((last() as { bySide?: string }).bySide).toBeUndefined();
    act(() => c.patchScenario({ detection: true }));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('offers the new unit settings to vary, by name', () => {
    const { c } = open('over-the-horizon');
    fireEvent.click(dialog().getByRole('button', { name: '+ Add variation' }));
    const added = c.state.get().scenario.redTeam!.perturbations.at(-1)!;
    const row = dialog().getAllByText(added.id)[0].closest('details')!;
    fireEvent.change(within(row).getByLabelText('Vary: what'), { target: { value: 'cvn1' } });
    const setting = within(row).getByLabelText('Vary: setting') as HTMLSelectElement;
    const labels = Array.from(setting.options).map((o) => o.textContent);
    expect(labels).toEqual(expect.arrayContaining(['Radar signature (1 = normal)', 'Decoys', 'Decoy chance (0–1)', 'Radar range vs 1 m² (m)']));
  });
});
