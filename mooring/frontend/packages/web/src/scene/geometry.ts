import type { Anchor, LocalFrame, Pose, SceneEntity } from './types';

const DEG = Math.PI / 180;

export function rotate(x: number, y: number, headingDeg: number): [number, number] {
  const c = Math.cos(headingDeg * DEG);
  const s = Math.sin(headingDeg * DEG);
  return [x * c - y * s, x * s + y * c];
}

/** Entity-local point to frame coordinates. Roll and pitch, when present, tilt the entity about its pose origin. */
export function entityToFrame(pose: Pose, x: number, y: number, z = 0): [number, number, number] {
  let lx = x;
  let ly = y;
  let lz = z;
  if (pose.rollDeg || pose.pitchDeg) {
    // Roll: right-hand about local +x (y toward z). Then pitch: right-hand about local +y (z toward x).
    const cr = Math.cos((pose.rollDeg ?? 0) * DEG);
    const sr = Math.sin((pose.rollDeg ?? 0) * DEG);
    const cp = Math.cos((pose.pitchDeg ?? 0) * DEG);
    const sp = Math.sin((pose.pitchDeg ?? 0) * DEG);
    const ry = ly * cr - lz * sr;
    const rz = ly * sr + lz * cr;
    lx = x * cp + rz * sp;
    ly = ry;
    lz = -x * sp + rz * cp;
  }
  const [rx, ry2] = rotate(lx, ly, pose.headingDeg);
  return [pose.x + rx, pose.y + ry2, pose.z + lz];
}

export function isTilted(pose: Pose): boolean {
  return !!(pose.rollDeg || pose.pitchDeg);
}

/**
 * Top ring of an extruded polygon on a tilted entity, in frame coordinates (z included), plus a flat bottom height.
 * The bottom stays at the pose's base level (the waterline for a hull), but is kept below the lowest top vertex.
 */
export function tiltedPolygonRing(pose: Pose, points: [number, number][], heightM: number, baseM = 0): { ring: [number, number, number][]; bottomZ: number } {
  const ring = points.map(([px, py]) => entityToFrame(pose, px, py, baseM + heightM));
  const lowestTop = Math.min(...ring.map((p) => p[2]));
  return { ring, bottomZ: Math.min(pose.z + baseM, lowestTop - 0.1) };
}

/** Resolve an anchor to frame coordinates, following its entity's current pose. */
export function resolveAnchor(
  anchor: Anchor,
  entities: Record<string, SceneEntity>,
): [number, number, number] | null {
  if (!anchor.entityId) return [anchor.x, anchor.y, anchor.z];
  const entity = entities[anchor.entityId];
  if (!entity) return null;
  return entityToFrame(entity.pose, anchor.x, anchor.y, anchor.z);
}

/** Frame coordinates to East/North meters (no curvature; fine at pier scale). */
export function frameToEnu(frame: LocalFrame, x: number, y: number): [number, number] {
  const b = frame.xBearingTrueDeg * DEG;
  return [x * Math.sin(b) - y * Math.cos(b), x * Math.cos(b) + y * Math.sin(b)];
}

export function enuToFrame(frame: LocalFrame, east: number, north: number): [number, number] {
  const b = frame.xBearingTrueDeg * DEG;
  return [east * Math.sin(b) + north * Math.cos(b), -east * Math.cos(b) + north * Math.sin(b)];
}

/** True bearing (clockwise from north) to a local angle (counter-clockwise from +x). */
export function bearingToLocalAngle(frame: LocalFrame, bearingTrueDeg: number): number {
  return normalizeDeg(frame.xBearingTrueDeg - bearingTrueDeg);
}

export function localAngleToBearing(frame: LocalFrame, angleDeg: number): number {
  return normalizeDeg(frame.xBearingTrueDeg - angleDeg);
}

export function normalizeDeg(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

/**
 * Camera heading (clockwise from north, degrees) that puts frame +x to the screen's right and +y up for a
 * top-down view: screen-up is the bearing of +y, i.e. x bearing - 90.
 */
export function topDownHeadingDeg(frame: LocalFrame): number {
  return normalizeDeg(frame.xBearingTrueDeg - 90);
}

/** Apply an edit policy to a requested pose, given the pose the drag started from. */
export function constrainMove(
  requested: { x: number; y: number },
  start: Pose,
  policy: NonNullable<SceneEntity['editable']>,
): { x: number; y: number } {
  let { x, y } = requested;
  if (policy.moveAxis === 'x') y = start.y;
  if (policy.moveAxis === 'y') x = start.x;
  if (policy.snapM && policy.snapM > 0) {
    x = Math.round(x / policy.snapM) * policy.snapM;
    y = Math.round(y / policy.snapM) * policy.snapM;
  }
  const b = policy.bounds;
  if (b) {
    if (b.minX !== undefined) x = Math.max(b.minX, x);
    if (b.maxX !== undefined) x = Math.min(b.maxX, x);
    if (b.minY !== undefined) y = Math.max(b.minY, y);
    if (b.maxY !== undefined) y = Math.min(b.maxY, y);
  }
  return { x, y };
}

export interface Bounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export function sceneBounds(entities: SceneEntity[]): Bounds | null {
  let b: Bounds | null = null;
  const add = (x: number, y: number) => {
    b = b
      ? {
          minX: Math.min(b.minX, x),
          maxX: Math.max(b.maxX, x),
          minY: Math.min(b.minY, y),
          maxY: Math.max(b.maxY, y),
        }
      : { minX: x, maxX: x, minY: y, maxY: y };
  };
  for (const e of entities) {
    if (e.excludeFromFit) continue;
    if (e.geometry.type === 'polygon') {
      for (const [px, py] of e.geometry.points) {
        const [x, y] = entityToFrame(e.pose, px, py);
        add(x, y);
      }
    } else {
      add(e.pose.x, e.pose.y);
    }
  }
  return b;
}
