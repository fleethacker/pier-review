import * as Cesium from 'cesium';
import type { SAMPosition } from '../missions/MaverickMissionData';
import { MISSILE_CONFIG } from '../missions/MaverickMissionData';

export type SAMState = 'idle' | 'tracking' | 'locked' | 'firing' | 'reloading';

export class SAMSite {
  public readonly id: string;
  public readonly position: Cesium.Cartesian3;
  public readonly detectionRadius: number;
  public readonly altitudeThreshold: number;
  public readonly label: string;
  public readonly modelUrl: string;

  public state: SAMState = 'idle';
  private trackingTime: number = 0;
  private reloadTimer: number = 0;
  private entity: Cesium.Entity | null = null;
  private rangeEntity: Cesium.Entity | null = null;
  private modelPrimitive: Cesium.Model | null = null;
  private viewer: Cesium.Viewer | null = null;
  private scene: Cesium.Scene | null = null;

  constructor(data: SAMPosition) {
    this.id = data.id;
    this.position = Cesium.Cartesian3.fromDegrees(data.lon, data.lat, data.alt);
    this.detectionRadius = data.detectionRadius;
    this.altitudeThreshold = data.altitudeThreshold;
    this.label = data.label || 'SAM';
    this.modelUrl = data.modelUrl || './sam-s300.glb';
  }

  public async initialize(viewer: Cesium.Viewer): Promise<void> {
    this.viewer = viewer;
    this.scene = viewer.scene;

    // Load 3D SAM model
    try {
      const hpr = new Cesium.HeadingPitchRoll(0, 0, 0);
      this.modelPrimitive = viewer.scene.primitives.add(
        await Cesium.Model.fromGltfAsync({
          url: this.modelUrl,
          scale: 5.0, // Scale up for visibility from altitude
          modelMatrix: Cesium.Transforms.headingPitchRollToFixedFrame(
            this.position,
            hpr,
            Cesium.Ellipsoid.WGS84
          ),
        })
      );
    } catch (err) {
      console.warn(`SAM ${this.id}: Failed to load model ${this.modelUrl}, using fallback`);
    }

    // Label entity (always visible from distance)
    this.entity = viewer.entities.add({
      position: this.position,
      point: {
        pixelSize: 10,
        color: Cesium.Color.RED.withAlpha(0.8),
        outlineColor: Cesium.Color.DARKRED,
        outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: this.label,
        font: '10px monospace',
        fillColor: Cesium.Color.RED.withAlpha(0.7),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -12),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        scale: 0.8,
      },
    });

    // Detection range circle on ground
    this.rangeEntity = viewer.entities.add({
      position: this.position,
      ellipse: {
        semiMajorAxis: this.detectionRadius,
        semiMinorAxis: this.detectionRadius,
        material: Cesium.Color.RED.withAlpha(0.05),
        outline: true,
        outlineColor: Cesium.Color.RED.withAlpha(0.15),
        outlineWidth: 1,
        height: Cesium.Cartographic.fromCartesian(this.position).height,
      },
    });
  }

  /**
   * Update SAM state based on aircraft position and AGL.
   * Returns true if a missile should be fired.
   */
  public update(deltaTime: number, aircraftPos: Cesium.Cartesian3, aircraftAGL: number): boolean {
    // Use horizontal distance (ignore altitude difference) for detection range
    const samCart = Cesium.Cartographic.fromCartesian(this.position);
    const acCart = Cesium.Cartographic.fromCartesian(aircraftPos);
    const dLat = acCart.latitude - samCart.latitude;
    const dLon = acCart.longitude - samCart.longitude;
    const avgLat = (acCart.latitude + samCart.latitude) / 2;
    const horizontalDist = Math.sqrt(
      (dLat * 6371000) ** 2 + (dLon * Math.cos(avgLat) * 6371000) ** 2
    );

    if (this.state === 'reloading') {
      this.reloadTimer -= deltaTime;
      if (this.reloadTimer <= 0) {
        this.state = 'idle';
        this.reloadTimer = 0;
      }
      return false;
    }

    if (this.state === 'firing') {
      this.state = 'reloading';
      this.reloadTimer = MISSILE_CONFIG.reloadTime;
      this.trackingTime = 0;
      return false;
    }

    const inRange = horizontalDist < this.detectionRadius;
    const aboveThreshold = aircraftAGL > this.altitudeThreshold;

    if (!inRange || !aboveThreshold) {
      if (this.state !== 'idle') {
        this.state = 'idle';
        this.trackingTime = 0;
        this.updateVisual();
      }
      return false;
    }

    if (this.state === 'idle') {
      this.state = 'tracking';
      this.trackingTime = 0;
      this.updateVisual();
    }

    if (this.state === 'tracking') {
      this.trackingTime += deltaTime;
      if (this.trackingTime >= MISSILE_CONFIG.lockOnTime) {
        this.state = 'locked';
        this.updateVisual();
      }
      return false;
    }

    if (this.state === 'locked') {
      this.state = 'firing';
      this.updateVisual();
      return true;
    }

    return false;
  }

  private updateVisual(): void {
    if (!this.entity?.point) return;

    switch (this.state) {
      case 'idle':
        (this.entity.point.color as any) = Cesium.Color.RED.withAlpha(0.8);
        (this.entity.point.pixelSize as any) = 10;
        break;
      case 'tracking':
        (this.entity.point.color as any) = Cesium.Color.YELLOW;
        (this.entity.point.pixelSize as any) = 14;
        break;
      case 'locked':
      case 'firing':
        (this.entity.point.color as any) = Cesium.Color.fromCssColorString('#ff0000');
        (this.entity.point.pixelSize as any) = 18;
        break;
      case 'reloading':
        (this.entity.point.color as any) = Cesium.Color.ORANGE.withAlpha(0.5);
        (this.entity.point.pixelSize as any) = 10;
        break;
    }
  }

  public getDistanceTo(pos: Cesium.Cartesian3): number {
    return Cesium.Cartesian3.distance(this.position, pos);
  }

  public destroy(): void {
    if (this.viewer) {
      if (this.entity) this.viewer.entities.remove(this.entity);
      if (this.rangeEntity) this.viewer.entities.remove(this.rangeEntity);
    }
    if (this.modelPrimitive && this.scene) {
      try {
        this.scene.primitives.remove(this.modelPrimitive);
      } catch {}
    }
    this.entity = null;
    this.rangeEntity = null;
    this.modelPrimitive = null;
  }
}
