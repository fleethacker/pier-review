import * as Cesium from 'cesium';
import { TypedEventEmitter } from './TypedEventEmitter';
import type { GameEvents, VehicleStateData, GameMode } from './types';
import type { CesiumVehicleGame } from '../bootstrap/main';
import type { CameraType } from '../managers/CameraManager';
import { getBaseLocation } from '../../baseLocation';
import type { QualityConfig } from '../core/Scene';
import { Aircraft } from '../vehicles/aircraft/Aircraft';
import { ModeManager } from '../modes/ModeManager';
import type { FlightProfile } from '../vehicles/aircraft/AutoPilot';
import { getFlightProfiles } from '../vehicles/aircraft/AutoPilot';
import { MaverickMission } from '../missions/MaverickMission';

export class GameBridge extends TypedEventEmitter<GameEvents> {
  private game: CesiumVehicleGame;
  private updateInterval: number | null = null;
  private currentMode: GameMode = 'play';
  private collisionEnabled: boolean = true;
  private modeManager: ModeManager;
  private maverickMission: MaverickMission | null = null;

  constructor(game: CesiumVehicleGame) {
    super();
    this.game = game;
    this.modeManager = new ModeManager(game);
    this.startUpdates();
    this.setupVehicleChangeListener();
    this.setupBuilderModeListener();
    this.setupMissionKeyListener();
    this.applyQualityPreset('performance');
    console.log('🎮 Applied performance mode on startup');
  }

  private setupMissionKeyListener(): void {
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && this.currentMode === 'builder') {
        e.preventDefault();
        this.startMission();
      }
    });
  }

  private setupBuilderModeListener(): void {
    this.game.getInputManager().onInput('toggleBuilder', (pressed) => {
      if (pressed) {
        this.toggleBuilderMode();
      }
    });
  }

  private setupVehicleChangeListener(): void {
    this.game.getVehicleManager().addVehicleChangeListener(() => {
      this.emitVehicleChangeEvents();
    });
  }

  private startUpdates(): void {
    this.updateInterval = window.setInterval(() => {
      this.emitVehicleState();
    }, 16);
  }

  private emitVehicleState(): void {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle.isModelReady()) {
      const state = vehicle.getState();
      this.emit('vehicleStateChanged', {
        speed: state.speed,
        velocity: state.velocity,
        position: state.position,
        heading: state.heading,
        pitch: state.pitch,
        roll: state.roll,
      });

      // Check for crash
      if (vehicle instanceof Aircraft && vehicle.isCrashed()) {
        this.emit('crashed', { crashed: true });
      }
    }
  }

  public emitVehicleChangeEvents(): void {
    this.emit('collisionDetectionChanged', { enabled: false });
  }

  public switchCamera(): void {
    // Single camera mode - no switching
  }

  public getCameraType(): CameraType {
    return this.game.getCameraManager().getActiveCameraType();
  }

  public toggleCollisionDetection(): void {
    this.collisionEnabled = !this.collisionEnabled;
    this.emit('collisionDetectionChanged', { enabled: this.collisionEnabled });
  }

  public getCollisionDetection(): boolean {
    return this.collisionEnabled;
  }

  public getVehicleState(): VehicleStateData | null {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle.isModelReady()) {
      const state = vehicle.getState();
      return {
        speed: state.speed,
        velocity: state.velocity,
        position: state.position,
        heading: state.heading,
        pitch: state.pitch,
        roll: state.roll,
      };
    }
    return null;
  }

  public teleportTo(longitude: number, latitude: number, altitude: number, heading: number = 0): void {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle) {
      const newPosition = Cesium.Cartesian3.fromDegrees(longitude, latitude, altitude);
      const currentState = vehicle.getState();
      vehicle.setState({
        ...currentState,
        position: newPosition,
        heading: Cesium.Math.toRadians(heading),
        pitch: 0,
        roll: 0,
        velocity: 0,
        speed: 0
      });
      this.emit('locationChanged', {
        longitude,
        latitude,
        altitude
      });
    }
  }

  public restart(): void {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft && vehicle.isCrashed()) {
      vehicle.resetCrash();
      // Reset to spawn position — query ground height and spawn 500m above
      const base = getBaseLocation();
      let spawnAlt = 3000;
      const groundPos = this.game.getScene().clampToHeight(
        Cesium.Cartesian3.fromDegrees(base.longitude, base.latitude, 10000)
      );
      if (groundPos) {
        spawnAlt = Cesium.Cartographic.fromCartesian(groundPos).height + 500;
      }
      const spawnPosition = Cesium.Cartesian3.fromDegrees(base.longitude, base.latitude, spawnAlt);
      const currentState = vehicle.getState();
      vehicle.setState({
        ...currentState,
        position: spawnPosition,
        heading: 0,
        pitch: 0,
        roll: 0,
        velocity: 0,
        speed: 0
      });
      this.emit('crashed', { crashed: false });
    }
  }

  public destroy(): void {
    if (this.updateInterval !== null) {
      clearInterval(this.updateInterval);
      this.updateInterval = null;
    }
    this.removeAllListeners();
  }

  public getQualitySettings(): QualityConfig {
    return this.game.getScene().getQualityConfig();
  }

  public updateQualitySettings(config: Partial<QualityConfig>): void {
    this.game.getScene().updateQualityConfig(config);
  }

  public toggleBuilderMode(): void {
    const newMode: GameMode = this.currentMode === 'play' ? 'builder' : 'play';
    this.setMode(newMode);
  }

  public setMode(mode: GameMode): void {
    if (this.currentMode === mode) {
      console.log(`🎮 Already in ${mode} mode`);
      return;
    }
    
    const previousMode = this.currentMode;
    this.currentMode = mode;
    
    this.modeManager.onModeChanged(previousMode, mode);
    
    this.emit('modeChanged', { mode, previousMode });
    
    console.log(`🎮 Mode changed: ${previousMode} → ${mode}`);
  }

  public getMode(): GameMode {
    return this.currentMode;
  }

  public applyQualityPreset(preset: 'performance' | 'balanced' | 'quality' | 'ultra'): void {
    const presets: Record<string, Partial<QualityConfig>> = {
      performance: {
        maximumScreenSpaceError: 32,
        dynamicScreenSpaceError: true,
        dynamicScreenSpaceErrorFactor: 32,
        skipLevelOfDetail: true,
        fxaaEnabled: true,
        bloomEnabled: false,
        hdr: false,
        exposure: 1.0,
      },
      balanced: {
        maximumScreenSpaceError: 16,
        dynamicScreenSpaceError: true,
        dynamicScreenSpaceErrorFactor: 24,
        skipLevelOfDetail: true,
        fxaaEnabled: true,
        bloomEnabled: true,
        hdr: true,
        exposure: 1.5,
      },
      quality: {
        maximumScreenSpaceError: 8,
        dynamicScreenSpaceError: true,
        dynamicScreenSpaceErrorFactor: 16,
        skipLevelOfDetail: true,
        fxaaEnabled: true,
        bloomEnabled: true,
        hdr: true,
        exposure: 1.5,
      },
      ultra: {
        maximumScreenSpaceError: 4,
        dynamicScreenSpaceError: false,
        dynamicScreenSpaceErrorFactor: 12,
        skipLevelOfDetail: false,
        fxaaEnabled: true,
        bloomEnabled: true,
        hdr: true,
        exposure: 1.8,
      },
    };

    const config = presets[preset];
    if (config) {
      this.updateQualitySettings(config);
      console.log(`🎨 Applied ${preset} quality preset`);
    }
  }

  public setThrottle(percent: number): void {
    this.game.getInputManager().setThrottlePercent(percent * 100);
  }

  public getGroundHeight(position: Cesium.Cartesian3): number {
    const ground = this.game.getScene().clampToHeight(position);
    if (ground) {
      return Cesium.Cartographic.fromCartesian(ground).height;
    }
    return 0;
  }

  public getAGL(): number {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (!vehicle) return 500;
    const pos = vehicle.getPosition();
    const currentHeight = Cesium.Cartographic.fromCartesian(pos).height;
    // Exclude the vehicle primitive so we clamp to terrain, not the drone model
    const primitive = (vehicle as any).primitive;
    const excludeList = primitive ? [primitive] : [];
    const ground = this.game.getScene().clampToHeight(pos, excludeList);
    if (ground) {
      const groundHeight = Cesium.Cartographic.fromCartesian(ground).height;
      return Math.max(10, currentHeight - groundHeight);
    }
    // If clampToHeight fails, return a reasonable default
    return 500;
  }

  public captureScreen(): string {
    const viewer = this.game.getScene().viewer;
    viewer.render();
    return viewer.canvas.toDataURL('image/jpeg', 0.8);
  }

  public setFlightProfile(profile: FlightProfile): void {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft) {
      vehicle.autopilot.setFlightProfile(profile);
    }
  }

  public getFlightProfiles() {
    return getFlightProfiles();
  }

  public startMission(): void {
    const objectManager = this.game.getObjectManager();
    const waypoints = objectManager.getWaypointPositions();
    if (waypoints.length === 0) return;

    // Switch back to play mode for auto-fly
    if (this.currentMode === 'builder') {
      this.setMode('play');
    }

    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft) {
      vehicle.startMission(waypoints, (event, index) => {
        if (event === 'waypointReached') {
          this.emit('waypointReached', { index });
        } else if (event === 'missionComplete') {
          this.emit('missionComplete', { totalWaypoints: waypoints.length });
        }
      });
    }
  }

  public abortMission(): void {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft) {
      vehicle.abortMission();
      this.emit('missionAborted', { reason: 'User aborted' });
    }
  }

  public isMissionActive(): boolean {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft) {
      return vehicle.isMissionActive();
    }
    return false;
  }

  public getWaypointCount(): number {
    return this.game.getObjectManager().getObjectCount();
  }

  public getWaypointPositions(): { lat: number; lon: number; alt: number }[] {
    const waypoints = this.game.getObjectManager().getWaypoints();
    return waypoints.map(w => {
      const cart = Cesium.Cartographic.fromCartesian(w.position);
      return {
        lat: Cesium.Math.toDegrees(cart.latitude),
        lon: Cesium.Math.toDegrees(cart.longitude),
        alt: cart.height,
      };
    });
  }

  public clearWaypoints(): void {
    this.game.getObjectManager().clear();
  }

  // === Wind System ===

  public setWind(direction: number, speed: number, turbulence: number): void {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft) {
      vehicle.windSystem.setWind(direction, speed, turbulence);
    }
  }

  public setRandomWind(): void {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft) {
      vehicle.windSystem.setRandom();
    }
  }

  public getWind(): { direction: number; speed: number; turbulence: number } {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft) {
      return vehicle.windSystem.getWind();
    }
    return { direction: 0, speed: 0, turbulence: 0 };
  }

  public setMLCorrection(enabled: boolean): void {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft) {
      vehicle.setMLCorrection(enabled);
    }
  }

  public isMLCorrectionEnabled(): boolean {
    const vehicle = this.game.getVehicleManager().getActiveVehicle();
    if (vehicle && vehicle instanceof Aircraft) {
      return vehicle.isMLCorrectionEnabled();
    }
    return false;
  }

  // === Maverick Mission ===

  /** Phase 1: Cinematic — call before mounting React UI */
  public async startMaverickCinematic(): Promise<void> {
    this.maverickMission = new MaverickMission(this.game, this);
    this.currentMode = 'maverick';

    await this.maverickMission.startCinematic();
  }

  /** Phase 2: Briefing + spawn — call after mounting React UI */
  public async startMaverickMission(): Promise<void> {
    if (!this.maverickMission) return;

    this.emit('modeChanged', { mode: 'maverick', previousMode: 'play' });

    // Add to game loop for per-frame updates
    this.game.getGameLoop().addUpdatable(this.maverickMission);

    await this.maverickMission.start();
  }

  public getMaverickMission(): MaverickMission | null {
    return this.maverickMission;
  }

  public isMaverickMode(): boolean {
    return this.currentMode === 'maverick';
  }

  /** Called by React UI when user presses "COMMENCE OPERATIONS" on briefing */
  public confirmMissionStart(): void {
    this.maverickMission?.confirmMissionStart();
  }

  public async retryMaverickMission(): Promise<void> {
    if (this.maverickMission) {
      this.game.getGameLoop().removeUpdatable(this.maverickMission);
      await this.maverickMission.retry();
      this.game.getGameLoop().addUpdatable(this.maverickMission);
    }
  }

  public deployCountermeasure(type: 'chaff' | 'flare'): void {
    this.maverickMission?.getThreatManager()?.deployCountermeasure(type);
  }

  public skipToTarget(): void {
    this.maverickMission?.skipToTarget();
  }
}

