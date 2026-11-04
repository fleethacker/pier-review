import * as Cesium from 'cesium';
import { MISSILE_CONFIG } from '../missions/MaverickMissionData';

export class Missile {
  public readonly id: string;
  public readonly sourceId: string; // which SAM fired it
  public position: Cesium.Cartesian3;
  public destroyed: boolean = false;
  public hitTarget: boolean = false;

  private velocity: Cesium.Cartesian3;
  private speed: number;
  private distanceTraveled: number = 0;
  private entity: Cesium.Entity | null = null;
  private trailEntity: Cesium.Entity | null = null;
  private viewer: Cesium.Viewer | null = null;
  private trailPositions: Cesium.Cartesian3[] = [];

  constructor(id: string, sourceId: string, startPosition: Cesium.Cartesian3, targetPosition: Cesium.Cartesian3) {
    this.id = id;
    this.sourceId = sourceId;
    this.position = Cesium.Cartesian3.clone(startPosition);
    this.speed = MISSILE_CONFIG.speed;

    // Initial velocity toward target
    const direction = Cesium.Cartesian3.subtract(targetPosition, startPosition, new Cesium.Cartesian3());
    Cesium.Cartesian3.normalize(direction, direction);
    this.velocity = Cesium.Cartesian3.multiplyByScalar(direction, this.speed, new Cesium.Cartesian3());
  }

  public initialize(viewer: Cesium.Viewer): void {
    this.viewer = viewer;

    // Missile marker — bright orange/red dot
    this.entity = viewer.entities.add({
      position: new Cesium.CallbackProperty(() => this.position, false) as any,
      point: {
        pixelSize: 6,
        color: Cesium.Color.ORANGERED,
        outlineColor: Cesium.Color.YELLOW,
        outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });

    // Smoke trail
    this.trailPositions = [Cesium.Cartesian3.clone(this.position)];
    this.trailEntity = viewer.entities.add({
      polyline: {
        positions: new Cesium.CallbackProperty(() => {
          return this.trailPositions.length >= 2 ? [...this.trailPositions] : undefined;
        }, false) as any,
        width: 2,
        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower: 0.3,
          color: Cesium.Color.ORANGE.withAlpha(0.6),
        }),
      },
    });
  }

  /**
   * Update missile position with pursuit guidance toward target.
   * Returns distance to target.
   */
  public update(deltaTime: number, targetPosition: Cesium.Cartesian3): number {
    if (this.destroyed) return Infinity;

    // Desired direction to target
    const toTarget = Cesium.Cartesian3.subtract(targetPosition, this.position, new Cesium.Cartesian3());
    const distance = Cesium.Cartesian3.magnitude(toTarget);
    Cesium.Cartesian3.normalize(toTarget, toTarget);

    // Current direction
    const currentDir = Cesium.Cartesian3.normalize(
      Cesium.Cartesian3.clone(this.velocity),
      new Cesium.Cartesian3()
    );

    // Blend toward target direction (limited turn rate)
    const maxTurnThisFrame = MISSILE_CONFIG.turnRate * deltaTime;
    const dot = Cesium.Cartesian3.dot(currentDir, toTarget);
    const angle = Math.acos(Math.max(-1, Math.min(1, dot)));

    let newDir: Cesium.Cartesian3;
    if (angle < maxTurnThisFrame || angle < 0.001) {
      newDir = toTarget;
    } else {
      const t = maxTurnThisFrame / angle;
      newDir = new Cesium.Cartesian3();
      Cesium.Cartesian3.lerp(currentDir, toTarget, t, newDir);
      Cesium.Cartesian3.normalize(newDir, newDir);
    }

    // Update velocity and position
    this.velocity = Cesium.Cartesian3.multiplyByScalar(newDir, this.speed, this.velocity);
    const delta = Cesium.Cartesian3.multiplyByScalar(this.velocity, deltaTime, new Cesium.Cartesian3());
    this.position = Cesium.Cartesian3.add(this.position, delta, this.position);
    this.distanceTraveled += this.speed * deltaTime;

    // Update trail
    this.trailPositions.push(Cesium.Cartesian3.clone(this.position));
    if (this.trailPositions.length > MISSILE_CONFIG.trailLength) {
      this.trailPositions.shift();
    }

    // Check max range
    if (this.distanceTraveled > MISSILE_CONFIG.maxRange) {
      this.destroyed = true;
    }

    // Check proximity fuse
    if (distance < MISSILE_CONFIG.proximityFuse) {
      this.hitTarget = true;
      this.destroyed = true;
    }

    return distance;
  }

  /**
   * Attempt to defeat this missile with countermeasures.
   * Returns true if the missile is defeated.
   */
  public attemptDefeat(chance: number): boolean {
    if (Math.random() < chance) {
      this.destroyed = true;
      return true;
    }
    return false;
  }

  public getDistanceTo(pos: Cesium.Cartesian3): number {
    return Cesium.Cartesian3.distance(this.position, pos);
  }

  public destroy(): void {
    if (this.viewer) {
      if (this.entity) this.viewer.entities.remove(this.entity);
      if (this.trailEntity) this.viewer.entities.remove(this.trailEntity);
    }
    this.entity = null;
    this.trailEntity = null;
    this.destroyed = true;
  }
}
