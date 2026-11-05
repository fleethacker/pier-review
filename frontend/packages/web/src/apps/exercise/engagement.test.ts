import { describe, expect, it } from 'vitest';
import { destination, distanceM, ktToMs } from './geo';
import { closestApproachM, makeRng, runScenario, statesAt, trailOf, unitStateAt, validateScenario } from './sim';
import type { SimEvent } from './sim';
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
    speedKt: 0,
    behavior: { type: 'hold' },
    // Undefended unless a test says otherwise, so missiles are not shot down by surprise.
    magazine: 0,
    ...patch,
  };
}

function scenario(units: UnitConfig[], durationS = 600, environment = still, seed?: number): ScenarioConfig {
  return { id: 't', name: 't', description: '', center: C, durationS, lightPreset: 'day', environment, units, seed };
}

const eventsOf = (events: SimEvent[], type: SimEvent['type']) => events.filter((e) => e.type === type);

/** A red missile launched at `target` from a red shooter, with a certain hit. */
function missile(id: string, target: string, atS: number, patch: Partial<UnitConfig> = {}): UnitConfig {
  return unit({
    id,
    classId: 'ASM',
    side: 'RED',
    speedKt: 300,
    launch: { byId: 'shooter', atS },
    behavior: { type: 'strike', targetId: target },
    pHit: 1,
    ...patch,
  });
}

const shooter = (at = destination(C, 0, 20_000)) => unit({ id: 'shooter', side: 'RED', start: at });

describe('aircraft', () => {
  it('flies at altitude, changes altitude between waypoints at its climb rate, and keeps its speed in the flying range', () => {
    const wp1 = { ...destination(C, 90, 40_000), altitudeM: 3000 };
    const wp2 = { ...destination(destination(C, 90, 40_000), 0, 30_000), altitudeM: 9000 };
    const t = runScenario(
      scenario([unit({ id: 'f', classId: 'FIGHTER', speedKt: 400, behavior: { type: 'route', waypoints: [wp1, wp2] } })], 900),
    );
    expect(unitStateAt(t, 0, 0).altM).toBe(6000);
    expect(unitStateAt(t, 0, 5).altM).toBeCloseTo(6000 - 5 * 120, 0);
    expect(unitStateAt(t, 0, 60).altM).toBeCloseTo(3000, 0);
    expect(unitStateAt(t, 0, 600).altM).toBeGreaterThan(8000);
    for (let at = 0; at <= 900; at += 30) {
      const s = unitStateAt(t, 0, at);
      expect(s.speedKt).toBeGreaterThanOrEqual(159.9);
      expect(s.speedKt).toBeLessThanOrEqual(650.01);
    }
  });

  it('circles the last waypoint when the route ends, rather than stopping in the air', () => {
    const wp = destination(C, 90, 20_000);
    const t = runScenario(scenario([unit({ id: 'f', classId: 'FIGHTER', speedKt: 400, behavior: { type: 'route', waypoints: [wp] } })], 1500));
    for (let at = 600; at <= 1500; at += 60) {
      const s = unitStateAt(t, 0, at);
      expect(distanceM(s, wp)).toBeLessThan(10_000);
      expect(s.speedKt).toBeGreaterThan(300);
    }
  });

  it('loiters around a point on request, and a fighter told to hold circles where it started', () => {
    const center = destination(C, 0, 15_000);
    const a = runScenario(scenario([unit({ id: 'f', classId: 'FIGHTER', speedKt: 350, behavior: { type: 'loiter', center, radiusM: 5000 } })], 1200));
    for (let at = 300; at <= 1200; at += 60) {
      const d = distanceM(unitStateAt(a, 0, at), center);
      expect(d).toBeGreaterThan(2500);
      expect(d).toBeLessThan(8000);
    }
    const b = runScenario(scenario([unit({ id: 'f', classId: 'FIGHTER', speedKt: 350, behavior: { type: 'hold' } })], 900));
    for (let at = 0; at <= 900; at += 30) {
      const s = unitStateAt(b, 0, at);
      expect(distanceM(s, C)).toBeLessThan(9000);
      expect(s.speedKt).toBeGreaterThanOrEqual(159.9);
    }
  });

  it('lets a helicopter hover, and the wind carries it', () => {
    const env: Environment = { ...still, windFromDeg: 270, windKt: 20 };
    const t = runScenario(scenario([unit({ id: 'h', classId: 'HELO', speedKt: 100, behavior: { type: 'hold' } })], 600, env));
    const s = unitStateAt(t, 0, 500);
    expect(s.speedKt).toBeLessThan(0.1);
    expect(s.sogKt).toBeCloseTo(20, 0);
    expect(s.cogDeg).toBeCloseTo(90, 0);
    expect(s.altM).toBe(300);
  });

  it('is not carried by the current, which only moves things on the water', () => {
    const env: Environment = { ...still, currentToDeg: 90, currentKt: 5 };
    const t = runScenario(scenario([unit({ id: 'h', classId: 'HELO', speedKt: 0, behavior: { type: 'hold' } })], 300, env));
    expect(unitStateAt(t, 0, 300).sogKt).toBeLessThan(0.1);
  });
});

describe('launching', () => {
  it('has a unit appear at its launcher only at the launch time', () => {
    const s = scenario([shooter(), unit({ id: 'tgt', start: C }), missile('m', 'tgt', 100)], 400);
    const t = runScenario(s);
    expect(unitStateAt(t, 2, 99).active).toBe(false);
    const at = unitStateAt(t, 2, 100);
    expect(at.active).toBe(true);
    expect(distanceM(at, destination(C, 0, 20_000))).toBeLessThan(10);
    const launch = eventsOf(t.events, 'launch');
    expect(launch).toHaveLength(1);
    expect(launch[0]).toMatchObject({ unitId: 'm', otherId: 'shooter', tS: 100 });
  });

  it('can launch aircraft that then follow their route', () => {
    const wp = destination(C, 90, 30_000);
    const s = scenario(
      [
        unit({ id: 'cv', classId: 'CVN', start: C }),
        unit({ id: 'f', classId: 'FIGHTER', speedKt: 350, launch: { byId: 'cv', atS: 60 }, behavior: { type: 'route', waypoints: [wp] } }),
      ],
      900,
    );
    const t = runScenario(s);
    expect(unitStateAt(t, 1, 59).active).toBe(false);
    expect(unitStateAt(t, 1, 60).active).toBe(true);
    expect(distanceM(unitStateAt(t, 1, 600), wp)).toBeLessThan(15_000);
  });

  it('aborts a launch whose launcher has already been destroyed', () => {
    const s = scenario(
      [
        unit({ id: 'shooter', side: 'RED', start: destination(C, 0, 20_000) }),
        unit({ id: 'victim', start: C, hp: 50 }),
        missile('killer', 'victim', 0, { damage: 200 }),
        unit({ id: 'late', classId: 'ASM', launch: { byId: 'victim', atS: 300 }, behavior: { type: 'strike', targetId: 'shooter' }, pHit: 1 }),
      ],
      600,
    );
    const t = runScenario(s);
    expect(eventsOf(t.events, 'destroyed').map((e) => e.unitId)).toEqual(['victim']);
    expect(eventsOf(t.events, 'aborted')).toHaveLength(1);
    expect(eventsOf(t.events, 'launch').map((e) => e.unitId)).toEqual(['killer']);
    expect(unitStateAt(t, 3, 500).active).toBe(false);
  });

  it('waits for a launcher that has not appeared yet, and leaves disabled units out entirely', () => {
    const s = scenario(
      [
        unit({ id: 'cv', classId: 'CVN', start: C }),
        unit({ id: 'f1', classId: 'FIGHTER', speedKt: 300, launch: { byId: 'cv', atS: 200 } }),
        unit({ id: 'f2', classId: 'FIGHTER', speedKt: 300, launch: { byId: 'f1', atS: 50 } }),
        unit({ id: 'off', classId: 'FIGHTER', disabled: true }),
      ],
      600,
    );
    const t = runScenario(s);
    expect(unitStateAt(t, 2, 150).active).toBe(false);
    expect(unitStateAt(t, 2, 200).active).toBe(true);
    expect(eventsOf(t.events, 'aborted')).toHaveLength(0);
    for (let at = 0; at <= 600; at += 100) expect(unitStateAt(t, 3, at).active).toBe(false);
  });

  it('keeps a trail only from the moment of launch', () => {
    const s = scenario([shooter(), unit({ id: 'tgt', start: C }), missile('m', 'tgt', 100)], 400);
    const t = runScenario(s);
    expect(trailOf(t, 2, 90, 200, 5)).toHaveLength(0);
    const trail = trailOf(t, 2, 110, 200, 5);
    expect(trail.length).toBeGreaterThan(1);
    expect(trail.length).toBeLessThanOrEqual(3);
  });
});

describe('missiles and damage', () => {
  it('flies to a ship and damages it by its damage rating', () => {
    const s = scenario([shooter(), unit({ id: 'tgt', start: C }), missile('m', 'tgt', 100)], 600);
    const t = runScenario(s);
    const hit = eventsOf(t.events, 'hit');
    expect(hit).toHaveLength(1);
    expect(hit[0]).toMatchObject({ unitId: 'm', otherId: 'tgt', hpAfter: 40 });
    // 20 km at roughly 570 kt: about a minute and a half.
    expect(hit[0].tS).toBeGreaterThan(160);
    expect(hit[0].tS).toBeLessThan(230);
    expect(unitStateAt(t, 1, 590).hp).toBe(40);
    expect(unitStateAt(t, 2, 590).active).toBe(false);
    expect(eventsOf(t.events, 'destroyed')).toHaveLength(0);
  });

  it('destroys a ship in two hits, leaving it dead in the water', () => {
    const s = scenario(
      [
        shooter(),
        unit({ id: 'tgt', start: C, speedKt: 20, behavior: { type: 'route', waypoints: [destination(C, 90, 80_000)] } }),
        missile('m1', 'tgt', 100),
        missile('m2', 'tgt', 104),
      ],
      900,
    );
    const t = runScenario(s);
    expect(eventsOf(t.events, 'hit').map((e) => e.hpAfter)).toEqual([40, 0]);
    const destroyed = eventsOf(t.events, 'destroyed');
    expect(destroyed).toHaveLength(1);
    expect(destroyed[0]).toMatchObject({ unitId: 'tgt', otherId: 'm2' });
    const end = unitStateAt(t, 1, 890);
    expect(end.hp).toBe(0);
    expect(end.active).toBe(true);
    expect(end.speedKt).toBeLessThan(0.1);
  });

  it('slows a ship that has lost more than half its hit points', () => {
    const s = scenario(
      [
        shooter(),
        unit({ id: 'tgt', start: C, speedKt: 30, behavior: { type: 'route', waypoints: [destination(C, 90, 90_000)] } }),
        missile('m', 'tgt', 100),
      ],
      900,
    );
    const t = runScenario(s);
    expect(unitStateAt(t, 1, 90).speedKt).toBeCloseTo(30, 0);
    expect(unitStateAt(t, 1, 850).speedKt).toBeLessThanOrEqual(15.6);
    expect(unitStateAt(t, 1, 850).speedKt).toBeGreaterThan(14);
  });

  it('lets a missile with enough damage destroy any ship in one hit, and honours hit point overrides', () => {
    const big = runScenario(scenario([shooter(), unit({ id: 'tgt', classId: 'CVN', start: C }), missile('m', 'tgt', 0, { damage: 400 })], 400));
    expect(eventsOf(big.events, 'destroyed').map((e) => e.unitId)).toEqual(['tgt']);
    const tough = runScenario(scenario([shooter(), unit({ id: 'tgt', start: C, hp: 1000 }), missile('m', 'tgt', 0)], 400));
    expect(eventsOf(tough.events, 'destroyed')).toHaveLength(0);
    expect(unitStateAt(tough, 1, 399).hp).toBe(940);
    const fac = runScenario(scenario([shooter(), unit({ id: 'tgt', classId: 'FAC', start: C }), missile('m', 'tgt', 0)], 400));
    expect(eventsOf(fac.events, 'destroyed')).toHaveLength(1);
  });

  it('misses without damage when the roll fails, and says so', () => {
    const t = runScenario(scenario([shooter(), unit({ id: 'tgt', start: C }), missile('m', 'tgt', 0, { pHit: 0 })], 400));
    expect(eventsOf(t.events, 'hit')).toHaveLength(0);
    const miss = eventsOf(t.events, 'miss');
    expect(miss).toHaveLength(1);
    expect(miss[0]).toMatchObject({ unitId: 'm', otherId: 'tgt', detail: 'did not detonate' });
    expect(unitStateAt(t, 1, 399).hp).toBe(100);
    expect(unitStateAt(t, 2, 399).active).toBe(false);
  });

  it('runs out of fuel short of a distant target', () => {
    const far = destination(C, 0, 200_000);
    const t = runScenario(scenario([unit({ id: 'shooter', side: 'RED', start: C }), unit({ id: 'tgt', start: far }), missile('m', 'tgt', 0)], 900));
    expect(eventsOf(t.events, 'hit')).toHaveLength(0);
    expect(eventsOf(t.events, 'miss')[0]).toMatchObject({ unitId: 'm', detail: 'out of range' });
  });

  it('hits a fast crossing target by aiming ahead of it', () => {
    const start = destination(C, 270, 25_000);
    const s = scenario(
      [
        unit({ id: 'shooter', side: 'RED', start: C }),
        unit({ id: 'cargo', classId: 'CARGO', start, headingDeg: 0, speedKt: 22, behavior: { type: 'route', waypoints: [destination(start, 0, 120_000)] } }),
        missile('m', 'cargo', 0),
      ],
      600,
    );
    const t = runScenario(s);
    expect(eventsOf(t.events, 'hit')).toHaveLength(1);
  });

  it('kills an aircraft with a surface-to-air missile, and a second missile at it loses its target', () => {
    const f = unit({
      id: 'f',
      side: 'RED',
      classId: 'FIGHTER',
      start: destination(C, 90, 40_000),
      headingDeg: 270,
      speedKt: 450,
      behavior: { type: 'route', waypoints: [destination(C, 270, 100_000)] },
    });
    const sam = (id: string): UnitConfig => ({
      ...unit({ id, classId: 'SAM', launch: { byId: 'ship', atS: 5 }, behavior: { type: 'strike', targetId: 'f' }, pHit: 1 }),
    });
    const t = runScenario(scenario([unit({ id: 'ship', start: C }), f, sam('s1'), sam('s2')], 400));
    expect(eventsOf(t.events, 'hit')).toHaveLength(1);
    expect(eventsOf(t.events, 'destroyed').map((e) => e.unitId)).toEqual(['f']);
    expect(eventsOf(t.events, 'miss')[0].detail).toBe('target lost');
    expect(unitStateAt(t, 1, 399).active).toBe(false);
  });

  it('shows an aircraft hit mid-air where it was, and not afterwards', () => {
    const f = unit({ id: 'f', side: 'RED', classId: 'FIGHTER', start: destination(C, 90, 30_000), headingDeg: 270, speedKt: 450, behavior: { type: 'route', waypoints: [destination(C, 270, 80_000)] } });
    const t = runScenario(
      scenario([unit({ id: 'ship', start: C }), f, unit({ id: 's', classId: 'SAM', launch: { byId: 'ship', atS: 0 }, behavior: { type: 'strike', targetId: 'f' }, pHit: 1 })], 300),
    );
    const killed = eventsOf(t.events, 'destroyed')[0];
    expect(unitStateAt(t, 1, killed.tS - 5).active).toBe(true);
    expect(unitStateAt(t, 1, killed.tS + 5).active).toBe(false);
  });
});

describe('defences', () => {
  const incoming = (extra: UnitConfig[] = [], tgt: Partial<UnitConfig> = {}, patch: Partial<UnitConfig> = {}) =>
    scenario([shooter(), unit({ id: 'tgt', start: C, ...tgt }), missile('m', 'tgt', 0, patch), ...extra], 400);

  it('shoots a missile down before it arrives', () => {
    const t = runScenario(incoming([], { pKill: 1, magazine: 5 }));
    expect(eventsOf(t.events, 'intercept')).toHaveLength(1);
    expect(eventsOf(t.events, 'intercept')[0]).toMatchObject({ unitId: 'm', otherId: 'tgt' });
    expect(eventsOf(t.events, 'hit')).toHaveLength(0);
    expect(unitStateAt(t, 1, 399).hp).toBe(100);
  });

  it('runs out of shots, so a later missile gets through', () => {
    const s = scenario(
      [shooter(), unit({ id: 'tgt', start: C, pKill: 1, magazine: 1 }), missile('m1', 'tgt', 0), missile('m2', 'tgt', 0)],
      400,
    );
    const t = runScenario(s);
    expect(eventsOf(t.events, 'intercept')).toHaveLength(1);
    expect(eventsOf(t.events, 'hit')).toHaveLength(1);
  });

  it('is protected by an escort of its own side, but not by a ship of the missile’s side or one that is out of range', () => {
    const base = (guard: Partial<UnitConfig>) =>
      runScenario(
        scenario(
          [shooter(), unit({ id: 'tgt', classId: 'CVN', start: C, magazine: 0 }), unit({ id: 'guard', start: destination(C, 90, 4000), pKill: 1, magazine: 5, ...guard }), missile('m', 'tgt', 0)],
          400,
        ),
      );
    expect(eventsOf(base({}).events, 'intercept').map((e) => e.otherId)).toEqual(['guard']);
    expect(eventsOf(base({ side: 'RED' }).events, 'intercept')).toHaveLength(0);
    expect(eventsOf(base({ start: destination(C, 90, 60_000) }).events, 'intercept')).toHaveLength(0);
    expect(eventsOf(base({ magazine: 0 }).events, 'intercept')).toHaveLength(0);
  });

  it('lets a missile through when every shot fails, however many shots the ship has', () => {
    const t = runScenario(incoming([], { pKill: 0, magazine: 50 }, { pHit: 1 }));
    expect(eventsOf(t.events, 'intercept')).toHaveLength(0);
    expect(eventsOf(t.events, 'hit')).toHaveLength(1);
  });

  it('turns many small chances into a leak rate: more missiles, more hits', () => {
    const salvo = (n: number, seed: number) => {
      const ms = Array.from({ length: n }, (_, i) => missile(`m${i}`, 'tgt', i * 3, { pHit: 0.85 }));
      return runScenario(scenario([shooter(), unit({ id: 'tgt', start: C }), ...ms], 500), { seed });
    };
    const hits = (n: number) => {
      let total = 0;
      for (let seed = 1; seed <= 40; seed++) total += eventsOf(salvo(n, seed).events, 'hit').length;
      return total / 40;
    };
    const a = hits(2);
    const b = hits(6);
    expect(b).toBeGreaterThan(a * 1.8);
  });
});

describe('mines', () => {
  const ship = (patch: Partial<UnitConfig> = {}) =>
    unit({ id: 'ship', start: C, speedKt: 15, behavior: { type: 'route', waypoints: [destination(C, 90, 12_000)] }, ...patch });
  const mine = (patch: Partial<UnitConfig> = {}, along = 5000, across = 0) =>
    unit({ id: 'mine', classId: 'MINE', side: 'RED', start: destination(destination(C, 90, along), 0, across), pHit: 1, ...patch });

  it('goes off under a ship that passes close, damaging it, and is used up', () => {
    const t = runScenario(scenario([ship(), mine()], 1200));
    const strike = eventsOf(t.events, 'mine');
    expect(strike).toHaveLength(1);
    expect(strike[0]).toMatchObject({ unitId: 'mine', otherId: 'ship', hpAfter: 30 });
    expect(unitStateAt(t, 0, 1190).hp).toBe(30);
    expect(unitStateAt(t, 1, 1190).active).toBe(false);
    expect(unitStateAt(t, 1, 0).active).toBe(true);
  });

  it('ignores ships that stay clear, and ships of its own side', () => {
    const clear = runScenario(scenario([ship(), mine({}, 5000, 400)], 1200));
    expect(clear.events).toHaveLength(0);
    const own = runScenario(scenario([ship({ side: 'RED' }), mine()], 1200));
    expect(own.events).toHaveLength(0);
    expect(unitStateAt(own, 1, 1190).active).toBe(true);
  });

  it('can fail to trigger, once, and the ship carries on', () => {
    const t = runScenario(scenario([ship(), mine({ pHit: 0 })], 1200));
    expect(eventsOf(t.events, 'mine')).toHaveLength(0);
    expect(eventsOf(t.events, 'miss')).toHaveLength(1);
    expect(eventsOf(t.events, 'miss')[0].detail).toBe('did not trigger');
    expect(unitStateAt(t, 0, 1190).hp).toBe(100);
    expect(unitStateAt(t, 1, 1190).active).toBe(true);
  });

  it('catches a fast ship that crosses its trigger radius between two steps', () => {
    const t = runScenario(
      scenario([ship({ classId: 'FAC', speedKt: 45, behavior: { type: 'route', waypoints: [destination(C, 90, 12_000)] } }), mine({ damage: 10 })], 1200, still),
    );
    expect(eventsOf(t.events, 'mine')).toHaveLength(1);
  });

  it('does not move, whatever the current does', () => {
    const env: Environment = { ...still, currentToDeg: 0, currentKt: 5 };
    const t = runScenario(scenario([mine()], 600, env));
    const a = unitStateAt(t, 0, 0);
    const b = unitStateAt(t, 0, 600);
    expect(distanceM(a, b)).toBe(0);
    expect(a.altM).toBe(-20);
  });
});

describe('chance and repeatability', () => {
  const trial = (seed?: number) =>
    scenario(
      [shooter(), unit({ id: 'tgt', start: C }), ...Array.from({ length: 5 }, (_, i) => missile(`m${i}`, 'tgt', i * 2, { pHit: 0.5 }))],
      500,
      still,
      seed,
    );

  it('gives the same run every time for the same seed, and the option beats the scenario seed', () => {
    const a = runScenario(trial(7));
    const b = runScenario(trial(7));
    expect(a.events).toEqual(b.events);
    expect(Array.from(a.data)).toEqual(Array.from(b.data));
    expect(runScenario(trial(7), { seed: 3 }).events).toEqual(runScenario(trial(99), { seed: 3 }).events);
  });

  it('gives different outcomes for different seeds', () => {
    const outcomes = new Set<string>();
    for (let seed = 1; seed <= 30; seed++) outcomes.add(JSON.stringify(eventsOf(runScenario(trial(seed)).events, 'hit').map((e) => e.unitId)));
    expect(outcomes.size).toBeGreaterThan(3);
  });

  it('hits about as often as the hit chance says', () => {
    let hits = 0;
    const runs = 200;
    for (let seed = 1; seed <= runs; seed++) {
      const t = runScenario(scenario([shooter(), unit({ id: 'tgt', start: C }), missile('m', 'tgt', 0, { pHit: 0.85 })], 400), { seed });
      hits += eventsOf(t.events, 'hit').length;
    }
    expect(hits / runs).toBeGreaterThan(0.78);
    expect(hits / runs).toBeLessThan(0.92);
  });

  it('draws uniform numbers from the seeded generator', () => {
    const r = makeRng(5);
    const xs = Array.from({ length: 2000 }, () => r());
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...xs)).toBeLessThan(1);
    expect(xs.reduce((a, b) => a + b, 0) / xs.length).toBeCloseTo(0.5, 1);
    expect(makeRng(5)()).toBe(xs[0]);
  });
});

describe('closest approach', () => {
  const p = (lon: number, lat: number, altM = 0) => ({ lon, lat, altM });
  it('finds the nearest point of two straight paths, even when they cross between the ends', () => {
    const a0 = p(-62, 33);
    const a1 = p(-61.99, 33);
    const b0 = p(-61.995, 32.9995);
    const b1 = p(-61.995, 33.0005);
    const { dist, s } = closestApproachM(a0, a1, b0, b1);
    expect(dist).toBeLessThan(1);
    expect(s).toBeCloseTo(0.5, 2);
  });
  it('includes height, and handles things that do not move', () => {
    const { dist } = closestApproachM(p(-62, 33, 0), p(-62, 33, 0), p(-62, 33, 300), p(-62, 33, 300));
    expect(dist).toBeCloseTo(300, 3);
  });
  it('clamps to the ends of the step', () => {
    const { s } = closestApproachM(p(-62, 33), p(-61.999, 33), p(-61.99, 33), p(-61.99, 33));
    expect(s).toBe(1);
  });
});

describe('validation of the new settings', () => {
  const ok = [shooter(), unit({ id: 'tgt', start: C })];
  const errs = (...extra: UnitConfig[]) => validateScenario(scenario([...ok, ...extra])).join('\n');

  it('accepts a sound missile launch', () => {
    expect(errs(missile('m', 'tgt', 10))).toBe('');
  });
  it('rejects things that make no sense', () => {
    expect(errs(unit({ id: 'x', behavior: { type: 'strike', targetId: 'tgt' } }))).toContain('only missiles can strike');
    expect(errs(unit({ id: 'x', behavior: { type: 'loiter', center: C, radiusM: 100 } }))).toContain('only aircraft can loiter');
    expect(errs(unit({ id: 'x', classId: 'FIGHTER', behavior: { type: 'loiter', center: C, radiusM: 0 } }))).toContain('radius');
    expect(errs(missile('m', 'ghost', 10))).toContain('does not exist');
    expect(errs(missile('m', 'm', 10))).toContain('itself');
    expect(errs(missile('m', 'tgt', 10, { launch: { byId: 'ghost', atS: 5 } }))).toContain('launcher "ghost"');
    expect(errs(missile('m', 'tgt', 10, { launch: { byId: 'm', atS: 5 } }))).toContain('cannot launch itself');
    expect(errs(missile('m', 'tgt', -5))).toContain('launch time');
    expect(errs(unit({ id: 'x', pHit: 1.5 }))).toContain('hit chance');
    expect(errs(unit({ id: 'x', pKill: -0.1 }))).toContain('defence kill chance');
    expect(errs(unit({ id: 'x', hp: 0 }))).toContain('hit points');
    expect(errs(unit({ id: 'x', damage: -1 }))).toContain('damage');
    expect(errs(unit({ id: 'x', magazine: -1 }))).toContain('magazine');
    expect(errs(unit({ id: 'x', altitudeM: -5 }))).toContain('altitude');
    expect(errs(unit({ id: 'x', classId: 'FIGHTER', behavior: { type: 'route', waypoints: [{ ...C, altitudeM: -1 }] } }))).toContain('waypoint altitudes');
    expect(errs(unit({ id: 'x', classId: 'BB' as never }))).toContain('unknown unit class');
  });
});

describe('state of destroyed ships over the run', () => {
  it('reports ships, missiles and mines consistently at every time', () => {
    const s = scenario([shooter(), unit({ id: 'tgt', start: C }), missile('m', 'tgt', 50)], 400);
    const t = runScenario(s);
    for (let at = 0; at <= 400; at += 10) {
      const [sh, tgt, m] = statesAt(t, at);
      expect(sh.active).toBe(true);
      expect(tgt.active).toBe(true);
      expect(m.active).toBe(at >= 50 && at < (eventsOf(t.events, 'hit')[0]?.tS ?? 0));
      if (m.active) expect(m.speedKt).toBeGreaterThan(200);
    }
    expect(ktToMs(1)).toBeGreaterThan(0);
  });
});
