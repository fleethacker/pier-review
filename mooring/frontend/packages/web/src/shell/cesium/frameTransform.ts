import * as Cesium from 'cesium';
import { enuToFrame, frameToEnu } from '../../scene/geometry';
import type { LocalFrame } from '../../scene/types';

/** Converts between scene-frame meters and Cesium world coordinates for one local frame. */
export class FrameTransform {
  readonly origin: Cesium.Cartesian3;
  readonly up: Cesium.Cartesian3;
  private readonly enu: Cesium.Matrix4;
  private readonly inverse: Cesium.Matrix4;

  constructor(readonly frame: LocalFrame) {
    this.origin = Cesium.Cartesian3.fromDegrees(frame.lonDeg, frame.latDeg, 0);
    this.up = Cesium.Cartesian3.normalize(this.origin, new Cesium.Cartesian3());
    this.enu = Cesium.Transforms.eastNorthUpToFixedFrame(this.origin);
    this.inverse = Cesium.Matrix4.inverseTransformation(this.enu, new Cesium.Matrix4());
  }

  toWorld(x: number, y: number, z = 0): Cesium.Cartesian3 {
    const [e, n] = frameToEnu(this.frame, x, y);
    return Cesium.Matrix4.multiplyByPoint(this.enu, new Cesium.Cartesian3(e, n, z), new Cesium.Cartesian3());
  }

  toFrame(world: Cesium.Cartesian3): [number, number] {
    const l = Cesium.Matrix4.multiplyByPoint(this.inverse, world, new Cesium.Cartesian3());
    return enuToFrame(this.frame, l.x, l.y);
  }

  /** Where a camera ray meets the frame's horizontal plane (z = 0), in frame meters. */
  groundPoint(ray: Cesium.Ray | undefined): [number, number] | null {
    if (!ray) return null;
    const plane = Cesium.Plane.fromPointNormal(this.origin, this.up);
    const hit = Cesium.IntersectionTests.rayPlane(ray, plane);
    return hit ? this.toFrame(hit) : null;
  }
}
