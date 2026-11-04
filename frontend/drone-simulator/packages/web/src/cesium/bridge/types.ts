import * as Cesium from 'cesium';
import type { CameraType } from '../managers/CameraManager';

export type GameMode = 'play' | 'builder' | 'maverick';

export interface VehicleStateData {
  speed: number;
  velocity: number;
  position: Cesium.Cartesian3;
  heading: number;
  pitch: number;
  roll: number;
}

export interface CameraStateData {
  type: CameraType;
}

export interface RoverModeData {
  enabled: boolean;
}

export interface CollisionDetectionData {
  enabled: boolean;
}

export interface OnlinePlayer {
  id: string;
  name: string;
  position: Cesium.Cartesian3;
  heading: number;
  vehicleType: string;
}

export interface PlayersData {
  players: OnlinePlayer[];
  updateType: 'full' | 'incremental';
}

export interface GameReadyData {
  ready: boolean;
}

export interface LocationChangedData {
  longitude: number;
  latitude: number;
  altitude: number;
}

export interface CrashData {
  crashed: boolean;
}

export interface ModeChangedData {
  mode: GameMode;
  previousMode: GameMode;
}

export interface WaypointReachedData {
  index: number;
}

export interface MissionCompleteData {
  totalWaypoints: number;
}

export interface MissionAbortedData {
  reason: string;
}

// Maverick mission types
export type MaverickPhase =
  | 'cinematic'
  | 'briefing'
  | 'deck'
  | 'takeoff'
  | 'transit'
  | 'canyon_run'
  | 'egress'
  | 'rtb'
  | 'complete'
  | 'failed';

export type SAMAlertType = 'tracking' | 'locked' | 'firing';

export interface MaverickPhaseChangedData {
  phase: MaverickPhase;
  previousPhase: MaverickPhase;
}

export interface SAMAlertData {
  type: SAMAlertType;
  samId: string;
  distance: number;
}

export interface MissileIncomingData {
  missileId: string;
  distance: number;
  timeToImpact: number;
}

export interface MissileDefeatedData {
  missileId: string;
  method: 'chaff' | 'flare' | 'evasion' | 'range';
}

export interface MissileHitData {
  missileId: string;
}

export interface CountermeasureDeployedData {
  type: 'chaff' | 'flare';
  remaining: number;
}

export interface MaverickCompleteData {
  time: number;
  missilesEvaded: number;
  countermeasuresUsed: number;
  phase: MaverickPhase;
}

export interface MaverickFailedData {
  reason: 'missile_hit' | 'crashed';
  phase: MaverickPhase;
  time: number;
}

export interface MaverickStateData {
  phase: MaverickPhase;
  missionTime: number;
  chaff: number;
  flares: number;
  missilesEvaded: number;
  agl: number;
  altitudeWarning: boolean;
}

export interface GameEvents {
  gameReady: GameReadyData;
  vehicleStateChanged: VehicleStateData;
  cameraChanged: CameraStateData;
  roverModeChanged: RoverModeData;
  collisionDetectionChanged: CollisionDetectionData;
  playersUpdated: PlayersData;
  locationChanged: LocationChangedData;
  crashed: CrashData;
  modeChanged: ModeChangedData;
  waypointReached: WaypointReachedData;
  missionComplete: MissionCompleteData;
  missionAborted: MissionAbortedData;
  // Maverick mission events
  maverickPhaseChanged: MaverickPhaseChangedData;
  samAlert: SAMAlertData;
  missileIncoming: MissileIncomingData;
  missileDefeated: MissileDefeatedData;
  missileHit: MissileHitData;
  countermeasureDeployed: CountermeasureDeployedData;
  maverickComplete: MaverickCompleteData;
  maverickFailed: MaverickFailedData;
  maverickState: MaverickStateData;
  // Bomb targeting events
  bombLock: { locked: boolean; distance: number; noLockAttempt?: boolean };
  bombDropped: Record<string, never>;
  bombHit: Record<string, never>;
  [key: string]: unknown;
}

