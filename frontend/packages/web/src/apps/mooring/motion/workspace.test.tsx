// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MotionController } from './controller';
import { MotionView } from './MotionView';
import { MotionCanvas } from './MotionCanvas';
import { adaptFrame } from './frames';
import type { SimFrame, SimScene } from './frames';
import { rasterTiles } from './basemap';
import { EnvironmentFlow } from './EnvironmentFlow';
import { SectionViews } from './SectionViews';
import type { ControlsConfig, TugDynamicsState, StateInput } from './workspace';
import { catalog, controls, loading, prediction, workspace } from './workspace.test-fixtures';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const raw = JSON.parse(readFileSync(path.join(dir, 'sim_frame.json'), 'utf8')) as SimFrame;
const scene = JSON.parse(readFileSync(path.join(dir, 'sim_scene.json'), 'utf8')) as SimScene;
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mounted() {
  const c = new MotionController({ faceBearingDeg: () => 90, tugIds: () => [], lineNumbers: () => [], layoutKey: () => 'test', ensureScenario: async () => null, initialState: () => null });
  const frame = adaptFrame({ ...raw, t_s: 0, controls, loading, line_controls: [{ line_number: 1, attached: false, paid_out_length_ft: 70, geometric_length_ft: 60, extension_ft: 0, tension_lbf: 0 }] }, { faceBearingDeg: 90 });
  c.state.set({ open: true, source: 'live', workspace, catalog, scene, frame, link: 'open', lifecycle: 'paused' });
  render(<MotionView controller={c} workspace />);
  return c;
}

describe('Maneuver workspace', () => {
  it('opens as a paused non-modal workspace with an explicit Start control and no intermediate launch action', () => {
    const c = mounted();
    const start = vi.spyOn(c, 'resume');
    expect(screen.getByRole('dialog', { name: 'Motion view' }).getAttribute('aria-modal')).toBe('false');
    expect(screen.queryByRole('button', { name: 'Open motion view' })).toBeNull();
    expect(start).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Start' }));
    expect(start).toHaveBeenCalledOnce();
  });

  it('collapses details without hiding validity, source or the controls', () => {
    mounted();
    fireEvent.click(screen.getByRole('button', { name: 'Hide details' }));
    expect(screen.queryByRole('complementary', { name: 'Frame readouts' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Show details' }).getAttribute('aria-expanded')).toBe('false');
    expect(screen.getByRole('group', { name: 'Frame validity and provenance' }).textContent).toContain('simulation');
    expect(screen.getByRole('slider', { name: 'Port engine' })).toBeTruthy();
  });

  it('edits orders locally, previews without applying, and applies only on an explicit action', () => {
    const c = mounted();
    const send = vi.spyOn(c, 'helmCommand');
    const preview = vi.spyOn(c, 'refreshPrediction').mockResolvedValue();
    fireEvent.change(screen.getByRole('slider', { name: 'Port engine' }), { target: { value: 50 } });
    expect(send).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Preview order' }));
    expect(preview).toHaveBeenCalledWith(expect.objectContaining({ port_throttle: 0.5 }));
    expect(send).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Apply helm order' }));
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ port_throttle: 0.5 }));
  });

  it('uses independent tug orders when the scenario configures tug dynamics', () => {
    const c = mounted();
    const send = vi.spyOn(c, 'tugMotionCommand');
    const direct = vi.spyOn(c, 'tugCommand');
    const tugId = c.s.frame!.tugs[0].id;
    const commanded = { mode: 'free' as const, target_velocity_x_fps: 0, target_velocity_y_fps: 0, target_heading_true_deg: 90, tow_length_ft: 100 };
    act(() => c.state.set({ workspace: { ...workspace, controls: { ...workspace.controls, tug_dynamics: [{ tug_id: tugId, max_target_speed_fps: 4, basis: 'synthetic' }] as ControlsConfig['tug_dynamics'] } }, frame: { ...c.s.frame!, tugDynamics: [{ tug_id: tugId, commanded, connection_state: 'free', transferred_x_lbf: 0, transferred_y_lbf: 0, contact_compression_ft: 0, tow_tension_lbf: 0 }] as TugDynamicsState[] } }));
    fireEvent.click(screen.getByRole('button', { name: 'Tugs' }));
    expect(screen.queryByRole('spinbutton', { name: 'Tug force (lbf)' })).toBeNull();
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Along-pier target (ft/s)' }), { target: { value: 1.2 } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply tug maneuver' }));
    expect(send).toHaveBeenCalledWith(tugId, { ...commanded, target_velocity_x_fps: 1.2 });
    expect(direct).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Tow length (ft)' }), { target: { value: 10001 } });
    expect((screen.getByRole('button', { name: 'Apply tug maneuver' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('copies supplied simulator velocities as explicitly synthetic input and leaves measured acceleration unknown', () => {
    const c = mounted();
    const apply = vi.spyOn(c, 'importState').mockResolvedValue();
    fireEvent.click(screen.getByText('Import supplied ship or tug state'));
    fireEvent.click(screen.getByRole('button', { name: 'Copy current simulated sample' }));
    const text = screen.getByRole('textbox', { name: 'State observation JSON' }) as HTMLTextAreaElement;
    const input = JSON.parse(text.value) as StateInput;
    expect(input).toMatchObject({ source: 'synthetic', entity_id: workspace.ship.class_id, surge_fps: c.s.frame!.ship.surgeFps, sway_fps: c.s.frame!.ship.swayFps, measured_acceleration: null });
    fireEvent.click(screen.getByRole('button', { name: 'Import into paused run' }));
    expect(apply).toHaveBeenCalledWith(input);
    act(() => c.state.set({ lifecycle: 'running' }));
    expect((screen.getByRole('button', { name: 'Import into paused run' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows missing seabed and clearance as unavailable in sectional views', () => {
    mounted();
    fireEvent.click(screen.getByRole('button', { name: 'Forward' }));
    expect(screen.getByRole('img', { name: /forward hull/ })).toBeTruthy();
    expect(screen.getByText(/Local seabed \/ clearance unavailable/)).toBeTruthy();
    expect(screen.queryByText(/0.00 ft \/ 0.00 ft/)).toBeNull();
  });

  it.each(['forward', 'aft'] as const)('keeps a port-side payload on the labelled port side in the %s view', (view) => {
    const c = mounted(); cleanup();
    const frame = { ...c.s.frame!, ship: { ...c.s.frame!.ship, rollDeg: 0, pitchDeg: 0 }, loading: { ...loading, payloads: [{ payload_id: 'p1', label: 'Port cargo', weight_lbf: 1, x_ft: 0, y_ft: 10, z_ft: 0 }] } };
    const result = render(<SectionViews s={{ ...c.s, frame }} view={view} />);
    const point = screen.getByText(/Port cargo/).parentElement!.querySelector('rect')!;
    const center = Number(point.getAttribute('x')) + Number(point.getAttribute('width')) / 2;
    if (view === 'forward') expect(center).toBeGreaterThan(450);
    else expect(center).toBeLessThan(450);
    expect(result.container.textContent).toContain('PORT');
  });

  it('retains supplied grounding evidence when the loading model is invalid', () => {
    const c = mounted(); cleanup();
    const frame = { ...c.s.frame!, loading: { ...loading, local_depth_mllw_ft: 18, depth_uncertainty_ft: 0.5, under_keel_ft: -1, under_keel_lower_ft: -1.5, validity: { state: 'invalid' as const, reasons: [{ code: 'GROUNDING', message: 'Modeled keel intersects supplied seabed.' }] } } };
    render(<SectionViews s={{ ...c.s, frame }} view="side" />);
    expect(screen.getByText('-1.00 ft / -1.50 ft')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('intersects supplied seabed');
    expect(screen.getByText(/Local supplied seabed: 18.0/)).toBeTruthy();
    expect(screen.queryByText(/outside supplied depth coverage/)).toBeNull();
    expect(screen.getByText(/Hull section unavailable: invalid/)).toBeTruthy();
  });

  it('keeps horizon truncation and unchecked hazards visible on the primary view', () => {
    const c = mounted();
    act(() => c.state.set({ prediction }));
    expect(screen.getByText(/TRUNCATED prediction/)).toBeTruthy();
    expect(screen.getByText(/Unchecked: coastline, traffic/)).toBeTruthy();
    expect(screen.getByText(/uncertainty unavailable/)).toBeTruthy();
  });

  it('opens an editable builder, retains the selected source, and loads paused through the controller', () => {
    const c = mounted();
    const load = vi.spyOn(c, 'loadWorkspace').mockResolvedValue();
    fireEvent.click(screen.getByRole('button', { name: 'Build scenario' }));
    expect(screen.getByRole('dialog', { name: 'Scenario builder' })).toBeTruthy();
    fireEvent.change(screen.getByRole('textbox', { name: 'Scenario name' }), { target: { value: 'Edited maneuver' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Wind speed (kt)' }), { target: { value: '18' } });
    fireEvent.click(screen.getByRole('button', { name: 'Load paused scenario' }));
    expect(load).toHaveBeenCalledWith(expect.objectContaining({ name: 'Edited maneuver', environment_mode: 'synthetic', environment: expect.objectContaining({ wind_speed_kt: 18 }) }));
  });

  it('reopens a saved custom configuration and resolves editable propulsion without allocating a session', async () => {
    const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('/configuration') ? { ...workspace.scenario.configuration, name: 'Saved custom ship', controls: workspace.controls } : [] }));
    vi.stubGlobal('fetch', fetcher);
    const c = mounted();
    const load = vi.spyOn(c, 'loadWorkspace').mockResolvedValue();
    const saved = { ...workspace.scenario, motion_scenario_id: 'custom-1', configuration: { ...workspace.scenario.configuration, name: 'Saved custom ship', controls: null } };
    act(() => c.state.set({ savedScenarios: [saved] }));
    fireEvent.click(screen.getByRole('button', { name: 'Build scenario' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved scenarios' }), { target: { value: 'custom-1' } });
    expect((screen.getByRole('textbox', { name: 'Scenario name' }) as HTMLInputElement).value).toBe('Saved custom ship');
    fireEvent.click(screen.getByText('Engine, rudder and thruster parameters'));
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Resolve training parameters' })));
    expect(load).not.toHaveBeenCalled();
    expect(fetcher.mock.calls.some(([url]) => url.endsWith('/sessions'))).toBe(false);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Ahead thrust per shaft (lbf)' }), { target: { value: '123456.7' } });
    fireEvent.click(screen.getByRole('button', { name: 'Load paused scenario' }));
    expect(load).toHaveBeenCalledWith(expect.objectContaining({ name: 'Saved custom ship', controls: expect.objectContaining({ propulsion: expect.objectContaining({ max_ahead_thrust_lbf: 123456.7, basis: 'synthetic', source: expect.stringContaining('User-authored') }) }) }));
  });

  it('never lets a delayed configuration resolver overwrite later builder edits', async () => {
    let finish!: (value: unknown) => void;
    vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/configuration') ? new Promise((r) => { finish = r; }) : Promise.resolve({ ok: true, json: async () => [] })));
    mounted();
    fireEvent.click(screen.getByRole('button', { name: 'Build scenario' }));
    fireEvent.click(screen.getByText('Engine, rudder and thruster parameters'));
    fireEvent.click(screen.getByRole('button', { name: 'Resolve training parameters' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Scenario name' }), { target: { value: 'Later edit' } });
    await act(async () => finish({ ok: true, json: async () => ({ ...workspace.scenario.configuration, name: 'Old resolved name', controls: workspace.controls }) }));
    expect((screen.getByRole('textbox', { name: 'Scenario name' }) as HTMLInputElement).value).toBe('Later edit');
    expect(screen.queryByRole('spinbutton', { name: 'Ahead thrust per shaft (lbf)' })).toBeNull();
  });
});

describe('Token-free geography and environmental display', () => {
  it('uses only a bounded visible tile set and preserves north/east orientation at an east-facing berth', () => {
    const layer = rasterTiles({ lat: 36.95, lon: -76.33, bearingDeg: 90 }, { x: -200, y: -100, w: 1400, h: 900 }, 'satellite');
    expect(layer.tiles.length).toBeGreaterThan(0);
    expect(layer.tiles.length).toBeLessThan(80);
    expect(layer.tiles.every((t) => t.url.startsWith('https://services.arcgisonline.com/') && !t.url.includes('token'))).toBe(true);
    const matrix = layer.transform.match(/matrix\((.*)\)/)![1].split(' ').map(Number);
    expect(matrix[0]).toBeGreaterThan(0); // image east is berth +x
    expect(matrix[3]).toBeLessThan(0); // image south is berth -y
    expect(Math.abs(matrix[1])).toBeLessThan(1e-9);
  });

  it('retains the vessel schematic and attribution when imagery fails', () => {
    const f = adaptFrame(raw, { faceBearingDeg: 90 });
    const result = render(<MotionCanvas frame={f} scene={scene} trail={[]} faceBearingDeg={90} basemap="satellite" origin={{ lat: 36.95, lon: -76.33, bearingDeg: 90 }} />);
    const tile = result.container.querySelector('image')!;
    fireEvent.error(tile);
    expect(screen.getByText(/Imagery incomplete/)).toBeTruthy();
    expect(screen.getByRole('link', { name: /Imagery.*Esri/ })).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Plan view of the ship, pier, lines and tugs' }).querySelectorAll('polygon').length).toBeGreaterThan(0);
  });

  it('does not request imagery without a supplied geographic origin', () => {
    const result = render(<MotionCanvas frame={adaptFrame(raw)} scene={scene} trail={[]} faceBearingDeg={90} basemap="satellite" />);
    expect(result.container.querySelectorAll('image')).toHaveLength(0);
    expect(screen.getByText(/Geographic origin unavailable/)).toBeTruthy();
  });

  it('draws only remaining prediction samples with ticks relative to the current simulation time', () => {
    render(<MotionCanvas frame={{ ...adaptFrame(raw), tS: 5 }} scene={scene} trail={[]} faceBearingDeg={90} prediction={prediction} />);
    expect(screen.getByText('+5 s')).toBeTruthy();
    expect(screen.queryByText('+0 s')).toBeNull();
    expect(screen.queryByText('+10 s')).toBeNull();
  });

  it('moves flow only when simulation time changes and respects static and unavailable states', () => {
    const frame = adaptFrame(raw, { faceBearingDeg: 90 });
    const bounds = { x: 0, y: 0, w: 1000, h: 600 };
    const display = { wind: true, current: true, animate: true };
    const result = render(<svg><EnvironmentFlow frame={frame} bounds={bounds} faceBearingDeg={90} display={display} /></svg>);
    const before = result.container.querySelector('path')!.getAttribute('d');
    result.rerender(<svg><EnvironmentFlow frame={{ ...frame }} bounds={bounds} faceBearingDeg={90} display={display} /></svg>);
    expect(result.container.querySelector('path')!.getAttribute('d')).toBe(before);
    result.rerender(<svg><EnvironmentFlow frame={{ ...frame, tS: frame.tS + 0.5 }} bounds={bounds} faceBearingDeg={90} display={display} /></svg>);
    expect(result.container.querySelector('path')!.getAttribute('d')).not.toBe(before);
    result.rerender(<svg><EnvironmentFlow frame={frame} bounds={bounds} faceBearingDeg={90} display={{ ...display, animate: false }} /></svg>);
    expect(result.container.querySelector('[data-flow="wind"]')?.getAttribute('data-sim-time')).toBe('static');
    result.rerender(<svg><EnvironmentFlow frame={{ ...frame, environment: null }} bounds={bounds} faceBearingDeg={90} display={display} /></svg>);
    expect(result.container.querySelectorAll('path')).toHaveLength(0);
  });
});
