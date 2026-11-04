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
  /** Bottom strip: timelines, feeds. */
  Bottom?: ComponentType;
  /** Always-visible notices, e.g. the mock-backend banner. */
  Banner?: ComponentType;
  /** Full-screen views the app can open (e.g. the safety sheet) rendered above the canvas. */
  Overlay?: ComponentType;
  onEdit?(edit: SceneEdit): void;
  dispose(): void;
}

/** One backend application the shell can drive. Registered once at startup; never imported by the shell itself. */
export interface AppDefinition {
  id: string;
  title: string;
  description: string;
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
