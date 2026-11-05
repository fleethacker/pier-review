import * as Cesium from 'cesium';
import { FlowField, flowSpeed } from '../../scene/flow';
import type { Bounds } from '../../scene/geometry';
import type { Lighting, SceneVector } from '../../scene/types';
import type { FrameTransform } from './frameTransform';

const css = (c: string) => Cesium.Color.fromCssColorString(c);
const WATER_MARGIN_M = 600;
const WATER_HEIGHT_M = 0.06;
const WIND_HEIGHT_M = 16;
const CURRENT_HEIGHT_M = 0.5;
/** Particle region around the arrows, in meters each side of their midpoint. */
const REGION = { halfW: 330, halfH: 230 };
const IMAGERY_STYLE = 'satellite-streets-v12';

const WATER_SOURCE = `
czm_material czm_getMaterial(czm_materialInput materialInput) {
  czm_material m = czm_getDefaultMaterial(materialInput);
  vec2 p = materialInput.st * extent / 3.2;
  float w = sin(p.x * 1.1 + time * 0.9) * sin(p.y * 1.3 - time * 0.7)
          + 0.6 * sin((p.x * 0.7 + p.y * 1.1) * 1.9 + time * 1.4)
          + 0.4 * sin((p.x - p.y) * 2.7 - time * 1.9);
  float shade = clamp(0.5 + 0.22 * w, 0.0, 1.0);
  float glint = smoothstep(1.3, 1.9, w);
  vec3 col = mix(deep.rgb, shallow.rgb, shade);
  col = mix(col, vec3(0.75, 0.92, 1.0), glint * 0.6);
  m.diffuse = col;
  m.alpha = clamp(baseAlpha + glint * 0.3, 0.0, 1.0);
  return m;
}`;

interface FlowSystem {
  field: FlowField;
  lines: Cesium.Polyline[];
  vector: SceneVector;
  heightM: number;
  trailM: number;
}

/**
 * Everything that makes the scene look alive: Mapbox imagery under it, rippling water, particles streaming along the
 * wind and current arrows, and a pulse clock for the lines that need attention. Imagery needs VITE_MAPBOX_TOKEN; with
 * no token, or if Mapbox refuses it, the scene falls back to the drawn water and carries on.
 */
export class SceneEffects {
  /** 0..1 and swinging; read by anything that should pulse. */
  pulse = 1;
  /** False when the user asked their system for reduced motion: no particles, no ripples, no pulsing. */
  readonly animated: boolean;

  private tf: FrameTransform | null = null;
  private bounds: Bounds | null = null;
  private water: Cesium.Primitive | null = null;
  private waterMaterial: Cesium.Material | null = null;
  private imagery: Cesium.ImageryLayer | null = null;
  private attribution: HTMLElement | null = null;
  private lines = new Cesium.PolylineCollection();
  private flows = new Map<string, FlowSystem>();
  private raf = 0;
  private last = 0;
  private disposed = false;
  private removeTileListener: (() => void) | null = null;
  private lighting: Lighting = 'night';

  constructor(
    private viewer: Cesium.Viewer,
    container: HTMLElement,
  ) {
    this.animated = !(typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
    viewer.scene.primitives.add(this.lines);
    this.addImagery(container);
    this.setLighting('night');
  }

  /**
   * Night is the dark HUD look with bloom, so lit things glow. Day lifts the imagery to near natural and eases the
   * glow off, for bright rooms and projectors.
   */
  setLighting(mode: Lighting): void {
    this.lighting = mode;
    const day = mode === 'day';
    const scene = this.viewer.scene;
    if (this.imagery) {
      this.imagery.brightness = day ? 1.0 : 0.62;
      this.imagery.contrast = day ? 1.05 : 1.15;
      this.imagery.saturation = day ? 1.0 : 0.8;
    }
    scene.backgroundColor = Cesium.Color.fromCssColorString(day ? '#8fb4d4' : '#0a1628');
    const bloom = scene.postProcessStages.bloom;
    bloom.enabled = !day;
    bloom.uniforms.glowOnly = false;
    bloom.uniforms.contrast = 128;
    bloom.uniforms.brightness = -0.55; // high threshold: only the lit accents glow, not the grey pier or imagery
    bloom.uniforms.delta = 0.9;
    bloom.uniforms.sigma = 2;
    bloom.uniforms.stepSize = 1;
    this.applyWaterLook();
    scene.requestRender();
  }

  private applyWaterLook(): void {
    const u = this.waterMaterial?.uniforms;
    if (!u) return;
    const day = this.lighting === 'day';
    u.deep = css(day ? '#1d6f9f' : '#0a2a48');
    u.shallow = css(day ? '#4ba3cf' : '#1f6a9a');
    u.baseAlpha = this.imagery ? (day ? 0.05 : 0.1) : 1;
  }

  // ---- imagery -------------------------------------------------------------------------------------------

  private addImagery(container: HTMLElement): void {
    const token = import.meta.env.VITE_MAPBOX_TOKEN as string | undefined;
    if (!token) return;
    const provider = new Cesium.MapboxStyleImageryProvider({ username: 'mapbox', styleId: IMAGERY_STYLE, accessToken: token });
    const layer = this.viewer.imageryLayers.addImageryProvider(provider);
    // Darken and cool the photo so the HUD colors and arrows stay the brightest things on screen.
    layer.brightness = 0.62;
    layer.contrast = 1.15;
    layer.saturation = 0.8;
    this.imagery = layer;
    provider.errorEvent.addEventListener(() => this.dropImagery());
    const globe = this.viewer.scene.globe;
    this.removeTileListener = globe.tileLoadProgressEvent.addEventListener(() => this.viewer.scene.requestRender());

    const credit = document.createElement('div');
    credit.textContent = '© Mapbox © OpenStreetMap © Maxar';
    credit.style.cssText =
      'position:absolute;left:8px;bottom:6px;font:9px "JetBrains Mono",monospace;color:#8ba4c4;opacity:.8;pointer-events:none;z-index:5';
    container.appendChild(credit);
    this.attribution = credit;
  }

  /** Mapbox said no (bad token, no network, quota): go back to the drawn water. */
  private dropImagery(): void {
    if (!this.imagery) return;
    this.viewer.imageryLayers.remove(this.imagery);
    this.imagery = null;
    this.attribution?.remove();
    this.attribution = null;
    if (this.waterMaterial) this.waterMaterial.uniforms.baseAlpha = 1;
    this.viewer.scene.requestRender();
  }

  // ---- water ---------------------------------------------------------------------------------------------

  setFrame(tf: FrameTransform | null): void {
    this.tf = tf;
    this.clearWater();
    this.bounds = null;
  }

  setBounds(bounds: Bounds | null): void {
    this.bounds = bounds;
    this.buildWater();
    this.ensureLoop();
  }

  private clearWater(): void {
    if (this.water) this.viewer.scene.primitives.remove(this.water);
    this.water = null;
    this.waterMaterial = null;
  }

  private buildWater(): void {
    this.clearWater();
    const { tf, bounds } = this;
    if (!tf || !bounds) return;
    const m = WATER_MARGIN_M;
    const corners = [
      [bounds.minX - m, bounds.minY - m],
      [bounds.maxX + m, bounds.minY - m],
      [bounds.maxX + m, bounds.maxY + m],
      [bounds.minX - m, bounds.maxY + m],
    ].map(([x, y]) => tf.toWorld(x, y, 0));
    const extent = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY) + 2 * m;
    const material = new Cesium.Material({
      fabric: {
        type: 'MooringWater',
        uniforms: {
          time: 0,
          extent,
          // With imagery the water is just a faint tint plus glints; without it, the whole surface is drawn.
          baseAlpha: this.imagery ? 0.1 : 1,
          deep: css('#0a2a48'),
          shallow: css('#1f6a9a'),
        },
        source: WATER_SOURCE,
      },
    });
    this.waterMaterial = material;
    this.applyWaterLook();
    this.water = this.viewer.scene.primitives.add(
      new Cesium.Primitive({
        geometryInstances: new Cesium.GeometryInstance({
          geometry: new Cesium.PolygonGeometry({
            polygonHierarchy: new Cesium.PolygonHierarchy(corners),
            height: WATER_HEIGHT_M,
            vertexFormat: Cesium.EllipsoidSurfaceAppearance.VERTEX_FORMAT,
          }),
        }),
        appearance: new Cesium.EllipsoidSurfaceAppearance({ material, flat: true, aboveGround: false }),
        asynchronous: false,
        allowPicking: false,
      }),
    );
    this.viewer.scene.requestRender();
  }

  // ---- flow particles ------------------------------------------------------------------------------------

  setVectors(vectors: SceneVector[]): void {
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    // Streaming particles are decoration; the arrows themselves still show direction and speed.
    const flowing = reduce ? [] : vectors.filter((v) => v.flow);
    for (const [id, sys] of [...this.flows]) {
      if (!flowing.some((v) => v.id === id)) {
        sys.lines.forEach((l) => this.lines.remove(l));
        this.flows.delete(id);
      }
    }
    if (!this.animated || flowing.length === 0 || !this.tf) {
      this.ensureLoop();
      return;
    }
    const region = this.regionFor(flowing);
    for (const v of flowing) {
      const isWind = v.kind === 'wind';
      const count = isWind ? 130 : 90;
      let sys = this.flows.get(v.id);
      if (!sys) {
        const color = css(v.color ?? '#ffffff').withAlpha(isWind ? 0.5 : 0.6);
        const field = new FlowField(count, region);
        const lines = field.streaks.map(() =>
          this.lines.add({
            positions: [Cesium.Cartesian3.ZERO, Cesium.Cartesian3.ZERO],
            width: isWind ? 1.6 : 2.6,
            material: Cesium.Material.fromType('Color', { color }),
          }),
        );
        sys = { field, lines, vector: v, heightM: isWind ? WIND_HEIGHT_M : CURRENT_HEIGHT_M, trailM: 0 };
        this.flows.set(v.id, sys);
      }
      sys.vector = v;
      sys.field.region = region;
      // Longer streaks for faster flow, so speed reads at a glance even when the motion is paused or small.
      sys.trailM = Math.min(4 + (v.flow?.mps ?? 0) * 0.9, 26);
    }
    this.ensureLoop();
  }

  private regionFor(vectors: SceneVector[]) {
    const n = vectors.length;
    const cx = vectors.reduce((a, v) => a + v.origin.x, 0) / n;
    const cy = vectors.reduce((a, v) => a + v.origin.y, 0) / n;
    return { cx, cy, ...REGION };
  }

  // ---- frame loop ----------------------------------------------------------------------------------------

  /** Request-render mode only draws on demand, so animation keeps its own loop, and only while there is any. */
  private ensureLoop(): void {
    if (this.disposed || this.raf || !this.animated) return;
    if (!this.water && this.flows.size === 0) return;
    this.last = performance.now();
    this.raf = requestAnimationFrame(this.tick);
  }

  private tick = (now: number): void => {
    this.raf = 0;
    if (this.disposed) return;
    const dt = Math.min((now - this.last) / 1000, 0.1);
    this.last = now;
    const t = now / 1000;
    this.pulse = 0.5 + 0.5 * Math.sin(t * 4);
    if (this.waterMaterial) this.waterMaterial.uniforms.time = t % 1000;
    this.stepFlows(dt, t);
    this.viewer.scene.requestRender();
    this.ensureLoop();
  };

  private stepFlows(dt: number, t: number): void {
    const tf = this.tf;
    if (!tf) return;
    for (const sys of this.flows.values()) {
      const v = sys.vector;
      const rad = (v.angleDeg * Math.PI) / 180;
      const dx = Math.cos(rad);
      const dy = Math.sin(rad);
      sys.field.step(dt, dx, dy, flowSpeed(v.flow?.mps ?? 0, v.flow?.gustiness, t));
      sys.field.streaks.forEach((s, i) => {
        sys.lines[i].positions = [
          tf.toWorld(s.x, s.y, sys.heightM),
          tf.toWorld(s.x + dx * sys.trailM, s.y + dy * sys.trailM, sys.heightM),
        ];
      });
    }
  }

  dispose(): void {
    this.disposed = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.removeTileListener?.();
    this.attribution?.remove();
    if (this.viewer.isDestroyed()) return;
    this.clearWater();
    this.viewer.scene.primitives.remove(this.lines);
  }
}
