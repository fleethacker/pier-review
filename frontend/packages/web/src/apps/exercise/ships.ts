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

/** One layer of the hull, stacked to fake a tapered, flared hull out of vertical extrusions. */
export interface HullSlice {
  /** Scale of the outline along and across the ship. */
  stretch: number;
  beamScale: number;
  base: number;
  top: number;
  color: string;
}

/** A small emissive light, in local meters. `height` is above the waterline. */
export interface ShipLight {
  x: number;
  y: number;
  height: number;
  color: string;
  /** Edge length of the light, meters. */
  size: number;
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
  /** Height of the block, meters. */
  h: number;
  /** Raised off the hull top, meters. */
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

function mix(hex: string, other: string, t: number): string {
  const ch = (h: string, i: number) => parseInt(h.slice(1 + i * 2, 3 + i * 2), 16);
  const c = [0, 1, 2].map((i) => Math.round(ch(hex, i) * (1 - t) + ch(other, i) * t));
  return `#${c.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

function parkedAircraft(positions: [number, number][], color = '#a7afb5'): Block[] {
  return positions.map(([x, y]) => b(x, 0.034, y, 0.26, 3, { lift: 1.5, color, rot: (x * 37 + y * 11) % 30 }));
}

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
  }
}

function slicesFor(cls: ShipClass): HullSlice[] {
  const fb = cls.freeboardM;
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
    const base = cls.freeboardM + (blk.lift ?? 0);
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
  return { hull: hullOutline(cls.loaM, cls.beamM), slices: slicesFor(cls), parts, lights: lightsFor(cls) };
}
