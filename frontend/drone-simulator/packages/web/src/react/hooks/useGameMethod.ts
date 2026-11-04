import { useGameBridge } from './useGameBridge';
import type { CameraType } from '../../cesium/managers/CameraManager';
import type { VehicleStateData } from '../../cesium/bridge/types';
import type { QualityConfig } from '../../cesium/core/Scene';

export function useGameMethod() {
  const bridge = useGameBridge();

  return {
    switchCamera: () => bridge.switchCamera(),
    getCameraType: (): CameraType => bridge.getCameraType(),
    toggleCollisionDetection: () => bridge.toggleCollisionDetection(),
    getCollisionDetection: (): boolean => bridge.getCollisionDetection(),
    getVehicleState: (): VehicleStateData | null => bridge.getVehicleState(),
    teleportTo: (longitude: number, latitude: number, altitude: number, heading?: number) => 
      bridge.teleportTo(longitude, latitude, altitude, heading),
    restart: () => bridge.restart(),
    getQualitySettings: (): QualityConfig => bridge.getQualitySettings(),
    updateQualitySettings: (config: Partial<QualityConfig>) => bridge.updateQualitySettings(config),
    applyQualityPreset: (preset: 'performance' | 'balanced' | 'quality' | 'ultra') => bridge.applyQualityPreset(preset),
    toggleBuilderMode: () => bridge.toggleBuilderMode(),
    setMode: (mode: 'play' | 'builder') => bridge.setMode(mode),
    getMode: () => bridge.getMode(),
    setThrottle: (percent: number) => bridge.setThrottle(percent),
    captureScreen: (): string => bridge.captureScreen(),
    setWind: (dir: number, speed: number, turb: number) => bridge.setWind(dir, speed, turb),
    setRandomWind: () => bridge.setRandomWind(),
    getWind: () => bridge.getWind(),
    setMLCorrection: (enabled: boolean) => bridge.setMLCorrection(enabled),
    isMLCorrectionEnabled: () => bridge.isMLCorrectionEnabled(),
    getAGL: (): number => bridge.getAGL(),
    setFlightProfile: (profile: string) => bridge.setFlightProfile(profile as any),
    getFlightProfiles: () => bridge.getFlightProfiles(),
    startMission: () => bridge.startMission(),
    abortMission: () => bridge.abortMission(),
    isMissionActive: (): boolean => bridge.isMissionActive(),
    getWaypointCount: (): number => bridge.getWaypointCount(),
    getWaypointPositions: () => bridge.getWaypointPositions(),
    clearWaypoints: () => bridge.clearWaypoints(),
    // Maverick mission
    retryMaverickMission: () => bridge.retryMaverickMission(),
    isMaverickMode: (): boolean => bridge.isMaverickMode(),
    deployCountermeasure: (type: 'chaff' | 'flare') => bridge.deployCountermeasure(type),
    confirmMissionStart: () => bridge.confirmMissionStart(),
    skipToTarget: () => bridge.skipToTarget(),
  };
}


