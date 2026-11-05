import { offsetM, stationFrom } from './geo';
import { makeRng } from './sim';
import type { LonLat, RedTeamSpec, ScenarioConfig, UnitConfig, Waypoint } from './types';

/** Open Atlantic, well clear of land and shipping lanes. */
export const OCEAN_CENTER = { lon: -62, lat: 33 };

const at = (eastM: number, northM: number) => offsetM(OCEAN_CENTER, eastM, northM);
const wp = (eastM: number, northM: number, speedKt?: number): Waypoint => ({ ...at(eastM, northM), speedKt });

/** Where an escort starts so it is already on its station when the leader is at `leader` on `headingDeg`. */
const station = (leader: LonLat, headingDeg: number, aheadM: number, abeamM: number): LonLat =>
  stationFrom(leader, headingDeg, aheadM, abeamM);

const CALM = { windFromDeg: 250, windKt: 12, currentToDeg: 45, currentKt: 0.8 };

const transit: ScenarioConfig = {
  id: 'csg-transit',
  name: 'Carrier group transit',
  description:
    'A carrier steams east and makes two course changes while a cruiser and two destroyers hold screen stations. A merchant crosses ahead.',
  center: OCEAN_CENTER,
  durationS: 5400,
  lightPreset: 'dusk',
  environment: CALM,
  units: [
    {
      id: 'cvn1',
      name: 'Carrier 1',
      classId: 'CVN',
      side: 'BLUE',
      start: at(-12000, 0),
      headingDeg: 90,
      speedKt: 18,
      maxTurnRateDegPerS: 0.1,
      behavior: { type: 'route', waypoints: [wp(14000, 0), wp(24000, -9000), wp(42000, -9000)] },
    },
    {
      id: 'cg1',
      name: 'Cruiser 1',
      classId: 'CG',
      side: 'BLUE',
      start: station(at(-12000, 0), 90, 3000, 0),
      headingDeg: 90,
      speedKt: 18,
      behavior: { type: 'escort', leaderId: 'cvn1', aheadM: 3000, abeamM: 0 },
    },
    {
      id: 'ddg1',
      name: 'Destroyer 1',
      classId: 'DDG',
      side: 'BLUE',
      start: station(at(-12000, 0), 90, 1200, -3000),
      headingDeg: 90,
      speedKt: 18,
      behavior: { type: 'escort', leaderId: 'cvn1', aheadM: 1200, abeamM: -3000 },
    },
    {
      id: 'ddg2',
      name: 'Destroyer 2',
      classId: 'DDG',
      side: 'BLUE',
      start: station(at(-12000, 0), 90, 1200, 3000),
      headingDeg: 90,
      speedKt: 18,
      behavior: { type: 'escort', leaderId: 'cvn1', aheadM: 1200, abeamM: 3000 },
    },
    {
      id: 'mv1',
      name: 'Merchant 1',
      classId: 'CARGO',
      side: 'NEUTRAL',
      start: at(18000, 22000),
      headingDeg: 180,
      speedKt: 15,
      behavior: { type: 'route', waypoints: [wp(18000, -40000)] },
    },
  ],
};

const encounter: ScenarioConfig = {
  id: 'surface-encounter',
  name: 'Surface contact intercept',
  description:
    'Three fast attack craft run at a destroyer pair. A cruiser closes from the north-west to shadow the lead craft while a merchant passes through.',
  center: OCEAN_CENTER,
  durationS: 2700,
  lightPreset: 'night',
  environment: { windFromDeg: 300, windKt: 18, currentToDeg: 90, currentKt: 1.2 },
  units: [
    {
      id: 'ddg1',
      name: 'Destroyer 1',
      classId: 'DDG',
      side: 'BLUE',
      start: at(-6000, -2000),
      headingDeg: 90,
      speedKt: 14,
      behavior: { type: 'route', waypoints: [wp(30000, -2000)] },
    },
    {
      id: 'ddg2',
      name: 'Destroyer 2',
      classId: 'DDG',
      side: 'BLUE',
      start: station(at(-6000, -2000), 90, 0, 2200),
      headingDeg: 90,
      speedKt: 14,
      behavior: { type: 'escort', leaderId: 'ddg1', aheadM: 0, abeamM: 2200 },
    },
    {
      id: 'cg1',
      name: 'Cruiser 1',
      classId: 'CG',
      side: 'BLUE',
      start: at(-14000, 16000),
      headingDeg: 120,
      speedKt: 28,
      behavior: { type: 'pursue', targetId: 'fac1', standoffM: 2500 },
    },
    {
      id: 'fac1',
      name: 'Fast craft 1',
      classId: 'FAC',
      side: 'RED',
      start: at(9000, 18000),
      headingDeg: 200,
      speedKt: 38,
      behavior: { type: 'route', waypoints: [wp(2000, -2500), wp(-8000, -9000), wp(-32000, -13000)] },
    },
    {
      id: 'fac2',
      name: 'Fast craft 2',
      classId: 'FAC',
      side: 'RED',
      start: station(at(9000, 18000), 200, -450, -400),
      headingDeg: 200,
      speedKt: 38,
      behavior: { type: 'escort', leaderId: 'fac1', aheadM: -450, abeamM: -400 },
    },
    {
      id: 'fac3',
      name: 'Fast craft 3',
      classId: 'FAC',
      side: 'RED',
      start: station(at(9000, 18000), 200, -450, 400),
      headingDeg: 200,
      speedKt: 38,
      behavior: { type: 'escort', leaderId: 'fac1', aheadM: -450, abeamM: 400 },
    },
    {
      id: 'mv1',
      name: 'Merchant 1',
      classId: 'CARGO',
      side: 'NEUTRAL',
      start: at(20000, 6000),
      headingDeg: 270,
      speedKt: 16,
      behavior: { type: 'route', waypoints: [wp(-30000, 6000)] },
    },
  ],
};

const drillStart = at(-8000, -6000);

const drill: ScenarioConfig = {
  id: 'formation-drill',
  name: 'Formation maneuvering drill',
  description:
    'A cruiser leads three destroyers around a box on a wide, slow turn radius, changing speed between legs. Watch the escorts swing about the guide and hold station.',
  center: OCEAN_CENTER,
  durationS: 5400,
  lightPreset: 'day',
  environment: { windFromDeg: 180, windKt: 8, currentToDeg: 0, currentKt: 0.5 },
  units: [
    {
      id: 'cg1',
      name: 'Guide',
      classId: 'CG',
      side: 'BLUE',
      start: drillStart,
      headingDeg: 90,
      speedKt: 16,
      maxTurnRateDegPerS: 0.2,
      behavior: {
        type: 'route',
        waypoints: [wp(2000, -6000, 16), wp(2000, 2000, 18), wp(-8000, 2000, 18), wp(-8000, -6000, 14)],
        loop: true,
      },
    },
    {
      id: 'ddg1',
      name: 'Escort 1',
      classId: 'DDG',
      side: 'BLUE',
      start: station(drillStart, 90, 0, -1200),
      headingDeg: 90,
      speedKt: 16,
      behavior: { type: 'escort', leaderId: 'cg1', aheadM: 0, abeamM: -1200 },
    },
    {
      id: 'ddg2',
      name: 'Escort 2',
      classId: 'DDG',
      side: 'BLUE',
      start: station(drillStart, 90, 0, 1200),
      headingDeg: 90,
      speedKt: 16,
      behavior: { type: 'escort', leaderId: 'cg1', aheadM: 0, abeamM: 1200 },
    },
    {
      id: 'ddg3',
      name: 'Escort 3',
      classId: 'DDG',
      side: 'BLUE',
      start: station(drillStart, 90, -1800, 0),
      headingDeg: 90,
      speedKt: 16,
      behavior: { type: 'escort', leaderId: 'cg1', aheadM: -1800, abeamM: 0 },
    },
  ],
};


/** Mines scattered over a box (meters east and north of the ocean center), always in the same places for a given seed. */
function minefield(count: number, eastM: number, northM: number, halfWidthM: number, halfHeightM: number, seed: number): UnitConfig[] {
  const rng = makeRng(seed);
  return Array.from({ length: count }, (_, i) => ({
    id: `mine${String(i + 1).padStart(2, '0')}`,
    name: `Mine ${i + 1}`,
    classId: 'MINE' as const,
    side: 'RED' as const,
    start: at(eastM + (rng() * 2 - 1) * halfWidthM, northM + (rng() * 2 - 1) * halfHeightM),
    headingDeg: 0,
    speedKt: 0,
    behavior: { type: 'hold' as const },
  }));
}

const blueGroup = (origin: LonLat, speedKt: number): UnitConfig[] => [
  {
    id: 'cvn1',
    name: 'Carrier 1',
    classId: 'CVN',
    side: 'BLUE',
    start: origin,
    headingDeg: 90,
    speedKt,
    maxTurnRateDegPerS: 0.1,
    behavior: { type: 'route', waypoints: [offsetM(origin, 60000, 0)] },
  },
  {
    id: 'cg1',
    name: 'Cruiser 1',
    classId: 'CG',
    side: 'BLUE',
    start: station(origin, 90, 3000, 0),
    headingDeg: 90,
    speedKt,
    behavior: { type: 'escort', leaderId: 'cvn1', aheadM: 3000, abeamM: 0 },
  },
  {
    id: 'ddg1',
    name: 'Destroyer 1',
    classId: 'DDG',
    side: 'BLUE',
    start: station(origin, 90, 1200, -3000),
    headingDeg: 90,
    speedKt,
    behavior: { type: 'escort', leaderId: 'cvn1', aheadM: 1200, abeamM: -3000 },
  },
  {
    id: 'ddg2',
    name: 'Destroyer 2',
    classId: 'DDG',
    side: 'BLUE',
    start: station(origin, 90, 1200, 3000),
    headingDeg: 90,
    speedKt,
    behavior: { type: 'escort', leaderId: 'cvn1', aheadM: 1200, abeamM: 3000 },
  },
];

const salvoOrigin = at(-12000, 0);
const salvoShooter = at(15000, 62000);

const salvoDefense: ScenarioConfig = {
  id: 'salvo-defense',
  name: 'Missile salvo on a carrier group',
  description:
    'A hostile destroyer fires eight anti-ship missiles at the carrier and two aircraft fire at the cruiser. The escorts shoot what they can. Open Red team to ask how often the carrier is hit, and how that changes with the size of the salvo.',
  center: OCEAN_CENTER,
  durationS: 1500,
  lightPreset: 'dusk',
  seed: 4,
  environment: { windFromDeg: 250, windKt: 12, currentToDeg: 45, currentKt: 0.8 },
  units: [
    ...blueGroup(salvoOrigin, 18),
    {
      id: 'bh1',
      name: 'Plane guard helo',
      classId: 'HELO',
      side: 'BLUE',
      start: station(salvoOrigin, 90, 0, 900),
      headingDeg: 90,
      speedKt: 18,
      altitudeM: 150,
      behavior: { type: 'escort', leaderId: 'cvn1', aheadM: -200, abeamM: 900 },
    },
    {
      id: 'rdd1',
      name: 'Hostile destroyer',
      classId: 'DDG',
      side: 'RED',
      start: salvoShooter,
      headingDeg: 180,
      speedKt: 8,
      behavior: { type: 'route', waypoints: [offsetM(salvoShooter, 0, -20000)] },
    },
    ...Array.from({ length: 8 }, (_, i): UnitConfig => ({
      id: `m${i + 1}`,
      name: `Missile ${i + 1}`,
      classId: 'ASM',
      side: 'RED',
      start: salvoShooter,
      headingDeg: 200,
      speedKt: 300,
      launch: { byId: 'rdd1', atS: 300 + i * 4 },
      behavior: { type: 'strike', targetId: 'cvn1' },
    })),
    {
      id: 'rf1',
      name: 'Raider 1',
      classId: 'FIGHTER',
      side: 'RED',
      start: at(70000, 38000),
      headingDeg: 250,
      speedKt: 420,
      altitudeM: 1500,
      behavior: { type: 'route', waypoints: [at(-40000, 0)] },
    },
    {
      id: 'rf2',
      name: 'Raider 2',
      classId: 'FIGHTER',
      side: 'RED',
      start: at(70000, 33000),
      headingDeg: 250,
      speedKt: 420,
      altitudeM: 1500,
      behavior: { type: 'route', waypoints: [at(-40000, -2000)] },
    },
    ...['rf1', 'rf2'].map((from, i): UnitConfig => ({
      id: `rm${i + 1}`,
      name: `Raider missile ${i + 1}`,
      classId: 'ASM',
      side: 'RED',
      start: at(70000, 35000),
      headingDeg: 250,
      speedKt: 300,
      launch: { byId: from, atS: 330 + i * 6 },
      behavior: { type: 'strike', targetId: 'cg1' },
    })),
  ],
  redTeam: {
    runs: 60,
    seed: 11,
    perturbations: [
      { id: 'wind', label: 'Wind speed', target: { kind: 'environment', field: 'windKt' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 5 } },
      { id: 'shooter-e', label: 'Hostile destroyer east', target: { kind: 'unit', unitId: 'rdd1', field: 'startEastM' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 6000 } },
      { id: 'shooter-n', label: 'Hostile destroyer north', target: { kind: 'unit', unitId: 'rdd1', field: 'startNorthM' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 6000 } },
      { id: 'cg-pkill', label: 'Cruiser defence kill chance', target: { kind: 'unit', unitId: 'cg1', field: 'pKill' }, mode: 'set', dist: { type: 'uniform', min: 0.3, max: 0.65 } },
      { id: 'ddg1-pkill', label: 'Destroyer 1 defence kill chance', target: { kind: 'unit', unitId: 'ddg1', field: 'pKill' }, mode: 'set', dist: { type: 'uniform', min: 0.25, max: 0.6 } },
      { id: 'ddg2-pkill', label: 'Destroyer 2 defence kill chance', target: { kind: 'unit', unitId: 'ddg2', field: 'pKill' }, mode: 'set', dist: { type: 'uniform', min: 0.25, max: 0.6 } },
      { id: 'asm-phit', label: 'Missile 1 hit chance', target: { kind: 'unit', unitId: 'm1', field: 'pHit' }, mode: 'set', dist: { type: 'uniform', min: 0.6, max: 0.95 } },
    ],
    outcomes: [
      { id: 'cv-hit', label: 'Carrier is hit', type: 'hit', unitId: 'cvn1' },
      { id: 'cv-twice', label: 'Carrier loses 15%+ of its strength', type: 'hp_below', unitId: 'cvn1', frac: 0.85 },
      { id: 'blue-loss', label: 'Any blue ship or aircraft lost', type: 'side_losses', side: 'BLUE', atLeast: 1 },
      { id: 'cg-hit', label: 'Cruiser is hit', type: 'hit', unitId: 'cg1' },
    ],
    sweep: { target: { kind: 'salvo', unitIds: Array.from({ length: 8 }, (_, i) => `m${i + 1}`) }, values: [1, 2, 4, 6, 8] },
  },
};

const mineTrack = (eastM: number): Waypoint[] => [wp(eastM, 0)];

const minefieldTransit: ScenarioConfig = {
  id: 'minefield-transit',
  name: 'Minefield transit',
  description:
    'Three destroyers and a merchant ship follow one track through an uncharted minefield. Each mine goes off with a chance when a ship passes close. Run the red team to see how likely each ship is to be lost.',
  center: OCEAN_CENTER,
  durationS: 3900,
  lightPreset: 'day',
  seed: 2,
  environment: { windFromDeg: 200, windKt: 10, currentToDeg: 90, currentKt: 0.4 },
  units: [
    ...['ddg1', 'ddg2', 'ddg3'].map((id, i): UnitConfig => ({
      id,
      name: `Destroyer ${i + 1}`,
      classId: 'DDG',
      side: 'BLUE',
      start: at(-14000 - i * 1500, 0),
      headingDeg: 90,
      speedKt: 15,
      behavior: { type: 'route', waypoints: mineTrack(14000) },
    })),
    {
      id: 'mv1',
      name: 'Merchant 1',
      classId: 'CARGO',
      side: 'NEUTRAL',
      start: at(-19000, 0),
      headingDeg: 90,
      speedKt: 15,
      behavior: { type: 'route', waypoints: mineTrack(14000) },
    },
    ...minefield(36, 0, 0, 3000, 1500, 7),
  ],
  redTeam: {
    runs: 200,
    seed: 5,
    perturbations: [
      { id: 'track-n', label: 'Track offset north (navigation error)', target: { kind: 'unit', unitId: 'ddg1', field: 'routeNorthM' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 250 } },
      { id: 'mine-p', label: 'Mine trigger chance (mine 1)', target: { kind: 'unit', unitId: 'mine01', field: 'pHit' }, mode: 'set', dist: { type: 'uniform', min: 0.4, max: 0.9 } },
    ],
    outcomes: [
      { id: 'lead-struck', label: 'Lead destroyer strikes a mine', type: 'hit', unitId: 'ddg1' },
      { id: 'any-strike', label: 'Any mine goes off', type: 'mine_strike' },
      { id: 'lost-ship', label: 'A destroyer is lost', type: 'side_losses', side: 'BLUE', atLeast: 1 },
      { id: 'merchant-hit', label: 'Merchant ship is damaged', type: 'hit', unitId: 'mv1' },
    ],
  },
};

const raidStart = at(70000, 30000);

const airRaid: ScenarioConfig = {
  id: 'air-raid',
  name: 'Air raid and SAM defence',
  description:
    'Four hostile fighters run in low on a cruiser and a destroyer, each firing an anti-ship missile. The ships answer with surface-to-air missiles and their close defences. Run the red team to see how often the cruiser gets through.',
  center: OCEAN_CENTER,
  durationS: 900,
  lightPreset: 'day',
  seed: 4,
  environment: { windFromDeg: 300, windKt: 8, currentToDeg: 0, currentKt: 0.3 },
  units: [
    {
      id: 'cg1',
      name: 'Cruiser 1',
      classId: 'CG',
      side: 'BLUE',
      start: at(0, 0),
      headingDeg: 90,
      speedKt: 12,
      behavior: { type: 'route', waypoints: [at(30000, 0)] },
    },
    {
      id: 'ddg1',
      name: 'Destroyer 1',
      classId: 'DDG',
      side: 'BLUE',
      start: station(at(0, 0), 90, 0, 2500),
      headingDeg: 90,
      speedKt: 12,
      behavior: { type: 'escort', leaderId: 'cg1', aheadM: 0, abeamM: 2500 },
    },
    ...Array.from({ length: 4 }, (_, i): UnitConfig => ({
      id: `rf${i + 1}`,
      name: `Raider ${i + 1}`,
      classId: 'FIGHTER',
      side: 'RED',
      start: offsetM(raidStart, i * 1500, i * 900),
      headingDeg: 255,
      speedKt: 450,
      altitudeM: 2000,
      behavior: { type: 'route', waypoints: [at(-30000, 0)] },
    })),
    ...Array.from({ length: 4 }, (_, i): UnitConfig => ({
      id: `rm${i + 1}`,
      name: `Raider missile ${i + 1}`,
      classId: 'ASM',
      side: 'RED',
      start: raidStart,
      headingDeg: 255,
      speedKt: 300,
      launch: { byId: `rf${i + 1}`, atS: 70 + i * 8 },
      behavior: { type: 'strike', targetId: 'cg1' },
    })),
    ...Array.from({ length: 4 }, (_, i): UnitConfig => ({
      id: `sam${i + 1}`,
      name: `SAM ${i + 1}`,
      classId: 'SAM',
      side: 'BLUE',
      start: at(0, 0),
      headingDeg: 70,
      speedKt: 600,
      launch: { byId: i % 2 === 0 ? 'cg1' : 'ddg1', atS: 150 + i * 8 },
      behavior: { type: 'strike', targetId: `rf${i + 1}` },
    })),
  ],
  redTeam: {
    runs: 200,
    seed: 3,
    perturbations: [
      { id: 'sam-phit', label: 'SAM 1 hit chance', target: { kind: 'unit', unitId: 'sam1', field: 'pHit' }, mode: 'set', dist: { type: 'uniform', min: 0.4, max: 0.9 } },
      { id: 'raid-alt', label: 'Raider 1 altitude', target: { kind: 'unit', unitId: 'rf1', field: 'altitudeM' }, mode: 'set', dist: { type: 'uniform', min: 30, max: 3000 } },
      { id: 'raid-n', label: 'Raider 1 start north', target: { kind: 'unit', unitId: 'rf1', field: 'startNorthM' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 3000 } },
      { id: 'cg-mag', label: 'Cruiser magazine', target: { kind: 'unit', unitId: 'cg1', field: 'magazine' }, mode: 'set', dist: { type: 'choice', values: [6, 12, 24, 40] } },
    ],
    outcomes: [
      { id: 'cg-hit', label: 'Cruiser is hit', type: 'hit', unitId: 'cg1' },
      { id: 'cg-lost', label: 'Cruiser is destroyed', type: 'destroyed', unitId: 'cg1' },
      { id: 'raiders-lost', label: 'At least two raiders shot down', type: 'side_losses', side: 'RED', atLeast: 2 },
      { id: 'close', label: 'A raider passes within 5 km of the cruiser', type: 'closest_approach', aId: 'rf1', bId: 'cg1', withinM: 5000 },
    ],
  },
};

export const PRESET_SCENARIOS: ScenarioConfig[] = [transit, encounter, drill, salvoDefense, minefieldTransit, airRaid];

export type { RedTeamSpec };

export function blankScenario(): ScenarioConfig {
  return {
    id: 'custom',
    name: 'New scenario',
    description: '',
    center: OCEAN_CENTER,
    durationS: 3600,
    lightPreset: 'day',
    environment: CALM,
    units: [
      {
        id: 'u1',
        name: 'Destroyer 1',
        classId: 'DDG',
        side: 'BLUE',
        start: OCEAN_CENTER,
        headingDeg: 90,
        speedKt: 15,
        behavior: { type: 'route', waypoints: [wp(15000, 0)] },
      },
    ],
  };
}

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
