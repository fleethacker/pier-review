import * as Cesium from 'cesium';
import { Vehicle, VehicleConfig } from '../Vehicle';
import { AircraftPhysics, AircraftInput } from './AircraftPhysics';
import { AutoPilot, type AutoPilotCallback } from './AutoPilot';
import { WindSystem } from '../../physics/WindSystem';

interface AircraftConfig extends VehicleConfig {
}

export class Aircraft extends Vehicle {
  private physics: AircraftPhysics;
  public autopilot: AutoPilot = new AutoPilot();
  public windSystem: WindSystem = new WindSystem();
  private mlCorrectionEnabled: boolean = false;
  private input: AircraftInput = {
    throttle: false,
    brake: false,
    turnLeft: false,
    turnRight: false,
    altitudeUp: false,
    altitudeDown: false,
    rollLeft: false,
    rollRight: false
  };
  private framesSinceCollisionCheck: number = 0;
  private crashed: boolean = false;
  private spawnGracePeriod: number = 180; // skip collision for ~3 seconds (60fps * 3)
  private collisionExclusions: any[] = []; // additional primitives to exclude from clampToHeight

  private static readonly scratchTransform = new Cesium.Matrix4();
  private static readonly scratchWorldForward = new Cesium.Cartesian3();
  private static readonly scratchForwardWorldDelta = new Cesium.Cartesian3();
  private static readonly scratchENU = new Cesium.Matrix4();
  private static readonly scratchUpCol = new Cesium.Cartesian4();
  private static readonly scratchUp = new Cesium.Cartesian3();
  private static readonly scratchVerticalDeltaVec = new Cesium.Cartesian3();
  private static readonly scratchTotalDelta = new Cesium.Cartesian3();
  private static readonly scratchLocalForward = new Cesium.Cartesian3();
  private static readonly scratchWorldForwardCollision = new Cesium.Cartesian3();
  private static readonly scratchProbe = new Cesium.Cartesian3();
  private static readonly scratchScaled = new Cesium.Cartesian3();

  constructor(id: string, config: AircraftConfig) {
    super(id, config);
    this.physics = new AircraftPhysics({
      minSpeed: 0,
      maxSpeed: 1800, // Simulation max 3x (real X-47B: 146 m/s / 525 km/h)
      speedChangeRate: 80,
      turnRate: Cesium.Math.toRadians(45),
      climbRate: 20,
      gravity: 2,
      rollRate: Cesium.Math.toRadians(60),
      maxRoll: Cesium.Math.toRadians(45),
      pitchRate: Cesium.Math.toRadians(60),
      maxPitch: Cesium.Math.toRadians(60)
    }, this.hpRoll.heading);
  }

  protected onModelReady(): void {
    if (this.primitive) {
      this.primitive.activeAnimations.addAll({
        multiplier: 0.6,
        loop: Cesium.ModelAnimationLoop.REPEAT
      });
    }
  }

  public update(deltaTime: number): void {
    if (!this.isReady || this.crashed || !this.physicsEnabled) return;

    // If autopilot is active, use its computed input
    const activeInput = this.autopilot.isActive()
      ? this.autopilot.computeInput(this.position, this.hpRoll.heading)
      : this.input;

    // Compute wind forces for this frame
    const windForce = this.windSystem.computeForce(this.hpRoll.heading, this.speed, deltaTime);

    const result = this.physics.update(deltaTime, activeInput, windForce);

    this.hpRoll.heading = result.heading;
    this.hpRoll.pitch = result.pitch;
    this.hpRoll.roll = result.roll;

    if (this.primitive) {
      Cesium.Transforms.headingPitchRollToFixedFrame(
        this.position,
        this.hpRoll,
        Cesium.Ellipsoid.WGS84,
        undefined,
        Aircraft.scratchTransform
      );
      const worldForward = Cesium.Matrix4.multiplyByPoint(
        Aircraft.scratchTransform,
        result.positionDelta,
        Aircraft.scratchWorldForward
      );
      const forwardWorldDelta = Cesium.Cartesian3.subtract(
        worldForward, 
        this.position, 
        Aircraft.scratchForwardWorldDelta
      );

      Cesium.Transforms.eastNorthUpToFixedFrame(this.position, undefined, Aircraft.scratchENU);
      const upCol = Cesium.Matrix4.getColumn(Aircraft.scratchENU, 2, Aircraft.scratchUpCol);
      Cesium.Cartesian3.fromCartesian4(upCol, Aircraft.scratchUp);
      const verticalDeltaVec = Cesium.Cartesian3.multiplyByScalar(
        Aircraft.scratchUp, 
        result.verticalDelta, 
        Aircraft.scratchVerticalDeltaVec
      );

      const totalDelta = Cesium.Cartesian3.add(
        forwardWorldDelta, 
        verticalDeltaVec, 
        Aircraft.scratchTotalDelta
      );
      this.position = Cesium.Cartesian3.add(this.position, totalDelta, this.position);
    }

    this.velocity = result.speed;
    this.speed = Math.abs(result.speed);

    if (this.spawnGracePeriod > 0) {
      this.spawnGracePeriod--;
    } else {
      this.framesSinceCollisionCheck++;
      if (this.framesSinceCollisionCheck >= 30) {
        this.framesSinceCollisionCheck = 0;
        this.performCollisionCheck();
      }
    }

    this.updateModelMatrix();
  }

  private performCollisionCheck(): void {
    if (!this.primitive || !this.sceneRef) return;

    const currentHeight = Cesium.Cartographic.fromCartesian(this.position).height;
    const exclusions = [this.primitive, ...this.collisionExclusions];
    const ground = this.sceneRef.clampToHeight(this.position, exclusions);
    if (ground) {
      const groundHeight = Cesium.Cartographic.fromCartesian(ground).height;
      if (currentHeight <= groundHeight + 5) {
        this.crash();
        return;
      }
    }
  }

  private crash(): void {
    this.crashed = true;
    this.velocity = 0;
    this.speed = 0;
    console.log('💥 Drone crashed');
  }

  public isCrashed(): boolean {
    return this.crashed;
  }

  public resetCrash(): void {
    this.crashed = false;
    this.spawnGracePeriod = 180;
  }

  /** Add primitives to exclude from terrain collision (e.g. carrier deck) */
  public addCollisionExclusion(primitive: any): void {
    this.collisionExclusions.push(primitive);
  }

  /** Extend spawn grace period (e.g. for carrier takeoff) */
  public setSpawnGracePeriod(frames: number): void {
    this.spawnGracePeriod = frames;
  }

  public setInput(input: Partial<AircraftInput>): void {
    // If user provides manual input during autopilot, abort autopilot
    if (this.autopilot.isActive()) {
      const hasManualInput = input.throttle || input.brake || input.turnLeft ||
        input.turnRight || input.altitudeUp || input.altitudeDown;
      if (hasManualInput) {
        this.autopilot.stop();
        console.log('AutoPilot: Aborted by manual input');
      }
    }
    Object.assign(this.input, input);
  }

  public startMission(waypoints: Cesium.Cartesian3[], callback: AutoPilotCallback): void {
    this.autopilot.start(waypoints, callback);
  }

  public abortMission(): void {
    this.autopilot.stop();
  }

  public isMissionActive(): boolean {
    return this.autopilot.isActive();
  }

  public setMLCorrection(enabled: boolean): void {
    this.mlCorrectionEnabled = enabled;
  }

  public isMLCorrectionEnabled(): boolean {
    return this.mlCorrectionEnabled;
  }
}

