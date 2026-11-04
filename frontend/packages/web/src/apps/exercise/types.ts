/** Scenario configuration for the exercise simulator. Plain JSON so scenarios can be saved, shared and edited by hand. */

export interface LonLat {
  lon: number;
  lat: number;
}

export type ClassId = 'CVN' | 'LHD' | 'CG' | 'DDG' | 'FAC' | 'CARGO';
export type Side = 'BLUE' | 'RED' | 'NEUTRAL';

export interface Waypoint extends LonLat {
  /** Speed to make good on the leg toward this waypoint. Falls back to the unit's cruise speed. */
  speedKt?: number;
}

export type Behavior =
  /** Steam through the waypoints in order. At the last one: loop back to the first, or come to a stop. */
  | { type: 'route'; waypoints: Waypoint[]; loop?: boolean }
  /** Keep station on another unit: `aheadM` along its heading, `abeamM` to its starboard (negative is port). */
  | { type: 'escort'; leaderId: string; aheadM: number; abeamM: number }
  /** Close on another unit and shadow it once within `standoffM`. */
  | { type: 'pursue'; targetId: string; standoffM: number }
  /** Stop and drift with the current and wind. */
  | { type: 'hold' };

export interface UnitConfig {
  id: string;
  name: string;
  classId: ClassId;
  side: Side;
  start: LonLat;
  headingDeg: number;
  /** Speed through the water at the start, and the cruise speed for behaviors that do not set their own. */
  speedKt: number;
  /** Caps the turn rate below what the ship can do. Formation guides turn slowly so escorts can keep station. */
  maxTurnRateDegPerS?: number;
  behavior: Behavior;
}

export interface Environment {
  /** Direction the wind blows from, degrees true. */
  windFromDeg: number;
  windKt: number;
  /** Direction the current flows toward, degrees true. */
  currentToDeg: number;
  currentKt: number;
}

export type LightPreset = 'dawn' | 'day' | 'dusk' | 'night';

export interface ScenarioConfig {
  id: string;
  name: string;
  description: string;
  /** Where the camera starts. */
  center: LonLat;
  durationS: number;
  lightPreset: LightPreset;
  environment: Environment;
  units: UnitConfig[];
}

/** Kinematic state of one unit at one instant. */
export interface UnitState {
  lon: number;
  lat: number;
  /** Where the bow points, degrees true. */
  headingDeg: number;
  /** Speed through the water. */
  speedKt: number;
  /** Course and speed over the ground (includes current and leeway). */
  cogDeg: number;
  sogKt: number;
}
