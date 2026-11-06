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
import { catalog, controls, loading, prediction, workspace } from './workspace.test-fixtures';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const raw = JSON.parse(readFileSync(path.join(dir, 'sim_frame.json'), 'utf8')) as SimFrame;
const scene = JSON.parse(readFileSync(path.join(dir, 'sim_scene.json'), 'utf8')) as SimScene;
afterEach(cleanup);

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

  it('shows missing seabed and clearance as unavailable in sectional views', () => {
    mounted();
    fireEvent.click(screen.getByRole('button', { name: 'Forward' }));
    expect(screen.getByRole('img', { name: /forward hull/ })).toBeTruthy();
    expect(screen.getByText(/Local seabed \/ clearance unavailable/)).toBeTruthy();
    expect(screen.queryByText(/0.00 ft \/ 0.00 ft/)).toBeNull();
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
