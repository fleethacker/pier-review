// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as Cesium from 'cesium';
import { SceneStore } from '../../scene/store';
import type { SceneEdit, SceneEntity } from '../../scene/types';

// Keep actual Cesium entities/materials, replacing only the WebGL view and screen projection.
vi.mock('cesium', async (original) => {
  const actual = await original<typeof import('cesium')>();
  return { ...actual, Viewer: class {
    entities = new actual.EntityCollection();
    dataSourceDisplay = { ready: true };
    camera = { getPickRay: (point: { x: number; y: number }) => point };
    cesiumWidget = { creditContainer: document.createElement('div') };
    scene;
    constructor(container: HTMLElement) {
      const canvas = document.createElement('canvas');
      container.appendChild(canvas);
      canvas.setPointerCapture = vi.fn();
      canvas.hasPointerCapture = () => false;
      canvas.releasePointerCapture = vi.fn();
      canvas.getBoundingClientRect = () => ({ left: 0, top: 0, right: 600, bottom: 400, width: 600, height: 400, x: 0, y: 0, toJSON: () => ({}) });
      this.scene = { canvas, requestRender: vi.fn(), globe: {}, fog: {}, screenSpaceCameraController: {},
        postProcessStages: { fxaa: {} }, pick: () => ({ id: new actual.Entity({ id: 'e:ship' }) }) };
    }
    destroy() {}
  } };
});
vi.mock('./viewController', () => ({ ViewController: class {
  mode = '2d'; screenUpBearingDeg = 0;
  playIntro() {} setFrame() {} fit() {} setMode() {} setPreset() {} panBy() {} orbit() {}
} }));
vi.mock('./effects', () => ({ SceneEffects: class {
  animated = false;
  setFrame() {} setVectors() {} setBounds() {} setLighting() {} dispose() {}
} }));
vi.mock('./frameTransform', () => ({ FrameTransform: class {
  toWorld(x: number, y: number, z: number) { return new Cesium.Cartesian3(x, y, z); }
  groundPoint(point: { x: number; y: number }) { return [point.x, point.y]; }
} }));

import { SceneRenderer } from './SceneRenderer';

const dispose: (() => void)[] = [];
afterEach(() => { dispose.splice(0).forEach((fn) => fn()); vi.useRealTimers(); });

function setup() {
  vi.useFakeTimers();
  const endpoint = (id: string, group: string, x: number, y: number): SceneEntity => ({ id, kind: 'fitting',
    pose: { x, y, z: 5, headingDeg: 0 }, geometry: { type: 'point', sizePx: 10 },
    connectable: { group, accepts: [group === 'a' ? 'b' : 'a'] } });
  const store = new SceneStore();
  store.setContent({ frame: { lonDeg: 0, latDeg: 0, xBearingTrueDeg: 90 }, entities: [
    { id: 'ship', kind: 'ship', pose: { x: 200, y: 200, z: 0, headingDeg: 0 }, geometry: { type: 'point', sizePx: 20 },
      editable: { moveAxis: 'xy', bounds: { minX: 0, maxX: 500, minY: 30 } } },
    endpoint('a1', 'a', 50, 50), endpoint('a2', 'a', 150, 50), endpoint('b1', 'b', 50, 150), endpoint('b2', 'b', 150, 150),
  ], links: [{ id: 'line', kind: 'link', from: { entityId: 'a1', x: 0, y: 0, z: 0 },
    to: { entityId: 'b1', x: 0, y: 0, z: 0 }, editableEndpoints: { from: 'a1', to: 'b1' } }], vectors: [] });
  const container = document.createElement('div');
  const edits: SceneEdit[] = [];
  const renderer = new SceneRenderer(container, store, (e) => edits.push(e), () => {});
  vi.spyOn(renderer, 'screenPositionOf').mockImplementation((id) => store.getState().entities[id]?.pose ?? null);
  dispose.push(() => renderer.dispose());
  const canvas = container.querySelector('canvas')!;
  const pointer = (type: string, x: number, y: number) => {
    const event = new MouseEvent(type, { clientX: x, clientY: y, button: 0, bubbles: true });
    Object.defineProperty(event, 'pointerId', { value: 1 });
    canvas.dispatchEvent(event);
  };
  return { store, pointer, edits, canvas, renderer };
}

describe('canvas pointer gestures', () => {
  it('moves both axes and commits only on release', () => {
    const { pointer, edits, store } = setup();
    pointer('pointerdown', 250, 200);
    pointer('pointermove', 290, 230);
    expect(store.getState().entities.ship.pose).toMatchObject({ x: 240, y: 230 });
    expect(edits.at(-1)).toMatchObject({ type: 'move', final: false });
    pointer('pointerup', 290, 230);
    expect(edits.at(-1)).toMatchObject({ type: 'move', final: true, pose: { x: 240, y: 230 } });
  });

  it.each(['pointercancel', 'escape'])('restores geometry on %s without a committed edit', (cancel) => {
    const { pointer, edits, store } = setup();
    pointer('pointerdown', 250, 200);
    pointer('pointermove', 290, 230);
    if (cancel === 'escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    else pointer('pointercancel', 290, 230);
    expect(store.getState().entities.ship.pose).toMatchObject({ x: 200, y: 200 });
    expect(edits.at(-1)).toMatchObject({ type: 'move', final: true, cancelled: true });
    pointer('pointerup', 290, 230);
    expect(edits).toHaveLength(2);
  });

  it('snaps a connection to the nearest compatible fitting and retains click selection', () => {
    const { pointer, edits, store } = setup();
    pointer('pointerdown', 50, 50);
    pointer('pointermove', 58, 151);
    expect(edits).toEqual([{ type: 'connect', fromEntityId: 'a1', toEntityId: null, final: false }]);
    pointer('pointerup', 58, 151);
    expect(edits.at(-1)).toMatchObject({ type: 'connect', fromEntityId: 'a1', toEntityId: 'b1', final: true, cancelled: false });
    pointer('pointerdown', 150, 50);
    pointer('pointerup', 150, 50);
    expect(store.getState().selection).toEqual({ type: 'entity', id: 'a2' });
    expect(edits).toHaveLength(2);
  });

  it('reconnects the chosen line endpoint, never another line', () => {
    const { pointer, edits, store } = setup();
    store.select({ type: 'link', id: 'line' });
    pointer('pointerdown', 50, 150);
    pointer('pointermove', 150, 150);
    pointer('pointerup', 150, 150);
    expect(edits.at(-1)).toMatchObject({ type: 'connect', linkId: 'line', endpoint: 'to',
      fromEntityId: 'b1', toEntityId: 'b2', final: true });
  });

  it.each([[150, 50], [700, 450]])('cancels a drop at invalid or outside-canvas position (%s, %s)', (x, y) => {
    const { pointer, edits } = setup();
    pointer('pointerdown', 50, 50);
    pointer('pointermove', x, y);
    pointer('pointerup', x, y);
    expect(edits.at(-1)).toMatchObject({ type: 'connect', toEntityId: null, final: true, cancelled: true });
  });

  it('discards an unfinished gesture when the scene is replaced', () => {
    const { pointer, edits, store } = setup();
    pointer('pointerdown', 250, 200);
    pointer('pointermove', 290, 230);
    store.clear();
    pointer('pointerup', 290, 230);
    expect(edits).toHaveLength(1);
  });
});

it('cancels a connection and pointer capture before handing the viewer to another app', () => {
  const { pointer, edits, canvas, renderer } = setup();
  canvas.hasPointerCapture = () => true;
  pointer('pointerdown', 50, 50);
  pointer('pointermove', 50, 150);
  expect(edits).toHaveLength(1);
  const replacement = new SceneStore();
  replacement.setContent({ frame: { lonDeg: 0, latDeg: 0, xBearingTrueDeg: 90 }, entities: [], links: [], vectors: [] });
  renderer.setStore(replacement);
  expect(canvas.releasePointerCapture).toHaveBeenCalledWith(1);
  pointer('pointerup', 50, 150);
  expect(edits).toHaveLength(1);
  pointer('pointerdown', 200, 200);
  expect(canvas.setPointerCapture).toHaveBeenCalledTimes(2);
  pointer('pointerup', 200, 200);
});
