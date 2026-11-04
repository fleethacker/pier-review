import { describe, expect, it, vi } from 'vitest';
import { clearApps, getApp, listApps, registerApp } from './app';
import { SceneStore } from './store';
import type { SceneContent, SceneEntity } from './types';

const entity = (id: string, x = 0): SceneEntity => ({
  id,
  kind: 'thing',
  pose: { x, y: 0, z: 0, headingDeg: 0 },
  geometry: { type: 'point', sizePx: 6 },
});

const content = (): SceneContent => ({
  frame: { lonDeg: -76, latDeg: 37, xBearingTrueDeg: 90 },
  entities: [entity('a'), entity('b', 5)],
  links: [{ id: 'l1', kind: 'line', from: { x: 0, y: 0, z: 0 }, to: { entityId: 'b', x: 0, y: 0, z: 0 } }],
  vectors: [],
});

describe('SceneStore', () => {
  it('replaces content, clears selection and bumps the revision', () => {
    const store = new SceneStore();
    store.setContent(content());
    store.select({ type: 'entity', id: 'a' });
    const rev = store.getState().contentRevision;
    store.setContent(content());
    expect(store.getState().selection).toBeNull();
    expect(store.getState().contentRevision).toBe(rev + 1);
    expect(Object.keys(store.getState().entities)).toEqual(['a', 'b']);
  });

  it('moves one entity without touching the others and notifies subscribers', () => {
    const store = new SceneStore();
    store.setContent(content());
    const listener = vi.fn();
    store.subscribe(listener);
    const before = store.getState().entities['a'];
    store.moveEntity('b', { x: 50, y: 0, z: 0, headingDeg: 0 });
    expect(store.getState().entities['b'].pose.x).toBe(50);
    expect(store.getState().entities['a']).toBe(before);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('ignores patches for unknown ids and repeated selections', () => {
    const store = new SceneStore();
    store.setContent(content());
    const listener = vi.fn();
    store.subscribe(listener);
    store.patchEntity('nope', { label: 'x' });
    store.select({ type: 'entity', id: 'a' });
    store.select({ type: 'entity', id: 'a' });
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe('app registry', () => {
  it('registers apps once', () => {
    clearApps();
    const def = { id: 'x', title: 'X', description: '', start: () => ({ dispose() {} }) };
    registerApp(def);
    expect(getApp('x')).toBe(def);
    expect(listApps()).toHaveLength(1);
    expect(() => registerApp(def)).toThrow(/already registered/);
    clearApps();
  });
});
