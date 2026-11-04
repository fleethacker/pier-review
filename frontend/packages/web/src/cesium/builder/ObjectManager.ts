import * as Cesium from 'cesium';
import { GameObject, GameObjectType } from '../objects/GameObject';
import { Waypoint } from '../objects/Waypoint';

export class ObjectManager {
  private objects: Map<string, GameObject> = new Map();
  private viewer: Cesium.Viewer;
  private nextWaypointIndex: number = 1;
  private pathEntity: Cesium.Entity | null = null;

  constructor(viewer: Cesium.Viewer) {
    this.viewer = viewer;
  }

  public placeObject(type: GameObjectType, position: Cesium.Cartesian3): GameObject {
    const id = `${type}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    let object: GameObject;

    switch (type) {
      case 'waypoint':
        object = new Waypoint({
          id,
          type,
          position,
          properties: { index: this.nextWaypointIndex++ }
        });
        break;
      default:
        throw new Error(`Unknown object type: ${type}`);
    }

    object.initialize(this.viewer);
    this.objects.set(id, object);
    this.updatePathLines();

    return object;
  }

  public removeObject(id: string): boolean {
    const object = this.objects.get(id);
    if (object) {
      object.destroy();
      this.objects.delete(id);
      this.updatePathLines();
      return true;
    }
    return false;
  }

  public getObject(id: string): GameObject | undefined {
    return this.objects.get(id);
  }

  public getAllObjects(): GameObject[] {
    return Array.from(this.objects.values());
  }

  public getWaypoints(): GameObject[] {
    return this.getAllObjects()
      .filter(o => o.type === 'waypoint')
      .sort((a, b) => (a.properties.index || 0) - (b.properties.index || 0));
  }

  public getWaypointPositions(): Cesium.Cartesian3[] {
    return this.getWaypoints().map(w => w.position.clone());
  }

  public getNextWaypointIndex(): number {
    return this.nextWaypointIndex;
  }

  public clear(): void {
    this.objects.forEach(obj => obj.destroy());
    this.objects.clear();
    this.nextWaypointIndex = 1;
    this.removePath();
  }

  public getObjectCount(): number {
    return this.objects.size;
  }

  private updatePathLines(): void {
    this.removePath();

    const waypoints = this.getWaypoints();
    if (waypoints.length < 2) return;

    const positions = waypoints.map(w => {
      const cart = Cesium.Cartographic.fromCartesian(w.position);
      return Cesium.Cartesian3.fromRadians(cart.longitude, cart.latitude, cart.height + 5);
    });

    this.pathEntity = this.viewer.entities.add({
      polyline: {
        positions,
        width: 2,
        material: new Cesium.PolylineDashMaterialProperty({
          color: Cesium.Color.fromCssColorString('#00e676'),
          dashLength: 16,
        }),
        clampToGround: false,
      },
    });
  }

  private removePath(): void {
    if (this.pathEntity) {
      this.viewer.entities.remove(this.pathEntity);
      this.pathEntity = null;
    }
  }
}
