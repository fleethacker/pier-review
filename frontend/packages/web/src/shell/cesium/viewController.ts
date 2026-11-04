import * as Cesium from 'cesium';
import { normalizeDeg, topDownHeadingDeg } from '../../scene/geometry';
import type { ViewMode } from '../../scene/types';
import type { FrameTransform } from './frameTransform';

const MIN_WIDTH_M = 15;
const MAX_WIDTH_M = 8000;
const TOP_DOWN_RANGE_M = 3000;

/**
 * Owns the camera. 2D is an orthographic camera looking straight down with frame +x to the right and +y up;
 * 3D is a perspective orbit camera around the same target. Cesium's own camera controller is disabled.
 */
export class ViewController {
  mode: ViewMode = '2d';
  private tf: FrameTransform | null = null;
  private target: [number, number] = [0, 0];
  private widthM = 400;
  private heading3dDeg = 0;
  private pitch3dDeg = -40;
  private range3dM = 500;

  constructor(private readonly camera: Cesium.Camera) {}

  setFrame(tf: FrameTransform): void {
    this.tf = tf;
    this.heading3dDeg = normalizeDeg(tf.frame.xBearingTrueDeg + 90);
  }

  fit(bounds: { minX: number; maxX: number; minY: number; maxY: number } | null, aspect: number): void {
    const b = bounds ?? { minX: -100, maxX: 100, minY: -60, maxY: 60 };
    const w = Math.max(b.maxX - b.minX, 20);
    const h = Math.max(b.maxY - b.minY, 20);
    this.target = [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
    this.widthM = Math.min(Math.max(w, h * aspect) * 1.2, MAX_WIDTH_M);
    this.range3dM = Math.max(w, h) * 0.9;
    this.apply();
  }

  setMode(mode: ViewMode): void {
    this.mode = mode;
    this.apply();
  }

  panBy(dx: number, dy: number): void {
    this.target = [this.target[0] + dx, this.target[1] + dy];
    this.apply();
  }

  orbit(dxPx: number, dyPx: number): void {
    if (this.mode !== '3d') return;
    this.heading3dDeg = normalizeDeg(this.heading3dDeg - dxPx * 0.3);
    this.pitch3dDeg = Math.min(-8, Math.max(-89, this.pitch3dDeg - dyPx * 0.2));
    this.apply();
  }

  /** factor < 1 zooms in. */
  zoomBy(factor: number): void {
    if (this.mode === '2d') {
      this.widthM = Math.min(MAX_WIDTH_M, Math.max(MIN_WIDTH_M, this.widthM * factor));
    } else {
      this.range3dM = Math.min(MAX_WIDTH_M, Math.max(MIN_WIDTH_M, this.range3dM * factor));
    }
    this.apply();
  }

  /** Screen-space heading of the camera in degrees clockwise from north (for the compass). */
  get screenUpBearingDeg(): number {
    if (!this.tf) return 0;
    return this.mode === '2d' ? topDownHeadingDeg(this.tf.frame) : this.heading3dDeg;
  }

  private apply(): void {
    if (!this.tf) return;
    const center = this.tf.toWorld(this.target[0], this.target[1], 0);
    const rad = Cesium.Math.toRadians;
    if (this.mode === '2d') {
      if (!(this.camera.frustum instanceof Cesium.OrthographicFrustum)) {
        this.camera.switchToOrthographicFrustum();
      }
      // lookAt ignores heading when looking straight down, so place the camera directly above the target.
      this.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
      const above = Cesium.Cartesian3.add(
        center,
        Cesium.Cartesian3.multiplyByScalar(this.tf.up, TOP_DOWN_RANGE_M, new Cesium.Cartesian3()),
        new Cesium.Cartesian3(),
      );
      this.camera.setView({
        destination: above,
        orientation: { heading: rad(topDownHeadingDeg(this.tf.frame)), pitch: -Math.PI / 2, roll: 0 },
      });
      (this.camera.frustum as Cesium.OrthographicFrustum).width = this.widthM;
    } else {
      if (!(this.camera.frustum instanceof Cesium.PerspectiveFrustum)) {
        this.camera.switchToPerspectiveFrustum();
      }
      this.camera.lookAt(
        center,
        new Cesium.HeadingPitchRange(rad(this.heading3dDeg), rad(this.pitch3dDeg), this.range3dM),
      );
    }
  }
}
