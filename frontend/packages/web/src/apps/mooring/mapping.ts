import { bearingToLocalAngle, entityToFrame } from '../../scene/geometry';
import type {
  LocalFrame,
  Pose,
  PropRow,
  SceneContent,
  SceneEntity,
  SceneLink,
  SceneVector,
  Status,
} from '../../scene/types';
import { ft, fmt } from './units';
import { classSupport } from './classSupport';
import type {
  AnalyzeResponse,
  Berth,
  Environment,
  MooringLine,
  ShipClass,
  SideTo,
  TugAssignment,
} from './types';

const DEFAULT_STANDOFF_FT = 3;

export const IDS = {
  pier: 'pier',
  ship: 'ship',
  pierFitting: (id: string) => `pier:${id}`,
  shipFitting: (id: string) => `sfit:${id}`,
  fender: (id: string) => `fender:${id}`,
  line: (n: number) => `line-${n}`,
  wind: 'wind',
  current: 'current',
  water: 'water-level',
  pierEdge: 'pier-edge',
  shipHalo: 'ship-halo',
  shipShadow: 'ship-shadow',
};

/** One color per environment variable, shared by the canvas arrows and the data key so the two read as a pair. */
export const ENV_COLORS = { wind: '#7fd1ff', current: '#7dffb2', water: '#9bb8d9' };

/** What a part count is called aboard: one part is single, two is a tanker moor, three is doubled up. */
export function partsName(parts: number): string {
  return parts === 1 ? 'single' : parts === 2 ? 'tanker moor ×2' : 'doubled up ×3';
}

export function berthFrame(berth: Berth): LocalFrame {
  return { lonDeg: berth.origin_lon, latDeg: berth.origin_lat, xBearingTrueDeg: berth.face_bearing_true_deg };
}

export function standoffFt(berth: Berth, override?: number | null): number {
  return override ?? berth.fenders?.[0]?.standoff_ft ?? DEFAULT_STANDOFF_FT;
}

/** Starboard side to the pier puts the bow toward +x; port side to puts it toward -x. */
export function shipPose(ship: ShipClass, side: SideTo, shipXFt: number, standoff: number): Pose {
  return { x: ft(shipXFt), y: ft(ship.beam_ft / 2 + standoff), z: 0, headingDeg: side === 'starboard' ? 0 : 180 };
}

/** Simple pointed-bow hull outline in the ship frame (+x forward, +y to port, midships origin), in meters. */
/**
 * Half-hull profiles, stern to bow, as [fraction of LOA from midships (+ forward), fraction of half-beam].
 * Mirrored to port and starboard. The widest point is always 1, so the outline spans exactly LOA and beam.
 */
const HALF_PROFILES: Record<string, [number, number][]> = {
  // Destroyer: transom stern, long parallel body, flared and sharply raked bow.
  DDG: [[-0.5, 0.74], [-0.46, 0.9], [-0.38, 0.98], [-0.3, 1], [0.12, 1], [0.24, 0.93], [0.34, 0.74], [0.42, 0.46], [0.47, 0.22], [0.5, 0]],
  // Cruiser: narrower and finer than the destroyer.
  CG: [[-0.5, 0.7], [-0.46, 0.88], [-0.38, 0.98], [-0.3, 1], [0.1, 1], [0.23, 0.92], [0.34, 0.7], [0.42, 0.42], [0.47, 0.2], [0.5, 0]],
  // Amphibious assault ship: full flat-sided body, squared stern, blunt bow.
  LHD: [[-0.5, 0.86], [-0.49, 0.97], [-0.44, 1], [0.3, 1], [0.38, 0.97], [0.44, 0.84], [0.48, 0.58], [0.5, 0.3], [0.5, 0]],
  LHA: [[-0.5, 0.86], [-0.49, 0.97], [-0.44, 1], [0.3, 1], [0.38, 0.97], [0.44, 0.84], [0.48, 0.58], [0.5, 0.3], [0.5, 0]],
  DEFAULT: [[-0.5, 0.8], [-0.25, 1], [0.2, 1], [0.5, 0]],
};

/** Carrier flight deck, port side [x, y] in LOA and half-beam fractions: the angled deck overhangs to port. */
const CVN_PORT: [number, number][] = [[-0.5, 0.72], [-0.46, 0.95], [-0.3, 1], [-0.08, 0.98], [0.04, 0.88], [0.2, 0.84], [0.38, 0.62], [0.46, 0.3], [0.5, 0]];
/** Starboard side: straighter, with the island sitting on the edge. */
const CVN_STBD: [number, number][] = [[-0.5, -0.72], [-0.47, -0.9], [-0.4, -0.96], [-0.2, -1], [0.18, -1], [0.3, -0.92], [0.4, -0.66], [0.46, -0.32], [0.5, 0]];

export function hullPoints(loaFt: number, beamFt: number, hullType?: string): [number, number][] {
  const hb = beamFt / 2;
  const at = (x: number, y: number): [number, number] => [ft(x * loaFt), ft(y * hb)];
  if (hullType === 'CVN') {
    return [...CVN_STBD.map(([x, y]) => at(x, y)), ...[...CVN_PORT].reverse().slice(1).map(([x, y]) => at(x, y))];
  }
  const half = HALF_PROFILES[hullType ?? ''] ?? HALF_PROFILES.DEFAULT;
  const stbd = half.map(([x, y]) => at(x, -y));
  const port = [...half].reverse().slice(1, -1).map(([x, y]) => at(x, y));
  return [...stbd, ...port];
}

const SHIP_COLOR = '#4c7db3';
const PIER_COLOR = '#7b828c';

function fittingColor(condition: string): string {
  if (condition === 'do_not_use') return '#8a3b4a';
  if (condition === 'suspect') return '#d9a441';
  return '#ffd54f';
}

function statusOf(s: string | undefined): Status {
  return s === 'GREEN' || s === 'AMBER' || s === 'RED' ? s : 'NONE';
}

/** Invalid/unknown results cannot supply usable forces or passing element colors. */
export function hasUsableAnalysis(analysis: AnalyzeResponse | null): boolean {
  return analysis?.validity?.state === 'valid' || analysis?.validity?.state === 'limited';
}

function usageProps(
  rows: PropRow[],
  result: { load_lbf: number; pct?: number | null; lines: number[] } | undefined,
): PropRow[] {
  if (!result) return rows;
  return [
    ...rows,
    { label: 'Load', value: fmt.lbf(result.load_lbf) },
    { label: 'Utilization', value: result.pct == null ? 'n/a' : fmt.pct(result.pct) },
    { label: 'Lines', value: result.lines.join(', ') },
  ];
}

export interface SceneInput {
  berth: Berth;
  ship: ShipClass | null;
  loading: string;
  side: SideTo;
  shipXFt: number;
  standoffFt: number;
  lines: MooringLine[];
  analysis: AnalyzeResponse | null;
  env: Environment | null;
  tugs?: TugAssignment[];
}

export function pierEntities(berth: Berth, analysis: AnalyzeResponse | null): SceneEntity[] {
  const deckHeight = ft(berth.deck_height_mllw_ft);
  const maxDepth = Math.max(...berth.fittings.map((f) => -f.y_ft), 20) + 25;
  const deck: SceneEntity = {
    id: IDS.pier,
    kind: 'pier',
    label: berth.name,
    pose: { x: 0, y: 0, z: 0, headingDeg: 0 },
    geometry: {
      type: 'polygon',
      points: [
        [0, 0],
        [ft(berth.face_length_ft), 0],
        [ft(berth.face_length_ft), -ft(maxDepth)],
        [0, -ft(maxDepth)],
      ],
      heightM: deckHeight,
    },
    color: PIER_COLOR,
    selectable: false,
    props: [
      { label: 'Berth', value: berth.berth_id },
      { label: 'Face length', value: fmt.ft(berth.face_length_ft) },
      { label: 'Deck height', value: `${fmt.ft(berth.deck_height_mllw_ft)} MLLW` },
      { label: 'Structure', value: berth.structure },
      { label: 'Data source', value: `${berth.provenance.source} (${berth.provenance.confidence})` },
    ],
  };

  const used = new Map((hasUsableAnalysis(analysis) ? analysis?.result.pier_fittings ?? [] : []).map((f) => [f.fitting_id, f]));
  const fittings = berth.fittings.map<SceneEntity>((f) => {
    const r = used.get(f.fitting_id);
    return {
      id: IDS.pierFitting(f.fitting_id),
      kind: 'pier-fitting',
      label: f.fitting_id,
      pose: { x: ft(f.x_ft), y: ft(f.y_ft), z: deckHeight + 0.05, headingDeg: 0 },
      geometry: { type: 'point', sizePx: r ? 11 : 8 },
      color: fittingColor(f.condition),
      status: r ? statusOf(r.status) : undefined,
      selectable: true,
      connectable: { group: 'pier-fitting', accepts: ['ship-fitting'] },
      props: usageProps(
        [
          { label: 'Type', value: f.kind },
          { label: 'Condition', value: f.condition },
          { label: 'Capacity (nominal)', value: fmt.lbf(f.capacity_nominal_lbf) },
          { label: 'Capacity (horizontal)', value: f.capacity_horizontal_lbf == null ? 'n/a' : fmt.lbf(f.capacity_horizontal_lbf) },
          { label: 'Position', value: `x ${fmt.ft(f.x_ft)}, y ${fmt.ft(f.y_ft)}` },
        ],
        r,
      ),
    };
  });

  const fenders = (berth.fenders ?? []).map<SceneEntity>((f) => ({
    id: IDS.fender(f.fender_id),
    kind: 'fender',
    label: undefined,
    pose: { x: ft(f.x_ft), y: 0, z: 0, headingDeg: 0 },
    geometry: {
      type: 'polygon',
      points: [
        [-ft(f.length_ft) / 2, 0],
        [ft(f.length_ft) / 2, 0],
        [ft(f.length_ft) / 2, ft(1.5)],
        [-ft(f.length_ft) / 2, ft(1.5)],
      ],
      heightM: ft(1),
    },
    color: '#2f2f33',
    selectable: true,
    props: [
      { label: 'Type', value: f.kind },
      { label: 'Standoff', value: fmt.ft(f.standoff_ft) },
      { label: 'Stiffness', value: fmt.lbfPerFt(f.stiffness_lbf_per_ft) },
    ],
  }));
  // A thin lit strip along the pier edge makes the face read as a quay.
  const edge: SceneEntity = {
    id: IDS.pierEdge,
    kind: 'pier-edge',
    pose: { x: 0, y: 0, z: 0, headingDeg: 0 },
    geometry: {
      type: 'polygon',
      points: [
        [0, 0.05],
        [ft(berth.face_length_ft), 0.05],
        [ft(berth.face_length_ft), -0.7],
        [0, -0.7],
      ],
      heightM: deckHeight + 0.14,
    },
    color: '#00e5ff',
    opacity: 0.85,
    noOutline: true,
    selectable: false,
  };
  return [deck, edge, ...fittings, ...fenders];
}

interface Block {
  /** Center along the ship as a fraction of LOA from midships (+ forward). */
  x: number;
  /** Length as a fraction of LOA. */
  len: number;
  /** Center across the ship as a fraction of beam (+ to port, - to starboard). */
  y: number;
  /** Width as a fraction of beam. */
  w: number;
  /** Height above the hull top, meters. */
  h: number;
  /** Raised off the hull top, meters (decks above the hull). */
  lift?: number;
  /** An arbitrary outline instead of the rectangle, as [fraction of LOA, fraction of beam] points. */
  poly?: [number, number][];
  color?: string;
}

const DECK = '#2f4f73';
const DECK_MARK = '#c9d6e6';
const GRAY = '#7ba3d1';
const DARK = '#5d86b3';

/** A rectangle given by its two corners, as a polygon block. */
const box = (x0: number, x1: number, y0: number, y1: number, h: number, lift = 0, color?: string): Block => ({
  x: (x0 + x1) / 2, len: Math.abs(x1 - x0), y: (y0 + y1) / 2, w: Math.abs(y1 - y0), h, lift, color,
});

/** A strip along the deck at an angle, for runway markings. Ends are [x, y] centers; width is a beam fraction. */
const strip = (x0: number, y0: number, x1: number, y1: number, width: number, h: number, lift: number, color: string): Block => {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const n = Math.hypot(dx, dy) || 1;
  const px = (-dy / n) * (width / 2);
  const py = (dx / n) * (width / 2);
  return {
    x: 0, len: 0, y: 0, w: 0, h, lift, color,
    poly: [[x0 + px, y0 + py], [x1 + px, y1 + py], [x1 - px, y1 - py], [x0 - px, y0 - py]],
  };
};

/** Above-deck detail per class, in fractions of LOA and beam, so each class reads as its own ship. */
export function superstructureProfile(hullType: string | undefined): Block[] {
  switch (hullType) {
    case 'CVN':
      return [
        // Flight deck markings: angled landing area to port, waist catapults forward, centerline strip.
        strip(-0.48, 0.08, 0.1, 0.34, 0.09, 0.2, 0.1, DECK_MARK),
        strip(-0.3, 0.02, 0.44, 0.02, 0.05, 0.2, 0.1, DECK_MARK),
        strip(0.1, -0.12, 0.46, -0.06, 0.04, 0.2, 0.1, DECK_MARK),
        // Island on the starboard edge: stepped base, bridge, then the mast and radar tower.
        { x: 0.04, len: 0.14, y: -0.37, w: 0.16, h: 7, lift: 0, color: GRAY },
        { x: 0.05, len: 0.1, y: -0.37, w: 0.14, h: 6, lift: 7, color: DARK },
        { x: 0.02, len: 0.035, y: -0.38, w: 0.07, h: 10, lift: 13, color: GRAY },
        { x: 0.075, len: 0.02, y: -0.38, w: 0.05, h: 5, lift: 13, color: DARK },
        // Aircraft on the flight deck, as low blocks.
        box(-0.4, -0.34, 0.12, 0.2, 4, 0, DARK),
        box(-0.3, -0.24, 0.2, 0.28, 4, 0, DARK),
        box(-0.2, -0.14, 0.3, 0.38, 4, 0, DARK),
        // Elevators and sponsons read as notches in the deck edge.
        box(-0.12, 0, -0.5, -0.42, 0.4, 0, DECK),
        box(0.18, 0.28, -0.5, -0.42, 0.4, 0, DECK),
      ];
    case 'LHD':
    case 'LHA':
      return [
        // Flat flight deck with spot markings and a starboard island.
        { x: -0.02, len: 0.96, y: 0, w: 0.98, h: 0.5, lift: 0, color: DECK },
        strip(-0.46, 0, 0.44, 0, 0.03, 0.2, 0.5, DECK_MARK),
        box(-0.38, -0.34, -0.14, 0.14, 0.2, 0.5, DECK_MARK),
        box(-0.22, -0.18, -0.14, 0.14, 0.2, 0.5, DECK_MARK),
        box(-0.06, -0.02, -0.14, 0.14, 0.2, 0.5, DECK_MARK),
        box(0.1, 0.14, -0.14, 0.14, 0.2, 0.5, DECK_MARK),
        box(0.26, 0.3, -0.14, 0.14, 0.2, 0.5, DECK_MARK),
        // Island: stepped bridge, then mast and the two stacks aft.
        { x: 0.1, len: 0.14, y: -0.36, w: 0.2, h: 7, lift: 0.5, color: GRAY },
        { x: 0.1, len: 0.09, y: -0.36, w: 0.16, h: 4, lift: 7.5, color: DARK },
        { x: 0.12, len: 0.03, y: -0.36, w: 0.06, h: 8, lift: 11.5, color: GRAY },
        { x: -0.02, len: 0.045, y: -0.36, w: 0.08, h: 6, lift: 0.5, color: DARK },
        { x: -0.08, len: 0.045, y: -0.36, w: 0.08, h: 6, lift: 0.5, color: DARK },
        // Deck-edge elevator to port and aircraft parked aft.
        box(-0.2, -0.1, 0.38, 0.48, 0.3, 0.5, DECK_MARK),
        box(-0.44, -0.38, 0.2, 0.3, 3, 0.5, DARK),
      ];
    case 'CG':
      return [
        // Forward gun, forward VLS, then the raked deckhouse with bridge wing level and mast.
        { x: 0.32, len: 0.035, y: 0, w: 0.12, h: 3, color: DARK },
        box(0.22, 0.28, -0.12, 0.12, 0.8, 0, DECK),
        { x: 0, len: 0, y: 0, w: 0, h: 9, color: GRAY, poly: [[0.2, -0.17], [0.2, 0.17], [0.14, 0.3], [-0.04, 0.3], [-0.04, -0.3], [0.14, -0.3]] },
        { x: 0.11, len: 0.07, y: 0, w: 0.26, h: 4, lift: 9, color: DARK },
        { x: 0.08, len: 0.025, y: 0, w: 0.06, h: 12, lift: 13, color: GRAY },
        // Two stacks, aft mast, aft VLS, aft gun and the helicopter deck.
        { x: -0.07, len: 0.06, y: 0, w: 0.17, h: 5, lift: 9, color: GRAY },
        { x: -0.13, len: 0.05, y: 0, w: 0.15, h: 4, lift: 9, color: DARK },
        { x: -0.18, len: 0.025, y: 0, w: 0.05, h: 9, lift: 9, color: GRAY },
        box(-0.26, -0.2, -0.12, 0.12, 0.8, 0, DECK),
        { x: -0.31, len: 0.035, y: 0, w: 0.12, h: 3, color: DARK },
        box(-0.5, -0.36, -0.36, 0.36, 0.3, 0, DECK),
        { x: -0.43, len: 0.07, y: 0, w: 0.2, h: 0.2, color: DECK_MARK, lift: 0.3 },
      ];
    default:
      return [
        // Arleigh Burke: gun and VLS forward, a raked deckhouse with the mast, twin stacks, then hangars and helo deck aft.
        { x: 0.32, len: 0.04, y: 0, w: 0.12, h: 3, color: DARK },
        box(0.22, 0.29, -0.11, 0.11, 0.8, 0, DECK),
        { x: 0, len: 0, y: 0, w: 0, h: 8, color: GRAY, poly: [[0.15, -0.17], [0.15, 0.17], [0.09, 0.3], [-0.12, 0.3], [-0.12, -0.3], [0.09, -0.3]] },
        { x: 0.07, len: 0.07, y: 0, w: 0.24, h: 4, lift: 8, color: DARK },
        { x: 0.0, len: 0.03, y: 0, w: 0.07, h: 13, lift: 8, color: GRAY },
        { x: -0.08, len: 0.045, y: 0.2, w: 0.1, h: 5, lift: 8, color: DARK },
        { x: -0.08, len: 0.045, y: -0.2, w: 0.1, h: 5, lift: 8, color: DARK },
        { x: -0.17, len: 0.025, y: 0, w: 0.05, h: 7, lift: 8, color: GRAY },
        box(-0.26, -0.19, -0.11, 0.11, 0.8, 0, DECK),
        { x: -0.34, len: 0.1, y: 0.18, w: 0.2, h: 5.5, color: GRAY },
        { x: -0.34, len: 0.1, y: -0.18, w: 0.2, h: 5.5, color: GRAY },
        box(-0.5, -0.39, -0.35, 0.35, 0.3, 0, DECK),
        { x: -0.45, len: 0.06, y: 0, w: 0.2, h: 0.2, color: DECK_MARK, lift: 0.3 },
      ];
  }
}

export function superstructure(ship: ShipClass, pose: Pose, freeboardM: number): SceneEntity[] {
  return superstructureProfile(ship.hull_type).map((b, i) => {
    const points: [number, number][] = b.poly
      ? b.poly.map(([x, y]) => [ft(x * ship.loa_ft), ft(y * ship.beam_ft)])
      : (() => {
          const cx = ft(b.x * ship.loa_ft);
          const cy = ft(b.y * ship.beam_ft);
          const hl = ft((b.len * ship.loa_ft) / 2);
          const hw = ft((b.w * ship.beam_ft) / 2);
          return [
            [cx - hl, cy - hw],
            [cx + hl, cy - hw],
            [cx + hl, cy + hw],
            [cx - hl, cy + hw],
          ];
        })();
    return {
      id: `${IDS.ship}-part:${i}`,
      kind: 'ship-part',
      pose: { ...pose, z: freeboardM + (b.lift ?? 0) },
      geometry: { type: 'polygon', points, heightM: b.h },
      color: b.color ?? GRAY,
      selectable: true,
      selectsId: IDS.ship,
    };
  });
}

export function shipEntities(
  ship: ShipClass,
  loading: string,
  side: SideTo,
  shipXFt: number,
  standoff: number,
  analysis: AnalyzeResponse | null,
  editable: boolean,
  berth: Berth,
): SceneEntity[] {
  const canEdit = editable && classSupport(ship, ship.class_id, loading, side).canPlan;
  const pose = shipPose(ship, side, shipXFt, standoff);
  const cond = ship.loading_conditions.find((c) => c.name === loading) ?? ship.loading_conditions[0];
  const freeboard = ft(cond?.freeboard_ft ?? 20);
  const hull: SceneEntity = {
    id: IDS.ship,
    kind: 'ship',
    label: ship.class_id,
    pose,
    geometry: { type: 'polygon', points: hullPoints(ship.loa_ft, ship.beam_ft, ship.hull_type), heightM: freeboard },
    color: SHIP_COLOR,
    selectable: true,
    editable: canEdit
      ? {
          moveAxis: 'xy',
          snapM: ft(1),
          bounds: { minX: 0, maxX: ft(berth.face_length_ft), minY: ft(ship.beam_ft / 2) },
        }
      : undefined,
    props: [
      { label: 'Class', value: ship.name },
      { label: 'LOA / beam', value: `${fmt.ft(ship.loa_ft)} / ${fmt.ft(ship.beam_ft)}` },
      { label: 'Loading', value: cond ? `${cond.name}, ${fmt.longTons(cond.displacement_lt)}` : loading },
      { label: 'Side to', value: side },
      { label: 'Midships at', value: `x ${fmt.ft(shipXFt)}` },
      { label: 'Standoff', value: fmt.ft(standoff) },
    ],
  };

  const sideName = side === 'starboard' ? 'starboard' : 'port';
  const used = new Map((hasUsableAnalysis(analysis) ? analysis?.result.ship_fittings ?? [] : []).map((f) => [f.fitting_id, f]));
  const fittings = (ship.fittings ?? [])
    .filter((f) => f.kind === 'bitt' && f.side === sideName)
    .map<SceneEntity>((f) => {
      const [x, y] = entityToFrame(pose, ft(f.x_ft), ft(f.y_ft));
      const r = used.get(f.fitting_id);
      return {
        id: IDS.shipFitting(f.fitting_id),
        kind: 'ship-fitting',
        label: f.fitting_id,
        pose: { x, y, z: ft(f.z_ft), headingDeg: 0 },
        geometry: { type: 'point', sizePx: r ? 10 : 7 },
        color: '#e0e6ee',
        status: r ? statusOf(r.status) : undefined,
        selectable: true,
        connectable: canEdit ? { group: 'ship-fitting', accepts: ['pier-fitting'] } : undefined,
        props: usageProps(
          [
            { label: 'Type', value: f.kind },
            { label: 'Safe working load', value: f.swl_lbf ? fmt.lbf(f.swl_lbf) : 'n/a' },
            { label: 'Height above waterline', value: fmt.ft(f.z_ft) },
          ],
          r,
        ),
      };
    });
  // On the water: a soft shadow under the hull, and a halo in the plan's overall status color.
  const outline = hullPoints(ship.loa_ft, ship.beam_ft, ship.hull_type);
  const grow = (pts: [number, number][], dx: number, dy: number, offX = 0, offY = 0): [number, number][] =>
    pts.map(([x, y]) => [x + Math.sign(x) * dx + offX, y + Math.sign(y) * dy + offY]);
  const away = side === 'starboard' ? 1 : -1; // ship +y points away from the pier when starboard side to
  const halo: SceneEntity = {
    id: IDS.shipHalo,
    kind: 'ship-halo',
    pose: { ...pose, z: 0.03 },
    geometry: { type: 'polygon', points: grow(outline, 9, 8), heightM: 0 },
    color: '#00e5ff',
    status: statusOf(analysis?.status),
    opacity: 0.26,
    noOutline: true,
    selectable: true,
    selectsId: IDS.ship,
  };
  const shadow: SceneEntity = {
    id: IDS.shipShadow,
    kind: 'ship-shadow',
    pose: { ...pose, z: 0.05 },
    geometry: { type: 'polygon', points: grow(outline, 2.5, 2.5, 0, away * 2.5), heightM: 0 },
    color: '#000000',
    opacity: 0.42,
    noOutline: true,
    selectable: true,
    selectsId: IDS.ship,
  };
  return [halo, shadow, hull, ...superstructure(ship, pose, freeboard), ...fittings];
}

export function lineLinks(
  berth: Berth,
  ship: ShipClass,
  lines: MooringLine[],
  analysis: AnalyzeResponse | null,
  missingFittingIds: string[] = [],
): SceneLink[] {
  const deckHeight = ft(berth.deck_height_mllw_ft);
  const results = new Map((hasUsableAnalysis(analysis) ? analysis?.result.lines ?? [] : []).map((l) => [l.line_number, l]));
  const links: SceneLink[] = [];
  for (const line of lines) {
    const sf = ship.fittings?.find((f) => f.fitting_id === line.ship_fitting_id);
    const pf = berth.fittings.find((f) => f.fitting_id === line.pier_fitting_id);
    if (!sf || !pf) {
      missingFittingIds.push(!sf ? line.ship_fitting_id : line.pier_fitting_id);
      continue;
    }
    const r = results.get(line.line_number);
    links.push({
      id: IDS.line(line.line_number),
      kind: 'mooring-line',
      from: { entityId: IDS.ship, x: ft(sf.x_ft), y: ft(sf.y_ft), z: ft(sf.z_ft) },
      to: { x: ft(pf.x_ft), y: ft(pf.y_ft), z: deckHeight + 0.05 },
      status: r ? statusOf(r.status) : undefined,
      color: '#c9d6e6',
      widthPx: 2 + line.parts * 1.5,
      strands: line.parts,
      label: `L${line.line_number}${line.parts > 1 ? ` ×${line.parts}` : ''}${r ? ` ${fmt.pct(r.pct_wll)}` : ''}`,
      selectable: true,
      editableEndpoints: { from: IDS.shipFitting(sf.fitting_id), to: IDS.pierFitting(pf.fitting_id) },
      props: [
        { label: 'Line', value: `#${line.line_number}${line.role ? ` ${line.role}` : ''}` },
        { label: 'Rope', value: `${line.spec_id} (${partsName(line.parts)})` },
        { label: 'Ship fitting', value: line.ship_fitting_id },
        { label: 'Pier fitting', value: line.pier_fitting_id },
        ...(r
          ? [
              { label: 'Tension', value: fmt.lbf(r.tension_lbf) },
              { label: '% working load', value: fmt.pct(r.pct_wll) },
              { label: '% breaking', value: fmt.pct(r.pct_mbs) },
              { label: 'Length', value: fmt.ft(r.length_ft, 1) },
              { label: 'Horizontal angle', value: fmt.deg(r.horiz_angle_deg) },
              { label: 'Vertical angle', value: fmt.deg(r.vert_angle_deg) },
            ]
          : []),
      ],
    });
  }
  return links;
}

/**
 * Wind blows FROM its bearing; current flows TOWARD its set. Arrows show the direction of motion. Each label is the
 * variable's name and speed only; bearings, gusts and the rest are in the data key beside the canvas.
 */
export function envVectors(frame: LocalFrame, env: Environment | null, center: { x: number; y: number }): SceneVector[] {
  if (!env) return [];
  const windTo = (env.wind_from_true_deg + 180) % 360;
  const windLen = Math.min(25 + env.wind_speed_kt * 2.2, 130);
  const curLen = Math.min(20 + env.current_speed_kt * 30, 110);
  const wAngle = bearingToLocalAngle(frame, windTo);
  const cAngle = bearingToLocalAngle(frame, env.current_set_true_deg);
  const place = (angle: number, len: number, dx: number) => {
    const rad = (angle * Math.PI) / 180;
    return { x: center.x + dx - (Math.cos(rad) * len) / 2, y: center.y - (Math.sin(rad) * len) / 2, z: 0.3 };
  };
  return [
    {
      id: IDS.wind,
      kind: 'wind',
      origin: place(wAngle, windLen, -60),
      angleDeg: wAngle,
      lengthM: windLen,
      color: ENV_COLORS.wind,
      // Streaks run faster than the real wind so they read on a 1 km scene; gusts make them surge.
      flow: { mps: Math.max(4, env.wind_speed_kt * 0.514 * 2.5), gustiness: Math.min(Math.max(env.wind_gust_kt / Math.max(env.wind_speed_kt, 1) - 1, 0), 1) },
      label: `WIND ${fmt.kt(env.wind_speed_kt)}`,
    },
    {
      id: IDS.current,
      kind: 'current',
      origin: place(cAngle, curLen, 80),
      angleDeg: cAngle,
      lengthM: curLen,
      color: ENV_COLORS.current,
      flow: { mps: Math.max(1.5, env.current_speed_kt * 0.514 * 8) },
      label: `CURRENT ${env.current_speed_kt.toFixed(1)} kt`,
    },
  ];
}

/** Variables with no direction get a plain readout beside the arrows instead. */
export function envReadouts(env: Environment | null, center: { x: number; y: number }): SceneEntity[] {
  if (!env) return [];
  const level = env.water_level_mllw_ft;
  return [
    {
      id: IDS.water,
      kind: 'readout',
      label: `WATER LEVEL ${level >= 0 ? '+' : ''}${fmt.ft(level, 1)}`,
      pose: { x: center.x + 10, y: center.y + 80, z: 0.3, headingDeg: 0 },
      geometry: { type: 'point', sizePx: 6 },
      color: ENV_COLORS.water,
      labelAlways: true,
      selectable: false,
    },
  ];
}

const TUG_LENGTH_M = 24;
const TUG_BEAM_M = 8;

/**
 * Tugs sit on the water side of the hull at their push points, bow toward the ship, with an arrow showing the
 * force direction the plan assigns (true bearing, converted to the frame).
 */
export function tugScene(
  ship: ShipClass,
  side: SideTo,
  shipXFt: number,
  standoff: number,
  assignments: TugAssignment[],
  frame: LocalFrame,
): { entities: SceneEntity[]; vectors: SceneVector[] } {
  const pose = shipPose(ship, side, shipXFt, standoff);
  const entities: SceneEntity[] = [];
  const vectors: SceneVector[] = [];
  for (const a of assignments) {
    const pp = ship.push_points?.find((p) => p.push_point_id === a.push_point_id);
    if (!pp) continue;
    const shipSideSign = pp.side === 'port' ? 1 : -1; // +y is port in the ship frame
    const lateral = ft(ship.beam_ft / 2) + TUG_LENGTH_M / 2 + 2;
    const [x, y] = entityToFrame(pose, ft(pp.x_ft), shipSideSign * lateral);
    const heading = pose.headingDeg + (shipSideSign > 0 ? -90 : 90);
    entities.push({
      id: `tug:${a.tug_id}:${a.push_point_id}`,
      kind: 'tug',
      label: a.tug_id,
      pose: { x, y, z: 0, headingDeg: heading },
      geometry: {
        type: 'polygon',
        points: [
          [-TUG_LENGTH_M / 2, -TUG_BEAM_M / 2],
          [TUG_LENGTH_M / 2 - 5, -TUG_BEAM_M / 2],
          [TUG_LENGTH_M / 2, 0],
          [TUG_LENGTH_M / 2 - 5, TUG_BEAM_M / 2],
          [-TUG_LENGTH_M / 2, TUG_BEAM_M / 2],
        ],
        heightM: 4,
      },
      color: '#e8a33d',
      selectable: true,
      props: [
        { label: 'Tug', value: a.tug_id },
        { label: 'Push point', value: a.push_point_id },
        { label: 'Mode', value: a.mode },
        { label: 'Force', value: fmt.lbf(a.force_lbf) },
        { label: 'Direction', value: a.direction_true_deg == null ? 'n/a' : `${fmt.deg(a.direction_true_deg)} true` },
      ],
    });
    entities.push({
      id: `wake:${a.tug_id}:${a.push_point_id}`,
      kind: 'wake',
      pose: { x, y, z: 0.06, headingDeg: heading },
      geometry: {
        type: 'polygon',
        points: [
          [-TUG_LENGTH_M / 2, -TUG_BEAM_M / 2],
          [-TUG_LENGTH_M / 2, TUG_BEAM_M / 2],
          [-TUG_LENGTH_M / 2 - 42, TUG_BEAM_M * 1.9],
          [-TUG_LENGTH_M / 2 - 42, -TUG_BEAM_M * 1.9],
        ],
        heightM: 0,
      },
      color: '#ffffff',
      opacity: 0.2,
      noOutline: true,
      selectable: true,
      selectsId: `tug:${a.tug_id}:${a.push_point_id}`,
    });
    if (a.direction_true_deg == null) continue;
    const angle = bearingToLocalAngle(frame, a.direction_true_deg);
    const len = Math.min(14 + a.force_lbf / 1800, 60);
    vectors.push({
      id: `tugforce:${a.tug_id}:${a.push_point_id}`,
      kind: 'tug-force',
      origin: { x, y, z: 6 },
      angleDeg: angle,
      lengthM: len,
      color: '#e8a33d',
      label: fmt.lbf(a.force_lbf),
    });
  }
  return { entities, vectors };
}

export function buildScene(input: SceneInput): SceneContent {
  const { berth, ship } = input;
  const frame = berthFrame(berth);
  const hasFittings = !!ship && (ship.fittings?.length ?? 0) > 0;
  const entities = pierEntities(berth, input.analysis);
  const links: SceneLink[] = [];
  let center = { x: ft(input.shipXFt), y: ft(60 + (ship?.beam_ft ?? 66)) };
  if (ship) {
    entities.push(
      ...shipEntities(ship, input.loading, input.side, input.shipXFt, input.standoffFt, input.analysis, hasFittings, berth),
    );
    links.push(...lineLinks(berth, ship, input.lines, input.analysis));
    center = { x: ft(input.shipXFt), y: ft(ship.beam_ft + input.standoffFt + 120) };
  }
  const tugs = ship && input.tugs?.length ? tugScene(ship, input.side, input.shipXFt, input.standoffFt, input.tugs, frame) : null;
  if (tugs) entities.push(...tugs.entities);
  entities.push(...envReadouts(input.env, center));
  return { frame, entities, links, vectors: [...envVectors(frame, input.env, center), ...(tugs?.vectors ?? [])] };
}
