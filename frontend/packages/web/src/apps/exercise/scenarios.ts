import { offsetM, stationFrom } from './geo';
import type { LonLat, ScenarioConfig, Waypoint } from './types';

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
  lightPreset: 'day',
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
  lightPreset: 'dusk',
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

export const PRESET_SCENARIOS: ScenarioConfig[] = [transit, encounter, drill];

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
