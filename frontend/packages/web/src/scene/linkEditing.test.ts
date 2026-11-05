import { describe, expect, it } from 'vitest';
import { beginConnection, canDropConnection } from './linkEditing';
import { SceneStore } from './store';
import type { SceneEntity } from './types';

function setup() {
  const store = new SceneStore();
  const endpoint = (id: string, group: string, other: string): SceneEntity => ({ id, kind: 'endpoint',
    pose: { x: 0, y: 0, z: 0, headingDeg: 0 }, geometry: { type: 'point', sizePx: 10 },
    connectable: { group, accepts: [other] } });
  store.setContent({ frame: { latDeg: 0, lonDeg: 0, xBearingTrueDeg: 0 }, entities: [
    endpoint('a1', 'a', 'b'), endpoint('a2', 'a', 'b'), endpoint('b1', 'b', 'a'), endpoint('b2', 'b', 'a')],
  links: [{ id: 'line', kind: 'test', from: { entityId: 'a1', x: 0, y: 0, z: 0 },
    to: { entityId: 'b1', x: 0, y: 0, z: 0 }, editableEndpoints: { from: 'a1', to: 'b1' } }], vectors: [] });
  return store;
}

describe('neutral connection editing', () => {
  it('joins opposite compatible groups only, without mutating the scene', () => {
    const store = setup();
    const state = store.getState();
    const edit = beginConnection(state, 'a1')!;
    expect(canDropConnection(state, edit, 'b1')).toBe(true);
    expect(canDropConnection(state, edit, 'a2')).toBe(false);
    expect(canDropConnection(state, edit, 'missing')).toBe(false);
    expect(beginConnection(state, 'missing')).toBeNull();
    expect(store.getState()).toBe(state);
  });

  it('reconnects only the selected endpoint and rejects stale endpoints', () => {
    const store = setup();
    store.select({ type: 'link', id: 'line' });
    const edit = beginConnection(store.getState(), 'a1')!;
    expect(edit).toMatchObject({ linkId: 'line', endpoint: 'from' });
    expect(canDropConnection(store.getState(), edit, 'a2')).toBe(true);
    expect(canDropConnection(store.getState(), edit, 'b2')).toBe(false);
    store.patchLink('line', { editableEndpoints: { from: 'a2', to: 'b1' } });
    expect(canDropConnection(store.getState(), edit, 'a2')).toBe(false);
  });
});
