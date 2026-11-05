import type { Berth, SideTo } from './types';

const POINTS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];

export function compass(deg: number): string {
  return POINTS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16];
}

const rad = (deg: number) => (deg * Math.PI) / 180;
const wrap = (deg: number) => ((deg % 360) + 360) % 360;

/** True heading of the bow: starboard side to puts the bow along the berth face bearing, port side to the reverse. */
export function shipHeadingTrue(berth: Berth, side: SideTo): number {
  return wrap(berth.face_bearing_true_deg + (side === 'starboard' ? 0 : 180));
}

export interface ShipComponents {
  /** Positive pushes the ship away from the pier, negative presses it onto the pier. */
  offPierKt: number;
  /** Positive pushes the ship toward its bow, negative toward its stern. */
  alongKt: number;
}

/** Splits wind or current moving toward `towardTrueDeg` into the parts that act across and along the moored ship. */
export function shipComponents(towardTrueDeg: number, speedKt: number, berth: Berth, side: SideTo): ShipComponents {
  const heading = shipHeadingTrue(berth, side);
  const awayFromPier = wrap(heading + (side === 'starboard' ? 90 : 270) + 180);
  return {
    offPierKt: speedKt * Math.cos(rad(towardTrueDeg - awayFromPier)),
    alongKt: speedKt * Math.cos(rad(towardTrueDeg - heading)),
  };
}

export function describeComponents(c: ShipComponents): { offPier: string; along: string } {
  const off = Math.abs(c.offPierKt);
  const along = Math.abs(c.alongKt);
  return {
    offPier: off < 0.05 ? 'none' : `${off.toFixed(1)} kt ${c.offPierKt > 0 ? 'off the pier' : 'onto the pier'}`,
    along: along < 0.05 ? 'none' : `${along.toFixed(1)} kt toward the ${c.alongKt > 0 ? 'bow' : 'stern'}`,
  };
}
