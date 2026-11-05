import { useSyncExternalStore } from 'react';

/** Minimal external store with selector hooks, in the same style as the shell's SceneStore. */
export class Store<S> {
  private listeners = new Set<() => void>();
  constructor(private state: S) {}
  getState = (): S => this.state;
  setState = (patch: Partial<S> | ((s: S) => Partial<S>)): void => {
    const p = typeof patch === 'function' ? patch(this.state) : patch;
    this.state = { ...this.state, ...p };
    this.listeners.forEach((l) => l());
  };
  subscribe = (l: () => void): (() => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };
}

export function useStore<S, T>(store: Store<S>, selector: (s: S) => T): T {
  return useSyncExternalStore(store.subscribe, () => selector(store.getState()));
}
