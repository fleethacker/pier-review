import * as Cesium from 'cesium';
import { normalizeDeg, topDownHeadingDeg } from '../../scene/geometry';
import type { CameraPreset, ViewMode } from '../../scene/types';
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
  private pitch3dDeg = -34;
  private range3dM = 500;

  private intro: { start: number; from: { widthM: number; range: number; pitch: number; heading: number } } | null = null;
  private introFrame = 0;

  /** `onFrame` asks for a redraw while the intro plays (the scene only renders on demand). */
  constructor(
    private readonly camera: Cesium.Camera,
    private readonly onFrame: () => void = () => {},
  ) {}

  /**
   * After the next fit, ease in from a high, steep, slightly turned view to the framed one. Any camera input
   * cancels it so it never fights the user.
   */
  playIntro(): void {
    // People who ask their system for less motion get the framed view straight away.
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    this.pendingIntro = !reduce;
  }
  private pendingIntro = false;

  private cancelIntro(): void {
    this.pendingIntro = false;
    this.intro = null;
    if (this.introFrame) cancelAnimationFrame(this.introFrame);
    this.introFrame = 0;
  }

  private startIntro(): void {
    const to = { widthM: this.widthM, range: this.range3dM, pitch: this.pitch3dDeg, heading: this.heading3dDeg };
    this.intro = {
      start: performance.now(),
      from: { widthM: to.widthM * 2.4, range: to.range * 2.6, pitch: -72, heading: to.heading + 28 },
    };
    const DURATION_MS = 2200;
    const tick = (now: number) => {
      const intro = this.intro;
      if (!intro) return;
      const t = Math.min((now - intro.start) / DURATION_MS, 1);
      const e = 1 - Math.pow(1 - t, 3); // ease out
      const mix = (a: number, b: number) => a + (b - a) * e;
      this.widthM = mix(intro.from.widthM, to.widthM);
      this.range3dM = mix(intro.from.range, to.range);
      this.pitch3dDeg = mix(intro.from.pitch, to.pitch);
      this.heading3dDeg = normalizeDeg(mix(intro.from.heading, to.heading));
      this.apply();
      this.onFrame();
      if (t < 1) this.introFrame = requestAnimationFrame(tick);
      else this.cancelIntro();
    };
    // Start from the far view right away, so the framed view never shows for a frame first.
    this.widthM = this.intro.from.widthM;
    this.range3dM = this.intro.from.range;
    this.pitch3dDeg = this.intro.from.pitch;
    this.heading3dDeg = normalizeDeg(this.intro.from.heading);
    this.apply();
    this.introFrame = requestAnimationFrame(tick);
  }

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
    if (this.pendingIntro && bounds) {
      this.pendingIntro = false;
      this.startIntro();
      return;
    }
    this.cancelIntro();
    this.apply();
  }

  setMode(mode: ViewMode): void {
    this.mode = mode;
    this.apply();
  }

  /**
   * Named camera positions. The frame's +x runs along the berth face; the ship lies along it with the pier on the -y
   * side, so the bearings below are relative to the frame's own axis.
   */
  setPreset(name: CameraPreset, target?: { x: number; y: number }): void {
    this.cancelIntro();
    if (target) this.target = [target.x, target.y];
    const x = this.tf?.frame.xBearingTrueDeg ?? 0;
    if (name === 'top') {
      this.mode = '2d';
    } else {
      this.mode = '3d';
      this.heading3dDeg = normalizeDeg(x + (name === 'bow' ? 180 : name === 'portQuarter' ? 45 : 90));
      this.pitch3dDeg = name === 'pierSide' ? -22 : -18;
      this.range3dM = 220;
    }
    this.apply();
  }

  panBy(dx: number, dy: number): void {
    this.cancelIntro();
    this.target = [this.target[0] + dx, this.target[1] + dy];
    this.apply();
  }

  orbit(dxPx: number, dyPx: number): void {
    if (this.mode !== '3d') return;
    this.cancelIntro();
    this.heading3dDeg = normalizeDeg(this.heading3dDeg - dxPx * 0.3);
    this.pitch3dDeg = Math.min(-8, Math.max(-89, this.pitch3dDeg - dyPx * 0.2));
    this.apply();
  }

  /** factor < 1 zooms in. */
  zoomBy(factor: number): void {
    this.cancelIntro();
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
