import type { ClassId, Side } from './types';

/** Surface ships move on the water, aircraft and missiles through the air, mines sit still. */
export type Domain = 'surface' | 'air' | 'static' | 'sub';

export interface WeaponSpec {
  /** Damage done on a hit. */
  damage: number;
  /** Detonates when within this distance of its target, meters. */
  fuzeM: number;
  /** Chance of doing the damage once there. */
  pHit: number;
  /** How far it can fly before running out of fuel, meters. */
  rangeM: number;
}

/** A ship's ability to shoot down incoming missiles aimed at it or at ships of its side nearby. */
export interface DefenceSpec {
  rangeM: number;
  /** Chance one shot shoots a missile down. */
  pKill: number;
  /** Shots it will fire at any one missile. */
  shots: number;
  /** Seconds between its shots. */
  reloadS: number;
  magazine: number;
  /** Seconds a missile has to have been tracked before this ship will shoot at it (when sensors matter). Default 6. */
  reactionS?: number;
}

/** What a unit can sense with and how easily it is sensed. Illustrative. */
export interface SensorSpec {
  /** Search radar range against a one-square-meter target, meters. Absent: no radar. */
  radarRangeM?: number;
  /** Height of the antenna above the sea, meters (aircraft use their altitude). */
  heightM?: number;
  /** Sonar range against something of normal noise, meters. Absent: no sonar. */
  sonarRangeM?: number;
  /** Radar cross-section, square meters. */
  rcsM2: number;
  /** How noisy it is: 1 is a surface ship. Quiet submarines are well below. */
  noise: number;
}

/** Illustrative dimensions and handling, rounded from public figures. Not for operational use. */
export interface ShipClass {
  id: ClassId;
  name: string;
  domain: Domain;
  loaM: number;
  beamM: number;
  /** Hull height above the waterline (for aircraft and missiles, the height of the body). */
  freeboardM: number;
  maxSpeedKt: number;
  accelKtPerS: number;
  /** Rudder-limited turn rate at speed. */
  turnRateDegPerS: number;
  /** Fraction of the wind speed the unit is pushed downwind at. Rough. Aircraft ride the air, so 1. */
  windage: number;
  /** Radius of the optional sensor ring. Illustrative. */
  sensorRangeNm: number;
  hullColor: string;
  deckColor: string;
  hp: number;
  /** Small things are drawn this many times larger (on top of the ship size slider) so they can be seen. */
  visualBoost: number;
  /** Scales the wake or ground-track trail. 0 for none. */
  trailScale: number;
  cruiseAltM?: number;
  /** Fixed-wing aircraft cannot fly slower than this. */
  minSpeedKt?: number;
  climbRateMps?: number;
  canHover?: boolean;
  weapon?: WeaponSpec;
  defence?: DefenceSpec;
}

/** Seas that slow a ship: speed falls this fraction per sea state above `limit`, to no less than 40%. */
export const SEA_KEEPING: Partial<Record<ClassId, { limit: number; slope: number }>> = {
  CVN: { limit: 6, slope: 0.03 },
  LHD: { limit: 6, slope: 0.04 },
  CG: { limit: 5, slope: 0.06 },
  DDG: { limit: 5, slope: 0.06 },
  FAC: { limit: 3, slope: 0.12 },
  CARGO: { limit: 5, slope: 0.08 },
  FFG: { limit: 5, slope: 0.07 },
};

export const SENSORS: Partial<Record<ClassId, SensorSpec>> = {
  CVN: { radarRangeM: 110_000, heightM: 35, rcsM2: 50_000, noise: 1.3 },
  LHD: { radarRangeM: 100_000, heightM: 30, rcsM2: 30_000, noise: 1.2 },
  CG: { radarRangeM: 130_000, heightM: 25, sonarRangeM: 15_000, rcsM2: 8_000, noise: 1 },
  DDG: { radarRangeM: 120_000, heightM: 22, sonarRangeM: 18_000, rcsM2: 6_000, noise: 1 },
  FAC: { radarRangeM: 35_000, heightM: 10, rcsM2: 300, noise: 0.8 },
  CARGO: { radarRangeM: 20_000, heightM: 20, rcsM2: 20_000, noise: 1.1 },
  FIGHTER: { radarRangeM: 150_000, heightM: 2, rcsM2: 5, noise: 0 },
  HELO: { radarRangeM: 60_000, heightM: 2, sonarRangeM: 6_000, rcsM2: 15, noise: 0 },
  ASM: { rcsM2: 0.3, noise: 0 },
  SAM: { rcsM2: 0.5, noise: 0 },
  SSN: { sonarRangeM: 25_000, heightM: 0, rcsM2: 100, noise: 0.35 },
  TORP: { rcsM2: 0, noise: 0.9 },
  FFG: { radarRangeM: 90_000, heightM: 20, sonarRangeM: 25_000, rcsM2: 3_000, noise: 0.9 },
  SSK: { sonarRangeM: 20_000, heightM: 0, rcsM2: 60, noise: 0.18 },
  // A medium-altitude surveillance drone: a small radar that sees a long way from up high.
  UAV: { radarRangeM: 40_000, heightM: 2, rcsM2: 0.5, noise: 0 },
  // An armed drone: small, slow and low, hard to pick out.
  DRONE: { rcsM2: 0.05, noise: 0 },
  // Airborne early warning: a big radar on a slow aircraft.
  AEW: { radarRangeM: 250_000, heightM: 2, rcsM2: 40, noise: 0 },
};

const surface = { domain: 'surface' as const, visualBoost: 1, trailScale: 1 };

export const SHIP_CLASSES: Record<ClassId, ShipClass> = {
  CVN: {
    ...surface,
    id: 'CVN',
    name: 'Aircraft carrier (CVN)',
    loaM: 333,
    beamM: 41,
    freeboardM: 18,
    maxSpeedKt: 30,
    accelKtPerS: 0.08,
    turnRateDegPerS: 1.2,
    windage: 0.008,
    sensorRangeNm: 120,
    hullColor: '#6f777e',
    deckColor: '#4d555c',
    hp: 400,
    defence: { rangeM: 7000, pKill: 0.35, shots: 1, reloadS: 14, magazine: 12 },
  },
  LHD: {
    ...surface,
    id: 'LHD',
    name: 'Amphibious assault ship (LHD)',
    loaM: 257,
    beamM: 32,
    freeboardM: 14,
    maxSpeedKt: 22,
    accelKtPerS: 0.1,
    turnRateDegPerS: 1.4,
    windage: 0.008,
    sensorRangeNm: 100,
    hullColor: '#737b82',
    deckColor: '#50585f',
    hp: 250,
    defence: { rangeM: 7000, pKill: 0.35, shots: 1, reloadS: 14, magazine: 10 },
  },
  CG: {
    ...surface,
    id: 'CG',
    name: 'Cruiser (CG)',
    loaM: 173,
    beamM: 17,
    freeboardM: 8,
    maxSpeedKt: 32,
    accelKtPerS: 0.15,
    turnRateDegPerS: 1.9,
    windage: 0.005,
    sensorRangeNm: 150,
    hullColor: '#7b838a',
    deckColor: '#a3abb2',
    hp: 120,
    defence: { rangeM: 9000, pKill: 0.5, shots: 2, reloadS: 12, magazine: 40 },
  },
  DDG: {
    ...surface,
    id: 'DDG',
    name: 'Destroyer (DDG)',
    loaM: 155,
    beamM: 20,
    freeboardM: 8,
    maxSpeedKt: 31,
    accelKtPerS: 0.2,
    turnRateDegPerS: 2.2,
    windage: 0.005,
    sensorRangeNm: 150,
    hullColor: '#7b838a',
    deckColor: '#a3abb2',
    hp: 100,
    defence: { rangeM: 9000, pKill: 0.45, shots: 2, reloadS: 12, magazine: 24 },
  },
  FAC: {
    ...surface,
    id: 'FAC',
    name: 'Fast attack craft (FAC)',
    loaM: 40,
    beamM: 7,
    freeboardM: 2.5,
    maxSpeedKt: 45,
    accelKtPerS: 0.8,
    turnRateDegPerS: 6,
    windage: 0.02,
    sensorRangeNm: 15,
    hullColor: '#8a7f73',
    deckColor: '#b3a89b',
    hp: 25,
    defence: { rangeM: 2500, pKill: 0.2, shots: 1, reloadS: 6, magazine: 4 },
  },
  CARGO: {
    ...surface,
    id: 'CARGO',
    name: 'Container ship (merchant)',
    loaM: 300,
    beamM: 46,
    freeboardM: 16,
    maxSpeedKt: 22,
    accelKtPerS: 0.05,
    turnRateDegPerS: 0.8,
    windage: 0.012,
    sensorRangeNm: 24,
    hullColor: '#7a2e2a',
    deckColor: '#c9c3b8',
    hp: 150,
  },
  FIGHTER: {
    id: 'FIGHTER',
    name: 'Fighter aircraft',
    domain: 'air',
    loaM: 16,
    beamM: 11,
    freeboardM: 1.8,
    maxSpeedKt: 650,
    accelKtPerS: 5,
    turnRateDegPerS: 6,
    windage: 1,
    sensorRangeNm: 100,
    hullColor: '#8d949b',
    deckColor: '#6f777e',
    hp: 30,
    visualBoost: 5,
    trailScale: 0.5,
    cruiseAltM: 6000,
    minSpeedKt: 160,
    climbRateMps: 120,
  },
  HELO: {
    id: 'HELO',
    name: 'Helicopter',
    domain: 'air',
    loaM: 17,
    beamM: 16,
    freeboardM: 2.4,
    maxSpeedKt: 150,
    accelKtPerS: 3,
    turnRateDegPerS: 15,
    windage: 1,
    sensorRangeNm: 40,
    hullColor: '#59636b',
    deckColor: '#434c53',
    hp: 20,
    visualBoost: 5,
    trailScale: 0.3,
    cruiseAltM: 300,
    minSpeedKt: 0,
    climbRateMps: 8,
    canHover: true,
  },
  ASM: {
    id: 'ASM',
    name: 'Anti-ship missile',
    domain: 'air',
    loaM: 6,
    beamM: 0.8,
    freeboardM: 0.5,
    maxSpeedKt: 570,
    accelKtPerS: 40,
    turnRateDegPerS: 14,
    windage: 0,
    sensorRangeNm: 0,
    hullColor: '#c9ccd0',
    deckColor: '#8a8f94',
    hp: 1,
    visualBoost: 10,
    trailScale: 0.6,
    cruiseAltM: 15,
    minSpeedKt: 0,
    climbRateMps: 40,
    weapon: { damage: 60, fuzeM: 45, pHit: 0.85, rangeM: 130_000 },
  },
  SAM: {
    id: 'SAM',
    name: 'Surface-to-air missile',
    domain: 'air',
    loaM: 5,
    beamM: 0.6,
    freeboardM: 0.4,
    maxSpeedKt: 1500,
    accelKtPerS: 120,
    turnRateDegPerS: 25,
    windage: 0,
    sensorRangeNm: 0,
    hullColor: '#e6e8ea',
    deckColor: '#c0522d',
    hp: 1,
    visualBoost: 10,
    trailScale: 0.6,
    cruiseAltM: 40,
    minSpeedKt: 0,
    climbRateMps: 250,
    weapon: { damage: 40, fuzeM: 60, pHit: 0.7, rangeM: 70_000 },
  },
  SSN: {
    id: 'SSN',
    name: 'Attack submarine (SSN)',
    domain: 'sub',
    loaM: 110,
    beamM: 12,
    freeboardM: 1.2,
    maxSpeedKt: 28,
    accelKtPerS: 0.1,
    turnRateDegPerS: 2,
    windage: 0,
    sensorRangeNm: 14,
    hullColor: '#1d2328',
    deckColor: '#262d33',
    hp: 150,
    visualBoost: 2,
    trailScale: 0.3,
  },
  TORP: {
    id: 'TORP',
    name: 'Torpedo',
    domain: 'sub',
    loaM: 6,
    beamM: 0.6,
    freeboardM: 0.3,
    maxSpeedKt: 50,
    accelKtPerS: 2,
    turnRateDegPerS: 6,
    windage: 0,
    sensorRangeNm: 0,
    hullColor: '#cfd6dc',
    deckColor: '#9fb0bd',
    hp: 1,
    visualBoost: 14,
    trailScale: 0.5,
    cruiseAltM: -15,
    weapon: { damage: 120, fuzeM: 20, pHit: 0.75, rangeM: 28_000 },
  },
  FFG: {
    ...surface,
    id: 'FFG',
    name: 'Frigate (FFG)',
    loaM: 135,
    beamM: 16,
    freeboardM: 6,
    maxSpeedKt: 29,
    accelKtPerS: 0.2,
    turnRateDegPerS: 2.3,
    windage: 0.006,
    sensorRangeNm: 80,
    hullColor: '#7b838a',
    deckColor: '#a3abb2',
    hp: 80,
    defence: { rangeM: 8000, pKill: 0.4, shots: 2, reloadS: 12, magazine: 20 },
  },
  SSK: {
    id: 'SSK',
    name: 'Diesel submarine (SSK)',
    domain: 'sub',
    loaM: 70,
    beamM: 8,
    freeboardM: 1,
    maxSpeedKt: 17,
    accelKtPerS: 0.06,
    turnRateDegPerS: 2.5,
    windage: 0,
    sensorRangeNm: 10,
    hullColor: '#1d2328',
    deckColor: '#262d33',
    hp: 90,
    visualBoost: 3,
    trailScale: 0.2,
  },
  UAV: {
    id: 'UAV',
    name: 'Surveillance drone (UAV)',
    domain: 'air',
    loaM: 11,
    beamM: 20,
    freeboardM: 1,
    maxSpeedKt: 180,
    accelKtPerS: 2,
    turnRateDegPerS: 6,
    windage: 1,
    sensorRangeNm: 60,
    hullColor: '#c9ced2',
    deckColor: '#9aa3aa',
    hp: 12,
    visualBoost: 6,
    trailScale: 0.2,
    cruiseAltM: 3000,
    minSpeedKt: 60,
    climbRateMps: 6,
  },
  AEW: {
    id: 'AEW',
    name: 'Airborne early warning (AEW)',
    domain: 'air',
    loaM: 18,
    beamM: 25,
    freeboardM: 2,
    maxSpeedKt: 320,
    accelKtPerS: 3,
    turnRateDegPerS: 4,
    windage: 1,
    sensorRangeNm: 200,
    hullColor: '#a9b0b6',
    deckColor: '#7d868d',
    hp: 40,
    visualBoost: 5,
    trailScale: 0.3,
    cruiseAltM: 8000,
    minSpeedKt: 120,
    climbRateMps: 15,
  },
  DRONE: {
    id: 'DRONE',
    name: 'Attack drone',
    domain: 'air',
    loaM: 3.5,
    beamM: 2.6,
    freeboardM: 0.4,
    maxSpeedKt: 110,
    accelKtPerS: 10,
    turnRateDegPerS: 12,
    windage: 0.5,
    sensorRangeNm: 0,
    hullColor: '#3b4147',
    deckColor: '#2b3036',
    hp: 1,
    visualBoost: 14,
    trailScale: 0.4,
    cruiseAltM: 60,
    minSpeedKt: 0,
    climbRateMps: 15,
    weapon: { damage: 25, fuzeM: 15, pHit: 0.6, rangeM: 90_000 },
  },
  MINE: {
    id: 'MINE',
    name: 'Naval mine',
    domain: 'static',
    loaM: 1.6,
    beamM: 1.6,
    freeboardM: 0.8,
    maxSpeedKt: 0,
    accelKtPerS: 0,
    turnRateDegPerS: 0,
    windage: 0,
    sensorRangeNm: 0,
    hullColor: '#3a3f44',
    deckColor: '#c0392b',
    hp: 1,
    visualBoost: 12,
    trailScale: 0,
    weapon: { damage: 70, fuzeM: 45, pHit: 0.7, rangeM: 0 },
  },
};

export const CLASS_IDS = Object.keys(SHIP_CLASSES) as ClassId[];

/** A missile: flies, homes on a target and is spent on reaching it. */
export const isMissile = (cls: ShipClass): boolean => (cls.domain === 'air' || cls.domain === 'sub') && !!cls.weapon;
export const isMine = (cls: ShipClass): boolean => cls.domain === 'static' && !!cls.weapon;
/** A ship or aircraft: what counts as a loss. */
export const isPlatform = (cls: ShipClass): boolean => !cls.weapon;

export const SIDE_COLORS: Record<Side, string> = {
  BLUE: '#3da5ff',
  RED: '#ff4a4a',
  NEUTRAL: '#e6d36a',
};

/** A box on the unit, in local meters: +x forward, +y to port. `base` and `height` are above the waterline (or the unit's altitude). */
export interface ShipPart {
  points: [number, number][];
  base: number;
  height: number;
  color: string;
}

/** One layer of the hull, stacked to fake a tapered, flared hull out of vertical extrusions. */
export interface HullSlice {
  /** Scale of the outline along and across the unit. */
  stretch: number;
  beamScale: number;
  base: number;
  top: number;
  color: string;
}

/** A small emissive light, in local meters. `height` is above the waterline (or the unit's altitude). */
export interface ShipLight {
  x: number;
  y: number;
  height: number;
  color: string;
  /** Edge length of the light, meters. */
  size: number;
  /** Glows even in daylight (a missile's exhaust). */
  alwaysGlow?: boolean;
}

export interface ShipShape {
  hull: [number, number][];
  slices: HullSlice[];
  parts: ShipPart[];
  lights: ShipLight[];
}

/** Half-beam fraction at positions along the hull, from stern (-0.5 of LOA) to bow (+0.5). */
const HULL_PROFILE: [number, number][] = [
  [-0.5, 0.78],
  [-0.4, 0.94],
  [-0.28, 1],
  [0.1, 1],
  [0.22, 0.9],
  [0.32, 0.72],
  [0.4, 0.48],
  [0.46, 0.22],
  [0.5, 0],
];

const OUTLINES: Partial<Record<ClassId, [number, number][]>> = {
  SSN: [[-0.5, 0], [-0.46, 0.45], [-0.3, 0.9], [0.1, 1], [0.38, 0.8], [0.5, 0]],
  SSK: [[-0.5, 0], [-0.46, 0.45], [-0.3, 0.9], [0.1, 1], [0.38, 0.8], [0.5, 0]],
  UAV: [[-0.5, 0.1], [-0.3, 0.14], [0, 0.14], [0.3, 0.1], [0.5, 0]],
  AEW: [[-0.5, 0.15], [-0.3, 0.2], [0.1, 0.22], [0.35, 0.14], [0.5, 0]],
  DRONE: [[-0.5, 0.4], [0.1, 0.5], [0.5, 0]],
  TORP: [[-0.5, 0.5], [0.3, 0.5], [0.5, 0]],
  FIGHTER: [[-0.5, 0.2], [-0.3, 0.24], [0, 0.24], [0.25, 0.16], [0.4, 0.08], [0.5, 0]],
  HELO: [[-0.5, 0.05], [-0.25, 0.1], [0.1, 0.15], [0.3, 0.13], [0.5, 0]],
  ASM: [[-0.5, 0.5], [0.2, 0.5], [0.5, 0]],
  SAM: [[-0.5, 0.5], [0.2, 0.5], [0.5, 0]],
};

function mirrored(profile: [number, number][], loaM: number, beamM: number): [number, number][] {
  const hb = beamM / 2;
  const port = profile.map(([u, w]): [number, number] => [u * loaM, w * hb]);
  const starboard = profile
    .slice(0, -1)
    .reverse()
    .map(([u, w]): [number, number] => [u * loaM, -w * hb]);
  return [...port, ...starboard];
}

export function hullOutline(loaM: number, beamM: number): [number, number][] {
  return mirrored(HULL_PROFILE, loaM, beamM);
}

function outlineFor(cls: ShipClass): [number, number][] {
  if (cls.domain === 'static') {
    return Array.from({ length: 12 }, (_, i): [number, number] => {
      const a = (i / 12) * Math.PI * 2;
      return [Math.cos(a) * cls.loaM * 0.5, Math.sin(a) * cls.beamM * 0.5];
    });
  }
  const custom = OUTLINES[cls.id];
  return custom ? mirrored(custom, cls.loaM, cls.beamM) : hullOutline(cls.loaM, cls.beamM);
}

interface Block {
  /** Center along the ship as a fraction of LOA (+ forward). */
  x: number;
  /** Length as a fraction of LOA. */
  len: number;
  /** Center across the ship as a fraction of beam (+ to port). */
  y: number;
  /** Width as a fraction of beam. */
  w: number;
  /** Height of the block, meters. */
  h: number;
  /** Raised off the hull top, meters (negative drops it below the top). */
  lift?: number;
  color?: string;
  /** Rotation about the block's center, degrees counter-clockwise seen from above. */
  rot?: number;
}

const b = (x: number, len: number, y: number, w: number, h: number, extra: Partial<Block> = {}): Block => ({ x, len, y, w, h, ...extra });

const MAST = '#394047';
const DOME = '#dfe3e6';
const DARK = '#4b535a';
const PAINT = '#e4e6e8';

export function mix(hex: string, other: string, t: number): string {
  const ch = (h: string, i: number) => parseInt(h.slice(1 + i * 2, 3 + i * 2), 16);
  const c = [0, 1, 2].map((i) => Math.round(ch(hex, i) * (1 - t) + ch(other, i) * t));
  return `#${c.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

function parkedAircraft(positions: [number, number][], color = '#a7afb5'): Block[] {
  return positions.map(([x, y]) => b(x, 0.034, y, 0.26, 3, { lift: 1.5, color, rot: (x * 37 + y * 11) % 30 }));
}

const missileParts = (fin: string): Block[] => [
  b(-0.38, 0.14, 0, 3.0, 0.1, { lift: -0.2, color: fin }),
  b(-0.4, 0.14, 0, 0.12, 1.0, { lift: -0.2, color: fin }),
];

function profile(id: ClassId): Block[] {
  switch (id) {
    case 'CVN':
      return [
        b(0, 0.96, 0, 1.7, 1.5),
        // Angled landing area, catapult tracks and elevator pads, painted on the deck.
        b(-0.1, 0.62, 0.2, 0.09, 0.12, { lift: 1.5, rot: -8, color: PAINT }),
        b(-0.1, 0.62, 0.43, 0.012, 0.12, { lift: 1.5, rot: -8, color: PAINT }),
        b(0.3, 0.3, 0.12, 0.014, 0.12, { lift: 1.5, color: PAINT }),
        b(0.3, 0.3, -0.12, 0.014, 0.12, { lift: 1.5, color: PAINT }),
        b(0.12, 0.05, 0.62, 0.2, 0.2, { lift: 1.5, color: DARK }),
        b(-0.3, 0.05, 0.62, 0.2, 0.2, { lift: 1.5, color: DARK }),
        b(-0.05, 0.05, -0.64, 0.2, 0.2, { lift: 1.5, color: DARK }),
        // Island with its mast and radar.
        b(0.1, 0.1, -0.78, 0.2, 18, { lift: 1.5, color: '#9aa2a9' }),
        b(0.1, 0.05, -0.78, 0.12, 10, { lift: 19.5, color: '#8a929a' }),
        b(0.1, 0.012, -0.78, 0.04, 14, { lift: 29.5, color: MAST }),
        b(0.085, 0.03, -0.78, 0.1, 2.5, { lift: 36, color: DOME }),
        ...parkedAircraft([[-0.36, -0.52], [-0.3, -0.55], [-0.24, -0.5], [-0.18, -0.55], [-0.4, 0.4], [0.2, -0.3], [0.26, -0.45], [0.36, 0.42]]),
      ];
    case 'LHD':
      return [
        b(0, 0.94, 0, 1.35, 1.5),
        b(-0.05, 0.6, 0.0, 0.015, 0.12, { lift: 1.5, color: PAINT }),
        b(0.1, 0.04, 0.5, 0.18, 0.2, { lift: 1.5, color: DARK }),
        b(-0.25, 0.04, 0.5, 0.18, 0.2, { lift: 1.5, color: DARK }),
        b(0.12, 0.12, -0.62, 0.2, 14, { lift: 1.5, color: '#9aa2a9' }),
        b(0.12, 0.012, -0.62, 0.05, 12, { lift: 15.5, color: MAST }),
        b(0.1, 0.03, -0.62, 0.1, 2.2, { lift: 26, color: DOME }),
        ...parkedAircraft([[-0.34, 0.2], [-0.28, 0.28], [-0.22, 0.2], [0.28, -0.1], [0.34, 0.25]], '#8f989f'),
      ];
    case 'CG':
    case 'FFG':
    case 'DDG': {
      const cg = id === 'CG';
      return [
        b(-0.36, 0.16, 0, 0.75, 0.5, { color: '#59616a' }),
        b(-0.22, 0.1, 0, 0.58, 4.5),
        b(0.02, cg ? 0.32 : 0.3, 0, 0.66, 6),
        b(0.03, 0.18, 0, 0.5, 3.5, { lift: 6 }),
        b(0.06, 0.06, 0, 0.74, 1.2, { lift: 6.2, color: '#8e969d' }),
        b(-0.03, 0.018, 0, 0.06, 20, { lift: 9.5, color: MAST }),
        b(0.0, 0.04, 0, 0.1, 3, { lift: 29.5, color: DOME }),
        b(-0.12, 0.06, 0, 0.24, 5, { lift: 6 }),
        b(0.27, 0.1, 0, 0.4, 0.8, { color: '#50575e' }),
        ...(cg ? [b(-0.3, 0.08, 0, 0.4, 0.8, { color: '#50575e' })] : []),
        b(0.37, 0.035, 0, 0.08, 2.4, { color: '#6b737a' }),
      ];
    }
    case 'FAC':
      return [
        b(-0.05, 0.3, 0, 0.55, 2.2),
        b(-0.02, 0.06, 0, 0.2, 4.5, { lift: 2.2, color: MAST }),
        b(0.0, 0.04, 0, 0.14, 1.2, { lift: 6.7, color: DOME }),
        b(0.28, 0.06, 0, 0.1, 1.4, { color: '#5b636a' }),
        b(-0.28, 0.1, 0, 0.5, 0.6, { color: '#6e665c' }),
      ];
    case 'CARGO': {
      const palette = ['#2f6fb0', '#d98a2b', '#3e8f5a', '#b23a3a', '#d8d2c4', '#5a6fa8', '#c9602d'];
      const stacks: Block[] = [];
      for (let i = 0; i < 8; i++) {
        for (const y of [-0.22, 0.22]) {
          stacks.push(b(-0.2 + i * 0.08, 0.068, y, 0.4, 6 + ((i * 3 + (y > 0 ? 2 : 0)) % 5) * 2.4, { color: palette[(i * 2 + (y > 0 ? 3 : 0)) % palette.length] }));
        }
      }
      return [
        b(-0.4, 0.09, 0, 0.82, 18, { color: '#e8e4da' }),
        b(-0.4, 0.06, 0, 0.7, 7, { lift: 18, color: '#f1eee6' }),
        b(-0.44, 0.03, 0, 0.3, 8, { lift: 6, color: '#b9322c' }),
        ...stacks,
        b(0.4, 0.05, 0, 0.6, 3, { color: '#6c6458' }),
      ];
    }
    case 'FIGHTER':
      return [
        // Swept wings and tailplanes, a fin and a canopy.
        b(-0.08, 0.26, 0.29, 0.5, 0.35, { lift: -1.1, rot: 30, color: '#7a828a' }),
        b(-0.08, 0.26, -0.29, 0.5, 0.35, { lift: -1.1, rot: -30, color: '#7a828a' }),
        b(-0.42, 0.12, 0.17, 0.2, 0.25, { lift: -1.2, rot: 25, color: '#7a828a' }),
        b(-0.42, 0.12, -0.17, 0.2, 0.25, { lift: -1.2, rot: -25, color: '#7a828a' }),
        b(-0.4, 0.2, 0, 0.03, 2.8, { color: '#59616a' }),
        b(0.12, 0.2, 0, 0.1, 0.7, { color: '#1c2630' }),
      ];
    case 'HELO':
      return [
        b(-0.38, 0.45, 0, 0.1, 0.8, { lift: -1.6, color: '#59636b' }),
        b(-0.46, 0.08, 0, 0.04, 1.8, { lift: -0.6, color: '#434c53' }),
        b(0.05, 0.05, 0, 0.05, 1.2, { color: '#2e353b' }),
        b(0.05, 0.95, 0, 0.07, 0.12, { lift: 1.2, rot: 25, color: '#20262b' }),
        b(0.05, 0.95, 0, 0.07, 0.12, { lift: 1.2, rot: 115, color: '#20262b' }),
      ];
    case 'ASM':
      return missileParts('#8a8f94');
    case 'SAM':
      return missileParts('#c0522d');
    case 'SSN':
    case 'SSK':
      return [b(0.1, 0.07, 0, 0.1, 6, { lift: 0.4, color: '#2b333a' })];
    case 'UAV':
      return [
        // Long thin wings, a fuselage, a V-tail and a sensor ball.
        b(0, 0.12, 0, 1, 0.12, { lift: -0.4, color: '#aeb6bc' }),
        b(-0.46, 0.1, 0, 0.35, 0.1, { lift: -0.2, color: '#9aa3aa' }),
        b(-0.4, 0.14, 0.1, 0.04, 0.9, { lift: -0.2, rot: 20, color: '#8a939a' }),
        b(0.32, 0.1, 0, 0.1, 0.5, { lift: -0.3, color: '#2b333a' }),
      ];
    case 'AEW':
      return [
        b(-0.05, 0.2, 0, 1, 0.3, { lift: -1.2, color: '#a9b0b6' }),
        b(-0.44, 0.1, 0, 0.5, 0.2, { lift: -0.6, color: '#8f979d' }),
        b(-0.44, 0.1, 0.22, 0.05, 2.4, { lift: -0.6, color: '#7d868d' }),
        b(-0.44, 0.1, -0.22, 0.05, 2.4, { lift: -0.6, color: '#7d868d' }),
        // The rotodome.
        b(-0.02, 0.4, 0, 0.5, 0.7, { lift: 1.4, color: '#dfe3e6' }),
      ];
    case 'DRONE':
      return [
        b(0, 0.9, 0, 0.3, 0.2, { lift: -0.1, color: '#4a5258' }),
        b(0.1, 0.25, 0, 1, 0.08, { lift: -0.1, color: '#50585e' }),
        b(-0.42, 0.12, 0, 0.7, 0.08, { lift: -0.1, color: '#50585e' }),
      ];
    case 'TORP':
      return missileParts('#9fb0bd');
    case 'MINE':
      return [
        b(0, 0.3, 0, 0.3, 0.7, { color: '#c0392b' }),
        b(0.42, 0.14, 0, 0.14, 0.4, { color: '#c0392b' }),
        b(-0.42, 0.14, 0, 0.14, 0.4, { color: '#c0392b' }),
        b(0, 0.14, 0.42, 0.14, 0.4, { color: '#c0392b' }),
        b(0, 0.14, -0.42, 0.14, 0.4, { color: '#c0392b' }),
      ];
  }
}

function slicesFor(cls: ShipClass): HullSlice[] {
  const fb = cls.freeboardM;
  if (cls.domain !== 'surface') return [{ stretch: 1, beamScale: 1, base: 0, top: fb, color: cls.hullColor }];
  const band = Math.min(1.6, fb * 0.18);
  return [
    { stretch: 0.995, beamScale: 0.97, base: 0, top: band, color: '#23282c' },
    { stretch: 1, beamScale: 1, base: band, top: fb * 0.84, color: cls.hullColor },
    { stretch: 1.006, beamScale: 1.06, base: fb * 0.84, top: fb, color: mix(cls.hullColor, '#ffffff', 0.14) },
  ];
}

function lightsFor(cls: ShipClass): ShipLight[] {
  const L = cls.loaM;
  const B = cls.beamM;
  const fb = cls.freeboardM;
  if (cls.domain === 'static') return [];
  if (cls.id === 'SSN') return [];
  if (cls.weapon) return [{ x: -0.5 * L, y: 0, height: fb * 0.6, color: cls.domain === 'sub' ? '#9be7ff' : '#ff9a3c', size: Math.max(1.2, L * 0.25), alwaysGlow: true }];
  if (cls.domain === 'air') {
    const tip = cls.id === 'FIGHTER' ? B * 0.48 : B * 0.2;
    return [
      { x: -0.18 * L, y: tip, height: 0.9, color: '#ff3b30', size: 0.7 },
      { x: -0.18 * L, y: -tip, height: 0.9, color: '#2bff72', size: 0.7 },
      { x: -0.42 * L, y: 0, height: fb + (cls.id === 'FIGHTER' ? 3 : 1.8), color: '#ffffff', size: 0.8 },
    ];
  }
  const lights: ShipLight[] = [
    { x: -0.03 * L, y: 0, height: fb + (cls.id === 'CARGO' ? 30 : cls.id === 'FAC' ? 7 : 30), color: '#ffffff', size: 1.6 },
    { x: -0.5 * L, y: 0, height: fb + 1.5, color: '#ffffff', size: 1.4 },
    { x: 0.3 * L, y: B * 0.5, height: fb + 1.5, color: '#ff3b30', size: 1.4 },
    { x: 0.3 * L, y: -B * 0.5, height: fb + 1.5, color: '#2bff72', size: 1.4 },
  ];
  if (L >= 200) {
    for (const x of [-0.4, -0.2, 0, 0.2, 0.4]) {
      for (const side of [-1, 1]) lights.push({ x: x * L, y: side * B * 0.82, height: fb + 0.6, color: '#ffd9a0', size: 1.6 });
    }
  }
  return lights;
}

export function shipShape(id: ClassId): ShipShape {
  const cls = SHIP_CLASSES[id];
  const parts = profile(id).map((blk): ShipPart => {
    const cx = blk.x * cls.loaM;
    const cy = blk.y * cls.beamM;
    const hl = (blk.len * cls.loaM) / 2;
    const hw = (blk.w * cls.beamM) / 2;
    const rot = ((blk.rot ?? 0) * Math.PI) / 180;
    const c = Math.cos(rot);
    const sn = Math.sin(rot);
    const base = Math.max(0, cls.freeboardM + (blk.lift ?? 0));
    const corners: [number, number][] = [
      [-hl, -hw],
      [hl, -hw],
      [hl, hw],
      [-hl, hw],
    ];
    return {
      points: corners.map(([px, py]): [number, number] => [cx + px * c - py * sn, cy + px * sn + py * c]),
      base,
      height: base + blk.h,
      color: blk.color ?? cls.deckColor,
    };
  });
  return { hull: outlineFor(cls), slices: slicesFor(cls), parts, lights: lightsFor(cls) };
}
