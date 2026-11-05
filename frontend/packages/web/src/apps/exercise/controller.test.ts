import { describe, expect, it } from 'vitest';
import { ExerciseController } from './controller';
import { prepareRun } from './montecarlo';
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

const salvo = () => PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!;
const unitOf = (c: ExerciseController, id: string) => c.state.get().scenario.units.find((u) => u.id === id)!;

describe('adding aircraft, missiles, mines and salvos', () => {
  it('adds an aircraft with a route, a helicopter that is slower, and a mine that stays put', () => {
    const c = make();
    c.addUnit('FIGHTER');
    const fighter = c.state.get().scenario.units.at(-1)!;
    expect(fighter).toMatchObject({ classId: 'FIGHTER', speedKt: 350, side: 'BLUE' });
    expect(fighter.behavior.type).toBe('route');
    expect(c.state.get().selectedId).toBe(fighter.id);
    expect(c.state.get().errors).toEqual([]);

    c.addUnit('HELO');
    expect(c.state.get().scenario.units.at(-1)!.speedKt).toBe(80);
    c.addUnit('MINE');
    const mine = c.state.get().scenario.units.at(-1)!;
    expect(mine).toMatchObject({ classId: 'MINE', side: 'RED', speedKt: 0, behavior: { type: 'hold' } });
    expect(c.state.get().active.trajectory.unitIds).toHaveLength(8);
  });

  it('adds a missile launched from a unit at one on the other side, or says why it cannot', () => {
    const c = make();
    c.addUnit('ASM');
    const m = c.state.get().scenario.units.at(-1)!;
    expect(m.launch).toEqual({ byId: 'cvn1', atS: 60 });
    expect(m.behavior).toMatchObject({ type: 'strike', targetId: 'mv1' });
    expect(c.state.get().errors).toEqual([]);

    const solo = new ExerciseController(undefined, { ...PRESET_SCENARIOS[0], units: [PRESET_SCENARIOS[0].units[0]] });
    solo.addUnit('SAM');
    expect(solo.state.get().scenario.units).toHaveLength(1);
    expect(solo.state.get().notice).toContain('needs a ship or aircraft');
  });

  it('adds a salvo of missiles launched in turn, with their own ids, on the launcher’s side', () => {
    const c = new ExerciseController(undefined, salvo());
    const before = c.state.get().scenario.units.length;
    c.addSalvo('rdd1', 'cg1', 'ASM', 3, 100, 5);
    const added = c.state.get().scenario.units.slice(before);
    expect(added).toHaveLength(3);
    expect(new Set(c.state.get().scenario.units.map((u) => u.id)).size).toBe(c.state.get().scenario.units.length);
    expect(added.map((u) => u.launch!.atS)).toEqual([100, 105, 110]);
    expect(added.every((u) => u.side === 'RED' && u.behavior.type === 'strike' && u.launch!.byId === 'rdd1')).toBe(true);
    expect(c.state.get().errors).toEqual([]);
  });

  it('refuses a salvo that makes no sense, and caps its size', () => {
    const c = new ExerciseController(undefined, salvo());
    const n = c.state.get().scenario.units.length;
    c.addSalvo('ghost', 'cg1', 'ASM', 3, 0, 5);
    expect(c.state.get().notice).toContain('needs a launcher');
    c.addSalvo('rdd1', 'cg1', 'FIGHTER', 3, 0, 5);
    c.addSalvo('rdd1', 'cg1', 'ASM', 0, 0, 5);
    expect(c.state.get().scenario.units).toHaveLength(n);
    c.addSalvo('rdd1', 'cg1', 'ASM', 500, 0, 1);
    expect(c.state.get().scenario.units).toHaveLength(n + 40);
  });

  it('leaves out units that were to launch from a unit that is removed, and stops missiles aimed at it', () => {
    const c = new ExerciseController(undefined, salvo());
    c.removeUnit('rdd1');
    expect(unitOf(c, 'm1').disabled).toBe(true);
    expect(unitOf(c, 'm1').launch).toBeUndefined();
    expect(unitOf(c, 'rm1').launch).toBeDefined();
    c.removeUnit('cg1');
    expect(unitOf(c, 'rm1').behavior.type).toBe('hold');
    expect(c.state.get().errors).toEqual([]);
  });

  it('switches to circling and striking where that makes sense, and says no where it does not', () => {
    const c = new ExerciseController(undefined, salvo());
    c.setBehaviorType('cvn1', 'loiter');
    expect(unitOf(c, 'cvn1').behavior.type).toBe('route');
    expect(c.state.get().notice).toContain('Only aircraft');
    c.setBehaviorType('rf1', 'loiter');
    expect(unitOf(c, 'rf1').behavior).toMatchObject({ type: 'loiter', radiusM: 4000 });
    c.setBehaviorType('cvn1', 'strike');
    expect(c.state.get().notice).toContain('Only missiles');
    c.setBehaviorType('m1', 'hold');
    c.setBehaviorType('m1', 'strike');
    expect(unitOf(c, 'm1').behavior).toMatchObject({ type: 'strike' });
    expect(c.state.get().errors).toEqual([]);
  });

  it('sets and clears when and by whom a unit is launched', () => {
    const c = new ExerciseController(undefined, salvo());
    c.patchLaunch('m1', { byId: 'rdd1', atS: 500 });
    expect(unitOf(c, 'm1').launch).toEqual({ byId: 'rdd1', atS: 500 });
    c.patchLaunch('m1', null);
    expect(unitOf(c, 'm1').launch).toBeUndefined();
  });

  it('keeps waypoint altitudes only while they are set', () => {
    const c = make();
    c.addUnit('FIGHTER');
    const id = c.state.get().selectedId!;
    c.patchWaypoint(id, 0, { altitudeM: 3000 });
    const wp = () => (unitOf(c, id).behavior.type === 'route' ? (unitOf(c, id).behavior as { waypoints: { altitudeM?: number }[] }).waypoints[0] : null);
    expect(wp()!.altitudeM).toBe(3000);
    c.patchWaypoint(id, 0, { altitudeM: undefined });
    expect('altitudeM' in wp()!).toBe(false);
  });

  it('re-rolls the chance seed, which changes how the chances fall but not the setup', () => {
    const c = new ExerciseController(undefined, salvo());
    const first = JSON.stringify(c.state.get().active.trajectory.events);
    const outcomes = new Set([first]);
    for (let seed = 1; seed <= 12; seed++) {
      c.patchScenario({ seed });
      outcomes.add(JSON.stringify(c.state.get().active.trajectory.events));
    }
    expect(outcomes.size).toBeGreaterThan(3);
    c.patchScenario({ seed: 4 });
    expect(JSON.stringify(c.state.get().active.trajectory.events)).toBe(first);
  });
});

describe('red team in the controller', () => {
  const small = () => {
    const c = new ExerciseController(undefined, salvo());
    c.setRedTeam({ ...c.redTeamSpec(), runs: 4, sweep: { target: { kind: 'salvo', unitIds: ['m1', 'm2', 'm3'] }, values: [1, 3] } });
    return c;
  };

  it('gives a scenario suggested settings the first time the panel opens, and keeps its own after that', () => {
    const c = make();
    expect(c.state.get().scenario.redTeam).toBeUndefined();
    c.toggleRedTeam(true);
    expect(c.state.get().redTeamOpen).toBe(true);
    const made = c.state.get().scenario.redTeam!;
    expect(made.outcomes.length).toBeGreaterThan(0);
    c.toggleRedTeam();
    expect(c.state.get().redTeamOpen).toBe(false);
    c.toggleRedTeam(true);
    expect(c.state.get().scenario.redTeam).toBe(made);
    const own = new ExerciseController(undefined, salvo());
    own.toggleRedTeam(true);
    expect(own.state.get().scenario.redTeam).toEqual(salvo().redTeam);
  });

  it('changes settings without re-running the scenario you are watching', () => {
    const c = new ExerciseController(undefined, salvo());
    const before = c.state.get().active;
    c.seek(300);
    c.setRedTeam({ ...c.redTeamSpec(), runs: 7 });
    expect(c.state.get().scenario.redTeam!.runs).toBe(7);
    expect(c.state.get().active).toBe(before);
    expect(c.clock.timeS).toBe(300);
    expect(c.state.get().errors).toEqual([]);
  });

  it('reports problems with the settings by name, and none for sound ones', () => {
    const c = new ExerciseController(undefined, salvo());
    expect(c.redTeamProblems()).toEqual([]);
    c.setRedTeam({ ...c.redTeamSpec(), outcomes: [{ id: 'x', type: 'destroyed', unitId: 'ghost' }] });
    expect(c.redTeamProblems().join()).toContain('"ghost"');
    expect(make().redTeamProblems()).toEqual([]);
  });

  it('runs a batch, reporting progress, and keeps the setup it measured', async () => {
    const c = small();
    const seen: number[] = [];
    c.state.subscribe(() => seen.push(c.state.get().mc.done));
    const run = c.runRedTeam();
    expect(c.state.get().mc.status).toBe('running');
    void c.runRedTeam();
    await run;
    const { mc } = c.state.get();
    expect(mc.status).toBe('done');
    expect(mc.result!.groups).toHaveLength(2);
    expect(mc.result!.totalRuns).toBe(8);
    expect(mc.done).toBe(8);
    expect(mc.spec!.runs).toBe(4);
    expect(mc.base!.id).toBe('salvo-defense');
    expect(Math.max(...seen)).toBe(8);
  });

  it('stops when asked and keeps what it has', async () => {
    const c = new ExerciseController(undefined, salvo());
    c.setRedTeam({ ...c.redTeamSpec(), runs: 5000, sweep: undefined });
    const run = c.runRedTeam();
    setTimeout(() => c.stopRedTeam(), 50);
    await run;
    expect(c.state.get().mc.status).toBe('done');
    expect(c.state.get().mc.result!.stopped).toBe(true);
    expect(c.state.get().mc.result!.totalRuns).toBeLessThan(5000);
  });

  it('shows why it could not run', async () => {
    const c = new ExerciseController(undefined, salvo());
    c.setRedTeam({ ...c.redTeamSpec(), outcomes: [] });
    await c.runRedTeam();
    expect(c.state.get().mc.status).toBe('error');
    expect(c.state.get().mc.error).toContain('at least one outcome');
  });

  it('replays one run of a finished batch exactly as the batch saw it', async () => {
    const c = small();
    await c.runRedTeam();
    const { mc } = c.state.get();
    const run = mc.result!.groups[1].hitRuns['cv-hit']?.[0] ?? mc.result!.groups[1].missRuns['cv-hit'][0];
    c.seek(200);
    c.replayRun(1, run, 'Carrier is hit');
    const s = c.state.get();
    expect(s.replay).toMatchObject({ run: run + 1, groupLabel: '3 of 3 enabled', outcomeLabel: 'Carrier is hit' });
    expect(s.replay!.values.length).toBeGreaterThan(0);
    expect(s.active.scenario).not.toBe(s.scenario);
    expect(s.active.scenario.units.filter((u) => u.disabled)).toHaveLength(0);
    expect(c.clock.timeS).toBe(0);
    expect(c.clock.playing).toBe(false);
    const prepared = prepareRun(mc.base!, mc.spec!, run, 3);
    expect(s.active.trajectory.events).toEqual(runScenario(prepared.scenario, { seed: prepared.seed }).events);
    // The scenario being edited is untouched, and the other batch shows only one missile of the three.
    expect(s.scenario.units.filter((u) => u.disabled)).toHaveLength(0);
    c.replayRun(0, run);
    expect(c.state.get().active.scenario.units.filter((u) => u.disabled).map((u) => u.id)).toEqual(['m2', 'm3']);
    expect(c.state.get().replay!.groupLabel).toBe('1 of 3 enabled');
  });

  it('goes back from a replay on request, and when the scenario is edited or another is loaded', async () => {
    const c = small();
    await c.runRedTeam();
    c.replayRun(0, 0);
    c.exitReplay();
    expect(c.state.get().replay).toBeNull();
    expect(c.state.get().active.scenario).toBe(c.state.get().scenario);
    expect(c.state.get().active.scenario.units.filter((u) => u.disabled)).toHaveLength(0);

    c.replayRun(0, 1);
    c.patchEnvironment({ windKt: 3 });
    expect(c.state.get().replay).toBeNull();
    expect(c.state.get().active.scenario.environment.windKt).toBe(3);

    c.replayRun(0, 1);
    c.loadPreset('formation-drill');
    expect(c.state.get().replay).toBeNull();
    expect(c.state.get().mc.status).toBe('idle');
    expect(c.state.get().mc.result).toBeNull();
  });

  it('ignores a replay request when there is no result, or no such batch', () => {
    const c = make();
    c.replayRun(0, 0);
    expect(c.state.get().replay).toBeNull();
  });

  it('gives a scenario loaded while the panel is open its own suggested settings', () => {
    const c = make();
    c.toggleRedTeam(true);
    c.loadPreset('blank');
    expect(c.state.get().scenario.redTeam).toBeDefined();
    expect(c.redTeamProblems()).toEqual([]);
    c.toggleRedTeam(false);
    c.loadPreset('formation-drill');
    expect(c.state.get().scenario.redTeam).toBeUndefined();
  });

  it('keeps the red-team settings through export and import', () => {
    const c = new ExerciseController(undefined, salvo());
    c.setRedTeam({ ...c.redTeamSpec(), runs: 12 });
    const json = c.exportJson();
    const d = make();
    expect(d.importJson(json)).toBe(true);
    expect(d.state.get().scenario.redTeam!.runs).toBe(12);
    expect(d.state.get().scenario.seed).toBe(4);
  });
});
