import * as Cesium from 'cesium';

/**
 * Loads and places a static 3D GLB model at a fixed world position.
 * Used for non-moving objects like aircraft carriers, buildings, etc.
 */
export class StaticModel {
  private primitive: Cesium.Model | null = null;
  private scene: Cesium.Scene | null = null;
  public position: Cesium.Cartesian3;
  public heading: number;

  constructor(position: Cesium.Cartesian3, heading: number = 0) {
    this.position = position;
    this.heading = heading;
  }

  public async load(
    scene: Cesium.Scene,
    url: string,
    scale: number = 1.0
  ): Promise<void> {
    this.scene = scene;

    const hpr = new Cesium.HeadingPitchRoll(
      Cesium.Math.toRadians(this.heading),
      0,
      0
    );

    this.primitive = scene.primitives.add(
      await Cesium.Model.fromGltfAsync({
        url,
        scale,
        modelMatrix: Cesium.Transforms.headingPitchRollToFixedFrame(
          this.position,
          hpr,
          Cesium.Ellipsoid.WGS84
        ),
      })
    );
  }

  /**
   * Get a position on the flight deck offset from the model origin.
   * Offsets are in local ENU coordinates (east, north, up).
   */
  public getDeckPosition(forwardOffset: number, rightOffset: number, upOffset: number): Cesium.Cartesian3 {
    const enu = Cesium.Transforms.eastNorthUpToFixedFrame(this.position);
    const headingRad = Cesium.Math.toRadians(this.heading);

    // Rotate offset by heading
    const cosH = Math.cos(headingRad);
    const sinH = Math.sin(headingRad);
    const east = forwardOffset * sinH + rightOffset * cosH;
    const north = forwardOffset * cosH - rightOffset * sinH;

    const localOffset = new Cesium.Cartesian3(east, north, upOffset);
    const worldOffset = Cesium.Matrix4.multiplyByPoint(enu, localOffset, new Cesium.Cartesian3());

    return worldOffset;
  }

  public getPrimitive(): Cesium.Model | null {
    return this.primitive;
  }

  public destroy(): void {
    if (this.primitive && this.scene) {
      try {
        this.scene.primitives.remove(this.primitive);
      } catch {}
      this.primitive = null;
    }
  }
}
