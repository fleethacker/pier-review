import * as Cesium from 'cesium';

export class BuilderCursor {
  private viewer: Cesium.Viewer;
  private position: Cesium.Cartesian3;
  private cursorEntity: Cesium.Entity | null = null;
  private ghostEntity: Cesium.Entity | null = null;
  private waypointIndex: number = 1;

  private moveSpeed: number = 20;
  private fastMoveSpeed: number = 80;

  private moveInput = {
    forward: false,
    backward: false,
    left: false,
    right: false,
    up: false,
    down: false,
    fast: false
  };

  constructor(viewer: Cesium.Viewer, startPosition: Cesium.Cartesian3) {
    this.viewer = viewer;
    this.position = startPosition.clone();
    this.createCursorEntity();
    this.createGhostPreview();
  }

  private createCursorEntity(): void {
    this.cursorEntity = this.viewer.entities.add({
      position: new Cesium.CallbackPositionProperty(() => this.position, false),
      point: {
        pixelSize: 10,
        color: Cesium.Color.fromCssColorString('#00e5ff'),
        outlineColor: Cesium.Color.fromCssColorString('#1a3a5c'),
        outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: new Cesium.CallbackProperty(() => `DROP WP-${String(this.waypointIndex).padStart(2, '0')}`, false) as any,
        font: '11px monospace',
        fillColor: Cesium.Color.fromCssColorString('#00e5ff'),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -20),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  private createGhostPreview(): void {
    this.ghostEntity = this.viewer.entities.add({
      position: new Cesium.CallbackPositionProperty(() => {
        const cart = Cesium.Cartographic.fromCartesian(this.position);
        return Cesium.Cartesian3.fromRadians(
          cart.longitude,
          cart.latitude,
          cart.height + 5
        );
      }, false),
      point: {
        pixelSize: 16,
        color: Cesium.Color.fromCssColorString('#00e5ff').withAlpha(0.3),
        outlineColor: Cesium.Color.fromCssColorString('#00e5ff').withAlpha(0.5),
        outlineWidth: 1,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: 'PLACE WAYPOINT',
        font: '9px monospace',
        fillColor: Cesium.Color.fromCssColorString('#4a6a8a'),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -15),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  public setWaypointIndex(index: number): void {
    this.waypointIndex = index;
  }

  public update(deltaTime: number): void {
    const speed = this.moveInput.fast ? this.fastMoveSpeed : this.moveSpeed;
    const moveDistance = speed * deltaTime;

    if (!this.hasAnyInput()) return;

    // Use fixed compass directions (North/East/Up) instead of camera-relative
    // so cursor always moves consistently regardless of camera angle
    const transform = Cesium.Transforms.eastNorthUpToFixedFrame(this.position);

    // North = Y axis in ENU
    const localNorth = new Cesium.Cartesian3(0, 1, 0);
    // East = X axis in ENU
    const localEast = new Cesium.Cartesian3(1, 0, 0);
    // Up = Z axis in ENU
    const localUp = new Cesium.Cartesian3(0, 0, 1);

    const worldNorth = Cesium.Matrix4.multiplyByPointAsVector(transform, localNorth, new Cesium.Cartesian3());
    const worldEast = Cesium.Matrix4.multiplyByPointAsVector(transform, localEast, new Cesium.Cartesian3());
    const worldUp = Cesium.Matrix4.multiplyByPointAsVector(transform, localUp, new Cesium.Cartesian3());

    Cesium.Cartesian3.normalize(worldNorth, worldNorth);
    Cesium.Cartesian3.normalize(worldEast, worldEast);
    Cesium.Cartesian3.normalize(worldUp, worldUp);

    // W = North, S = South, D = East, A = West
    if (this.moveInput.forward) {
      const delta = Cesium.Cartesian3.multiplyByScalar(worldNorth, moveDistance, new Cesium.Cartesian3());
      Cesium.Cartesian3.add(this.position, delta, this.position);
    }
    if (this.moveInput.backward) {
      const delta = Cesium.Cartesian3.multiplyByScalar(worldNorth, -moveDistance, new Cesium.Cartesian3());
      Cesium.Cartesian3.add(this.position, delta, this.position);
    }
    if (this.moveInput.right) {
      const delta = Cesium.Cartesian3.multiplyByScalar(worldEast, moveDistance, new Cesium.Cartesian3());
      Cesium.Cartesian3.add(this.position, delta, this.position);
    }
    if (this.moveInput.left) {
      const delta = Cesium.Cartesian3.multiplyByScalar(worldEast, -moveDistance, new Cesium.Cartesian3());
      Cesium.Cartesian3.add(this.position, delta, this.position);
    }
    if (this.moveInput.up) {
      const delta = Cesium.Cartesian3.multiplyByScalar(worldUp, moveDistance, new Cesium.Cartesian3());
      Cesium.Cartesian3.add(this.position, delta, this.position);
    }
    if (this.moveInput.down) {
      const delta = Cesium.Cartesian3.multiplyByScalar(worldUp, -moveDistance, new Cesium.Cartesian3());
      Cesium.Cartesian3.add(this.position, delta, this.position);
    }
  }

  private hasAnyInput(): boolean {
    return Object.values(this.moveInput).some(value => value === true);
  }

  public setMoveInput(input: Partial<typeof this.moveInput>): void {
    Object.assign(this.moveInput, input);
  }

  public getPosition(): Cesium.Cartesian3 {
    return this.position.clone();
  }

  public setPosition(position: Cesium.Cartesian3): void {
    this.position = position.clone();
  }

  public destroy(): void {
    if (this.cursorEntity) {
      this.viewer.entities.remove(this.cursorEntity);
      this.cursorEntity = null;
    }
    if (this.ghostEntity) {
      this.viewer.entities.remove(this.ghostEntity);
      this.ghostEntity = null;
    }
  }

  public updateGhostPreview(objectType: string): void {
    if (!this.ghostEntity || !this.ghostEntity.label) return;
    this.ghostEntity.label.text = new Cesium.ConstantProperty(`PLACE ${objectType.toUpperCase()}`);
  }
}
