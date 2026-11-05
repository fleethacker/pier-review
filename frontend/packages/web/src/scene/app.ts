import type { ComponentType } from 'react';
import type { SceneStore } from './store';
import type { SceneEdit } from './types';

/** What the shell gives an application when it starts. */
export interface AppHost {
  store: SceneStore;
}

/** A running application. The shell renders its components in fixed slots and forwards canvas edits to it. */
export interface AppInstance {
  /** Left column: pickers, forms, results. */
  Sidebar?: ComponentType;
  /** Right column: a key or description box for what the canvas shows. */
  Side?: ComponentType;
  /** Bottom strip: timelines, feeds. */
  Bottom?: ComponentType;
  /** Always-visible notices, e.g. the mock-backend banner. */
  Banner?: ComponentType;
  /** Full-screen views the app can open (e.g. the safety sheet) rendered above the canvas. */
  Overlay?: ComponentType;
  onEdit?(edit: SceneEdit): void;
  /** The shell shows one of the app's declared tabs; the app switches its panels to it. */
  setTab?(tabId: string): void;
  /** Tell the shell when the app changes tab by itself (e.g. after saving a transit as a mission). */
  onTabChange?(listener: (tabId: string) => void): () => void;
  dispose(): void;
}

/** One entry in the shell's tab bar. */
export interface AppTab {
  id: string;
  label: string;
}

/** One backend application the shell can drive. Registered once at startup; never imported by the shell itself. */
export interface AppDefinition {
  id: string;
  title: string;
  description: string;
  /** Tabs this app contributes to the shell's tab bar, in order. Without tabs the app is one tab named by its title. */
  tabs?: AppTab[];
  /** The physics and modeling capabilities this application uses, shown on the landing page. */
  physics?: string[];
  start(host: AppHost): Promise<AppInstance> | AppInstance;
}

const apps = new Map<string, AppDefinition>();

export function registerApp(app: AppDefinition): void {
  if (apps.has(app.id)) throw new Error(`App "${app.id}" is already registered`);
  apps.set(app.id, app);
}

export function listApps(): AppDefinition[] {
  return [...apps.values()];
}

export function getApp(id: string): AppDefinition | undefined {
  return apps.get(id);
}

/** Test helper. */
export function clearApps(): void {
  apps.clear();
}
