import * as Cesium from 'cesium';
import { Updatable } from '../core/GameLoop';
import { SAMSite } from '../objects/SAMSite';
import { Missile } from '../objects/Missile';
import { TypedEventEmitter } from '../bridge/TypedEventEmitter';
import type { GameEvents } from '../bridge/types';
import { SAM_POSITIONS, COUNTERMEASURES, MISSILE_CONFIG } from '../missions/MaverickMissionData';

interface ThreatManagerConfig {
  viewer: Cesium.Viewer;
  getAircraftPosition: () => Cesium.Cartesian3;
  getAircraftAGL: () => number;
  getAircraftRollRate: () => number;
  emitter: TypedEventEmitter<GameEvents>;
}

export class ThreatManager implements Updatable {
  private sams: SAMSite[] = [];
  private missiles: Missile[] = [];
  private viewer: Cesium.Viewer;
  private getAircraftPosition: () => Cesium.Cartesian3;
  private getAircraftAGL: () => number;
  private getAircraftRollRate: () => number;
  private emitter: TypedEventEmitter<GameEvents>;
  private missileCounter: number = 0;
  private missilesEvaded: number = 0;
  private active: boolean = false;

  // Countermeasure state
  public chaff: number = COUNTERMEASURES.chaff;
  public flares: number = COUNTERMEASURES.flares;
  private countermeasuresUsed: number = 0;

  // Cooldown to prevent spamming alerts
  private alertCooldown: number = 0;
  private debugTimer: number = 0;

  constructor(config: ThreatManagerConfig) {
    this.viewer = config.viewer;
    this.getAircraftPosition = config.getAircraftPosition;
    this.getAircraftAGL = config.getAircraftAGL;
    this.getAircraftRollRate = config.getAircraftRollRate;
    this.emitter = config.emitter;
  }

  public async initialize(): Promise<void> {
    // Create SAM sites from mission data
    for (const samData of SAM_POSITIONS) {
      const sam = new SAMSite(samData);
      await sam.initialize(this.viewer);
      this.sams.push(sam);
    }
    this.active = true;
    console.log(`Threat Manager: ${this.sams.length} SAM sites active`);
  }

  public update(deltaTime: number): void {
    if (!this.active) return;

    const aircraftPos = this.getAircraftPosition();
    const aircraftAGL = this.getAircraftAGL();

    this.alertCooldown = Math.max(0, this.alertCooldown - deltaTime);

    // Debug: log SAM status every 3 seconds
    this.debugTimer = (this.debugTimer || 0) + deltaTime;
    if (this.debugTimer > 3) {
      this.debugTimer = 0;
      const closestSam = this.sams.reduce((closest, sam) => {
        const d = sam.getDistanceTo(aircraftPos);
        return d < closest.dist ? { sam, dist: d } : closest;
      }, { sam: this.sams[0], dist: Infinity });
      console.log(`ThreatMgr: AGL=${Math.round(aircraftAGL)}m, closest SAM=${closestSam.sam.id} dist=${Math.round(closestSam.dist)}m state=${closestSam.sam.state} threshold=${closestSam.sam.altitudeThreshold}m`);
    }

    // Update SAMs
    for (const sam of this.sams) {
      const shouldFire = sam.update(deltaTime, aircraftPos, aircraftAGL);

      // Emit SAM alerts
      if (sam.state === 'tracking' || sam.state === 'locked' || sam.state === 'firing') {
        if (this.alertCooldown <= 0) {
          this.emitter.emit('samAlert', {
            type: sam.state === 'firing' ? 'firing' : sam.state,
            samId: sam.id,
            distance: sam.getDistanceTo(aircraftPos),
          });
          this.alertCooldown = 0.5; // throttle alerts to every 500ms
        }
      }

      if (shouldFire) {
        this.launchMissile(sam, aircraftPos);
      }
    }

    // Update missiles
    for (let i = this.missiles.length - 1; i >= 0; i--) {
      const missile = this.missiles[i];
      if (missile.destroyed) {
        if (missile.hitTarget) {
          this.emitter.emit('missileHit', { missileId: missile.id });
        }
        missile.destroy();
        this.missiles.splice(i, 1);
        continue;
      }

      const distance = missile.update(deltaTime, aircraftPos);

      // Emit incoming warning
      if (distance < 2000) {
        const timeToImpact = distance / MISSILE_CONFIG.speed;
        this.emitter.emit('missileIncoming', {
          missileId: missile.id,
          distance,
          timeToImpact,
        });
      }
    }
  }

  private launchMissile(sam: SAMSite, targetPos: Cesium.Cartesian3): void {
    const missileId = `missile-${++this.missileCounter}`;
    const missile = new Missile(missileId, sam.id, sam.position, targetPos);
    missile.initialize(this.viewer);
    this.missiles.push(missile);

    console.log(`Missile launched: ${missileId} from ${sam.id}`);
  }

  /**
   * Deploy countermeasure. Returns true if any missile was defeated.
   */
  public deployCountermeasure(type: 'chaff' | 'flare'): boolean {
    if (type === 'chaff' && this.chaff <= 0) return false;
    if (type === 'flare' && this.flares <= 0) return false;

    if (type === 'chaff') this.chaff--;
    else this.flares--;
    this.countermeasuresUsed++;

    const remaining = type === 'chaff' ? this.chaff : this.flares;
    this.emitter.emit('countermeasureDeployed', { type, remaining });

    const aircraftPos = this.getAircraftPosition();

    // Spawn visual effect behind aircraft
    this.spawnCountermeasureEffect(type, aircraftPos);
    const rollRate = this.getAircraftRollRate();
    const isEvading = Math.abs(rollRate) > Cesium.Math.toRadians(30);

    let defeated = false;
    const baseChance = type === 'chaff'
      ? COUNTERMEASURES.chaffDefeatChance
      : COUNTERMEASURES.flareDefeatChance;
    const totalChance = baseChance + (isEvading ? COUNTERMEASURES.evasionBonus : 0);

    // Try to defeat each active missile within 300m
    for (const missile of this.missiles) {
      if (missile.destroyed) continue;
      const dist = missile.getDistanceTo(aircraftPos);
      if (dist < 300) {
        if (missile.attemptDefeat(totalChance)) {
          this.missilesEvaded++;
          defeated = true;
          this.emitter.emit('missileDefeated', {
            missileId: missile.id,
            method: type,
          });
          console.log(`Missile ${missile.id} defeated by ${type}`);
        }
      }
    }

    return defeated;
  }

  public getActiveMissileCount(): number {
    return this.missiles.filter(m => !m.destroyed).length;
  }

  public getMissilesEvaded(): number {
    return this.missilesEvaded;
  }

  public getCountermeasuresUsed(): number {
    return this.countermeasuresUsed;
  }

  public getClosestThreat(): { type: 'sam' | 'missile'; distance: number; state: string } | null {
    const aircraftPos = this.getAircraftPosition();
    let closest: { type: 'sam' | 'missile'; distance: number; state: string } | null = null;

    for (const missile of this.missiles) {
      if (missile.destroyed) continue;
      const dist = missile.getDistanceTo(aircraftPos);
      if (!closest || dist < closest.distance) {
        closest = { type: 'missile', distance: dist, state: 'incoming' };
      }
    }

    for (const sam of this.sams) {
      if (sam.state === 'idle' || sam.state === 'reloading') continue;
      const dist = sam.getDistanceTo(aircraftPos);
      if (!closest || (dist < closest.distance && sam.state === 'locked')) {
        closest = { type: 'sam', distance: dist, state: sam.state };
      }
    }

    return closest;
  }

  /**
   * Spawn animated countermeasure particles behind the aircraft.
   * Chaff = silver/white metallic strips spreading out
   * Flares = bright orange/yellow hot points falling away
   */
  private spawnCountermeasureEffect(type: 'chaff' | 'flare', origin: Cesium.Cartesian3): void {
    const count = type === 'chaff' ? 12 : 6;
    const color = type === 'chaff'
      ? Cesium.Color.WHITE.withAlpha(0.9)
      : Cesium.Color.ORANGE;
    const glowColor = type === 'chaff'
      ? Cesium.Color.SILVER.withAlpha(0.6)
      : Cesium.Color.YELLOW;
    const lifetimeMs = type === 'chaff' ? 3000 : 2000;
    const spread = type === 'chaff' ? 40 : 25;

    const enu = Cesium.Transforms.eastNorthUpToFixedFrame(origin);

    for (let i = 0; i < count; i++) {
      // Random velocity in local ENU (east, north, up)
      const vx = (Math.random() - 0.5) * spread;
      const vy = (Math.random() - 0.5) * spread;
      const vz = -Math.random() * spread * 0.8 - 5; // mostly downward

      const startPos = Cesium.Cartesian3.clone(origin);
      const spawnTime = performance.now();

      // Use CallbackProperty for real-time animation
      const posCallback = new Cesium.CallbackProperty(() => {
        const elapsed = (performance.now() - spawnTime) / 1000;
        const localOffset = new Cesium.Cartesian3(
          vx * elapsed,
          vy * elapsed,
          vz * elapsed - 4.9 * elapsed * elapsed // gravity
        );
        return Cesium.Matrix4.multiplyByPoint(enu, localOffset, new Cesium.Cartesian3());
      }, false);

      const pixelSize = type === 'chaff'
        ? 3 + Math.random() * 3
        : 5 + Math.random() * 4;

      const entity = this.viewer.entities.add({
        position: posCallback as any,
        point: {
          pixelSize,
          color: i % 2 === 0 ? color : glowColor,
          outlineColor: type === 'flare' ? Cesium.Color.RED.withAlpha(0.5) : undefined,
          outlineWidth: type === 'flare' ? 1 : 0,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });

      setTimeout(() => {
        try { this.viewer.entities.remove(entity); } catch {}
      }, lifetimeMs);
    }
  }

  public deactivate(): void {
    this.active = false;
  }

  public destroy(): void {
    this.active = false;
    for (const sam of this.sams) sam.destroy();
    for (const missile of this.missiles) missile.destroy();
    this.sams = [];
    this.missiles = [];
  }
}
