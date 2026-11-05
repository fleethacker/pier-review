import { describe, expect, it, vi } from 'vitest';
import { destination, distanceM } from './geo';
import { evaluateOutcomes, runMonteCarlo, validateRedTeam } from './montecarlo';
import { parseScenario, exportScenario } from './scenarioJson';
import { PRESET_SCENARIOS } from './scenarios';
import { detectionRangeM, readSample, runScenario, seaSpeedFactor, seaStateFromWind, validateScenario } from './sim';
import { eventText } from './status';
import type { Environment, RedTeamSpec, ScenarioConfig, UnitConfig } from './types';

vi.setConfig({ testTimeout: 60_000 });

const C = { lon: -62, lat: 33 };
const still: Environment = { windFromDeg: 0, windKt: 0, currentToDeg: 0, currentKt: 0 };
const unit = (patch: Partial<UnitConfig> & Pick<UnitConfig, 'id'>): UnitConfig => ({
  name: patch.id,
  classId: 'DDG',
  side: 'BLUE',
  start: C,
  headingDeg: 90,
  speedKt: 0,
  behavior: { type: 'hold' },
  magazine: 0,
  ...patch,
});
const scenario = (units: UnitConfig[], patch: Partial<ScenarioConfig> = {}): ScenarioConfig => ({
  id: 't',
  name: 't',
  description: '',
  center: C,
  durationS: 900,
  lightPreset: 'day',
  environment: still,
  units,
  ...patch,
});
const north = (m: number) => destination(C, 0, m);
const range = (sensor: UnitConfig, target: UnitConfig, alt = 0, speed = 0, sea = 0) => detectionRangeM(sensor, 0, target, alt, speed, sea);

describe('detection range', () => {
  const ddg = unit({ id: 'ddg' });

  it('is cut off by the horizon for low targets, however big the radar', () => {
    const skimmer = unit({ id: 'm', classId: 'ASM', side: 'RED' });
    const r = range(ddg, skimmer, 15);
    expect(r).toBeGreaterThan(20_000);
    expect(r).toBeLessThan(40_000);
    expect(range({ ...ddg, radarRangeM: 1_000_000 }, skimmer, 15)).toBeCloseTo(r, 0);
  });

  it('reaches much farther for a high flyer than a sea skimmer', () => {
    const jet = unit({ id: 'j', classId: 'FIGHTER', side: 'RED' });
    expect(range(ddg, jet, 8000)).toBeGreaterThan(range(ddg, unit({ id: 'm', classId: 'ASM', side: 'RED' }), 15) * 5);
  });

  it('shrinks with the fourth root of the signature', () => {
    const jet = unit({ id: 'j', classId: 'FIGHTER', side: 'RED' });
    const normal = range(ddg, jet, 8000);
    const stealthy = range(ddg, { ...jet, signature: 0.0001 }, 8000);
    expect(stealthy / normal).toBeCloseTo(0.1, 1);
  });

  it('is cut by sea clutter on low targets only', () => {
    const skimmer = unit({ id: 'm', classId: 'ASM', side: 'RED' });
    const jet = unit({ id: 'j', classId: 'FIGHTER', side: 'RED' });
    expect(range(ddg, skimmer, 15, 0, 6)).toBeCloseTo(range(ddg, skimmer, 15, 0, 0) * 0.64, 1);
    expect(range(ddg, jet, 8000, 0, 6)).toBe(range(ddg, jet, 8000, 0, 0));
  });

  it('hears a quiet submarine only when it is close, and a fast one from farther', () => {
    const ssn = unit({ id: 's', classId: 'SSN', side: 'RED' });
    const slow = range(ddg, ssn, -30, 4);
    const fast = range(ddg, ssn, -30, 25);
    expect(slow).toBeLessThan(10_000);
    expect(fast).toBeGreaterThan(slow * 1.5);
    // The submarine hears a surface ship from much farther.
    expect(range(ssn, ddg, 0, 15)).toBeGreaterThan(slow * 3);
  });

  it('cannot see mines, a submerged target by radar, or anything with no sensor', () => {
    expect(range(ddg, unit({ id: 'mine', classId: 'MINE', side: 'RED' }))).toBe(0);
    expect(range(unit({ id: 'm', classId: 'ASM' }), ddg)).toBe(0);
    expect(range(unit({ id: 'f', classId: 'FIGHTER' }), unit({ id: 's', classId: 'SSN', side: 'RED' }), -30, 25)).toBe(0);
  });
});

describe('sea state', () => {
  it('follows the wind, to a limit', () => {
    expect(seaStateFromWind(0)).toBe(0);
    expect(seaStateFromWind(15)).toBe(3);
    expect(seaStateFromWind(200)).toBe(8);
  });

  it('slows small craft far more than carriers, and never below 40%', () => {
    expect(seaSpeedFactor('CVN', 6)).toBe(1);
    expect(seaSpeedFactor('FAC', 6)).toBeCloseTo(0.64, 5);
    expect(seaSpeedFactor('FAC', 8)).toBeCloseTo(0.4, 5);
    expect(seaSpeedFactor('FAC', 2)).toBe(1);
    expect(seaSpeedFactor('FIGHTER', 8)).toBe(1);
  });

  it('slows a fast craft in a rough sea when it is on, and not when it is off', () => {
    const units = [unit({ id: 'fac', classId: 'FAC', speedKt: 45, behavior: { type: 'route', waypoints: [north(80_000)] }, headingDeg: 0 })];
    const rough: Environment = { ...still, windKt: 35 };
    const travelled = (patch: Partial<ScenarioConfig>) => {
      const t = runScenario(scenario(units, { environment: rough, durationS: 600, ...patch }));
      return distanceM(readSample(t, 0, 0), readSample(t, t.count - 1, 0));
    };
    const off = travelled({});
    const on = travelled({ seaState: true });
    expect(on / off).toBeGreaterThan(0.5);
    expect(on / off).toBeLessThan(0.7);
    expect(travelled({ seaState: true, environment: still })).toBeCloseTo(travelled({ environment: still }), 0);
  });
});

describe('launches wait for a track', () => {
  // A hostile shooter 100 km from a destroyer (in missile range, far over its radar horizon), with a scout helicopter flying toward it.
  const world = (detection: boolean, scout = true) =>
    scenario(
      [
        unit({ id: 'tgt', start: north(0) }),
        unit({ id: 'shooter', side: 'RED', start: north(100_000), headingDeg: 180 }),
        ...(scout
          ? [unit({ id: 'scout', classId: 'HELO', side: 'RED', start: north(100_000), headingDeg: 180, speedKt: 150, altitudeM: 300, behavior: { type: 'route', waypoints: [north(0)] } })]
          : []),
        unit({ id: 'm', classId: 'ASM', side: 'RED', speedKt: 300, launch: { byId: 'shooter', atS: 10 }, behavior: { type: 'strike', targetId: 'tgt' } }),
      ],
      { detection, durationS: 3000 },
    );

  it('fires on time when everything is visible, even over the horizon', () => {
    const t = runScenario(world(false));
    expect(t.events.find((e) => e.type === 'launch')!.tS).toBe(10);
    expect(t.events.some((e) => e.type === 'held')).toBe(false);
  });

  it('holds the shot until the scout finds the target and it is in range, and says why', () => {
    const t = runScenario(world(true));
    const held = t.events.filter((e) => e.type === 'held');
    expect(held).toHaveLength(1);
    expect(held[0].tS).toBe(10);
    expect(held[0].detail).toBe('not tracked');
    const found = t.events.find((e) => e.type === 'detected' && e.unitId === 'tgt')!;
    expect(found.otherId).toBe('scout');
    const launch = t.events.find((e) => e.type === 'launch')!;
    expect(launch.tS).toBeGreaterThanOrEqual(found.tS);
    expect(t.events.some((e) => e.type === 'hit')).toBe(true);
    expect(eventText(held[0], (id) => id)).toContain('held: not tracked');
  });

  it('never fires if nothing finds the target', () => {
    const t = runScenario(world(true, false));
    expect(t.events.some((e) => e.type === 'launch')).toBe(false);
    expect(t.events.filter((e) => e.type === 'held')).toHaveLength(1);
  });

  it('holds a salvo and lets it go with the planned spacing', () => {
    const base = world(true);
    const more = { ...base, units: [...base.units, ...[2, 3].map((i) => ({ ...base.units.at(-1)!, id: `m${i}`, launch: { byId: 'shooter', atS: 10 + (i - 1) * 4 } }))] };
    const launches = runScenario(more).events.filter((e) => e.type === 'launch').map((e) => e.tS);
    expect(launches).toHaveLength(3);
    expect(launches[1] - launches[0]).toBe(4);
    expect(launches[2] - launches[1]).toBe(4);
  });
});

describe('defences need a track', () => {
  const incoming = (radarRangeM?: number) =>
    scenario(
      [
        unit({ id: 'tgt', classId: 'CG', pKill: 1, magazine: 10, radarRangeM }),
        unit({ id: 'shooter', side: 'RED', start: north(30_000), headingDeg: 180 }),
        unit({ id: 'm', classId: 'ASM', side: 'RED', speedKt: 300, pHit: 1, launch: { byId: 'shooter', atS: 0 }, behavior: { type: 'strike', targetId: 'tgt' } }),
        unit({ id: 'scout', classId: 'HELO', side: 'RED', start: north(15_000), altitudeM: 200 }),
      ],
      { detection: true, durationS: 400 },
    );

  it('shoots down a tracked missile', () => {
    const t = runScenario(incoming());
    expect(t.events.some((e) => e.type === 'intercept')).toBe(true);
    expect(t.events.some((e) => e.type === 'hit')).toBe(false);
  });

  it('cannot shoot at one it never saw, and is hit', () => {
    const blind = runScenario(incoming(0));
    expect(blind.events.some((e) => e.type === 'intercept')).toBe(false);
    expect(blind.events.some((e) => e.type === 'hit')).toBe(true);
  });

  it('is the same as before when sensors are not simulated', () => {
    const s = { ...incoming(0), detection: undefined };
    expect(runScenario(s).events.some((e) => e.type === 'intercept')).toBe(true);
  });
});

describe('decoys', () => {
  const salvo = (decoys?: number, pDecoy?: number) =>
    scenario([
      unit({ id: 'tgt', decoys, pDecoy }),
      unit({ id: 'shooter', side: 'RED', start: north(30_000), headingDeg: 180 }),
      ...[0, 1, 2].map((i) => unit({ id: `m${i}`, classId: 'ASM', side: 'RED', speedKt: 300, pHit: 1, launch: { byId: 'shooter', atS: i * 5 }, behavior: { type: 'strike', targetId: 'tgt' } })),
    ]);

  it('lead weapons away, one decoy per weapon, until they run out', () => {
    const t = runScenario(salvo(2, 1));
    const decoyed = t.events.filter((e) => e.type === 'miss' && e.detail === 'led away by a decoy');
    expect(decoyed).toHaveLength(2);
    expect(t.events.filter((e) => e.type === 'hit')).toHaveLength(1);
  });

  it('do nothing without a chance, and are not there unless given', () => {
    expect(runScenario(salvo(5, 0)).events.filter((e) => e.type === 'hit')).toHaveLength(3);
    expect(runScenario(salvo()).events.filter((e) => e.type === 'hit')).toHaveLength(3);
  });
});

describe('submarines and torpedoes', () => {
  const ambush = (patch: Partial<UnitConfig> = {}, tgt: Partial<UnitConfig> = {}) =>
    scenario(
      [
        unit({ id: 'ssn', classId: 'SSN', side: 'RED', start: north(10_000), headingDeg: 180 }),
        unit({ id: 'tgt', ...tgt }),
        unit({ id: 'tp', classId: 'TORP', side: 'RED', speedKt: 45, pHit: 1, launch: { byId: 'ssn', atS: 0 }, behavior: { type: 'strike', targetId: 'tgt' }, ...patch }),
      ],
      { detection: true, durationS: 900 },
    );

  it('runs a torpedo under the water into a ship, which is damaged', () => {
    const t = runScenario(ambush());
    const hit = t.events.find((e) => e.type === 'hit')!;
    expect(hit.unitId).toBe('tp');
    expect(hit.otherId).toBe('tgt');
    expect(readSample(t, 20, 2).altM).toBeLessThan(0);
    expect(hit.hpAfter).toBe(0);
  });

  it('cannot be shot down by a ship that can shoot down missiles', () => {
    const t = runScenario(ambush({}, { pKill: 1, magazine: 20 }));
    expect(t.events.some((e) => e.type === 'intercept')).toBe(false);
    expect(t.events.some((e) => e.type === 'hit')).toBe(true);
  });

  it('is led away by decoys', () => {
    const t = runScenario(ambush({}, { decoys: 1, pDecoy: 1 }));
    expect(t.events.some((e) => e.type === 'hit')).toBe(false);
    expect(t.events.some((e) => e.detail === 'led away by a decoy')).toBe(true);
  });

  it('runs out of fuel at the end of its range', () => {
    const far = scenario(
      [
        unit({ id: 'ssn', classId: 'SSN', side: 'RED', start: north(60_000) }),
        unit({ id: 'tgt' }),
        unit({ id: 'tp', classId: 'TORP', side: 'RED', speedKt: 45, launch: { byId: 'ssn', atS: 0 }, behavior: { type: 'strike', targetId: 'tgt' } }),
      ],
      { durationS: 3000 },
    );
    const e = runScenario(far).events.find((x) => x.type === 'miss')!;
    expect(e.detail).toBe('out of range');
  });

  it('keeps torpedoes for aimed shots: a missile cannot target a submarine, a torpedo cannot target an aircraft', () => {
    const bad = scenario([
      unit({ id: 'ssn', classId: 'SSN' }),
      unit({ id: 'jet', classId: 'FIGHTER', side: 'RED' }),
      unit({ id: 'x', classId: 'ASM', side: 'RED', launch: { byId: 'jet', atS: 1 }, behavior: { type: 'strike', targetId: 'ssn' } }),
      unit({ id: 'y', classId: 'TORP', side: 'BLUE', launch: { byId: 'ssn', atS: 1 }, behavior: { type: 'strike', targetId: 'jet' } }),
    ]);
    const problems = validateScenario(bad);
    expect(problems.some((p) => /cannot hit a submerged target/.test(p))).toBe(true);
    expect(problems.some((p) => /torpedo cannot hit an aircraft/.test(p))).toBe(true);
  });
});

describe('validation and files', () => {
  it('checks the new unit settings', () => {
    const s = scenario([unit({ id: 'a', signature: 0, radarRangeM: -1, decoys: -2, pDecoy: 2 })]);
    expect(validateScenario(s)).toHaveLength(4);
  });

  it('keeps the new switches and settings through a file', () => {
    const s = scenario([unit({ id: 'a', signature: 0.2, radarRangeM: 50_000, decoys: 3, pDecoy: 0.4 })], { detection: true, seaState: true });
    const back = parseScenario(exportScenario(s));
    expect(back.detection).toBe(true);
    expect(back.seaState).toBe(true);
    expect(back.units[0]).toMatchObject({ signature: 0.2, radarRangeM: 50_000, decoys: 3, pDecoy: 0.4 });
    expect(parseScenario(exportScenario(scenario([unit({ id: 'a' })]))).detection).toBeUndefined();
  });
});

describe('the detected outcome', () => {
  const spec = (bySide?: 'BLUE' | 'RED'): RedTeamSpec => ({ runs: 5, seed: 1, perturbations: [], outcomes: [{ id: 'd', type: 'detected', unitId: 'tgt', ...(bySide ? { bySide } : {}) }] });
  const s = scenario([unit({ id: 'tgt' }), unit({ id: 'foe', side: 'RED', start: north(20_000) })], { detection: true });

  it('happens when a side picks the unit up, and can be limited to one side', () => {
    const traj = runScenario(s);
    expect(evaluateOutcomes(s, traj, spec().outcomes)[0]).toMatchObject({ hit: true, tS: 0 });
    expect(evaluateOutcomes(s, traj, spec('RED').outcomes)[0].hit).toBe(true);
    expect(evaluateOutcomes(s, traj, spec('BLUE').outcomes)[0].hit).toBe(false);
  });

  it('needs sensors switched on to mean anything', () => {
    const off = { ...s, detection: undefined };
    expect(validateRedTeam(off, spec()).some((p) => /Sensors and detection/.test(p))).toBe(true);
    expect(validateRedTeam(s, spec())).toEqual([]);
  });

  it('is measured in a batch', async () => {
    const res = await runMonteCarlo(s, spec('RED'), { workers: 0 });
    expect(res.groups[0].outcomes[0].p).toBe(1);
    expect(res.groups[0].outcomes[0].label).toBe('tgt detected by red');
  });
});

describe('the new presets', () => {
  it.each(['sub-ambush', 'over-the-horizon'])('%s runs and its red-team setup is valid', (id) => {
    const s = PRESET_SCENARIOS.find((p) => p.id === id)!;
    expect(validateScenario(s)).toEqual([]);
    expect(validateRedTeam(s, s.redTeam!)).toEqual([]);
    expect(s.detection && s.seaState).toBe(true);
    expect(runScenario(s).events.length).toBeGreaterThan(5);
    expect(parseScenario(exportScenario(s)).units).toHaveLength(s.units.length);
  });

  it('the ambush: the submarine finds the group first, the escorts never find it, torpedoes hit', () => {
    const s = PRESET_SCENARIOS.find((p) => p.id === 'sub-ambush')!;
    const t = runScenario(s);
    expect(t.events.find((e) => e.type === 'detected' && e.otherId === 'ssn1')).toBeTruthy();
    expect(t.events.some((e) => e.type === 'detected' && e.unitId === 'ssn1')).toBe(false);
    expect(t.events.filter((e) => e.type === 'launch')).toHaveLength(4);
    expect(t.events.some((e) => e.type === 'hit')).toBe(true);
  });

  it('over the horizon: the salvo is held until the helicopter finds the carrier, then flies', () => {
    const s = PRESET_SCENARIOS.find((p) => p.id === 'over-the-horizon')!;
    const t = runScenario(s);
    const held = t.events.filter((e) => e.type === 'held');
    expect(held.length).toBe(8);
    const found = t.events.find((e) => e.type === 'detected' && e.unitId === 'cvn1' && e.otherId === 'rh1')!;
    const launches = t.events.filter((e) => e.type === 'launch');
    expect(launches).toHaveLength(8);
    expect(Math.min(...launches.map((l) => l.tS))).toBeGreaterThanOrEqual(found.tS);
    expect(launches[1].tS - launches[0].tS).toBe(3);
  });

  it('over the horizon: flying the scout higher gets the shot off sooner', () => {
    const s = PRESET_SCENARIOS.find((p) => p.id === 'over-the-horizon')!;
    const firstLaunch = (alt: number) => {
      const c = JSON.parse(JSON.stringify(s)) as ScenarioConfig;
      c.units.find((u) => u.id === 'rh1')!.altitudeM = alt;
      return runScenario(c).events.find((e) => e.type === 'launch')!.tS;
    };
    expect(firstLaunch(1000)).toBeLessThan(firstLaunch(150));
    expect(firstLaunch(150)).toBeLessThan(firstLaunch(50));
  });
});
