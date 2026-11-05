import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  adaptFrame,
  bearingToBerthAngle,
  currentArrow,
  frameIndexAt,
  parseSimMessage,
  shipToBerth,
  utilizationStatus,
  windArrow,
} from './frames';
import type { SimFrame, SimLifecycle, SimRecording, SimScene } from './frames';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const load = <T,>(name: string): T => JSON.parse(readFileSync(path.join(dir, name), 'utf8')) as T;

const frame = load<SimFrame>('sim_frame.json');
const scene = load<SimScene>('sim_scene.json');
const recording = load<SimRecording>('sim_recording_60s.json');

const legacy: SimFrame = {
  t_s: 5,
  pose: { x_ft: 300, y_ft: 80, heading_true_deg: 100, u_kt: 1, v_kt: 0.2, r_degps: 0 },
  tugs: [{ tug_id: 'T1', force_lbf: 4000, direction_rel_deg: 90 }],
  lines: [{ line_number: 1, tension_lbf: 1200 }],
  fenders: [{ fender_id: 'F1', reaction_lbf: 0, compression_ft: 0, status: 'GREEN' }],
  alerts: ['legacy alert text'],
};

describe('rm0 example frame', () => {
  const v = adaptFrame(frame, { faceBearingDeg: scene.face_bearing_true_deg });

  it('reads identity, pose and time from supplied state', () => {
    expect(v.rm0).toBe(true);
    expect(v.tS).toBe(30);
    expect(v.sequence).toBe(32);
    expect(v.ship.x_ft).toBe(300);
    expect(v.ship.yawDeg).toBe(0);
    expect(v.ship.headingTrueDeg).toBe(90);
  });

  it('keeps unsimulated vertical motion null rather than zero', () => {
    expect(v.ship.heaveMllwFt).toBeNull();
    expect(v.ship.rollDeg).toBeNull();
    expect(v.ship.pitchDeg).toBeNull();
    expect(v.ship.dofs.heave).toBe('not_simulated');
    expect(v.ship.dofs.sway).toBe('prescribed');
  });

  it('carries frame validity and provenance for the badges', () => {
    expect(v.badge.validity).toBe('limited');
    expect(v.badge.provenance).toBe('mock');
    expect(v.badge.reasons.length).toBeGreaterThan(0);
  });

  it('reports every unavailable wave component as unavailable, never as a zero height', () => {
    expect(v.environment!.waves.map((w) => w.key)).toEqual(['ocean_swell', 'local_chop', 'ship_wake', 'tug_wake']);
    for (const w of v.environment!.waves) {
      expect(w.part.available).toBe(false);
      expect(w.heightFt).toBeNull();
      expect(w.periodS).toBeNull();
    }
    expect(v.environment!.wind.speedKt).toBe(12);
    expect(v.environment!.water.levelMllwFt).toBe(2);
  });

  it('marks the wave force total unavailable when no wave component is available', () => {
    const wave = v.forces.find((f) => f.key === 'wave')!;
    expect(wave.force).toBeNull();
    expect(wave.availability).toBe('unavailable');
    expect(v.forces.find((f) => f.key === 'wind')!.force).toEqual({ x: 0, y: 500 });
  });

  it('exposes tug kinematics, lines, fittings and fenders', () => {
    expect(v.tugs).toHaveLength(1);
    expect(v.tugs[0].position).not.toBeNull();
    expect(v.tugs[0].velocity).not.toBeNull();
    expect(v.lines.length).toBeGreaterThan(0);
    expect(v.lines[0].shipEnd).not.toBeNull();
    expect(v.fittings.length).toBe(4);
    expect(v.fenders[0].compressionFt).not.toBeNull();
    expect(v.alerts[0].severity).not.toBeNull();
  });
});

describe('legacy frames', () => {
  const v = adaptFrame(legacy, {});

  it('are adapted without rm0 fields and flagged as an assumed berth orientation', () => {
    expect(v.rm0).toBe(false);
    expect(v.assumedFaceBearing).toBe(true);
    expect(v.ship.yawDeg).toBe(90 - 100);
  });

  it('treat absent validity as unknown, never valid', () => {
    expect(v.badge.validity).toBe('unknown');
    expect(v.badge.provenance).toBe('legacy');
  });

  it('shows missing components as unavailable', () => {
    expect(v.environment).toBeNull();
    expect(v.forces).toEqual([]);
    expect(v.tugs[0].position).toBeNull();
    expect(v.tugs[0].legacyForceLbf).toBeNull(); // no validity accompanies this legacy load
    expect(v.lines[0].shipEnd).toBeNull();
    expect(v.lines[0].status).toBe('unknown');
  });

  it('does not invent a severity for plain-text alerts', () => {
    expect(v.alerts).toEqual([{ code: null, severity: null, message: 'legacy alert text', elementIds: [] }]);
  });

  it('uses the supplied face bearing when there is one', () => {
    const w = adaptFrame(legacy, { faceBearingDeg: 120 });
    expect(w.assumedFaceBearing).toBe(false);
    expect(w.ship.yawDeg).toBe(20);
  });
});

describe('motion load validity', () => {
  it.each(['invalid', 'unknown', undefined] as const)('withholds %s component loads even in a usable frame', (state) => {
    const validity = state ? { state, reasons: [] } : undefined;
    const v = adaptFrame({ ...frame,
      line_states: frame.line_states!.map((l) => ({ ...l, validity })),
      fitting_loads: frame.fitting_loads!.map((f) => ({ ...f, validity })),
      fender_states: frame.fender_states!.map((f) => ({ ...f, validity })),
      tug_states: frame.tug_states!.map((t) => ({ ...t, validity })),
      forces: { ...frame.forces!, wind: { ...frame.forces!.wind!, validity } },
    });
    expect(v.badge.validity).toBe('limited');
    expect(v.lines.every((l) => l.tensionLbf === null && l.status === 'unknown')).toBe(true);
    expect(v.fittings.every((f) => f.loadLbf === null && f.status === null)).toBe(true);
    expect(v.fenders.every((f) => f.reactionLbf === null && f.status === null)).toBe(true);
    expect(v.tugs.every((t) => t.actualForce === null && t.legacyForceLbf === null)).toBe(true);
    expect(v.forces.find((f) => f.key === 'wind')!.force).toBeNull();
  });

  it.each(['invalid', 'unknown', undefined] as const)('withholds %s loads without dropping geometry or alerts', (state) => {
    const v = adaptFrame({ ...frame, validity: state ? { state, reasons: [] } : undefined });
    expect(v.lines.every((l) => l.tensionLbf === null && l.status === 'unknown')).toBe(true);
    expect(v.lines[0].shipEnd).not.toBeNull();
    expect(v.fittings.every((f) => f.loadLbf === null && f.utilizationPct === null && f.status === null)).toBe(true);
    expect(v.fenders.every((f) => f.reactionLbf === null && f.status === null)).toBe(true);
    expect(v.tugs.every((t) => t.actualForce === null && t.legacyForceLbf === null)).toBe(true);
    expect(v.forces).toEqual([]);
    expect(v.alerts.length).toBeGreaterThan(0);
  });

  it('does not display an unavailable component as a green result', () => {
    const v = adaptFrame({ ...frame,
      line_states: frame.line_states!.map((l) => ({ ...l, availability: 'unavailable' })),
      fitting_loads: frame.fitting_loads!.map((f) => ({ ...f, availability: 'unavailable', status: 'GREEN' })),
      fender_states: frame.fender_states!.map((f) => ({ ...f, availability: 'unavailable', status: 'GREEN' })),
    });
    expect(v.lines.every((l) => l.status === 'unknown')).toBe(true);
    expect(v.fittings.every((f) => f.status === null)).toBe(true);
    expect(v.fenders.every((f) => f.status === null)).toBe(true);
  });
});

describe('geometry', () => {
  it('rotates ship-local points counterclockwise by yaw, then translates', () => {
    const p = shipToBerth({ x_ft: 10, y_ft: 0 }, { x_ft: 100, y_ft: 50, yawDeg: 90 });
    expect(p.x).toBeCloseTo(100);
    expect(p.y).toBeCloseTo(60);
  });

  it('maps bearings (clockwise) to berth angles (counterclockwise from +x)', () => {
    expect(bearingToBerthAngle(90, 90)).toBe(0);
    expect(bearingToBerthAngle(0, 90)).toBe(90);
  });

  it('points the wind arrow away from where the wind comes from, and the current arrow toward its set', () => {
    // Berth +x faces 090. Wind FROM 180 (south) blows toward north (bearing 000) = berth +y here.
    const w = windArrow(180, 90);
    expect(w.x).toBeCloseTo(0);
    expect(w.y).toBeCloseTo(1);
    // Current TOWARD 090 runs along berth +x.
    const c = currentArrow(90, 90);
    expect(c.x).toBeCloseTo(1);
    expect(c.y).toBeCloseTo(0);
  });
});

describe('recording and lifecycle fixtures', () => {
  it('parses every recording frame and keeps run time monotonic', () => {
    expect(recording.frames.length).toBeGreaterThan(10);
    let last = -1;
    for (const f of recording.frames) {
      const v = adaptFrame(f, { faceBearingDeg: scene.face_bearing_true_deg });
      expect(v.tS).toBeGreaterThanOrEqual(last);
      last = v.tS;
      expect(Number.isFinite(v.ship.x_ft)).toBe(true);
    }
  });

  it('finds the frame at a scrub time', () => {
    const i = frameIndexAt(recording.frames, 30);
    expect(recording.frames[i].t_s).toBeLessThanOrEqual(30);
    expect(frameIndexAt(recording.frames, -5)).toBe(0);
    expect(frameIndexAt(recording.frames, 1e9)).toBe(recording.frames.length - 1);
    expect(frameIndexAt([], 3)).toBe(-1);
  });

  it('classifies socket messages', () => {
    expect(parseSimMessage(frame).kind).toBe('frame');
    expect(parseSimMessage(legacy).kind).toBe('frame');
    for (const s of ['created', 'running', 'paused', 'reset', 'ended', 'error']) {
      const l = load<SimLifecycle>(`sim_lifecycle_${s}.json`);
      const m = parseSimMessage(l);
      expect(m.kind).toBe('lifecycle');
      if (m.kind === 'lifecycle') expect(m.lifecycle.state).toBe(s);
    }
    expect(parseSimMessage({ hello: 1 }).kind).toBe('unknown');
    expect(parseSimMessage(null).kind).toBe('unknown');
  });
});

describe('utilizationStatus', () => {
  it('bands load against capacity and refuses to guess without a rating', () => {
    expect(utilizationStatus(50, 100)).toBe('GREEN');
    expect(utilizationStatus(70, 100)).toBe('AMBER');
    expect(utilizationStatus(120, 100)).toBe('RED');
    expect(utilizationStatus(null, 100)).toBeNull();
    expect(utilizationStatus(50, null)).toBeNull();
  });
});
