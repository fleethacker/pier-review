import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { adaptFrame } from './frames';
import type { SimFrame, SimScene } from './frames';
import { entityToFrame } from '../../../scene/geometry';
import { drawableWaterLevelFt, motionSceneParts } from './sceneMapper';
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
    const heaving = { ...v, ship: { ...v.ship, heaveMllwFt: 2, dofs: { ...v.ship.dofs, heave: 'prescribed' as const } } };
    const p = motionSceneParts(heaving, scene, dims);
    expect(p.entities.find((e) => e.id === 'motion-ship')!.pose.z).toBeCloseTo(2 * 0.3048);
    expect(p.notDrawn).not.toContain('heave (not simulated)');
  });

  it('draws tugs that have positions and lines that have endpoints, colored by status', () => {
    expect(parts.entities.some((e) => e.kind === 'motion-tug')).toBe(true);
    expect(parts.links.length).toBeGreaterThan(0);
    const taut = parts.links.find((l) => v.lines.find((x) => `motion-line:${x.lineNumber}` === l.id)?.status === 'taut');
    expect(taut?.status).toBe('NONE'); // taut is a physical state, not a safe-load result
    expect(taut?.color).toBe('#00bcd4');
  });

  it('does not give invalid line loads a reassuring color or load-scaled width', () => {
    const invalid = adaptFrame({ ...frame, validity: { state: 'invalid', reasons: [] } });
    const p = motionSceneParts(invalid, scene, dims);
    expect(p.links.length).toBeGreaterThan(0);
    expect(p.links.every((l) => l.status === 'NONE' && l.widthPx === 2)).toBe(true);
  });

  it('does not invent what a legacy frame lacks', () => {
    const legacy = adaptFrame({ t_s: 1, pose: { x_ft: 10, y_ft: 20, heading_true_deg: 90, u_kt: 0, v_kt: 0, r_degps: 0 }, tugs: [{ tug_id: 'T1', force_lbf: 1, direction_rel_deg: 90 }], lines: [{ line_number: 1, tension_lbf: 5 }], fenders: [], alerts: [] }, {});
    const p = motionSceneParts(legacy, null, null);
    expect(p.entities).toHaveLength(1);
    expect(p.entities[0].geometry.type).toBe('point');
    expect(p.links).toHaveLength(0);
    expect(p.notDrawn).toEqual(expect.arrayContaining(['hull outline', '1 tug position', '1 line (no endpoints supplied)']));
  });

  describe('roll, pitch and water surface (only when the frame supplies them)', () => {
    const withMotion = (pose: Record<string, number | null>, dofs: Record<string, string>, water?: Record<string, unknown>) =>
      adaptFrame(
        {
          ...frame,
          motion: { ...frame.motion!, pose: { ...frame.motion!.pose, ...pose }, dofs: { ...frame.motion!.dofs, ...dofs } },
          environment: water ? { ...frame.environment!, water: { ...frame.environment!.water, ...water } } : frame.environment,
        } as SimFrame,
        { faceBearingDeg: scene.face_bearing_true_deg },
      );
    const shipOf = (p: ReturnType<typeof motionSceneParts>) => p.entities.find((e) => e.id === 'motion-ship')!;

    it('leaves the ship level when the fixture supplies no roll or pitch', () => {
      const s = shipOf(parts);
      expect(s.pose.rollDeg).toBeUndefined();
      expect(s.pose.pitchDeg).toBeUndefined();
    });

    it('draws roll and pitch when simulated or prescribed and present', () => {
      const p = motionSceneParts(withMotion({ roll_deg: 5, pitch_deg: -2 }, { roll: 'simulated', pitch: 'prescribed' }), scene, dims);
      expect(shipOf(p).pose.rollDeg).toBe(5);
      expect(shipOf(p).pose.pitchDeg).toBe(-2);
      expect(p.notDrawn.join(' ')).not.toMatch(/roll|pitch/);
    });

    it('does not draw a value whose dof is not simulated or prescribed, or that is absent', () => {
      const p1 = motionSceneParts(withMotion({ roll_deg: 5, pitch_deg: 3 }, { roll: 'not_simulated', pitch: 'unknown' }), scene, dims);
      expect(shipOf(p1).pose.rollDeg).toBeUndefined();
      expect(shipOf(p1).pose.pitchDeg).toBeUndefined();
      expect(p1.notDrawn).toContain('roll and pitch');
      const p2 = motionSceneParts(withMotion({ roll_deg: 5, pitch_deg: null }, { roll: 'simulated', pitch: 'simulated' }), scene, dims);
      expect(shipOf(p2).pose.rollDeg).toBe(5);
      expect(shipOf(p2).pose.pitchDeg).toBeUndefined();
      expect(p2.notDrawn).toContain('pitch');
      expect(p2.notDrawn).not.toContain('roll and pitch');
    });

    it('does not treat zero as missing: a present 0 is drawn', () => {
      const p = motionSceneParts(withMotion({ roll_deg: 0, pitch_deg: 0 }, { roll: 'simulated', pitch: 'simulated' }), scene, dims);
      expect(p.notDrawn.join(' ')).not.toMatch(/roll|pitch/);
    });

    it('tilts deckhouse parts with the ship about the same pivot', () => {
      const p = motionSceneParts(withMotion({ roll_deg: 5 }, { roll: 'simulated' }), scene, dims);
      const part = p.entities.find((e) => e.kind === 'motion-ship-part')!;
      expect(part.pose.z).toBe(shipOf(p).pose.z);
      expect(part.pose.rollDeg).toBe(5);
      expect(part.geometry.type === 'polygon' && part.geometry.baseM).toBe(6);
    });

    it('lowers the starboard side for a positive roll (right-hand about ship +x, sway +port)', () => {
      const p = motionSceneParts(withMotion({ roll_deg: 5, yaw_deg: 30 }, { roll: 'simulated' }), scene, dims);
      const pose = shipOf(p).pose;
      expect(entityToFrame(pose, 0, 10, 0)[2] - pose.z).toBeCloseTo(10 * Math.sin((5 * Math.PI) / 180)); // port up
      expect(entityToFrame(pose, 0, -10, 0)[2] - pose.z).toBeLessThan(0); // starboard down
      expect(entityToFrame(pose, 50, 0, 0)[2]).toBeCloseTo(pose.z); // bow level
    });

    it('lowers the bow for a positive pitch (right-hand about ship +y)', () => {
      const p = motionSceneParts(withMotion({ pitch_deg: 3 }, { pitch: 'simulated' }), scene, dims);
      const pose = shipOf(p).pose;
      expect(entityToFrame(pose, 50, 0, 0)[2] - pose.z).toBeCloseTo(-50 * Math.sin((3 * Math.PI) / 180));
      expect(entityToFrame(pose, -50, 0, 0)[2]).toBeGreaterThan(pose.z);
    });

    it('draws a water plane at the supplied level, labelled by availability, and excludes it from camera fit', () => {
      const w = parts.entities.find((e) => e.id === 'motion-water')!;
      expect(w.pose.z).toBeCloseTo(2 * 0.3048);
      expect(w.opacity).toBeLessThan(0.5);
      expect(w.excludeFromFit).toBe(true);
      expect(w.selectable).toBe(false);
      expect(parts.notDrawn).not.toContain('water surface');
      expect(drawableWaterLevelFt(v)).toBe(2);
    });

    it('draws no plane and lists water surface when the level is absent or unavailable', () => {
      for (const water of [{ level_mllw_ft: null }, { availability: 'unavailable' }]) {
        const p = motionSceneParts(withMotion({}, {}, water), scene, dims);
        expect(p.entities.some((e) => e.id === 'motion-water')).toBe(false);
        expect(p.notDrawn).toContain('water surface');
      }
      const noEnv = motionSceneParts(adaptFrame({ ...frame, environment: null } as SimFrame, { faceBearingDeg: 90 }), scene, dims);
      expect(noEnv.entities.some((e) => e.kind === 'motion-water')).toBe(false);
      expect(noEnv.notDrawn).toContain('water surface');
    });
  });
});

it('does not draw a numeric heave whose DOF is not simulated', () => {
  const v = adaptFrame(frame);
  const p = motionSceneParts({ ...v, ship: { ...v.ship, heaveMllwFt: 2, dofs: { ...v.ship.dofs, heave: 'not_simulated' } } }, scene, dims);
  expect(p.entities.find((e) => e.id === 'motion-ship')!.pose.z).toBe(0);
});
