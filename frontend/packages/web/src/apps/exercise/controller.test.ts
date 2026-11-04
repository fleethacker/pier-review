import { describe, expect, it } from 'vitest';
import { ExerciseController } from './controller';
import { PRESET_SCENARIOS } from './scenarios';
import { parseScenario } from './scenarioJson';
import { runScenario } from './sim';

const make = () => new ExerciseController(undefined, PRESET_SCENARIOS[0]);

describe('ExerciseController scenario editing', () => {
  it('starts with a run of the first preset and no errors', () => {
    const c = make();
    const s = c.state.get();
    expect(s.errors).toEqual([]);
    expect(s.active.scenario.id).toBe('csg-transit');
    expect(c.clock.durationS).toBe(5400);
  });

  it('re-runs the simulation when the environment changes', () => {
    const c = make();
    const before = c.state.get().active.trajectory;
    c.patchEnvironment({ currentKt: 3, currentToDeg: 180 });
    const after = c.state.get().active.trajectory;
    expect(after).not.toBe(before);
    expect(Array.from(after.data)).not.toEqual(Array.from(before.data));
  });

  it('keeps the last good run on screen while an edit is invalid, then recovers', () => {
    const c = make();
    const good = c.state.get().active;
    c.patchScenario({ durationS: 5 });
    expect(c.state.get().errors.join()).toContain('Duration');
    expect(c.state.get().scenario.durationS).toBe(5);
    expect(c.state.get().active).toBe(good);
    expect(c.clock.durationS).toBe(5400);
    c.patchScenario({ durationS: 600 });
    expect(c.state.get().errors).toEqual([]);
    expect(c.state.get().active.scenario.durationS).toBe(600);
    expect(c.clock.durationS).toBe(600);
  });

  it('adds a unit, selects it and runs it', () => {
    const c = make();
    c.addUnit();
    const s = c.state.get();
    expect(s.scenario.units).toHaveLength(6);
    expect(s.selectedId).toBe(s.scenario.units[5].id);
    expect(s.active.trajectory.unitIds).toHaveLength(6);
  });

  it('turns escorts and pursuers into holds when their leader is removed, and clears the selection', () => {
    const c = make();
    c.select('cvn1');
    c.removeUnit('cvn1');
    const s = c.state.get();
    expect(s.errors).toEqual([]);
    expect(s.scenario.units.find((u) => u.id === 'cg1')!.behavior.type).toBe('hold');
    expect(s.selectedId).toBeNull();
  });

  it('gives a new behavior sensible defaults and refuses escort or pursue with nobody else', () => {
    const c = make();
    c.setBehaviorType('mv1', 'escort');
    const b = c.state.get().scenario.units.find((u) => u.id === 'mv1')!.behavior;
    expect(b.type).toBe('escort');
    c.setBehaviorType('mv1', 'route');
    expect(c.state.get().scenario.units.find((u) => u.id === 'mv1')!.behavior.type).toBe('route');

    const solo = new ExerciseController(undefined, { ...PRESET_SCENARIOS[0], units: [PRESET_SCENARIOS[0].units[0]] });
    solo.setBehaviorType('cvn1', 'pursue');
    expect(solo.state.get().scenario.units[0].behavior.type).toBe('route');
    expect(solo.state.get().notice).toContain('Add another unit');
  });

  it('adds, edits and removes waypoints, converting a non-route unit to a route', () => {
    const c = make();
    c.addWaypoint('cvn1', { lon: -61, lat: 33 });
    let b = c.state.get().scenario.units.find((u) => u.id === 'cvn1')!.behavior;
    expect(b.type === 'route' && b.waypoints).toHaveLength(4);
    c.patchWaypoint('cvn1', 3, { speedKt: 12 });
    b = c.state.get().scenario.units.find((u) => u.id === 'cvn1')!.behavior;
    expect(b.type === 'route' && b.waypoints[3].speedKt).toBe(12);
    c.patchWaypoint('cvn1', 3, { speedKt: undefined });
    b = c.state.get().scenario.units.find((u) => u.id === 'cvn1')!.behavior;
    expect(b.type === 'route' && 'speedKt' in b.waypoints[3]).toBe(false);
    c.removeWaypoint('cvn1', 3);
    b = c.state.get().scenario.units.find((u) => u.id === 'cvn1')!.behavior;
    expect(b.type === 'route' && b.waypoints).toHaveLength(3);

    c.addWaypoint('cg1', { lon: -61.5, lat: 33.1 });
    const cg = c.state.get().scenario.units.find((u) => u.id === 'cg1')!.behavior;
    expect(cg).toMatchObject({ type: 'route' });
  });

  it('does not let a removed last waypoint through', () => {
    const c = make();
    for (let i = 0; i < 3; i++) c.removeWaypoint('mv1', 0);
    expect(c.state.get().errors.join()).toContain('at least one waypoint');
  });

  it('loads presets and the blank scenario, resetting the clock and re-framing the map', () => {
    const c = make();
    c.seek(1000);
    const rev = c.state.get().scenarioRevision;
    c.loadPreset('formation-drill');
    expect(c.state.get().active.scenario.id).toBe('formation-drill');
    expect(c.clock.timeS).toBe(0);
    expect(c.state.get().scenarioRevision).toBe(rev + 1);
    c.loadPreset('blank');
    expect(c.state.get().scenario.units).toHaveLength(1);
  });

  it('round-trips a scenario through JSON and rejects bad input without changing anything', () => {
    const c = make();
    const json = c.exportJson();
    c.loadPreset('formation-drill');
    expect(c.importJson(json)).toBe(true);
    expect(c.state.get().scenario.id).toBe('csg-transit');

    const before = c.state.get().scenario;
    expect(c.importJson('{nope')).toBe(false);
    expect(c.state.get().notice).toContain('not valid JSON');
    expect(c.importJson(JSON.stringify({ ...before, units: [{ ...before.units[0], classId: 'BB' }] }))).toBe(false);
    expect(c.state.get().notice).toContain('classId');
    expect(c.state.get().scenario).toBe(before);
  });
});

describe('scenario JSON', () => {
  it('accepts every preset as written and rejects structural mistakes with a useful message', () => {
    for (const p of PRESET_SCENARIOS) expect(parseScenario(JSON.stringify(p)).id).toBe(p.id);
    const p = PRESET_SCENARIOS[0];
    expect(() => parseScenario('[]')).toThrow(/must be an object/);
    expect(() => parseScenario(JSON.stringify({ ...p, units: 3 }))).toThrow(/units must be a list/);
    expect(() => parseScenario(JSON.stringify({ ...p, environment: { ...p.environment, windKt: 'x' } }))).toThrow(/windKt/);
    expect(() => parseScenario(JSON.stringify({ ...p, units: [{ ...p.units[0], behavior: { type: 'dance' } }] }))).toThrow(/behavior.type/);
    expect(() => parseScenario(JSON.stringify({ ...p, units: [{ ...p.units[1], behavior: { type: 'escort', leaderId: 'ghost', aheadM: 0, abeamM: 0 } }] }))).toThrow(/does not exist/);
  });

  it('fills in a missing name, id and light preset', () => {
    const loose = JSON.parse(JSON.stringify(PRESET_SCENARIOS[2])) as Record<string, unknown> & { units: Record<string, unknown>[] };
    for (const key of ['id', 'lightPreset', 'description']) delete loose[key];
    for (const u of loose.units) delete u.name;
    const parsed = parseScenario(JSON.stringify(loose));
    expect(parsed.id).toBe('imported');
    expect(parsed.lightPreset).toBe('day');
    expect(parsed.units[0].name).toBe(parsed.units[0].id);
  });
});

describe('ExerciseController playback', () => {
  it('advances at the playback rate and stops at the end', () => {
    const c = make();
    c.setRate(60);
    c.play();
    c.clock.tick(2);
    expect(c.clock.timeS).toBe(120);
    c.clock.tick(1e6);
    expect(c.clock.timeS).toBe(c.clock.durationS);
    expect(c.clock.playing).toBe(false);
  });

  it('does not advance while paused, and restarts from the top when played at the end', () => {
    const c = make();
    c.clock.tick(10);
    expect(c.clock.timeS).toBe(0);
    c.seek(1e9);
    expect(c.clock.timeS).toBe(c.clock.durationS);
    c.play();
    expect(c.clock.timeS).toBe(0);
    expect(c.state.get().playing).toBe(true);
    c.pause();
    expect(c.state.get().playing).toBe(false);
  });

  it('notifies listeners and clamps time when the duration shrinks', () => {
    const c = make();
    let calls = 0;
    const off = c.clock.subscribe(() => calls++);
    c.seek(3000);
    expect(calls).toBe(1);
    c.patchScenario({ durationS: 600 });
    expect(c.clock.timeS).toBe(600);
    off();
    c.seek(1);
    expect(calls).toBe(2);
  });

  it('reports ship states at the current time', () => {
    const c = make();
    const start = c.currentStates();
    c.seek(600);
    const later = c.currentStates();
    expect(later[0].lon).toBeGreaterThan(start[0].lon);
  });

  it('only follows a selected ship', () => {
    const c = make();
    c.setFollow('follow');
    expect(c.state.get().follow).toBe('off');
    expect(c.state.get().notice).toContain('Select a ship');
    c.select('cvn1');
    c.setFollow('chase');
    expect(c.state.get().follow).toBe('chase');
    c.select(null);
    expect(c.state.get().follow).toBe('off');
    c.setPlacing(true);
    expect(c.state.get().placing).toBe(false);
  });
});

describe('camera and presentation', () => {
  it('lets the camera orbit with nothing selected, but follow and chase need a ship', () => {
    const c = make();
    c.setFollow('orbit');
    expect(c.state.get().follow).toBe('orbit');
    c.setFollow('follow');
    expect(c.state.get().follow).toBe('orbit');
    expect(c.state.get().notice).toContain('Select a ship');
    c.select('cvn1');
    c.select(null);
    expect(c.state.get().follow).toBe('orbit');
    c.setFollow('off');
    c.select('cvn1');
    c.setFollow('chase');
    c.select(null);
    expect(c.state.get().follow).toBe('off');
  });

  it('turns presentation mode on and off', () => {
    const c = make();
    expect(c.state.get().presenting).toBe(false);
    c.setPresenting(true);
    expect(c.state.get().presenting).toBe(true);
    c.setPresenting(false);
    expect(c.state.get().presenting).toBe(false);
  });
});

describe('simulation cost', () => {
  it('re-runs the longest preset fast enough to do on every edit', () => {
    const preset = PRESET_SCENARIOS.reduce((a, b) => (b.durationS > a.durationS ? b : a));
    const t0 = performance.now();
    runScenario(preset);
    runScenario(preset);
    runScenario(preset);
    const each = (performance.now() - t0) / 3;
    expect(each).toBeLessThan(500);
  });
});
