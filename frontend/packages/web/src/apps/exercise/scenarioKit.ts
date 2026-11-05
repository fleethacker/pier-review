import { offsetM, stationFrom } from './geo';
import { makeRng } from './sim';
import type { LonLat, UnitConfig, Waypoint } from './types';

/** Open Atlantic, well clear of land and shipping lanes. */
export const OCEAN_CENTER = { lon: -62, lat: 33 };

export const at = (eastM: number, northM: number) => offsetM(OCEAN_CENTER, eastM, northM);
export const wp = (eastM: number, northM: number, speedKt?: number): Waypoint => ({ ...at(eastM, northM), speedKt });

/** Where an escort starts so it is already on its station when the leader is at `leader` on `headingDeg`. */
export const station = (leader: LonLat, headingDeg: number, aheadM: number, abeamM: number): LonLat =>
  stationFrom(leader, headingDeg, aheadM, abeamM);


/** Mines scattered over a box (meters east and north of the ocean center), always in the same places for a given seed. */
export function minefield(count: number, eastM: number, northM: number, halfWidthM: number, halfHeightM: number, seed: number): UnitConfig[] {
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
