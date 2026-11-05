/** Scenario configuration for the exercise simulator. Plain JSON so scenarios can be saved, shared and edited by hand. */

export interface LonLat {
  lon: number;
  lat: number;
}

export type ClassId = 'CVN' | 'LHD' | 'CG' | 'DDG' | 'FAC' | 'CARGO' | 'FIGHTER' | 'HELO' | 'ASM' | 'SAM' | 'MINE';
export type Side = 'BLUE' | 'RED' | 'NEUTRAL';

export interface Waypoint extends LonLat {
  /** Speed to make good on the leg toward this waypoint. Falls back to the unit's cruise speed. */
  speedKt?: number;
  /** Aircraft only: altitude to be at when reaching this waypoint, meters. */
  altitudeM?: number;
}

export type Behavior =
  /** Go through the waypoints in order. At the last one: loop back to the first, or stop (aircraft circle there). */
  | { type: 'route'; waypoints: Waypoint[]; loop?: boolean }
  /** Keep station on another unit: `aheadM` along its heading, `abeamM` to its starboard (negative is port). */
  | { type: 'escort'; leaderId: string; aheadM: number; abeamM: number }
  /** Close on another unit and shadow it once within `standoffM`. */
  | { type: 'pursue'; targetId: string; standoffM: number }
  /** Aircraft only: circle a point. */
  | { type: 'loiter'; center: LonLat; radiusM: number }
  /** Missiles only: home on a unit and detonate on reaching it. */
  | { type: 'strike'; targetId: string }
  /** Stop and drift with the current and wind (aircraft that cannot hover circle where they are). */
  | { type: 'hold' };

export interface UnitConfig {
  id: string;
  name: string;
  classId: ClassId;
  side: Side;
  start: LonLat;
  headingDeg: number;
  /** Speed through the water (or air) at the start, and the cruise speed for behaviors that do not set their own. */
  speedKt: number;
  /** Caps the turn rate below what the unit can do. Formation guides turn slowly so escorts can keep station. */
  maxTurnRateDegPerS?: number;
  behavior: Behavior;
  /** Aircraft: starting altitude and the altitude held when a waypoint does not say otherwise. Meters. */
  altitudeM?: number;
  /**
   * The unit does not exist until `atS`, when it appears at `byId`'s position (a missile fired, an aircraft launched).
   * If the launcher has been destroyed by then, the launch is aborted.
   */
  launch?: { byId: string; atS: number };
  /** Leave the unit out of the run altogether. */
  disabled?: boolean;
  /** Hit points. Defaults to the class's. Anything that does at least this much damage in one hit destroys the unit. */
  hp?: number;
  /** Damage a missile or mine does to what it hits. Defaults to the class's. */
  damage?: number;
  /** Chance a missile or mine does its damage when it reaches its target, 0 to 1. Defaults to the class's. */
  pHit?: number;
  /** Chance each of this ship's defensive shots shoots down an incoming missile, 0 to 1. Defaults to the class's. */
  pKill?: number;
  /** Defensive shots this ship has. Defaults to the class's. */
  magazine?: number;
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

// ---- red team: random variation and the questions to ask of it ----

export type Dist =
  | { type: 'uniform'; min: number; max: number }
  | { type: 'normal'; mean: number; sd: number }
  | { type: 'triangular'; min: number; mode: number; max: number }
  | { type: 'choice'; values: number[]; weights?: number[] };

export type EnvField = 'windKt' | 'windFromDeg' | 'currentKt' | 'currentToDeg';
export type UnitField =
  | 'speedKt'
  | 'headingDeg'
  /** Offsets in meters from the unit's start. */
  | 'startEastM'
  | 'startNorthM'
  /** Offsets in meters applied to every waypoint (and loiter center) of the unit's route. */
  | 'routeEastM'
  | 'routeNorthM'
  | 'launchAtS'
  | 'altitudeM'
  | 'hp'
  | 'damage'
  | 'pHit'
  | 'pKill'
  | 'magazine'
  /** 0 or 1. */
  | 'disabled';

export type PerturbTarget = { kind: 'environment'; field: EnvField } | { kind: 'unit'; unitId: string; field: UnitField };

export interface Perturbation {
  id: string;
  label?: string;
  target: PerturbTarget;
  /** How the draw combines with the scenario's value: replace it, add to it, or multiply it. Offsets always add. */
  mode: 'set' | 'add' | 'scale';
  dist: Dist;
}

export type OutcomeSpec = { id: string; label?: string } & (
  /** The unit is destroyed. */
  | { type: 'destroyed'; unitId: string }
  /** The unit is hit by anything. */
  | { type: 'hit'; unitId: string }
  /** The unit's hit points fall below this fraction of its maximum. */
  | { type: 'hp_below'; unitId: string; frac: number }
  /** At least this many ships or aircraft of a side are destroyed. */
  | { type: 'side_losses'; side: Side; atLeast: number }
  /** A mine goes off on a ship (any mine, or one ship). */
  | { type: 'mine_strike'; unitId?: string }
  /** At least this many incoming missiles are shot down. */
  | { type: 'intercepts'; atLeast: number }
  /** Two units come within this distance of each other at some point. */
  | { type: 'closest_approach'; aId: string; bId: string; withinM: number }
);

/** Sweep one setting over a list of values, running the whole batch at each: "how does it change with salvo size?" */
export interface SweepSpec {
  target: PerturbTarget | { kind: 'salvo'; unitIds: string[] };
  values: number[];
}

export interface RedTeamSpec {
  /** Runs per batch (per sweep value, if sweeping). */
  runs: number;
  seed: number;
  perturbations: Perturbation[];
  outcomes: OutcomeSpec[];
  sweep?: SweepSpec;
}

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
  /** Seeds the chance rolls (missile hits, defensive shots, mines) of the run you watch. Default 1. */
  seed?: number;
  /** Settings for the Monte Carlo runner. Does not affect the run you watch. */
  redTeam?: RedTeamSpec;
}

/** Kinematic state of one unit at one instant. */
export interface UnitState {
  lon: number;
  lat: number;
  /** Where the nose points, degrees true. */
  headingDeg: number;
  /** Speed through the water or air. */
  speedKt: number;
  /** Course and speed over the ground (includes current, wind and leeway). */
  cogDeg: number;
  sogKt: number;
  /** Meters above the sea (negative below it). */
  altM: number;
  /** Hit points left. 0 means destroyed. */
  hp: number;
  /** False before a unit is launched and after a missile, mine or aircraft is spent or destroyed. */
  active: boolean;
}
