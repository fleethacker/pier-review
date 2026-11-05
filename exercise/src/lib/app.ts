import type { ComponentType } from 'react';

/** What the chrome gives the application when it starts. Nothing yet: the exercise app owns all of its own state. */
export type AppHost = Record<string, never>;

/** A running application. The chrome renders its components in fixed slots. */
export interface AppInstance {
  /** Centre column: the map. */
  Canvas?: ComponentType;
  /** Left column: pickers, forms, results. */
  Sidebar?: ComponentType;
  /** Right column: a key for what the canvas shows. */
  Side?: ComponentType;
  /** Bottom strip: the timeline. */
  Bottom?: ComponentType;
  /** Always-visible notices. */
  Banner?: ComponentType;
  /** Full-screen views the app can open, rendered above the canvas. */
  Overlay?: ComponentType;
  /** The chrome shows one of the app's declared tabs; the app switches its panels to it. */
  setTab?(tabId: string): void;
  dispose(): void;
}

/** One entry in the tab bar. */
export interface AppTab {
  id: string;
  label: string;
}

export interface AppDefinition {
  id: string;
  title: string;
  description: string;
  /** Tabs the app contributes to the tab bar, in order. */
  tabs?: AppTab[];
  /** The physics and modeling capabilities the application uses. */
  physics?: string[];
  start(host: AppHost): Promise<AppInstance> | AppInstance;
}
