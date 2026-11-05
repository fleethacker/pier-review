import { describe, expect, it, vi } from 'vitest';
import { destination } from './geo';
import { runMonteCarlo, validateRedTeam } from './montecarlo';
import { exportScenario, parseScenario } from './scenarioJson';
import { PRESET_SCENARIOS } from './scenarios';
import { buildStaticData, DEFAULT_VIEW } from './scene';
import { SHIP_CLASSES, shipShape } from './ships';
import { detectionRangeM, runScenario, validateScenario } from './sim';
import type { ClassId, Environment, ScenarioConfig, UnitConfig } from './types';

vi.setConfig({ testTimeout: 120_000 });

const C = { lon: -62, lat: 33 };
const still: Environment = { windFromDeg: 0, windKt: 0, currentToDeg: 0, currentKt: 0 };
const unit = (patch: Partial<UnitConfig> & Pick<UnitConfig, 'id'>): UnitConfig => ({ name: patch.id, classId: 'DDG', side: 'BLUE', start: C, headingDeg: 90, speedKt: 0, behavior: { type: 'hold' }, magazine: 0, ...patch });
const scenario = (units: UnitConfig[], patch: Partial<ScenarioConfig> = {}): ScenarioConfig => ({ id: 't', name: 't', description: '', center: C, durationS: 600, lightPreset: 'day', environment: still, units, ...patch });
const range = (sensor: UnitConfig, target: UnitConfig, sensorAlt = 0, targetAlt = 0, speed = 0) => detectionRangeM(sensor, sensorAlt, target, targetAlt, speed, 0);
const north = (m: number) => destination(C, 0, m);

describe('the new unit classes', () => {
  it('draw as proper bodies with parts, big enough to see', () => {
    for (const id of ['UAV', 'AEW', 'DRONE', 'SSK', 'FFG'] as ClassId[]) {
      const cls = SHIP_CLASSES[id];
      const shape = shipShape(id);
      expect(shape.hull.length, id).toBeGreaterThan(4);
      if (cls.domain === 'air') {
        expect(shape.parts.length, id).toBeGreaterThan(1);
        expect(cls.visualBoost, id).toBeGreaterThan(4);
      }
      for (const part of shape.parts) {
        expect(part.base).toBeGreaterThanOrEqual(0);
        expect(part.height).toBeGreaterThan(part.base);
      }
    }
  });

  it('a surveillance drone sees ships from a very long way, and an early-warning aircraft sees a sea skimmer far beyond any ship', () => {
    const uav = unit({ id: 'u', classId: 'UAV' });
    const ship = unit({ id: 's', side: 'RED' });
    expect(range(uav, ship, 3000, 0)).toBeGreaterThan(150_000);
    const skimmer = unit({ id: 'm', classId: 'ASM', side: 'RED' });
    const ddg = unit({ id: 'd' });
    const aew = unit({ id: 'a', classId: 'AEW' });
    expect(range(aew, skimmer, 8000, 15)).toBeGreaterThan(range(ddg, skimmer, 0, 15) * 4);
  });

  it('a small attack drone is hard to pick out, and a diesel submarine is quieter than a nuclear one', () => {
    const ddg = unit({ id: 'd' });
    expect(range(ddg, unit({ id: 'x', classId: 'DRONE', side: 'RED' }), 0, 300)).toBeLessThan(range(ddg, unit({ id: 'm', classId: 'ASM', side: 'RED' }), 0, 300));
    const ssn = range(ddg, unit({ id: 'n', classId: 'SSN', side: 'RED' }), 0, -30, 5);
    const ssk = range(ddg, unit({ id: 'k', classId: 'SSK', side: 'RED' }), 0, -30, 5);
    expect(ssk).toBeLessThan(ssn * 0.7);
  });

  it('a frigate hears a submarine from farther than a destroyer does', () => {
    const sub = unit({ id: 's', classId: 'SSN', side: 'RED' });
    expect(range(unit({ id: 'f', classId: 'FFG' }), sub, 0, -30, 5)).toBeGreaterThan(range(unit({ id: 'd' }), sub, 0, -30, 5));
  });

  it('an attack drone flies low, is shot at like a missile, and does modest damage when it gets through', () => {
    const target = unit({ id: 'tgt', pKill: 0, magazine: 0 });
    const shooter = unit({ id: 'mother', classId: 'CARGO', side: 'RED', start: north(30_000), headingDeg: 180 });
    const drone = (id: string, atS: number) => unit({ id, classId: 'DRONE', side: 'RED', speedKt: 90, pHit: 1, launch: { byId: 'mother', atS }, behavior: { type: 'strike', targetId: 'tgt' } });
    const t = runScenario(scenario([target, shooter, drone('d1', 0), drone('d2', 5)], { durationS: 1200 }));
    const hits = t.events.filter((e) => e.type === 'hit');
    expect(hits).toHaveLength(2);
    expect(hits[0].hpAfter).toBe(75);
    expect(hits[1].hpAfter).toBe(50);
    const defended = runScenario(scenario([{ ...target, pKill: 1, magazine: 10 }, shooter, drone('d1', 0)], { durationS: 1200 }));
    expect(defended.events.some((e) => e.type === 'intercept')).toBe(true);
    expect(defended.events.some((e) => e.type === 'hit')).toBe(false);
  });

  it('a helicopter can sink a submarine it has a track on, with a torpedo', () => {
    const ssn = unit({ id: 'ssn', classId: 'SSN', side: 'RED', start: north(3000), speedKt: 12, behavior: { type: 'hold' } });
    const helo = unit({ id: 'helo', classId: 'HELO', altitudeM: 100 });
    const tp = unit({ id: 'tp', classId: 'TORP', speedKt: 45, pHit: 1, launch: { byId: 'helo', atS: 0 }, behavior: { type: 'strike', targetId: 'ssn' } });
    const t = runScenario(scenario([ssn, helo, tp], { durationS: 600 }));
    expect(t.events.find((e) => e.type === 'hit')?.otherId).toBe('ssn');
  });
});

describe('the large scenarios', () => {
  const LARGE = ['joint-task-force', 'convoy-escort', 'drone-swarm', 'theater-campaign'];
  const get = (id: string) => PRESET_SCENARIOS.find((p) => p.id === id)!;

  it.each(LARGE)('%s is valid, big, mixed, and its red-team setup is valid', (id) => {
    const s = get(id);
    expect(validateScenario(s)).toEqual([]);
    expect(validateRedTeam(s, s.redTeam!)).toEqual([]);
    expect(s.units.length).toBeGreaterThanOrEqual(60);
    expect(new Set(s.units.map((u) => u.id)).size).toBe(s.units.length);
    expect(s.detection && s.seaState).toBe(true);
    const classes = new Set(s.units.map((u) => u.classId));
    for (const c of ['FIGHTER', 'HELO', 'UAV', 'SSN', 'DRONE', 'ASM', 'TORP', 'FFG', 'MINE'] as ClassId[]) {
      if (id === 'drone-swarm' && ['SSN', 'TORP', 'MINE'].includes(c)) continue;
      expect(classes.has(c), `${id} has ${c}`).toBe(true);
    }
    expect(new Set(s.units.map((u) => u.side))).toEqual(new Set(['BLUE', 'RED']));
  });

  it('the theater campaign is the biggest: two axes, four submarines, two minefields, two drone carriers, early warning on both sides', () => {
    const s = get('theater-campaign');
    expect(s.units.length).toBeGreaterThanOrEqual(200);
    expect(s.units.filter((u) => u.classId === 'SSN' || u.classId === 'SSK')).toHaveLength(4);
    expect(s.units.filter((u) => u.classId === 'AEW').map((u) => u.side).sort()).toEqual(['BLUE', 'BLUE', 'RED']);
    expect(s.units.filter((u) => u.classId === 'MINE')).toHaveLength(40);
    expect(new Set(s.units.filter((u) => u.classId === 'DRONE').map((u) => u.launch!.byId)).size).toBe(2);
    expect(s.units.filter((u) => u.side === 'BLUE' && SHIP_CLASSES[u.classId].domain === 'surface' && !SHIP_CLASSES[u.classId].weapon).length).toBeGreaterThanOrEqual(16);
    for (const g of [200, 3000]) expect(runScenario({ ...s, durationS: 3600 }, { seed: g }).events.length).toBeGreaterThan(200);
  });

  it('the task force and the convoy have submarines and mines, and the swarm has two waves of drones', () => {
    for (const id of ['joint-task-force', 'convoy-escort']) {
      const classes = get(id).units.map((u) => u.classId);
      expect(classes.filter((c) => c === 'SSN' || c === 'SSK').length).toBeGreaterThanOrEqual(2);
      expect(classes.filter((c) => c === 'MINE').length).toBeGreaterThanOrEqual(18);
    }
    const launchers = new Set(get('drone-swarm').units.filter((u) => u.classId === 'DRONE').map((u) => u.launch!.byId));
    expect(launchers.size).toBe(2);
  });

  it.each(LARGE)('%s plays out with launches, detections, shots held for a track, interceptions and damage', (id) => {
    const t = runScenario(get(id));
    const types = new Set(t.events.map((e) => e.type));
    for (const need of ['detected', 'launch', 'intercept', 'hit'] as const) expect(types.has(need), `${id} has a ${need}`).toBe(true);
    if (id !== 'drone-swarm') expect(types.has('held')).toBe(true);
  });

  it('shows waypoints only for the selected route, so a hundred units do not bury the map', () => {
    const s = get('joint-task-force');
    expect(buildStaticData(s, DEFAULT_VIEW, null).waypoints.features).toHaveLength(0);
    expect(buildStaticData(s, DEFAULT_VIEW, null).routes.features.length).toBeGreaterThan(5);
    const one = buildStaticData(s, DEFAULT_VIEW, 'cvn1');
    expect(one.waypoints.features.map((f) => f.properties.id)).toEqual(['cvn1']);
    expect(one.handles.features.length).toBe(1);
  });

  it('every part of the task force does something: submarines are found and fire, mines go off, drones get through', () => {
    const t = runScenario(get('joint-task-force'));
    expect(t.events.some((e) => e.type === 'detected' && e.unitId === 'rsub1' && e.otherId)).toBe(true);
    expect(t.events.some((e) => e.type === 'launch' && /^tp[12]x/.test(e.unitId))).toBe(true);
    expect(t.events.some((e) => e.type === 'mine')).toBe(true);
    expect(t.events.filter((e) => e.type === 'launch' && /^dr\d/.test(e.unitId)).length).toBeGreaterThan(10);
  });

  it('losing the early-warning aircraft changes what the task force sees', () => {
    const s = get('joint-task-force');
    const without = JSON.parse(JSON.stringify(s)) as ScenarioConfig;
    without.units.find((u) => u.id === 'aew1')!.disabled = true;
    const firstSeen = (sc: ScenarioConfig) => runScenario(sc).events.find((e) => e.type === 'detected' && e.unitId === 'rf1' && sc.units.find((u) => u.id === e.otherId)?.side === 'BLUE')?.tS ?? Infinity;
    expect(firstSeen(without)).toBeGreaterThanOrEqual(firstSeen(s));
  });

  it('the drone sweep shows more drones, more danger', async () => {
    const s = get('drone-swarm');
    const res = await runMonteCarlo(s, { ...s.redTeam!, runs: 10, perturbations: [], sweep: { target: s.redTeam!.sweep!.target, values: [0, 32] } }, { workers: 0 });
    const p = (g: number) => res.groups[g].outcomes.find((o) => o.id === 'lhd-hit')!.p;
    expect(p(1)).toBeGreaterThan(p(0));
  });

  it.each(LARGE)('%s survives a trip through a file', (id) => {
    const back = parseScenario(exportScenario(get(id)));
    expect(back.units).toHaveLength(get(id).units.length);
    expect(back.redTeam!.outcomes.length).toBe(get(id).redTeam!.outcomes.length);
  });
});
