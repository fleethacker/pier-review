import type { SceneEntity, SceneLink, Status } from '../../../scene/types';
import { ft } from '../units';
import type { SimScene, ViewFrame } from './frames';

/** What the mapper needs about the ship when the scene supplies no hull outline of its own. */
export interface ShipDims {
  /** Hull footprint in ship-local meters, midships origin. */
  hull: [number, number][];
  freeboardM: number;
  /** Cosmetic deckhouse and mast blocks for the 3D view, already in ship-local meters. */
  parts: { id: string; points: [number, number][]; heightM: number; liftM: number; color?: string }[];
}

export const MOTION_KINDS = ['motion-ship', 'motion-ship-part', 'motion-tug', 'motion-water'];

const DRAWABLE_DOF = new Set(['simulated', 'prescribed']);
const WATER_HALF_M = 300;
const WATER_SNAP_M = 100;

/** Roll or pitch is drawn only when the frame calls that axis simulated or prescribed AND supplies a value. */
export function drawableAttitude(ship: ViewFrame['ship']): { rollDeg: number | null; pitchDeg: number | null } {
  return {
    rollDeg: ship.rollDeg != null && DRAWABLE_DOF.has(ship.dofs.roll) ? ship.rollDeg : null,
    pitchDeg: ship.pitchDeg != null && DRAWABLE_DOF.has(ship.dofs.pitch) ? ship.pitchDeg : null,
  };
}

/** Water level (ft MLLW) to draw, or null. The adapter already nulls it unless the water component is available. */
export function drawableWaterLevelFt(frame: ViewFrame): number | null {
  const w = frame.environment?.water;
  return w && w.availability === 'available' ? w.levelMllwFt : null;
}

const TUG_L = 28;
const TUG_B = 9;
const LINE_COLOR: Record<string, { status: Status; color?: string }> = {
  overloaded: { status: 'RED' },
  // Taut describes line state, not a capacity or safety assessment.
  taut: { status: 'NONE', color: '#00bcd4' },
  slack: { status: 'NONE', color: '#6b7f99' },
  unknown: { status: 'NONE', color: '#6b7f99' },
};

export interface MotionSceneParts {
  entities: SceneEntity[];
  links: SceneLink[];
  /** What was left out because the frame did not supply it; shown to the user, never filled in. */
  notDrawn: string[];
}

/**
 * Turns one frame into scene entities for the Cesium view. Only supplied state is drawn: a tug without a position, a
 * line without endpoints, or a ship without simulated heave is simply not drawn that way, and is listed in `notDrawn`.
 * The scene frame is the berth frame (meters, +x along the berth face, counterclockwise), the same as the simulator's.
 */
export function motionSceneParts(frame: ViewFrame, scene: SimScene | null, dims: ShipDims | null): MotionSceneParts {
  const notDrawn: string[] = [];
  const { ship } = frame;
  const heave = ship.heaveMllwFt;
  const { rollDeg, pitchDeg } = drawableAttitude(ship);
  const tilted = !!(rollDeg || pitchDeg);
  const levelPose = { x: ft(ship.x_ft), y: ft(ship.y_ft), z: heave != null ? ft(heave) : 0, headingDeg: ship.yawDeg };
  const pose = {
    ...levelPose,
    ...(rollDeg != null ? { rollDeg } : {}),
    ...(pitchDeg != null ? { pitchDeg } : {}),
  };

  const hull: [number, number][] | null = scene?.ship_hull_outline?.length
    ? scene.ship_hull_outline.map((p): [number, number] => [ft(p.x_ft ?? 0), ft(p.y_ft ?? 0)])
    : (dims?.hull ?? null);
  const entities: SceneEntity[] = [];
  if (hull) {
    entities.push({
      id: 'motion-ship',
      kind: 'motion-ship',
      label: 'Ship',
      pose,
      geometry: { type: 'polygon', points: hull, heightM: dims?.freeboardM ?? 6 },
      color: '#5b8fc9',
      selectable: false,
    });
    for (const p of dims?.parts ?? []) {
      const lift = (dims?.freeboardM ?? 0) + p.liftM;
      entities.push({
        id: `motion-ship-part:${p.id}`,
        kind: 'motion-ship-part',
        // Tilted: keep the ship's pivot and carry the lift in the geometry so the part rotates with the hull.
        pose: tilted ? pose : { ...pose, z: pose.z + lift },
        geometry: { type: 'polygon', points: p.points, heightM: p.heightM, ...(tilted ? { baseM: lift } : {}) },
        color: p.color ?? '#7ba3d1',
        selectable: false,
      });
    }
  } else {
    entities.push({ id: 'motion-ship', kind: 'motion-ship', label: 'Ship (no hull outline supplied)', pose, geometry: { type: 'point', sizePx: 14 }, color: '#00e5ff', selectable: false });
    notDrawn.push('hull outline');
  }
  if (heave == null) notDrawn.push('heave (not simulated)');
  if (rollDeg == null && pitchDeg == null) notDrawn.push('roll and pitch');
  else if (rollDeg == null) notDrawn.push('roll');
  else if (pitchDeg == null) notDrawn.push('pitch');

  // Display-only water surface at the level the frame supplied; never a default level.
  const waterFt = drawableWaterLevelFt(frame);
  if (waterFt == null) notDrawn.push('water surface');
  else {
    const cx = Math.round(levelPose.x / WATER_SNAP_M) * WATER_SNAP_M;
    const cy = Math.round(levelPose.y / WATER_SNAP_M) * WATER_SNAP_M;
    entities.push({
      id: 'motion-water',
      kind: 'motion-water',
      pose: { x: cx, y: cy, z: ft(waterFt), headingDeg: 0 },
      geometry: { type: 'polygon', points: [[-WATER_HALF_M, -WATER_HALF_M], [WATER_HALF_M, -WATER_HALF_M], [WATER_HALF_M, WATER_HALF_M], [-WATER_HALF_M, WATER_HALF_M]], heightM: 0 },
      color: '#2a7fbf',
      opacity: 0.3,
      noOutline: true,
      excludeFromFit: true,
      selectable: false,
    });
  }

  const tugsWithoutPosition = frame.tugs.filter((t) => !t.position).length;
  for (const t of frame.tugs) {
    if (!t.position) continue;
    entities.push({
      id: `motion-tug:${t.id}`,
      kind: 'motion-tug',
      label: t.id,
      pose: { x: ft(t.position.x), y: ft(t.position.y), z: 0, headingDeg: (t.headingTrueDeg != null ? scene?.face_bearing_true_deg != null ? scene.face_bearing_true_deg - t.headingTrueDeg : 0 : 0) },
      geometry: {
        type: 'polygon',
        points: [[-TUG_L / 2, -TUG_B / 2], [TUG_L / 2 - 4, -TUG_B / 2], [TUG_L / 2, 0], [TUG_L / 2 - 4, TUG_B / 2], [-TUG_L / 2, TUG_B / 2]],
        heightM: 4,
      },
      color: '#e8a33d',
      selectable: false,
    });
  }
  if (tugsWithoutPosition) notDrawn.push(`${tugsWithoutPosition} tug position${tugsWithoutPosition > 1 ? 's' : ''}`);

  const maxTension = Math.max(1, ...frame.lines.map((l) => l.tensionLbf ?? 0));
  const links: SceneLink[] = [];
  let linesWithoutEnds = 0;
  for (const l of frame.lines) {
    if (!l.shipEnd || !l.pierEnd) {
      linesWithoutEnds += 1;
      continue;
    }
    const style = LINE_COLOR[l.status] ?? LINE_COLOR.unknown;
    links.push({
      id: `motion-line:${l.lineNumber}`,
      kind: 'motion-line',
      from: { x: ft(l.shipEnd.x), y: ft(l.shipEnd.y), z: 0 },
      to: { x: ft(l.pierEnd.x), y: ft(l.pierEnd.y), z: 0 },
      status: style.status,
      color: style.color,
      widthPx: 2 + 4 * ((l.tensionLbf ?? 0) / maxTension),
      label: `${l.lineNumber}`,
      selectable: false,
    });
  }
  if (linesWithoutEnds) notDrawn.push(`${linesWithoutEnds} line${linesWithoutEnds > 1 ? 's' : ''} (no endpoints supplied)`);
  return { entities, links, notDrawn };
}
