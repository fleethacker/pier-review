import type { ClassId, Side } from './types';

/** Illustrative dimensions and handling, rounded from public figures. Not for operational use. */
export interface ShipClass {
  id: ClassId;
  name: string;
  loaM: number;
  beamM: number;
  /** Hull height above the waterline. */
  freeboardM: number;
  maxSpeedKt: number;
  accelKtPerS: number;
  /** Rudder-limited turn rate at speed. */
  turnRateDegPerS: number;
  /** Fraction of the wind speed the ship is pushed downwind at. Rough. */
  windage: number;
  /** Radius of the optional sensor ring. Illustrative. */
  sensorRangeNm: number;
  hullColor: string;
  deckColor: string;
}

export const SHIP_CLASSES: Record<ClassId, ShipClass> = {
  CVN: {
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
  },
  LHD: {
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
  },
  CG: {
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
  },
  DDG: {
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
  },
  FAC: {
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
  },
  CARGO: {
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
  },
};

export const CLASS_IDS = Object.keys(SHIP_CLASSES) as ClassId[];

export const SIDE_COLORS: Record<Side, string> = {
  BLUE: '#3da5ff',
  RED: '#ff4a4a',
  NEUTRAL: '#e6d36a',
};

/** A box on the ship, in local meters: +x forward, +y to port. `base` and `height` are above the waterline. */
export interface ShipPart {
  points: [number, number][];
  base: number;
  height: number;
  color: string;
}

export interface ShipShape {
  hull: [number, number][];
  parts: ShipPart[];
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

export function hullOutline(loaM: number, beamM: number): [number, number][] {
  const hb = beamM / 2;
  const port = HULL_PROFILE.map(([u, w]): [number, number] => [u * loaM, w * hb]);
  const starboard = HULL_PROFILE.slice(0, -1)
    .reverse()
    .map(([u, w]): [number, number] => [u * loaM, -w * hb]);
  return [...port, ...starboard];
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
  /** Height above the hull top, meters. */
  h: number;
  /** Raised off the hull top, meters. */
  lift?: number;
  color?: string;
}

function profile(id: ClassId): Block[] {
  switch (id) {
    case 'CVN':
      return [
        { x: 0, len: 0.96, y: 0, w: 1.7, h: 1.5, lift: 0 },
        { x: 0.1, len: 0.1, y: -0.78, w: 0.2, h: 20, lift: 1.5, color: '#9aa2a9' },
      ];
    case 'LHD':
      return [
        { x: 0, len: 0.94, y: 0, w: 1.35, h: 1.5 },
        { x: 0.12, len: 0.12, y: -0.62, w: 0.2, h: 17, lift: 1.5, color: '#9aa2a9' },
      ];
    case 'CG':
      return [
        { x: 0.05, len: 0.3, y: 0, w: 0.64, h: 9 },
        { x: -0.12, len: 0.07, y: 0, w: 0.3, h: 16 },
        { x: 0.3, len: 0.07, y: 0, w: 0.3, h: 3 },
      ];
    case 'DDG':
      return [
        { x: 0.08, len: 0.28, y: 0, w: 0.64, h: 9 },
        { x: -0.1, len: 0.07, y: 0, w: 0.28, h: 15 },
        { x: 0.3, len: 0.06, y: 0, w: 0.3, h: 3 },
      ];
    case 'FAC':
      return [
        { x: -0.05, len: 0.32, y: 0, w: 0.55, h: 3 },
        { x: -0.02, len: 0.08, y: 0, w: 0.2, h: 6 },
      ];
    case 'CARGO':
      return [
        { x: -0.37, len: 0.12, y: 0, w: 0.8, h: 24, color: '#e8e4da' },
        { x: -0.18, len: 0.14, y: 0, w: 0.86, h: 14, color: '#2f6fb0' },
        { x: 0, len: 0.14, y: 0, w: 0.86, h: 16, color: '#d98a2b' },
        { x: 0.18, len: 0.14, y: 0, w: 0.86, h: 12, color: '#3e8f5a' },
        { x: 0.34, len: 0.1, y: 0, w: 0.8, h: 9, color: '#b23a3a' },
      ];
  }
}

export function shipShape(id: ClassId): ShipShape {
  const cls = SHIP_CLASSES[id];
  const parts = profile(id).map((b): ShipPart => {
    const cx = b.x * cls.loaM;
    const cy = b.y * cls.beamM;
    const hl = (b.len * cls.loaM) / 2;
    const hw = (b.w * cls.beamM) / 2;
    const base = cls.freeboardM + (b.lift ?? 0);
    return {
      points: [
        [cx - hl, cy - hw],
        [cx + hl, cy - hw],
        [cx + hl, cy + hw],
        [cx - hl, cy + hw],
      ],
      base,
      height: base + b.h,
      color: b.color ?? cls.deckColor,
    };
  });
  return { hull: hullOutline(cls.loaM, cls.beamM), parts };
}
