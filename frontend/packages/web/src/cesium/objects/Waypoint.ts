import * as Cesium from 'cesium';
import { GameObject, GameObjectData } from './GameObject';

export class Waypoint extends GameObject {
  constructor(data: GameObjectData) {
    super(data);
  }

  public createEntity(_viewer: Cesium.Viewer): Cesium.Entity {
    const cartographic = Cesium.Cartographic.fromCartesian(this.position);
    const heightAboveTerrain = 5;
    const elevatedPosition = Cesium.Cartesian3.fromRadians(
      cartographic.longitude,
      cartographic.latitude,
      cartographic.height + heightAboveTerrain
    );

    const groundPosition = Cesium.Cartesian3.fromRadians(
      cartographic.longitude,
      cartographic.latitude,
      cartographic.height
    );

    const idx = this.properties.index || '';

    return new Cesium.Entity({
      id: this.id,
      position: elevatedPosition,
      point: {
        pixelSize: 14,
        color: Cesium.Color.fromCssColorString('#00e5ff'),
        outlineColor: Cesium.Color.fromCssColorString('#1a3a5c'),
        outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: `WP-${String(idx).padStart(2, '0')}`,
        font: '11px monospace',
        fillColor: Cesium.Color.fromCssColorString('#00e5ff'),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -15),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      polyline: {
        positions: [elevatedPosition, groundPosition],
        width: 1,
        material: Cesium.Color.fromCssColorString('#00e5ff').withAlpha(0.3),
      },
    });
  }

  protected updateRotation(): void {
    // Waypoints don't rotate
  }
}
