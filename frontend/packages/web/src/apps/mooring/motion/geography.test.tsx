// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MotionCanvas } from './MotionCanvas';
import { contextPaths, GeographyScale, scaleBar } from './MotionGeography';
import { adaptFrame } from './frames';
import type { SimFrame, SimScene } from './frames';
import type { WorkspaceSession } from './workspace';
import { workspace } from './workspace.test-fixtures';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const raw = JSON.parse(readFileSync(path.join(dir, 'sim_frame.json'), 'utf8')) as SimFrame;
const scene = JSON.parse(readFileSync(path.join(dir, 'sim_scene.json'), 'utf8')) as SimScene;
const ring = [[0, 0], [300, 0], [300, -100], [0, -100], [0, 0]].map(([x_ft, y_ft]) => ({ x_ft, y_ft }));
const context: NonNullable<SimScene['geographic_context']> = {
  coordinate_frame: 'berth_ft', coverage: 'partial', coverage_outline: ring,
  features: [{ feature_id: 'land', kind: 'land', name: 'Supplied land', geometry_type: 'Polygon', rings: [ring, ring.map((p) => ({ x_ft: 30 + p.x_ft / 10, y_ft: -30 + p.y_ft / 10 }))], source_date: '20030825' },
    { feature_id: 'edge', kind: 'shoreline_construction', name: 'Pier edge', geometry_type: 'LineString', rings: [[{ x_ft: 0, y_ft: 0 }, { x_ft: 300, y_ft: 0 }]], source_date: null }],
  source: 'https://encdirect.noaa.gov/', attribution: 'NOAA test context', retrieved_at_utc: '2026-11-06T00:00:00Z', limitations: ['Partial archived geometry; no traffic or depth assurance.'], runtime_collision_checks: false,
};
const route: NonNullable<WorkspaceSession['route']> = { route_id: 'test-route', title: 'Authored Norfolk approach', source: 'Synthetic authored demonstration', limitations: ['Not navigational guidance.'], waypoints: [{ name: 'Channel', lat: 36.995, lon: -76.045, speed_kt: 8 }, { name: 'Turn', lat: 37.02, lon: -76.35, speed_kt: 5 }, { name: 'Berth approach', lat: 36.9575, lon: -76.3317, speed_kt: 1 }] };
const origin = { lat: 36.957533, lon: -76.331655, bearingDeg: 99.5 };
afterEach(cleanup);

describe('Bounded Motion geography', () => {
  it('preserves polygon holes and open construction lines without inventing closed land', () => {
    const paths = contextPaths(context);
    expect(paths[0].d.match(/ Z/g)).toHaveLength(2);
    expect(paths[1].d).not.toContain('Z');
    const result = render(<MotionCanvas frame={adaptFrame(raw)} scene={{ ...scene, geographic_context: context, berth_outline: [] }} trail={[]} faceBearingDeg={90} />);
    const land = screen.getByLabelText('Supplied land · supplied Polygon');
    expect(land.getAttribute('fill-rule')).toBe('evenodd');
    expect(land.getAttribute('fill')).toBe('#47534d');
    expect(screen.getByLabelText('Geographic dataset boundary — coverage inside remains partial').getAttribute('fill')).toBe('none');
    const information = screen.getByText('Map information · partial shoreline').closest('details')!;
    expect(information.open).toBe(false);
    fireEvent.click(screen.getByText('Map information · partial shoreline'));
    expect(information.open).toBe(true);
    expect(result.container.querySelector('rect[fill="#3b4a5c"]')).toBeNull();
    expect(screen.getByText(/runtime land collisions not checked/)).toBeTruthy();
    result.rerender(<MotionCanvas frame={adaptFrame(raw)} scene={{ ...scene, geographic_context: context, berth_outline: [] }} trail={[]} faceBearingDeg={90} basemap="satellite" />);
    expect(land.getAttribute('fill')).toBe('none');
    expect(screen.getByText(/Photographed ships are archived background/)).toBeTruthy();
  });
  it('omits incomplete and nonfinite shapes rather than filling assumed geography', () => {
    expect(contextPaths({ ...context, features: [{ ...context.features[0], rings: [ring, [{ x_ft: NaN, y_ft: 0 }, ...ring]] }, { ...context.features[1], rings: [[{ x_ft: null, y_ft: 0 }, { x_ft: 20, y_ft: 0 }]] }] })).toEqual([]);
    render(<MotionCanvas frame={adaptFrame(raw)} scene={{ ...scene, berth_outline: [], geographic_context: null }} trail={[]} faceBearingDeg={90} />);
    expect(screen.getByText(/blank areas are unknown, not confirmed water/)).toBeTruthy();
    expect(screen.queryByLabelText('Supplied finite berth outline')).toBeNull();
  });
  it('opens a distant carrier at readable vessel scale and keeps explicit fits fixed as state advances', () => {
    const f = adaptFrame(raw, { faceBearingDeg: 90 });
    const carrier = { ...workspace.ship, name: 'Carrier', hull_type: 'CVN', loa_ft: 1092, beam_ft: 134 };
    const carrierFrame = { ...f, ship: { ...f.ship, x_ft: 85000, y_ft: 10000, yawDeg: 0 }, tugs: [] };
    const carrierScene = { ...scene, ship_hull_outline: [{ x_ft: -546, y_ft: -67 }, { x_ft: 546, y_ft: -67 }, { x_ft: 546, y_ft: 67 }, { x_ft: -546, y_ft: 67 }] };
    const result = render(<MotionCanvas frame={carrierFrame} scene={carrierScene} shipClass={carrier} route={route} origin={origin} trail={[]} faceBearingDeg={90} />);
    const svg = screen.getByRole('img', { name: 'Plan view of the ship, pier, lines and tugs' });
    const original = svg.getAttribute('viewBox')!;
    expect(1092 / Number(original.split(' ')[2])).toBeGreaterThan(0.5);
    expect(screen.getByLabelText('Authored demonstration route — not navigational guidance')).toBeTruthy();
    expect(screen.getByText(/Above-water overhang unavailable/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Fit berth' })); const berth = svg.getAttribute('viewBox');
    fireEvent.click(screen.getByRole('button', { name: 'Fit route' })); const wholeRoute = svg.getAttribute('viewBox');
    expect(berth).not.toBe(wholeRoute); expect(original).not.toBe(wholeRoute);
    fireEvent.keyDown(svg, { key: 'ArrowLeft' }); const panned = svg.getAttribute('viewBox');
    result.rerender(<MotionCanvas frame={{ ...carrierFrame, ship: { ...carrierFrame.ship, x_ft: 75000 } }} scene={carrierScene} shipClass={carrier} route={route} origin={origin} trail={[]} faceBearingDeg={90} />);
    expect(svg.getAttribute('viewBox')).toBe(panned);
    fireEvent.click(screen.getByRole('button', { name: 'Fit ship' }));
    expect(svg.getAttribute('viewBox')).not.toBe(panned);
  });
  it('keeps the nearby pier visible in an approach start without fitting a far-away trail', () => {
    const f = adaptFrame(raw, { faceBearingDeg: 90 });
    const approach = { ...f, ship: { ...f.ship, x_ft: 696, y_ft: 300, yawDeg: 0 }, tugs: [] };
    const pier = { ...scene, pier_fittings: [
      { ...scene.pier_fittings![0], position: { x_ft: 0, y_ft: 0 } },
      { ...scene.pier_fittings![0], fitting_id: 'far-end', position: { x_ft: 1392, y_ft: 0 } },
    ] };
    render(<MotionCanvas frame={approach} scene={pier} shipClass={{ ...workspace.ship, loa_ft: 567 }} origin={origin} trail={[{ x: 80000, y: 30000 }]} faceBearingDeg={90} />);
    const [x, y, width, height] = screen.getByRole('img', { name: 'Plan view of the ship, pier, lines and tugs' }).getAttribute('viewBox')!.split(' ').map(Number);
    expect(x).toBeLessThan(0); expect(x + width).toBeGreaterThan(1392);
    expect(y).toBeLessThan(-300); expect(y + height).toBeGreaterThan(0);
    expect(width).toBeLessThan(5000);
  });
  it('renders supplied tug length and beam independently of camera or text scale', () => {
    const f = adaptFrame(raw); const tug = f.tugs[0];
    const sized = { ...scene, tug_dimensions: [{ tug_id: tug.id, length_ft: 90, beam_ft: 32, basis: 'synthetic' as const }] };
    render(<MotionCanvas frame={f} scene={sized} route={route} origin={origin} trail={[]} faceBearingDeg={90} />);
    const hull = screen.getByLabelText(`${tug.id} supplied tug footprint`);
    const before = hull.getAttribute('points')!;
    const points = before.split(' ').map((p) => p.split(',').map(Number));
    expect(Math.max(...points.map((p) => p[0])) - Math.min(...points.map((p) => p[0]))).toBe(90);
    expect(Math.max(...points.map((p) => p[1])) - Math.min(...points.map((p) => p[1]))).toBe(32);
    fireEvent.click(screen.getByRole('button', { name: 'Fit route' })); fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(hull.getAttribute('points')).toBe(before);
  });
  it('labels unsized tug symbols and disables route fit when no route is supplied', () => {
    const f = adaptFrame(raw);
    render(<MotionCanvas frame={f} scene={scene} trail={[]} faceBearingDeg={90} />);
    expect(screen.getByLabelText(`${f.tugs[0].id} tug symbol — not to scale`)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Fit route' }) as HTMLButtonElement).disabled).toBe(true);
  });
  it('uses physical display scale including letterboxing and true north orientation', () => {
    expect(scaleBar(1000, 500, 1000, 500)).toEqual({ feet: 50, pixels: 50 });
    expect(scaleBar(1000, 1000, 1000, 500)).toEqual({ feet: 100, pixels: 50 });
    expect(scaleBar(1000, 500, 0, 0)).toBeNull();
    render(<GeographyScale faceBearingDeg={90} scale={scaleBar(1000, 500, 1000, 500)} />);
    const north = screen.getByLabelText('True north');
    expect(Number(north.getAttribute('data-north-x'))).toBeCloseTo(0);
    expect(Number(north.getAttribute('data-north-y'))).toBe(-1);
    expect(screen.getByLabelText('50 feet distance scale')).toBeTruthy();
  });
});
