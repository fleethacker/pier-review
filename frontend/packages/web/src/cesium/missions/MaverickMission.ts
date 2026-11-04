import * as Cesium from 'cesium';
import { Updatable } from '../core/GameLoop';
import { StaticModel } from '../objects/StaticModel';
import { ThreatManager } from '../managers/ThreatManager';
import { TypedEventEmitter } from '../bridge/TypedEventEmitter';
import type { GameEvents, MaverickPhase } from '../bridge/types';
import { Aircraft } from '../vehicles/aircraft/Aircraft';
import type { CesiumVehicleGame } from '../bootstrap/main';
import {
  CARRIER_POSITION,
  MISSION_WAYPOINTS,
  SAM_POSITIONS,
  COUNTERMEASURES,
  BOMB_TARGET,
} from './MaverickMissionData';

export class MaverickMission implements Updatable {
  private game: CesiumVehicleGame;
  private emitter: TypedEventEmitter<GameEvents>;
  private carrier: StaticModel | null = null;
  private threatManager: ThreatManager | null = null;
  private aircraft: Aircraft | null = null;

  private phase: MaverickPhase = 'cinematic';
  private missionStartTime: number = 0;
  private waypoints: Cesium.Cartesian3[] = [];

  // Key positions for distance-based phase transitions
  private canyonEntrance: Cesium.Cartesian3;
  private targetPosition: Cesium.Cartesian3;
  private canyonExit: Cesium.Cartesian3;
  private carrierPosition: Cesium.Cartesian3;

  // Bomb targeting state
  private targetLocked: boolean = false;
  private bombDropped: boolean = false;
  private bombHit: boolean = false;
  private bombFlightTime: number = 0;
  private bombLaunchPos: Cesium.Cartesian3 | null = null;
  private bombEntity: Cesium.Entity | null = null;
  private targetEntity: Cesium.Entity | null = null;
  private impactTimer: number = 0; // countdown after impact to auto-dismiss
  private hitByMissile: boolean = false; // true if a SAM missile hit us

  // Input/event cleanup
  private inputCleanups: Array<() => void> = [];
  private eventCleanups: Array<() => void> = [];

  constructor(game: CesiumVehicleGame, emitter: TypedEventEmitter<GameEvents>) {
    this.game = game;
    this.emitter = emitter;
    // Canyon entrance (first canyon waypoint)
    this.canyonEntrance = Cesium.Cartesian3.fromDegrees(-117.38, 36.34, 450);
    // Bomb target
    this.targetPosition = Cesium.Cartesian3.fromDegrees(BOMB_TARGET.lon, BOMB_TARGET.lat, BOMB_TARGET.alt);
    // Canyon exit (first egress waypoint)
    this.canyonExit = Cesium.Cartesian3.fromDegrees(-117.15, 36.48, 500);
    // Carrier
    this.carrierPosition = Cesium.Cartesian3.fromDegrees(CARRIER_POSITION.lon, CARRIER_POSITION.lat, CARRIER_POSITION.alt);
  }

  /** Phase 1: Cinematic — runs BEFORE React UI is mounted */
  public async startCinematic(): Promise<void> {
    const scene = this.game.getScene();

    this.waypoints = MISSION_WAYPOINTS.map(wp =>
      Cesium.Cartesian3.fromDegrees(wp.lon, wp.lat, wp.alt)
    );

    const carrierPos = Cesium.Cartesian3.fromDegrees(
      CARRIER_POSITION.lon, CARRIER_POSITION.lat, CARRIER_POSITION.alt
    );
    this.carrier = new StaticModel(carrierPos, CARRIER_POSITION.heading);
    await this.carrier.load(scene.scene, './carrier-real.glb', 1.0);

    this.setPhase('cinematic');
    scene.startEarthSpin();
    await this.delay(2000);
    scene.stopEarthSpin();

    await scene.zoomToLocation(
      Cesium.Cartesian3.fromDegrees(CARRIER_POSITION.lon, CARRIER_POSITION.lat, 500),
      3500
    );
  }

  /** Phase 2: Briefing + spawn — runs AFTER React UI is mounted */
  public async start(): Promise<void> {
    const viewer = this.game.getScene().viewer;

    this.setPhase('briefing');

    // Spawn aircraft on carrier deck
    const forwardMeters = -80;
    const rightMeters = -12;
    const headingRad = Cesium.Math.toRadians(CARRIER_POSITION.heading);
    const cosH = Math.cos(headingRad);
    const sinH = Math.sin(headingRad);
    const dLon = (forwardMeters * sinH + rightMeters * cosH) / (111000 * Math.cos(Cesium.Math.toRadians(CARRIER_POSITION.lat)));
    const dLat = (forwardMeters * cosH - rightMeters * sinH) / 111000;
    const deckPos = Cesium.Cartesian3.fromDegrees(
      CARRIER_POSITION.lon + dLon,
      CARRIER_POSITION.lat + dLat,
      119
    );

    const aircraft = await this.game.getVehicleManager().spawnAircraft(
      'maverick-aircraft', deckPos, Cesium.Math.toRadians(CARRIER_POSITION.heading)
    );
    this.aircraft = aircraft as Aircraft;
    const carrierPrimitive = this.carrier?.getPrimitive();
    if (carrierPrimitive) {
      this.aircraft.addCollisionExclusion(carrierPrimitive);
    }
    this.aircraft.setSpawnGracePeriod(600); // ~10 seconds grace for takeoff
    this.game.getCameraManager().setTarget(aircraft);
    this.game.start();

    // Initialize threat manager
    this.threatManager = new ThreatManager({
      viewer,
      getAircraftPosition: () => this.aircraft?.getPosition() || this.carrierPosition,
      getAircraftAGL: () => this.getAGL(),
      getAircraftRollRate: () => this.aircraft ? this.aircraft.getState().roll : 0,
      emitter: this.emitter,
    });
    await this.threatManager.initialize();

    this.setPhase('deck');
    this.missionStartTime = performance.now();

    this.setupInputListeners();
    this.setupEventListeners();
    this.createTargetMarker(viewer);
  }

  /** Teleport aircraft near the canyon for quick demo */
  public skipToTarget(): void {
    if (!this.aircraft) return;
    // Place before canyon entrance, well above terrain (~1500m elevation area)
    const skipPos = Cesium.Cartesian3.fromDegrees(-117.50, 36.30, 2500);
    const state = this.aircraft.getState();
    this.aircraft.setState({
      ...state,
      position: skipPos,
      speed: 100,
      velocity: 100,
      heading: Cesium.Math.toRadians(45), // NE toward canyon
      pitch: 0,
      roll: 0,
    });
    // Reset collision grace period so we don't instantly crash
    this.aircraft.setSpawnGracePeriod(300); // ~5 seconds
    this.setPhase('transit');
  }

  private setupInputListeners(): void {
    const inputManager = this.game.getInputManager();

    const chaffCb = (pressed: boolean) => {
      if (pressed && this.threatManager && this.isFlying()) {
        this.threatManager.deployCountermeasure('chaff');
      }
    };
    const flareCb = (pressed: boolean) => {
      if (pressed && this.threatManager && this.isFlying()) {
        this.threatManager.deployCountermeasure('flare');
      }
    };
    const bombCb = (pressed: boolean) => {
      if (pressed && this.isFlying() && !this.bombDropped) {
        if (this.targetLocked) {
          this.dropBomb();
        } else {
          const dist = this.aircraft ? Math.round(Cesium.Cartesian3.distance(this.aircraft.getPosition(), this.targetPosition)) : 99999;
          this.emitter.emit('bombLock', { locked: false, distance: dist, noLockAttempt: true });
        }
      }
    };

    inputManager.onInput('deployChaff', chaffCb);
    inputManager.onInput('deployFlares', flareCb);
    inputManager.onInput('spawnObject', bombCb);

    this.inputCleanups.push(
      () => inputManager.offInput('deployChaff', chaffCb),
      () => inputManager.offInput('deployFlares', flareCb),
      () => inputManager.offInput('spawnObject', bombCb),
    );
  }

  private setupEventListeners(): void {
    const missileHitUnsub = this.emitter.on('missileHit', () => this.onMissileHit());
    const crashUnsub = this.emitter.on('crashed', (data) => {
      if (data.crashed) this.onCrash();
    });
    this.eventCleanups.push(missileHitUnsub, crashUnsub);
  }

  /** Is the aircraft in a flying phase? */
  private isFlying(): boolean {
    return this.phase === 'takeoff' || this.phase === 'transit' ||
           this.phase === 'canyon_run' || this.phase === 'egress' || this.phase === 'rtb';
  }

  private createTargetMarker(viewer: Cesium.Viewer): void {
    this.targetEntity = viewer.entities.add({
      position: this.targetPosition,
      point: {
        pixelSize: 16,
        color: Cesium.Color.RED.withAlpha(0.9),
        outlineColor: Cesium.Color.DARKRED,
        outlineWidth: 3,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: BOMB_TARGET.label,
        font: '12px monospace',
        fillColor: Cesium.Color.RED,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -20),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      ellipse: {
        semiMajorAxis: BOMB_TARGET.hitRadius,
        semiMinorAxis: BOMB_TARGET.hitRadius,
        material: Cesium.Color.RED.withAlpha(0.1),
        outline: true,
        outlineColor: Cesium.Color.RED.withAlpha(0.4),
        outlineWidth: 2,
        height: BOMB_TARGET.alt,
      },
    });
  }

  // === BOMB TARGETING ===

  private dropBomb(): void {
    if (!this.aircraft) return;
    this.bombDropped = true;
    this.bombFlightTime = 0;
    this.bombLaunchPos = Cesium.Cartesian3.clone(this.aircraft.getPosition());
    this.emitter.emit('bombDropped', {} as Record<string, never>);

    // Create visible missile entity using CallbackProperty for real-time animation
    const launchPos = Cesium.Cartesian3.clone(this.bombLaunchPos);
    const targetPos = this.targetPosition;
    const totalDist = Cesium.Cartesian3.distance(launchPos, targetPos);
    const missileSpeed = 300;
    const spawnTime = performance.now();

    const posCallback = new Cesium.CallbackProperty(() => {
      const elapsed = (performance.now() - spawnTime) / 1000;
      const progress = Math.min(1, (elapsed * missileSpeed) / totalDist);
      return Cesium.Cartesian3.lerp(launchPos, targetPos, progress, new Cesium.Cartesian3());
    }, false);

    this.bombEntity = this.game.getScene().viewer.entities.add({
      position: posCallback as any,
      point: {
        pixelSize: 8,
        color: Cesium.Color.RED,
        outlineColor: Cesium.Color.YELLOW,
        outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  private updateBombTargeting(deltaTime: number): void {
    if (!this.aircraft || !this.isFlying()) return;

    const distance = Cesium.Cartesian3.distance(this.aircraft.getPosition(), this.targetPosition);

    // Update lock status (only when bomb not yet dropped)
    if (!this.bombDropped && !this.bombHit) {
      this.targetLocked = distance < BOMB_TARGET.lockDistance;
      this.emitter.emit('bombLock', {
        locked: this.targetLocked,
        distance: Math.round(distance),
      });
    }

    // Missile in flight
    if (this.bombDropped && !this.bombHit) {
      this.bombFlightTime += deltaTime;
      const missileSpeed = 300;
      const totalDistance = Cesium.Cartesian3.distance(this.bombLaunchPos!, this.targetPosition);
      const flightDistance = this.bombFlightTime * missileSpeed;

      if (flightDistance >= totalDistance) {
        this.bombHit = true;
        this.impactTimer = 5; // 5 seconds to show impact, then egress
        if (this.bombEntity) {
          try { this.game.getScene().viewer.entities.remove(this.bombEntity); } catch {}
          this.bombEntity = null;
        }
        this.emitter.emit('bombHit', {} as Record<string, never>);
      }
    }

    // After impact, countdown then transition to egress
    if (this.bombHit && this.impactTimer > 0) {
      this.impactTimer -= deltaTime;
      if (this.impactTimer <= 0) {
        this.setPhase('egress');
        // Clear the impact state so UI dismisses
        this.emitter.emit('bombLock', { locked: false, distance: 0 });
      }
    }
  }

  // === MAIN UPDATE LOOP ===

  public update(deltaTime: number): void {
    if (this.phase === 'complete' || this.phase === 'failed') return;

    // Update threat manager during flight
    if (this.threatManager && this.isFlying()) {
      this.threatManager.update(deltaTime);
    }

    // Update bomb targeting
    this.updateBombTargeting(deltaTime);

    // Distance-based phase transitions (works with manual flight, no autopilot needed)
    if (this.isFlying() && this.aircraft) {
      this.updatePhaseByDistance();
    }

    // Deck/takeoff speed-based transitions
    if (this.phase === 'deck') {
      this.updateDeckPhase();
    } else if (this.phase === 'takeoff') {
      this.updateTakeoffPhase();
    }

    this.emitState();
  }

  /** Phase transitions based on distance to key locations */
  private updatePhaseByDistance(): void {
    if (!this.aircraft) return;
    const pos = this.aircraft.getPosition();

    const distToCanyon = Cesium.Cartesian3.distance(pos, this.canyonEntrance);
    const distToTarget = Cesium.Cartesian3.distance(pos, this.targetPosition);
    const distToExit = Cesium.Cartesian3.distance(pos, this.canyonExit);
    const distToCarrier = Cesium.Cartesian3.distance(pos, this.carrierPosition);

    // Transit → Canyon Run: within 5km of canyon entrance
    if (this.phase === 'transit' && distToCanyon < 5000) {
      this.setPhase('canyon_run');
    }
    // Canyon Run → Egress: bomb hit handles this via impactTimer
    // But also transition if they pass the exit without bombing
    if (this.phase === 'canyon_run' && !this.bombHit && distToExit < 3000 && distToCanyon > 5000) {
      this.setPhase('egress');
    }
    // Egress → RTB: once 10km past canyon exit
    if (this.phase === 'egress' && distToCanyon > 15000 && distToTarget > 10000) {
      this.setPhase('rtb');
    }
    // RTB → Complete: within 5km of carrier
    if (this.phase === 'rtb' && distToCarrier < 5000) {
      this.completeMission();
    }
  }

  private updateDeckPhase(): void {
    if (!this.aircraft) return;
    if (this.aircraft.getState().speed > 20) {
      this.setPhase('takeoff');
    }
  }

  private updateTakeoffPhase(): void {
    if (!this.aircraft) return;
    const state = this.aircraft.getState();
    const alt = Cesium.Cartographic.fromCartesian(state.position).height;
    // Must be above 200m altitude AND going faster than 80 m/s
    if (alt > 200 && state.speed > 80) {
      this.setPhase('transit');
    }
  }

  // === MISSION EVENTS ===

  public onMissileHit(): void {
    if (this.phase === 'failed' || this.phase === 'complete') return;
    this.hitByMissile = true;
    const currentPhase = this.phase;
    this.setPhase('failed');
    this.emitter.emit('maverickFailed', {
      reason: 'missile_hit', phase: currentPhase, time: this.getMissionTime(),
    });
    if (this.aircraft) this.aircraft.physicsEnabled = false;
    this.threatManager?.deactivate();
  }

  public onCrash(): void {
    if (this.phase === 'failed' || this.phase === 'complete') return;
    // If a missile just hit us, report it as missile_hit not terrain crash
    const reason = this.hitByMissile ? 'missile_hit' : 'crashed';
    const currentPhase = this.phase;
    this.setPhase('failed');
    this.emitter.emit('maverickFailed', {
      reason, phase: currentPhase, time: this.getMissionTime(),
    });
    this.threatManager?.deactivate();
  }

  private completeMission(): void {
    this.setPhase('complete');
    const evaded = this.threatManager?.getMissilesEvaded() || 0;
    const cmUsed = this.threatManager?.getCountermeasuresUsed() || 0;
    this.emitter.emit('maverickComplete', {
      time: this.getMissionTime(), missilesEvaded: evaded,
      countermeasuresUsed: cmUsed, phase: 'complete',
    });
    this.threatManager?.deactivate();
  }

  // === HELPERS ===

  private setPhase(phase: MaverickPhase): void {
    const previous = this.phase;
    if (previous === phase) return;
    this.phase = phase;
    this.emitter.emit('maverickPhaseChanged', { phase, previousPhase: previous });
  }

  private emitState(): void {
    const tm = this.threatManager;
    this.emitter.emit('maverickState', {
      phase: this.phase,
      missionTime: this.getMissionTime(),
      chaff: tm?.chaff ?? COUNTERMEASURES.chaff,
      flares: tm?.flares ?? COUNTERMEASURES.flares,
      missilesEvaded: tm?.getMissilesEvaded() ?? 0,
      agl: this.getAGL(),
      altitudeWarning: this.isAltitudeWarning(),
    });
  }

  private isAltitudeWarning(): boolean {
    if (this.phase !== 'canyon_run' && this.phase !== 'egress') return false;
    return this.getAGL() > 150;
  }

  private getAGL(): number {
    if (!this.aircraft) return 500;
    const pos = this.aircraft.getPosition();
    const currentHeight = Cesium.Cartographic.fromCartesian(pos).height;

    // Try clampToHeight first
    const primitive = (this.aircraft as any).primitive;
    const excludeList = primitive ? [primitive] : [];
    const carrierPrimitive = this.carrier?.getPrimitive();
    if (carrierPrimitive) excludeList.push(carrierPrimitive);

    const ground = this.game.getScene().clampToHeight(pos, excludeList);
    if (ground) {
      const groundHeight = Cesium.Cartographic.fromCartesian(ground).height;
      const agl = currentHeight - groundHeight;
      if (agl > 0 && agl < 50000) return agl; // valid AGL
    }

    // Fallback: estimate AGL from absolute altitude
    // Canyon floor is roughly 200-400m MSL, ridgelines 600-1000m
    // Use altitude above ~300m as rough AGL in canyon area
    const estimatedGroundLevel = 300;
    return Math.max(0, currentHeight - estimatedGroundLevel);
  }

  public getMissionTime(): number {
    if (this.missionStartTime === 0) return 0;
    return (performance.now() - this.missionStartTime) / 1000;
  }

  public getPhase(): MaverickPhase { return this.phase; }
  public getThreatManager(): ThreatManager | null { return this.threatManager; }
  public confirmMissionStart(): void { /* kept for API compat */ }

  public async retry(): Promise<void> {
    // Remove aircraft from scene immediately so it doesn't fly around during cinematic
    if (this.aircraft) {
      this.game.getVehicleManager().removeVehicle(this.aircraft.id);
    }
    this.game.stop();
    this.destroy();
    // Reset all state
    this.phase = 'cinematic';
    this.missionStartTime = 0;
    this.targetLocked = false;
    this.bombDropped = false;
    this.bombHit = false;
    this.bombFlightTime = 0;
    this.impactTimer = 0;
    this.hitByMissile = false;
    // Full restart — recreate carrier, cinematic, spawn on deck
    await this.startCinematic();
    await this.start();
  }

  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  public destroy(): void {
    for (const unsub of this.eventCleanups) unsub();
    this.eventCleanups = [];
    for (const unsub of this.inputCleanups) unsub();
    this.inputCleanups = [];
    this.threatManager?.destroy();
    this.threatManager = null;
    this.carrier?.destroy();
    this.carrier = null;
    if (this.bombEntity) {
      try { this.game.getScene().viewer.entities.remove(this.bombEntity); } catch {}
      this.bombEntity = null;
    }
    if (this.targetEntity) {
      try { this.game.getScene().viewer.entities.remove(this.targetEntity); } catch {}
      this.targetEntity = null;
    }
    this.aircraft = null;
  }
}
