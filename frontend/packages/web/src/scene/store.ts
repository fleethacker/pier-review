import { useSyncExternalStore } from 'react';
import type {
  Pose,
  SceneContent,
  SceneEntity,
  SceneLink,
  SceneState,
  SceneVector,
  Selection,
  ViewMode,
} from './types';

type Listener = () => void;

function index<T extends { id: string }>(items: T[]): Record<string, T> {
  return Object.fromEntries(items.map((i) => [i.id, i]));
}

export class SceneStore {
  private state: SceneState = {
    frame: null,
    entities: {},
    links: {},
    vectors: {},
    selection: null,
    viewMode: '2d',
    contentRevision: 0,
    fitRevision: 0,
  };
  private listeners = new Set<Listener>();

  getState = (): SceneState => this.state;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private set(patch: Partial<SceneState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l());
  }

  /** Replace everything (new berth, new app). Clears selection and asks the shell to refit the view. */
  setContent(content: SceneContent): void {
    this.set({
      frame: content.frame,
      entities: index(content.entities),
      links: index(content.links),
      vectors: index(content.vectors),
      selection: null,
      contentRevision: this.state.contentRevision + 1,
    });
  }

  clear(): void {
    this.set({
      frame: null,
      entities: {},
      links: {},
      vectors: {},
      selection: null,
      contentRevision: this.state.contentRevision + 1,
    });
  }

  upsertEntities(entities: SceneEntity[]): void {
    this.set({ entities: { ...this.state.entities, ...index(entities) } });
  }

  patchEntity(id: string, patch: Partial<SceneEntity>): void {
    const current = this.state.entities[id];
    if (!current) return;
    this.set({ entities: { ...this.state.entities, [id]: { ...current, ...patch } } });
  }

  moveEntity(id: string, pose: Pose): void {
    this.patchEntity(id, { pose });
  }

  setLinks(links: SceneLink[]): void {
    this.set({ links: index(links) });
  }

  patchLink(id: string, patch: Partial<SceneLink>): void {
    const current = this.state.links[id];
    if (!current) return;
    this.set({ links: { ...this.state.links, [id]: { ...current, ...patch } } });
  }

  setVectors(vectors: SceneVector[]): void {
    this.set({ vectors: index(vectors) });
  }

  select(selection: Selection): void {
    const cur = this.state.selection;
    if (cur?.id === selection?.id && cur?.type === selection?.type) return;
    this.set({ selection });
  }

  requestFit(): void {
    this.set({ fitRevision: this.state.fitRevision + 1 });
  }

  /** Set by the renderer: returns a PNG data URL of the current view, or null before the canvas exists. */
  capture: () => string | null = () => null;

  setViewMode(viewMode: ViewMode): void {
    if (viewMode !== this.state.viewMode) this.set({ viewMode });
  }
}

export function useScene<T>(store: SceneStore, selector: (s: SceneState) => T): T {
  return useSyncExternalStore(store.subscribe, () => selector(store.getState()));
}
