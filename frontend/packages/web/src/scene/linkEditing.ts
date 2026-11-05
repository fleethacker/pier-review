import type { SceneEdit, SceneState } from './types';

export type ConnectionEdit = Extract<SceneEdit, { type: 'connect' }>;

/** Capture the selected link at pointer-down; subsequent selection changes cannot retarget this gesture. */
export function beginConnection(state: SceneState, fromEntityId: string): ConnectionEdit | null {
  if (!state.entities[fromEntityId]?.connectable) return null;
  const link = state.selection?.type === 'link' ? state.links[state.selection.id] : undefined;
  const endpoint = link?.editableEndpoints?.from === fromEntityId ? 'from'
    : link?.editableEndpoints?.to === fromEntityId ? 'to' : undefined;
  return { type: 'connect', fromEntityId, toEntityId: null, final: false,
    ...(endpoint && link ? { linkId: link.id, endpoint } : {}) };
}

/** New connections join compatible groups; reconnections replace an endpoint with the same group. */
export function canDropConnection(state: SceneState, edit: ConnectionEdit, targetId: string): boolean {
  const source = state.entities[edit.fromEntityId]?.connectable;
  const target = state.entities[targetId]?.connectable;
  if (!source || !target || targetId === edit.fromEntityId) return false;
  if (edit.linkId) {
    const link = state.links[edit.linkId];
    if (!edit.endpoint || link?.editableEndpoints?.[edit.endpoint] !== edit.fromEntityId) return false;
    const fixedId = link.editableEndpoints[edit.endpoint === 'from' ? 'to' : 'from'];
    const fixed = state.entities[fixedId]?.connectable;
    return source.group === target.group && !!fixed
      && target.accepts.includes(fixed.group) && fixed.accepts.includes(target.group);
  }
  return source.accepts.includes(target.group) && target.accepts.includes(source.group);
}
