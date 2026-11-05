/**
 * Neutral scene model. The shell renders this; apps (adapters) produce it. Nothing here is specific to any
 * application. Local frame: meters, +x along `frame.xBearingTrueDeg`, +y is x rotated 90 deg counter-clockwise
 * seen from above (bearing x - 90), +z up. Headings and angles are degrees counter-clockwise from +x.
 */

export type Status = 'GREEN' | 'AMBER' | 'RED' | 'NONE';

export interface LocalFrame {
  lonDeg: number;
  latDeg: number;
  /** True bearing of the frame's +x axis. */
  xBearingTrueDeg: number;
}

export interface Pose {
  x: number;
  y: number;
  z: number;
  headingDeg: number;
}

export type Geometry =
  | {
      type: 'polygon';
      /** Footprint in entity-local coordinates (meters), rotated by the entity pose. */
      points: [number, number][];
      /** Extrusion height above the pose z. 0 renders a flat polygon. */
      heightM: number;
    }
  | { type: 'point'; sizePx: number };

export interface EditPolicy {
  moveAxis: 'x' | 'y' | 'xy';
  /** Allowed range of the entity pose, in frame meters. */
  bounds?: { minX?: number; maxX?: number; minY?: number; maxY?: number };
  /** Snap step in meters. */
  snapM?: number;
}

export interface PropRow {
  label: string;
  value: string;
}

export interface SceneEntity {
  id: string;
  /** Application-defined category, e.g. "ship" or "fitting". The shell only uses it for grouping and layers. */
  kind: string;
  label?: string;
  /** Draw the label all the time, not only on hover or selection (point entities). */
  labelAlways?: boolean;
  /** Skip the dark outline; for translucent decoration such as shadows, halos and wakes. */
  noOutline?: boolean;
  pose: Pose;
  geometry: Geometry;
  /** CSS color. When `status` is set it overrides the fill. */
  color?: string;
  opacity?: number;
  status?: Status;
  selectable?: boolean;
  editable?: EditPolicy;
  /** Clicking or dragging this entity acts on another one (a ship's deckhouse stands in for the ship). */
  selectsId?: string;
  props?: PropRow[];
}

/** One end of a link: a point in an entity's local frame, or in the scene frame when `entityId` is absent. */
export interface Anchor {
  entityId?: string;
  x: number;
  y: number;
  z: number;
}

export interface SceneLink {
  id: string;
  kind: string;
  from: Anchor;
  to: Anchor;
  status?: Status;
  color?: string;
  widthPx?: number;
  /** More than one: drawn heavier with a light outline, so a doubled-up line is told apart at a glance. */
  strands?: number;
  label?: string;
  selectable?: boolean;
  props?: PropRow[];
}

/** Arrow overlay, e.g. wind or current. `angleDeg` is local (CCW from +x). */
export interface SceneVector {
  id: string;
  kind: string;
  origin: { x: number; y: number; z: number };
  angleDeg: number;
  lengthM: number;
  label?: string;
  color?: string;
  /** When set, the shell also streams animated particles along the arrow's direction across the scene. */
  flow?: { mps: number; /** 0 = steady; 0.3 = speed swings by about +-15%. */ gustiness?: number };
}

export type Selection = { type: 'entity' | 'link'; id: string } | null;
export type ViewMode = '2d' | '3d';
export type Lighting = 'day' | 'night';
/** Named camera positions. They assume the ship lies along the berth face (+x), pier on the -y side. */
export type CameraPreset = 'top' | 'bow' | 'portQuarter' | 'pierSide';

export interface SceneContent {
  frame: LocalFrame;
  entities: SceneEntity[];
  links: SceneLink[];
  vectors: SceneVector[];
}

export interface SceneState {
  frame: LocalFrame | null;
  entities: Record<string, SceneEntity>;
  links: Record<string, SceneLink>;
  vectors: Record<string, SceneVector>;
  selection: Selection;
  viewMode: ViewMode;
  lighting: Lighting;
  /** Incremented whenever the content is replaced; the shell refits the camera when it changes. */
  contentRevision: number;
  /** Incremented to ask the shell to refit the camera to the current content. */
  fitRevision: number;
  /** Set to move the camera to a named position; `revision` changes on every request so repeats still apply. */
  cameraPreset: { name: CameraPreset; revision: number; /** Frame meters to look at; the current target when absent. */ target?: { x: number; y: number } } | null;
}

/** Edits the user makes on the canvas. The active app decides what they mean. */
export type SceneEdit = {
  type: 'move';
  entityId: string;
  pose: Pose;
  /** False while dragging, true on release. */
  final: boolean;
};
