import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { adaptFrame } from './frames';
import type { SimFrame, SimScene } from './frames';
import { motionSceneParts } from './sceneMapper';
import type { ShipDims } from './sceneMapper';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const load = <T,>(n: string): T => JSON.parse(readFileSync(path.join(dir, n), 'utf8')) as T;
const frame = load<SimFrame>('sim_frame.json');
const scene = load<SimScene>('sim_scene.json');
const dims: ShipDims = { hull: [[-50, -10], [50, -10], [50, 10], [-50, 10]], freeboardM: 6, parts: [{ id: '0', points: [[0, -3], [10, -3], [10, 3], [0, 3]], heightM: 8, liftM: 0 }] };

describe('motionSceneParts', () => {
  const v = adaptFrame(frame, { faceBearingDeg: scene.face_bearing_true_deg });
  const parts = motionSceneParts(v, scene, dims);

  it('places the ship from the frame pose in meters, using the scene hull outline', () => {
    const ship = parts.entities.find((e) => e.id === 'motion-ship')!;
    expect(ship.pose.x).toBeCloseTo(300 * 0.3048);
    expect(ship.pose.y).toBeCloseTo(72.5 * 0.3048);
    expect(ship.pose.headingDeg).toBe(0);
    expect(ship.geometry.type).toBe('polygon');
    if (ship.geometry.type === 'polygon') expect(ship.geometry.points).toHaveLength(scene.ship_hull_outline!.length);
  });

  it('keeps the ship at the waterline and says heave is not drawn when it is not simulated', () => {
    expect(parts.entities.find((e) => e.id === 'motion-ship')!.pose.z).toBe(0);
    expect(parts.notDrawn).toContain('heave (not simulated)');
    expect(parts.notDrawn).toContain('roll and pitch');
  });

  it('follows simulated heave', () => {
    const heaving = { ...v, ship: { ...v.ship, heaveMllwFt: 2 } };
    const p = motionSceneParts(heaving, scene, dims);
    expect(p.entities.find((e) => e.id === 'motion-ship')!.pose.z).toBeCloseTo(2 * 0.3048);
    expect(p.notDrawn).not.toContain('heave (not simulated)');
  });

  it('draws tugs that have positions and lines that have endpoints, colored by status', () => {
    expect(parts.entities.some((e) => e.kind === 'motion-tug')).toBe(true);
    expect(parts.links.length).toBeGreaterThan(0);
    const taut = parts.links.find((l) => v.lines.find((x) => `motion-line:${x.lineNumber}` === l.id)?.status === 'taut');
    expect(taut?.status).toBe('GREEN');
  });

  it('does not invent what a legacy frame lacks', () => {
    const legacy = adaptFrame({ t_s: 1, pose: { x_ft: 10, y_ft: 20, heading_true_deg: 90, u_kt: 0, v_kt: 0, r_degps: 0 }, tugs: [{ tug_id: 'T1', force_lbf: 1, direction_rel_deg: 90 }], lines: [{ line_number: 1, tension_lbf: 5 }], fenders: [], alerts: [] }, {});
    const p = motionSceneParts(legacy, null, null);
    expect(p.entities).toHaveLength(1);
    expect(p.entities[0].geometry.type).toBe('point');
    expect(p.links).toHaveLength(0);
    expect(p.notDrawn).toEqual(expect.arrayContaining(['hull outline', '1 tug position', '1 line (no endpoints supplied)']));
  });
});
