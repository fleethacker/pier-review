import { describe, expect, it } from 'vitest';
import { angleDiff, bearingTo, destination, distanceM, ktToMs, offsetM, stationFrom } from './geo';
import { runScenario, statesAt, trailOf, unitStateAt, validateScenario } from './sim';
import type { Environment, ScenarioConfig, UnitConfig } from './types';

const C = { lon: -62, lat: 33 };
const still: Environment = { windFromDeg: 0, windKt: 0, currentToDeg: 0, currentKt: 0 };

function unit(patch: Partial<UnitConfig> & Pick<UnitConfig, 'id'>): UnitConfig {
  return {
    name: patch.id,
    classId: 'DDG',
    side: 'BLUE',
    start: C,
    headingDeg: 90,
    speedKt: 15,
    behavior: { type: 'hold' },
    ...patch,
  };
}

function scenario(units: UnitConfig[], environment = still, durationS = 1200): ScenarioConfig {
  return {
    id: 't',
    name: 't',
    description: '',
    center: C,
    durationS,
    lightPreset: 'day',
    environment,
    units,
  };
}

describe('validateScenario', () => {
  it('accepts a sound scenario', () => {
    expect(validateScenario(scenario([unit({ id: 'a' })]))).toEqual([]);
  });

  it('rejects duplicate ids, missing leaders, self and circular escorts, empty routes and bad durations', () => {
    const dup = validateScenario(scenario([unit({ id: 'a' }), unit({ id: 'a' })]));
    expect(dup.join()).toContain('share the id');

    const missing = validateScenario(scenario([unit({ id: 'a', behavior: { type: 'escort', leaderId: 'zz', aheadM: 0, abeamM: 0 } })]));
    expect(missing.join()).toContain('does not exist');

    const self = validateScenario(scenario([unit({ id: 'a', behavior: { type: 'escort', leaderId: 'a', aheadM: 0, abeamM: 0 } })]));
    expect(self.join()).toContain('itself');

    const loop = validateScenario(
      scenario([
        unit({ id: 'a', behavior: { type: 'escort', leaderId: 'b', aheadM: 0, abeamM: 0 } }),
        unit({ id: 'b', behavior: { type: 'escort', leaderId: 'a', aheadM: 0, abeamM: 0 } }),
      ]),
    );
    expect(loop.join()).toContain('loops back');

    expect(validateScenario(scenario([unit({ id: 'a', behavior: { type: 'route', waypoints: [] } })])).join()).toContain('waypoint');
    expect(validateScenario(scenario([unit({ id: 'a', behavior: { type: 'pursue', targetId: 'x', standoffM: 1 } })])).join()).toContain('does not exist');
    expect(validateScenario({ ...scenario([]), durationS: 5 }).join()).toContain('Duration');
    expect(validateScenario(scenario([unit({ id: 'a', start: { lon: 0, lat: 89 } })])).join()).toContain('out of range');
  });

  it('refuses to run an invalid scenario', () => {
    expect(() => runScenario({ ...scenario([]), durationS: 5 })).toThrow(/Duration/);
  });
});

describe('route following', () => {
  it('steams to a waypoint at cruise speed and stops there', () => {
    const target = destination(C, 90, 4000);
    const s = scenario([unit({ id: 'a', speedKt: 15, behavior: { type: 'route', waypoints: [{ ...target }] } })], still, 1200);
    const t = runScenario(s);
    const end = unitStateAt(t, 0, 1200);
    expect(distanceM(end, target)).toBeLessThan(300);
    expect(end.speedKt).toBeLessThan(0.1);
    // Mid-run it is making its cruise speed.
    expect(unitStateAt(t, 0, 100).speedKt).toBeCloseTo(15, 1);
  });

  it('limits acceleration and turn rate to the class', () => {
    const s = scenario([unit({ id: 'a', classId: 'CVN', speedKt: 0, headingDeg: 0, behavior: { type: 'route', waypoints: [{ ...destination(C, 180, 20000), speedKt: 30 }] } })]);
    const t = runScenario(s);
    // CVN accelerates at 0.08 kt/s: after 60 s it cannot exceed 4.8 kt.
    expect(unitStateAt(t, 0, 60).speedKt).toBeLessThanOrEqual(4.81);
    // And it needs ~150 s to come round 180 degrees at 1.2 deg/s at best.
    expect(Math.abs(angleDiff(unitStateAt(t, 0, 30).headingDeg, 0))).toBeLessThan(36.1);
  });

  it('applies the per-leg speed and loops when asked', () => {
    const a = destination(C, 90, 3000);
    const b = destination(a, 0, 3000);
    const s = scenario(
      [unit({ id: 'a', speedKt: 10, behavior: { type: 'route', loop: true, waypoints: [{ ...a, speedKt: 20 }, { ...b, speedKt: 10 }] } })],
      still,
      3600,
    );
    const t = runScenario(s);
    expect(unitStateAt(t, 0, 200).speedKt).toBeCloseTo(20, 0);
    // Still moving at the end: it never ran out of waypoints.
    expect(unitStateAt(t, 0, 3600).speedKt).toBeGreaterThan(5);
  });

  it('does not hang when every looped waypoint is already reached', () => {
    const s = scenario([unit({ id: 'a', behavior: { type: 'route', loop: true, waypoints: [{ ...C }, { ...offsetM(C, 10, 10) }] } })], still, 120);
    expect(() => runScenario(s)).not.toThrow();
  });
});

describe('environment', () => {
  it('lets a held ship drift with the current', () => {
    const env: Environment = { ...still, currentToDeg: 90, currentKt: 2 };
    const t = runScenario(scenario([unit({ id: 'a', speedKt: 0 })], env, 1800));
    const end = unitStateAt(t, 0, 1800);
    expect(distanceM(C, end)).toBeCloseTo(ktToMs(2) * 1800, -1);
    expect(bearingTo(C, end)).toBeCloseTo(90, 0);
    expect(end.sogKt).toBeCloseTo(2, 1);
    expect(end.cogDeg).toBeCloseTo(90, 0);
  });

  it('adds the current to a ship under way', () => {
    const env: Environment = { ...still, currentToDeg: 90, currentKt: 2 };
    const target = destination(C, 90, 50000);
    const t = runScenario(scenario([unit({ id: 'a', speedKt: 10, behavior: { type: 'route', waypoints: [target] } })], env, 600));
    expect(unitStateAt(t, 0, 600).sogKt).toBeCloseTo(12, 0);
  });

  it('pushes a ship downwind a little, more for a small craft', () => {
    const env: Environment = { ...still, windFromDeg: 270, windKt: 40 };
    const t = runScenario(
      scenario([unit({ id: 'big', classId: 'DDG', speedKt: 0 }), unit({ id: 'small', classId: 'FAC', speedKt: 0 })], env, 1800),
    );
    const [big, small] = statesAt(t, 1800);
    expect(big.lon).toBeGreaterThan(C.lon);
    expect(small.lon).toBeGreaterThan(big.lon);
  });
});

describe('station keeping', () => {
  it('holds an escort on its station through a turn', () => {
    const leaderRoute = [destination(C, 90, 8000), destination(destination(C, 90, 8000), 0, 8000)];
    const station = { aheadM: 800, abeamM: 1500 };
    const s = scenario(
      [
        unit({ id: 'lead', classId: 'CG', speedKt: 16, behavior: { type: 'route', waypoints: leaderRoute } }),
        unit({
          id: 'esc',
          start: stationFrom(C, 90, station.aheadM - 300, station.abeamM + 200),
          speedKt: 16,
          behavior: { type: 'escort', leaderId: 'lead', ...station },
        }),
      ],
      { ...still, currentToDeg: 30, currentKt: 1 },
      1500,
    );
    const t = runScenario(s);
    // Straight run, before the turn.
    for (const at of [500, 600]) {
      const [lead, esc] = statesAt(t, at);
      expect(distanceM(esc, stationFrom(lead, lead.headingDeg, station.aheadM, station.abeamM))).toBeLessThan(80);
    }
    // After the leader has settled on the new leg.
    const [lead, esc] = statesAt(t, 1450);
    expect(distanceM(esc, stationFrom(lead, lead.headingDeg, station.aheadM, station.abeamM))).toBeLessThan(150);
    expect(Math.abs(angleDiff(esc.headingDeg, lead.headingDeg))).toBeLessThan(10);
  });

  it('runs to a distant station at full speed', () => {
    const s = scenario(
      [
        unit({ id: 'lead', speedKt: 12, behavior: { type: 'route', waypoints: [destination(C, 90, 40000)] } }),
        unit({ id: 'esc', start: destination(C, 270, 5000), speedKt: 12, behavior: { type: 'escort', leaderId: 'lead', aheadM: 0, abeamM: 1000 } }),
      ],
      still,
      1800,
    );
    const t = runScenario(s);
    expect(unitStateAt(t, 1, 300).speedKt).toBeGreaterThan(20);
    const [lead, esc] = statesAt(t, 1800);
    expect(distanceM(esc, stationFrom(lead, lead.headingDeg, 0, 1000))).toBeLessThan(100);
  });
});

describe('pursuit', () => {
  it('closes on a target and shadows it', () => {
    const s = scenario(
      [
        unit({ id: 'prey', speedKt: 12, headingDeg: 0, behavior: { type: 'route', waypoints: [destination(C, 0, 60000)] } }),
        unit({ id: 'hunter', start: destination(C, 270, 12000), speedKt: 28, behavior: { type: 'pursue', targetId: 'prey', standoffM: 2000 } }),
      ],
      still,
      1800,
    );
    const t = runScenario(s);
    const [prey, hunter] = statesAt(t, 1800);
    expect(distanceM(prey, hunter)).toBeLessThan(2600);
    expect(Math.abs(hunter.speedKt - prey.speedKt)).toBeLessThan(2);
  });
});

describe('trajectory', () => {
  const s = scenario([unit({ id: 'a', behavior: { type: 'route', waypoints: [destination(C, 90, 30000)] } })], still, 600);

  it('is deterministic', () => {
    const a = runScenario(s);
    const b = runScenario(s);
    expect(Array.from(a.data)).toEqual(Array.from(b.data));
  });

  it('interpolates between samples, wraps headings and clamps time', () => {
    const t = runScenario(s);
    const a = unitStateAt(t, 0, 10);
    const b = unitStateAt(t, 0, 11);
    const mid = unitStateAt(t, 0, 10.5);
    expect(mid.lon).toBeCloseTo((a.lon + b.lon) / 2, 8);
    expect(unitStateAt(t, 0, -50)).toEqual(unitStateAt(t, 0, 0));
    expect(unitStateAt(t, 0, 99999)).toEqual(unitStateAt(t, 0, 600));
  });

  it('coarsens the step for very long runs so memory stays bounded', () => {
    const long = runScenario({ ...s, durationS: 24 * 3600 });
    expect(long.dtS).toBe(4);
    expect(long.count).toBe(21601);
  });

  it('returns a trail newest-first that stops at the start of the run', () => {
    const t = runScenario(s);
    const trail = trailOf(t, 0, 300, 120, 20);
    expect(trail).toHaveLength(7);
    expect(trail[0][0]).toBeGreaterThan(trail[6][0]);
    expect(trailOf(t, 0, 30, 120, 20)).toHaveLength(2);
  });
});
