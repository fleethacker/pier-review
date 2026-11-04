import * as Cesium from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { constrainMove, entityToFrame, resolveAnchor, sceneBounds } from '../../scene/geometry';
import type { SceneStore } from '../../scene/store';
import type { SceneEdit, SceneEntity, SceneLink, SceneState, SceneVector } from '../../scene/types';
import { COLORS, STATUS_COLOR, colorFor } from '../theme';
import { SceneEffects } from './effects';
import { FrameTransform } from './frameTransform';
import { ViewController } from './viewController';

const MAX_GEOMETRY_WAIT_MS = 20000;
const KICK_INTERVAL_MS = 100;
const FONT = '11px "JetBrains Mono", monospace';
const css = (c: string) => Cesium.Color.fromCssColorString(c);

interface Drag {
  entityId: string;
  startPose: SceneEntity['pose'];
  grab: [number, number];
  moved: boolean;
}

/** Draws a SceneStore with Cesium and turns pointer input into selection, drags and camera moves. */
export class SceneRenderer {
  readonly view: ViewController;
  private effects: SceneEffects;
  private viewer: Cesium.Viewer;
  private tf: FrameTransform | null = null;
  private cache = new Map<string, { src: unknown; entity: Cesium.Entity; geomSig: string }>();
  private unsubscribe: () => void;
  private lastState: SceneState | null = null;
  private lastContentRevision = -1;
  private lastFitRevision = 0;
  private hoverId: string | null = null;
  private drag: Drag | null = null;
  private pan: { lastX: number; lastY: number; button: number } | null = null;
  private pointerDown: { x: number; y: number; id: string | null } | null = null;
  private disposed = false;
  private kicking = false;
  private kickUntil = 0;

  constructor(
    container: HTMLElement,
    private store: SceneStore,
    private onEdit: (edit: SceneEdit) => void,
    private onViewChangeCb: (screenUpBearingDeg: number) => void,
  ) {
    this.viewer = new Cesium.Viewer(container, {
      baseLayer: false,
      baseLayerPicker: false,
      geocoder: false,
      timeline: false,
      animation: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: false,
      requestRenderMode: true,
      maximumRenderTimeChange: Infinity,
      contextOptions: { webgl: { preserveDrawingBuffer: true } },
    });
    this.view = new ViewController(this.viewer.camera, () => this.viewer.scene.requestRender());
    if (!(typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches)) this.view.playIntro();
    this.effects = new SceneEffects(this.viewer, container);

    this.configureScene();
    this.installInput();
    this.store.capture = () => {
      this.viewer.render();
      return this.viewer.scene.canvas.toDataURL('image/jpeg', 0.92);
    };
    this.unsubscribe = this.store.subscribe(() => this.sync());
    this.sync();
  }

  /**
   * Request-render mode only draws on demand, but entity geometry is built asynchronously in workers. Keep asking
   * for frames for a moment after every change so late-finishing geometry appears without needing a mouse move.
   */
  private kick(): void {
    this.kickUntil = performance.now() + 1500;
    if (this.kicking) return;
    this.kicking = true;
    const tick = () => {
      if (this.disposed) return;
      this.viewer.scene.requestRender();
      const now = performance.now();
      const buildingGeometry = !this.viewer.dataSourceDisplay.ready && now < this.kickUntil + MAX_GEOMETRY_WAIT_MS;
      if (now < this.kickUntil || buildingGeometry) setTimeout(tick, KICK_INTERVAL_MS);
      else this.kicking = false;
    };
    tick();
  }

  /** Window coordinates (CSS px, relative to the page) of an entity's anchor point; for tests and tooling. */
  screenPositionOf(entityId: string): { x: number; y: number } | null {
    const e = this.store.getState().entities[entityId];
    if (!e || !this.tf) return null;
    const world = this.tf.toWorld(e.pose.x, e.pose.y, e.pose.z);
    const pt = Cesium.SceneTransforms.worldToWindowCoordinates(this.viewer.scene, world);
    if (!pt) return null;
    const rect = this.viewer.scene.canvas.getBoundingClientRect();
    return { x: rect.left + pt.x, y: rect.top + pt.y };
  }

  /** True once every entity's geometry is built; for tests and tooling. */
  get geometryReady(): boolean {
    return this.viewer.dataSourceDisplay.ready;
  }

  /** Id of the scene item under a page coordinate; for tests and tooling. */
  pickAtPage(x: number, y: number): string | null {
    return this.pickId(this.canvasPoint({ clientX: x, clientY: y }));
  }

  private onViewChange(): void {
    this.onViewChangeCb(this.view.screenUpBearingDeg);
  }

  dispose(): void {
    this.disposed = true;
    this.unsubscribe();
    this.effects.dispose();
    this.store.capture = () => null;
    this.viewer.destroy();
  }

  private configureScene(): void {
    const scene = this.viewer.scene;
    scene.globe.baseColor = css(COLORS.water);
    scene.globe.showGroundAtmosphere = false;
    scene.globe.enableLighting = false;
    scene.globe.depthTestAgainstTerrain = false;
    if (scene.skyAtmosphere) scene.skyAtmosphere.show = false;
    if (scene.skyBox) scene.skyBox.show = false;
    if (scene.sun) scene.sun.show = false;
    if (scene.moon) scene.moon.show = false;
    scene.fog.enabled = false;
    scene.backgroundColor = css(COLORS.background);
    scene.screenSpaceCameraController.enableInputs = false;
    scene.postProcessStages.fxaa.enabled = true;
    // Fixed, even light so shading does not depend on the time of day.
    scene.light = new Cesium.DirectionalLight({ direction: new Cesium.Cartesian3(0.3, 0.2, -1) });
    (this.viewer.cesiumWidget.creditContainer as HTMLElement).style.display = 'none';
  }

  // ---- scene sync ----------------------------------------------------------------------------------------

  private sync(): void {
    if (this.disposed) return;
    const state = this.store.getState();
    const prev = this.lastState;
    this.lastState = state;

    if (state.frame && (!prev || prev.frame !== state.frame)) {
      this.tf = new FrameTransform(state.frame);
      this.view.setFrame(this.tf);
      this.effects.setFrame(this.tf);
      if (prev?.frame && !(typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches)) this.view.playIntro();
      this.clearEntities();
    }
    if (!state.frame || !this.tf) {
      this.clearEntities();
      this.kick();
      return;
    }

    const selectedId = state.selection ? this.keyFor(state.selection.type, state.selection.id) : null;
    const prevSelectedId = prev?.selection ? this.keyFor(prev.selection.type, prev.selection.id) : null;

    const seen = new Set<string>();
    for (const e of Object.values(state.entities)) {
      const key = this.keyFor('entity', e.id);
      seen.add(key);
      const cached = this.cache.get(key);
      const dirty = !cached || cached.src !== e || key === selectedId || key === prevSelectedId;
      if (dirty) this.upsert(key, e, this.renderEntity(e, key === selectedId, key === this.hoverId));
    }
    // Links depend on entity poses, so rebuild them whenever anything changed.
    for (const l of Object.values(state.links)) {
      const key = this.keyFor('link', l.id);
      seen.add(key);
      this.upsert(key, null, this.renderLink(l, state, key === selectedId));
    }
    for (const v of Object.values(state.vectors)) {
      const key = `v:${v.id}`;
      seen.add(key);
      const cached = this.cache.get(key);
      if (!cached || cached.src !== v) this.upsert(key, v, this.renderVector(v));
    }
    if (!prev || prev.vectors !== state.vectors) this.effects.setVectors(Object.values(state.vectors));
    for (const key of [...this.cache.keys()]) {
      if (!seen.has(key)) {
        this.viewer.entities.remove(this.cache.get(key)!.entity);
        this.cache.delete(key);
      }
    }

    if (state.contentRevision !== this.lastContentRevision || state.fitRevision !== this.lastFitRevision) {
      this.lastContentRevision = state.contentRevision;
      this.lastFitRevision = state.fitRevision;
      this.fit(state);
    }
    if (!prev || prev.lighting !== state.lighting) this.effects.setLighting(state.lighting);
    if (!prev || prev.viewMode !== state.viewMode) {
      this.view.setMode(state.viewMode);
      this.onViewChange();
    }
    this.kick();
  }

  private fit(state: SceneState): void {
    const canvas = this.viewer.scene.canvas;
    const aspect = canvas.clientWidth / Math.max(canvas.clientHeight, 1);
    const bounds = sceneBounds(Object.values(state.entities));
    this.effects.setBounds(bounds);
    this.view.fit(bounds, aspect);
    this.view.setMode(state.viewMode);
    this.onViewChange();
  }

  private keyFor(type: 'entity' | 'link', id: string): string {
    return type === 'entity' ? `e:${id}` : `l:${id}`;
  }

  private clearEntities(): void {
    this.viewer.entities.removeAll();
    this.cache.clear();
  }

  /**
   * Create the Cesium entity, or patch it in place. Removing and re-adding on every change would leave picking
   * briefly blind (the pick buffer is only rebuilt on the next frame), so only changed fields are assigned and
   * geometry is rebuilt only when its coordinates changed.
   */
  private upsert(key: string, src: unknown, built: Cesium.Entity.ConstructorOptions): void {
    const geomSig = geometrySignature(built);
    const cached = this.cache.get(key);
    if (!cached) {
      const entity = this.viewer.entities.add({ ...built, id: key });
      this.cache.set(key, { src, entity, geomSig });
      return;
    }
    const entity = cached.entity as unknown as Record<string, Record<string, unknown> | undefined>;
    for (const gfx of ['polygon', 'point', 'polyline', 'label'] as const) {
      const next = (built as Record<string, Record<string, unknown> | undefined>)[gfx];
      if (!next) {
        if (entity[gfx]) (cached.entity as unknown as Record<string, unknown>)[gfx] = undefined;
        continue;
      }
      const target = entity[gfx];
      if (!target) {
        (cached.entity as unknown as Record<string, unknown>)[gfx] = next;
        continue;
      }
      for (const [field, value] of Object.entries(next)) {
        if (geomSig === cached.geomSig && GEOMETRY_FIELDS.has(field)) continue;
        target[field] = value;
      }
    }
    if (built.position && cached.geomSig !== geomSig) cached.entity.position = built.position as never;
    else if (built.position && !cached.entity.position) cached.entity.position = built.position as never;
    cached.src = src;
    cached.geomSig = geomSig;
  }

  private renderEntity(e: SceneEntity, selected: boolean, hovered: boolean): Cesium.Entity.ConstructorOptions {
    const tf = this.tf!;
    const base = colorFor(e.status, e.color ?? '#6f8fb3');
    const fill = css(base).withAlpha(e.opacity ?? 1);
    const outline = css(selected ? COLORS.selection : hovered ? '#ffffff' : '#0a1628');
    const [cx, cy, cz] = entityToFrame(e.pose, 0, 0, 0);
    const options: Cesium.Entity.ConstructorOptions = {};

    if (e.geometry.type === 'polygon') {
      const positions = e.geometry.points.map(([px, py]) => {
        const [x, y] = entityToFrame(e.pose, px, py);
        return tf.toWorld(x, y, e.pose.z);
      });
      options.polygon = {
        hierarchy: positions,
        height: e.pose.z,
        extrudedHeight: e.geometry.heightM > 0 ? e.pose.z + e.geometry.heightM : undefined,
        material: fill,
        outline: !e.noOutline,
        outlineColor: outline,
        outlineWidth: 2,
      };
    } else {
      options.position = tf.toWorld(cx, cy, cz);
      options.point = {
        pixelSize: e.geometry.sizePx + (selected || hovered ? 4 : 0),
        color: fill,
        outlineColor: outline,
        outlineWidth: selected ? 3 : 1.5,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      };
    }

    const showLabel = e.label && (e.geometry.type === 'polygon' || e.labelAlways || selected || hovered);
    if (showLabel) {
      let [lx, ly] = [cx, cy];
      if (e.geometry.type === 'polygon' && e.geometry.points.length > 0) {
        const pts = e.geometry.points;
        const mx = pts.reduce((a, p) => a + p[0], 0) / pts.length;
        const my = pts.reduce((a, p) => a + p[1], 0) / pts.length;
        [lx, ly] = entityToFrame(e.pose, mx, my);
      }
      options.position = tf.toWorld(lx, ly, cz + (e.geometry.type === 'polygon' ? e.geometry.heightM : 0));
      options.label = {
        text: e.label,
        font: FONT,
        fillColor: e.labelAlways ? css(base) : css(COLORS.text),
        outlineColor: css(COLORS.background),
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, e.geometry.type === 'point' ? -16 : 0),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      };
    }
    return options;
  }

  private renderLink(l: SceneLink, state: SceneState, selected: boolean): Cesium.Entity.ConstructorOptions {
    const tf = this.tf!;
    const a = resolveAnchor(l.from, state.entities);
    const b = resolveAnchor(l.to, state.entities);
    if (!a || !b) return {};
    const color = css(colorFor(l.status, l.color ?? '#c9d6e6'));
    // Sag like a real line: a shallow curve, never dipping below the water. Over-limit lines pulse.
    const horiz = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const midZ = (a[2] + b[2]) / 2;
    const sag = Math.max(Math.min(0.04 * horiz, 3.5, midZ - 0.5), 0);
    const SAMPLES = 14;
    const positions = Array.from({ length: SAMPLES }, (_, i) => {
      const t = i / (SAMPLES - 1);
      return tf.toWorld(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t - sag * 4 * t * (1 - t));
    });
    const pulsing = this.effects.animated && l.status === 'RED';
    const glowColor = pulsing
      ? new Cesium.CallbackProperty(() => color.withAlpha(0.5 + 0.5 * this.effects.pulse), false)
      : color;
    const options: Cesium.Entity.ConstructorOptions = {
      polyline: {
        positions,
        width: (l.widthPx ?? 3) + 5 + (selected ? 3 : 0),
        material: new Cesium.PolylineGlowMaterialProperty({ color: glowColor, glowPower: selected ? 0.4 : pulsing ? 0.35 : 0.22 }),
        arcType: Cesium.ArcType.NONE,
      },
    };
    if (l.label) {
      options.position = tf.toWorld((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2);
      options.label = {
        text: l.label,
        font: FONT,
        fillColor: css(COLORS.text),
        outlineColor: css(COLORS.background),
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -10),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      };
    }
    return options;
  }

  private renderVector(v: SceneVector): Cesium.Entity.ConstructorOptions {
    const tf = this.tf!;
    const rad = (v.angleDeg * Math.PI) / 180;
    const end: [number, number] = [
      v.origin.x + Math.cos(rad) * v.lengthM,
      v.origin.y + Math.sin(rad) * v.lengthM,
    ];
    const color = css(v.color ?? STATUS_COLOR.NONE);
    const options: Cesium.Entity.ConstructorOptions = {
      polyline: {
        positions: [tf.toWorld(v.origin.x, v.origin.y, v.origin.z), tf.toWorld(end[0], end[1], v.origin.z)],
        width: 14,
        material: new Cesium.PolylineArrowMaterialProperty(color),
        arcType: Cesium.ArcType.NONE,
      },
    };
    if (v.label) {
      options.position = tf.toWorld((v.origin.x + end[0]) / 2, (v.origin.y + end[1]) / 2, v.origin.z);
      options.label = {
        text: v.label,
        font: FONT,
        fillColor: color,
        outlineColor: css(COLORS.background),
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
        pixelOffset: new Cesium.Cartesian2(14, 0),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      };
    }
    return options;
  }

  // ---- input -----------------------------------------------------------------------------------------------

  private canvasPoint(ev: { clientX: number; clientY: number }): Cesium.Cartesian2 {
    const rect = this.viewer.scene.canvas.getBoundingClientRect();
    return new Cesium.Cartesian2(ev.clientX - rect.left, ev.clientY - rect.top);
  }

  private ground(pos: Cesium.Cartesian2): [number, number] | null {
    return this.tf ? this.tf.groundPoint(this.viewer.camera.getPickRay(pos)) : null;
  }

  private pickId(pos: Cesium.Cartesian2): string | null {
    const picked = this.viewer.scene.pick(pos);
    const id = picked?.id instanceof Cesium.Entity ? picked.id.id : null;
    return id && (id.startsWith('e:') || id.startsWith('l:')) ? id : null;
  }

  private installInput(): void {
    const canvas = this.viewer.scene.canvas;
    canvas.addEventListener('pointerdown', this.onPointerDown);
    canvas.addEventListener('pointermove', this.onPointerMove);
    canvas.addEventListener('pointerup', this.onPointerUp);
    canvas.addEventListener('pointercancel', this.onPointerUp);
    canvas.addEventListener('wheel', this.onWheel, { passive: false });
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  private onPointerDown = (ev: PointerEvent): void => {
    const canvas = this.viewer.scene.canvas;
    canvas.setPointerCapture(ev.pointerId);
    const pos = this.canvasPoint(ev);
    const id = this.pickId(pos);
    this.pointerDown = { x: ev.clientX, y: ev.clientY, id };
    const state = this.store.getState();

    if (ev.button === 0 && id?.startsWith('e:')) {
      const entity = this.resolveEntity(id.slice(2), state);
      if (entity?.editable) {
        const grab = this.ground(pos);
        if (grab) {
          this.drag = { entityId: entity.id, startPose: entity.pose, grab, moved: false };
          return;
        }
      }
    }
    this.pan = { lastX: ev.clientX, lastY: ev.clientY, button: ev.button };
  };

  private onPointerMove = (ev: PointerEvent): void => {
    const pos = this.canvasPoint(ev);
    const state = this.store.getState();

    if (this.drag) {
      const entity = state.entities[this.drag.entityId];
      const g = this.ground(pos);
      if (!entity?.editable || !g) return;
      const p = this.drag.startPose;
      const want = { x: p.x + (g[0] - this.drag.grab[0]), y: p.y + (g[1] - this.drag.grab[1]) };
      const { x, y } = constrainMove(want, p, entity.editable);
      this.drag.moved = true;
      const pose = { ...p, x, y };
      this.store.moveEntity(entity.id, pose);
      this.onEdit({ type: 'move', entityId: entity.id, pose, final: false });
      return;
    }

    if (this.pan) {
      const dx = ev.clientX - this.pan.lastX;
      const dy = ev.clientY - this.pan.lastY;
      this.pan.lastX = ev.clientX;
      this.pan.lastY = ev.clientY;
      const orbit = this.view.mode === '3d' && this.pan.button === 0;
      if (orbit) {
        this.view.orbit(dx, dy);
      } else {
        const before = this.ground(new Cesium.Cartesian2(ev.clientX - dx - this.rectLeft(), ev.clientY - dy - this.rectTop()));
        const after = this.ground(pos);
        if (before && after) this.view.panBy(before[0] - after[0], before[1] - after[1]);
      }
      this.kick();
      this.onViewChange();
      return;
    }

    const id = this.pickId(pos);
    if (id !== this.hoverId) {
      const prevId = this.hoverId;
      this.hoverId = id;
      this.refreshEntity(prevId);
      this.refreshEntity(id);
      const hit = id?.startsWith('e:') ? state.entities[id.slice(2)] : id?.startsWith('l:') ? state.links[id.slice(2)] : null;
      const interactive = !!hit && ('editable' in hit ? !!hit.editable || !!hit.selectable : !!hit.selectable);
      this.viewer.scene.canvas.style.cursor = interactive ? (hit && 'editable' in hit && hit.editable ? 'grab' : 'pointer') : 'default';
    }
  };

  private onPointerUp = (ev: PointerEvent): void => {
    const canvas = this.viewer.scene.canvas;
    if (canvas.hasPointerCapture(ev.pointerId)) canvas.releasePointerCapture(ev.pointerId);
    const down = this.pointerDown;
    const clicked = down && Math.hypot(ev.clientX - down.x, ev.clientY - down.y) < 4;

    if (this.drag) {
      const d = this.drag;
      this.drag = null;
      const entity = this.store.getState().entities[d.entityId];
      if (entity && d.moved) this.onEdit({ type: 'move', entityId: entity.id, pose: entity.pose, final: true });
      if (!d.moved) this.store.select({ type: 'entity', id: d.entityId });
    } else if (clicked && ev.button === 0) {
      const state = this.store.getState();
      const id = down!.id;
      const target = id?.startsWith('e:') ? this.resolveEntity(id.slice(2), state) : undefined;
      if (target && target.selectable !== false) {
        this.store.select({ type: 'entity', id: target.id });
      } else if (id?.startsWith('l:') && state.links[id.slice(2)]?.selectable !== false) {
        this.store.select({ type: 'link', id: id.slice(2) });
      } else {
        this.store.select(null);
      }
    }
    this.pan = null;
    this.pointerDown = null;
  };

  private onWheel = (ev: WheelEvent): void => {
    ev.preventDefault();
    const pos = this.canvasPoint(ev);
    const before = this.ground(pos);
    this.view.zoomBy(Math.exp(ev.deltaY * 0.0012));
    const after = this.ground(pos);
    if (before && after && this.view.mode === '2d') this.view.panBy(before[0] - after[0], before[1] - after[1]);
    this.kick();
    this.onViewChange();
  };

  /** An entity that stands in for another (selectsId) resolves to that other entity. */
  private resolveEntity(id: string, state: SceneState): SceneEntity | undefined {
    const e = state.entities[id];
    return e?.selectsId ? state.entities[e.selectsId] ?? e : e;
  }

  private rectLeft(): number {
    return this.viewer.scene.canvas.getBoundingClientRect().left;
  }
  private rectTop(): number {
    return this.viewer.scene.canvas.getBoundingClientRect().top;
  }

  private refreshEntity(key: string | null): void {
    if (!key || !key.startsWith('e:') || !this.lastState) return;
    const e = this.lastState.entities[key.slice(2)];
    if (!e) return;
    const sel = this.lastState.selection;
    this.upsert(key, e, this.renderEntity(e, sel?.type === 'entity' && sel.id === e.id, key === this.hoverId));
    this.kick();
  }
}

const GEOMETRY_FIELDS = new Set(['hierarchy', 'positions', 'height', 'extrudedHeight']);

/** Cheap fingerprint of everything that decides a shape's coordinates, so unchanged shapes are not rebuilt. */
function geometrySignature(o: Cesium.Entity.ConstructorOptions): string {
  const parts: string[] = [];
  const pos = (v: unknown) => (v instanceof Cesium.Cartesian3 ? `${v.x.toFixed(2)},${v.y.toFixed(2)},${v.z.toFixed(2)}` : '');
  const polygon = o.polygon as { hierarchy?: unknown; height?: number; extrudedHeight?: number } | undefined;
  const polyline = o.polyline as { positions?: unknown } | undefined;
  if (polygon && Array.isArray(polygon.hierarchy)) parts.push(polygon.hierarchy.map(pos).join(';'), String(polygon.height), String(polygon.extrudedHeight));
  if (polyline && Array.isArray(polyline.positions)) parts.push(polyline.positions.map(pos).join(';'));
  if (o.position) parts.push(pos(o.position));
  return parts.join('|');
}
