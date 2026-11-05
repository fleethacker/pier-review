import { useSyncExternalStore } from 'react';
import type {
  Pose,
  SceneContent,
  SceneEntity,
  SceneLink,
  SceneState,
  SceneVector,
  CameraPreset,
  Lighting,
  Selection,
  ViewMode,
} from './types';

type Listener = () => void;

const LIGHTING_KEY = 'scene-lighting';

function loadLighting(): Lighting {
  try {
    return localStorage.getItem(LIGHTING_KEY) === 'day' ? 'day' : 'night';
  } catch {
    return 'night';
  }
}

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
    lighting: loadLighting(),
    contentRevision: 0,
    fitRevision: 0,
    cameraPreset: null,
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

  /** Swap every entity of the given kinds for a new set (e.g. tugs that were added or removed). */
  replaceEntitiesOfKind(kinds: string[], entities: SceneEntity[]): void {
    const kept = Object.values(this.state.entities).filter((e) => !kinds.includes(e.kind));
    this.set({ entities: index([...kept, ...entities]) });
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

  setCameraPreset(name: CameraPreset, target?: { x: number; y: number }): void {
    this.set({ cameraPreset: { name, target, revision: (this.state.cameraPreset?.revision ?? 0) + 1 } });
  }

  requestFit(): void {
    this.set({ fitRevision: this.state.fitRevision + 1 });
  }

  /** Set by the renderer: returns a JPEG data URL of the current view, or null before the canvas exists. */
  capture: () => string | null = () => null;

  setLighting(lighting: Lighting): void {
    if (lighting === this.state.lighting) return;
    this.set({ lighting });
    try {
      localStorage.setItem(LIGHTING_KEY, lighting);
    } catch {
      // Storage can be blocked; the choice still applies for this session.
    }
  }

  setViewMode(viewMode: ViewMode): void {
    if (viewMode !== this.state.viewMode) this.set({ viewMode });
  }
}

export function useScene<T>(store: SceneStore, selector: (s: SceneState) => T): T {
  return useSyncExternalStore(store.subscribe, () => selector(store.getState()));
}
