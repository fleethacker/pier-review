import type { components } from '../../../api/modeling';
import type { ControlState, LoadingState, LineControlState } from './workspace';

/**
 * View model for the motion view. Frames arrive either as legacy `SimFrame`s (pose, tug forces, line tensions only) or
 * as `rm0-v1` frames (see docs/MOTION_FRAME_DESIGN.md). This adapter turns both into one shape without inventing
 * physics: an absent value is `null` ("unavailable"), never zero, and an absent validity is `unknown`, never valid.
 */

type S = components['schemas'];
export type SimFrame = S['SimFrame'];
export type SimScene = S['SimScene'];
export type SimLifecycle = S['SimLifecycle'];
export type SimRecording = S['SimRecording'];
export type Validity = S['Validity'];
export type Provenance = S['MotionProvenance'];

export type Availability = 'available' | 'unavailable' | 'not_simulated' | 'unknown';
export type ValidityState = Validity['state'];
export type ProvenanceKind = Provenance['kind'] | 'legacy';
export type Severity = 'INFO' | 'AMBER' | 'RED';

export interface Vec2 {
  x: number;
  y: number;
}

export interface Badge {
  validity: ValidityState;
  reasons: string[];
  provenance: ProvenanceKind;
  provenanceSource: string | null;
}

export interface ViewShip {
  x_ft: number;
  y_ft: number;
  /** Counterclockwise from berth +x. */
  yawDeg: number;
  headingTrueDeg: number;
  heaveMllwFt: number | null;
  rollDeg: number | null;
  pitchDeg: number | null;
  /** Per-axis: simulated, prescribed, not_simulated or unknown. Empty for legacy frames. */
  dofs: Record<string, string>;
  /** Ship-axes velocity, ft/s. */
  surgeFps: number | null;
  swayFps: number | null;
  yawDegps: number | null;
  surgeFps2: number | null;
  swayFps2: number | null;
}

export interface ViewTug {
  id: string;
  position: Vec2 | null;
  headingTrueDeg: number | null;
  velocity: Vec2 | null;
  acceleration: Vec2 | null;
  commandedForce: Vec2 | null;
  actualForce: Vec2 | null;
  /** Legacy frames carry only a scalar force and a direction relative to the ship. */
  legacyForceLbf: number | null;
  legacyDirectionRelDeg: number | null;
  mode: string;
  contactState: string;
  utilizationPct: number | null;
  pushPointId: string | null;
  availability: Availability;
  badge: Badge | null;
}

export type LineStatus = 'slack' | 'taut' | 'overloaded' | 'unknown';

export interface ViewLine {
  lineNumber: number;
  tensionLbf: number | null;
  status: LineStatus;
  shipEnd: Vec2 | null;
  pierEnd: Vec2 | null;
  polyline: Vec2[] | null;
  shipFittingId: string | null;
  pierFittingId: string | null;
  availability: Availability;
}

export interface ViewFitting {
  id: string;
  owner: 'ship' | 'pier';
  loadLbf: number | null;
  capacityLbf: number | null;
  utilizationPct: number | null;
  status: 'GREEN' | 'AMBER' | 'RED' | null;
}

export interface ViewFender {
  id: string;
  compressionFt: number | null;
  reactionLbf: number | null;
  status: 'GREEN' | 'AMBER' | 'RED' | null;
  availability: Availability;
}

export interface ViewEnvPart {
  available: boolean;
  availability: Availability;
  source: string | null;
  basis: string | null;
  /** Seconds since the source issued it, when supplied. */
  ageS: number | null;
  provenance: ProvenanceKind;
}

export interface ViewEnvironment {
  validAtUtc: string | null;
  wind: ViewEnvPart & { speedKt: number | null; gustKt: number | null; fromTrueDeg: number | null };
  current: ViewEnvPart & { speedKt: number | null; setTrueDeg: number | null };
  water: ViewEnvPart & { levelMllwFt: number | null };
  waves: {
    key: 'ocean_swell' | 'local_chop' | 'ship_wake' | 'tug_wake';
    label: string;
    part: ViewEnvPart;
    heightFt: number | null;
    heightBasis: string;
    periodS: number | null;
    fromTrueDeg: number | null;
  }[];
}

export type ForceKey = 'wind' | 'current' | 'wave' | 'tugs' | 'lines' | 'fenders';

export interface ViewForce {
  key: ForceKey;
  label: string;
  /** Berth-frame vector, lbf. Null means unavailable (not zero). */
  force: Vec2 | null;
  yawMomentFtLbf: number | null;
  availability: Availability;
}

export interface ViewAlert {
  code: string | null;
  severity: Severity | null;
  message: string;
  elementIds: string[];
}

export interface ViewFrame {
  rm0: boolean;
  tS: number;
  sequence: number | null;
  runId: string | null;
  sessionId: string | null;
  sceneId: string | null;
  sceneRevision: string | null;
  badge: Badge;
  ship: ViewShip;
  tugs: ViewTug[];
  lines: ViewLine[];
  fittings: ViewFitting[];
  fenders: ViewFender[];
  environment: ViewEnvironment | null;
  forces: ViewForce[];
  alerts: ViewAlert[];
  /** True when the berth face bearing was not supplied and the adapter had to assume one. */
  assumedFaceBearing: boolean;
  controls: ControlState | null;
  loading: LoadingState | null;
  lineControls: LineControlState[];
}

export const DEFAULT_FACE_BEARING = 90;

const norm = (deg: number) => ((deg % 360) + 360) % 360;

export function isRm0(frame: SimFrame): boolean {
  return frame.schema_version === 'rm0-v1';
}

export function badgeOf(validity: Validity | null | undefined, provenance: Provenance | null | undefined): Badge {
  return {
    validity: validity?.state ?? 'unknown',
    reasons: (validity?.reasons ?? []).map((r) => r.message || r.code),
    provenance: provenance?.kind ?? 'unknown',
    provenanceSource: provenance?.source ?? null,
  };
}

/** Legacy frames have neither validity nor provenance: say so instead of implying "valid" or "mock". */
const LEGACY_BADGE: Badge = { validity: 'unknown', reasons: [], provenance: 'legacy', provenanceSource: null };

function vec(v: { x_ft?: number | null; y_ft?: number | null } | null | undefined): Vec2 | null {
  if (!v || v.x_ft == null || v.y_ft == null) return null;
  return { x: v.x_ft, y: v.y_ft };
}

function force(v: { x_lbf?: number | null; y_lbf?: number | null } | null | undefined): Vec2 | null {
  if (!v || v.x_lbf == null || v.y_lbf == null) return null;
  return { x: v.x_lbf, y: v.y_lbf };
}

function velocity(v: { x_fps?: number | null; y_fps?: number | null } | null | undefined): Vec2 | null {
  if (!v || v.x_fps == null || v.y_fps == null) return null;
  return { x: v.x_fps, y: v.y_fps };
}

function acceleration(v: { x_fps2?: number | null; y_fps2?: number | null } | null | undefined): Vec2 | null {
  if (!v || v.x_fps2 == null || v.y_fps2 == null) return null;
  return { x: v.x_fps2, y: v.y_fps2 };
}

function envPart(
  p:
    | {
        availability: Availability;
        provenance?: Provenance | null;
        metadata?: { source?: string | null; basis?: string | null; age_s?: number | null } | null;
      }
    | null
    | undefined,
): ViewEnvPart {
  const availability = p?.availability ?? 'unknown';
  return {
    available: availability === 'available',
    availability,
    source: p?.metadata?.source ?? p?.provenance?.source ?? null,
    basis: p?.metadata?.basis ?? null,
    ageS: p?.metadata?.age_s ?? null,
    provenance: p?.provenance?.kind ?? 'unknown',
  };
}

// Every field is read through a helper that treats "not available" as null, so an unavailable value cannot leak as 0.
function whenAvailable<T>(part: { availability: Availability }, value: T | null | undefined): T | null {
  return part.availability === 'available' && value != null ? value : null;
}

const WAVE_LABELS: Record<ViewEnvironment['waves'][number]['key'], string> = {
  ocean_swell: 'Ocean swell',
  local_chop: 'Local chop',
  ship_wake: 'Ship wake',
  tug_wake: 'Tug wake',
};

function adaptEnvironment(env: S['MotionEnvironment'] | null | undefined): ViewEnvironment | null {
  if (!env) return null;
  const wind = envPart(env.wind);
  const current = envPart(env.current);
  const water = envPart(env.water);
  return {
    validAtUtc: env.valid_at_utc ?? null,
    wind: {
      ...wind,
      speedKt: whenAvailable(wind, env.wind?.speed_kt),
      gustKt: whenAvailable(wind, env.wind?.gust_kt),
      fromTrueDeg: whenAvailable(wind, env.wind?.from_true_deg),
    },
    current: {
      ...current,
      speedKt: whenAvailable(current, env.current?.speed_kt),
      setTrueDeg: whenAvailable(current, env.current?.set_true_deg),
    },
    water: { ...water, levelMllwFt: whenAvailable(water, env.water?.level_mllw_ft) },
    waves: (Object.keys(WAVE_LABELS) as (keyof typeof WAVE_LABELS)[]).map((key) => {
      const w = env.waves?.[key];
      const part = envPart(w);
      return {
        key,
        label: WAVE_LABELS[key],
        part,
        heightFt: whenAvailable(part, w?.height_ft),
        heightBasis: w?.height_basis ?? 'unknown',
        periodS: whenAvailable(part, w?.period_s),
        fromTrueDeg: whenAvailable(part, w?.from_true_deg),
      };
    }),
  };
}

const FORCE_ROWS: { key: ForceKey; label: string }[] = [
  { key: 'wind', label: 'Wind' },
  { key: 'current', label: 'Current' },
  { key: 'wave', label: 'Waves' },
  { key: 'tugs', label: 'Tugs' },
  { key: 'lines', label: 'Lines' },
  { key: 'fenders', label: 'Fenders' },
];

const usableValidity = (validity: Validity | null | undefined) => validity?.state === 'valid' || validity?.state === 'limited';

function adaptForces(forces: S['MotionForces'] | null | undefined): ViewForce[] {
  if (!forces) return [];
  const wave = (() => {
    // Waves are four separate components; sum only the available ones and flag the total unavailable if none is.
    const parts = Object.values(forces.waves ?? {}).filter(
      (c): c is NonNullable<typeof c> => !!c && (c as { availability: Availability }).availability === 'available',
    );
    const vecs = parts.map((c) => force((c as { force?: { x_lbf?: number | null; y_lbf?: number | null } | null }).force));
    if (!parts.length || parts.some((c) => !usableValidity(c.validity)) || vecs.some((v) => v === null)) return null;
    return vecs.reduce<Vec2>((a, v) => ({ x: a.x + v!.x, y: a.y + v!.y }), { x: 0, y: 0 });
  })();
  return FORCE_ROWS.map(({ key, label }) => {
    if (key === 'wave') {
      return { key, label, force: wave, yawMomentFtLbf: null, availability: wave ? 'available' : 'unavailable' };
    }
    const w = forces[key] as
      | { availability: Availability; validity?: Validity | null; force?: { x_lbf?: number | null; y_lbf?: number | null } | null; yaw_moment_ftlbf?: number | null }
      | null
      | undefined;
    const availability = w?.availability === 'available' && !usableValidity(w.validity) ? 'unavailable' : w?.availability ?? 'unavailable';
    return {
      key,
      label,
      force: whenAvailable({ availability }, force(w?.force)),
      yawMomentFtLbf: whenAvailable({ availability }, w?.yaw_moment_ftlbf),
      availability,
    };
  });
}

export interface AdaptOptions {
  /** True bearing of berth +x, from the scene. Needed to turn legacy headings into berth-frame yaw. */
  faceBearingDeg?: number | null;
}

export function adaptFrame(frame: SimFrame, opts: AdaptOptions = {}): ViewFrame {
  const rm0 = isRm0(frame);
  const usable = usableValidity(frame.validity);
  const usableComponent = (c: { availability: Availability; validity?: Validity | null }) =>
    usable && c.availability === 'available' && usableValidity(c.validity);
  const assumed = opts.faceBearingDeg == null;
  const face = opts.faceBearingDeg ?? DEFAULT_FACE_BEARING;
  const motion = frame.motion ?? null;

  // Ship pose: prefer the rich motion block; fall back to the legacy pose projection.
  const mp = motion?.pose;
  const ship: ViewShip = (() => {
    if (mp && mp.x_ft != null && mp.y_ft != null && mp.yaw_deg != null) {
      return {
        x_ft: mp.x_ft,
        y_ft: mp.y_ft,
        yawDeg: mp.yaw_deg,
        headingTrueDeg: norm(face - mp.yaw_deg),
        heaveMllwFt: ['simulated', 'prescribed'].includes(motion!.dofs.heave) ? mp.heave_mllw_ft ?? null : null,
        rollDeg: ['simulated', 'prescribed'].includes(motion!.dofs.roll) ? mp.roll_deg ?? null : null,
        pitchDeg: ['simulated', 'prescribed'].includes(motion!.dofs.pitch) ? mp.pitch_deg ?? null : null,
        dofs: { ...(motion!.dofs as unknown as Record<string, string>) },
        surgeFps: motion!.velocity.surge_fps ?? null,
        swayFps: motion!.velocity.sway_fps ?? null,
        yawDegps: motion!.velocity.yaw_degps ?? null,
        surgeFps2: motion!.acceleration?.surge_fps2 ?? null,
        swayFps2: motion!.acceleration?.sway_fps2 ?? null,
      };
    }
    return {
      x_ft: frame.pose.x_ft,
      y_ft: frame.pose.y_ft,
      yawDeg: face - frame.pose.heading_true_deg,
      headingTrueDeg: norm(frame.pose.heading_true_deg),
      heaveMllwFt: null,
      rollDeg: null,
      pitchDeg: null,
      dofs: {},
      surgeFps: null,
      swayFps: null,
      yawDegps: null,
      surgeFps2: null,
      swayFps2: null,
    };
  })();

  const richTugs = frame.tug_states ?? null;
  const tugs: ViewTug[] = richTugs
    ? richTugs.map((t) => ({
        id: t.tug_id,
        position: vec(t.position),
        headingTrueDeg: t.heading_true_deg ?? null,
        velocity: velocity(t.velocity),
        acceleration: acceleration(t.acceleration),
        commandedForce: force(t.commanded_force),
        actualForce: usableComponent(t) ? force(t.actual_force) : null,
        legacyForceLbf: usableComponent(t) ? frame.tugs.find((l) => l.tug_id === t.tug_id)?.force_lbf ?? null : null,
        legacyDirectionRelDeg: frame.tugs.find((l) => l.tug_id === t.tug_id)?.direction_rel_deg ?? null,
        mode: t.mode,
        contactState: t.contact_state,
        utilizationPct: usableComponent(t) ? t.capacity_utilization_pct ?? null : null,
        pushPointId: t.push_point_id ?? null,
        availability: t.availability,
        badge: badgeOf(t.validity, t.provenance),
      }))
    : frame.tugs.map((t) => ({
        id: t.tug_id,
        position: null,
        headingTrueDeg: null,
        velocity: null,
        acceleration: null,
        commandedForce: null,
        actualForce: null,
        legacyForceLbf: t.force_lbf,
        legacyDirectionRelDeg: t.direction_rel_deg,
        mode: 'unknown',
        contactState: 'unknown',
        utilizationPct: null,
        pushPointId: null,
        availability: 'unknown' as Availability,
        badge: null,
      }));

  const richLines = frame.line_states ?? null;
  const lines: ViewLine[] = richLines
    ? richLines.map((l) => ({
        lineNumber: l.line_number,
        tensionLbf: usableComponent(l) ? (l.tension_lbf ?? null) : null,
        status: usableComponent(l) ? l.status : 'unknown',
        shipEnd: vec(l.ship_end),
        pierEnd: vec(l.pier_end),
        polyline: l.polyline ? (l.polyline.map(vec).filter((p): p is Vec2 => p !== null) as Vec2[]) : null,
        shipFittingId: l.ship_fitting_id ?? null,
        pierFittingId: l.pier_fitting_id ?? null,
        availability: l.availability,
      }))
    : frame.lines.map((l) => ({
        lineNumber: l.line_number,
        tensionLbf: usable ? l.tension_lbf : null,
        status: 'unknown' as LineStatus,
        shipEnd: null,
        pierEnd: null,
        polyline: null,
        shipFittingId: null,
        pierFittingId: null,
        availability: 'unknown' as Availability,
      }));

  const fenders: ViewFender[] = frame.fender_states
    ? frame.fender_states.map((f) => ({
        id: f.fender_id,
        compressionFt: usableComponent(f) ? (f.compression_ft ?? null) : null,
        reactionLbf: usableComponent(f) ? (f.reaction_lbf ?? null) : null,
        status: usableComponent(f) ? f.status ?? null : null,
        availability: f.availability,
      }))
    : frame.fenders.map((f) => ({
        id: f.fender_id,
        compressionFt: usable ? f.compression_ft : null,
        reactionLbf: usable ? f.reaction_lbf : null,
        status: usable ? f.status : null,
        availability: 'unknown' as Availability,
      }));

  const alerts: ViewAlert[] = frame.structured_alerts?.length
    ? frame.structured_alerts.map((a) => ({
        code: a.code,
        severity: a.severity,
        message: a.message,
        elementIds: a.element_ids ?? [],
      }))
    : // Legacy strings carry no severity; do not guess one.
      frame.alerts.map((message) => ({ code: null, severity: null, message, elementIds: [] }));

  return {
    rm0,
    tS: frame.t_s,
    sequence: frame.sequence ?? null,
    runId: frame.run_id ?? null,
    sessionId: frame.session_id ?? null,
    sceneId: frame.scene_id ?? null,
    sceneRevision: frame.scene_revision ?? null,
    badge: rm0 ? badgeOf(frame.validity, frame.provenance) : { ...LEGACY_BADGE, ...(frame.validity ? badgeOf(frame.validity, frame.provenance) : {}) },
    ship,
    tugs: usable ? tugs : tugs.map((t) => ({ ...t, actualForce: null, legacyForceLbf: null, utilizationPct: null })),
    lines,
    fittings: (frame.fitting_loads ?? []).map((f) => ({
      id: f.fitting_id,
      owner: f.owner,
      loadLbf: usableComponent(f) ? (f.load_lbf ?? null) : null,
      capacityLbf: f.capacity_lbf ?? null,
      utilizationPct: usableComponent(f) ? (f.utilization_pct ?? null) : null,
      status: usableComponent(f) ? f.status ?? null : null,
    })),
    fenders,
    environment: adaptEnvironment(frame.environment),
    forces: adaptForces(usable ? frame.forces : null),
    alerts,
    assumedFaceBearing: assumed && !rm0,
    controls: frame.controls ?? null,
    loading: frame.loading ?? null,
    lineControls: frame.line_controls ?? [],
  };
}

// ---- geometry -----------------------------------------------------------------------------------------------

/** Ship-local point (origin midships) to berth axes: rotate by yaw counterclockwise, then translate. */
export function shipToBerth(p: { x_ft?: number | null; y_ft?: number | null }, ship: Pick<ViewShip, 'x_ft' | 'y_ft' | 'yawDeg'>): Vec2 {
  const a = (ship.yawDeg * Math.PI) / 180;
  const x = p.x_ft ?? 0;
  const y = p.y_ft ?? 0;
  return {
    x: ship.x_ft + x * Math.cos(a) - y * Math.sin(a),
    y: ship.y_ft + x * Math.sin(a) + y * Math.cos(a),
  };
}

/**
 * Angle in the berth frame (counterclockwise from +x, degrees) of a true bearing. Bearings run clockwise and berth
 * +x points along `faceBearingDeg`, so the angle is face - bearing.
 */
export function bearingToBerthAngle(bearingTrueDeg: number, faceBearingDeg: number): number {
  return faceBearingDeg - bearingTrueDeg;
}

/** Unit vector in berth axes pointing TOWARD the given true bearing. */
export function towardBearing(bearingTrueDeg: number, faceBearingDeg: number): Vec2 {
  const a = (bearingToBerthAngle(bearingTrueDeg, faceBearingDeg) * Math.PI) / 180;
  return { x: Math.cos(a), y: Math.sin(a) };
}

/** Wind direction is FROM, current set is TOWARD: return the way each arrow points. */
export function windArrow(fromTrueDeg: number, faceBearingDeg: number): Vec2 {
  return towardBearing(fromTrueDeg + 180, faceBearingDeg);
}

export function currentArrow(setTrueDeg: number, faceBearingDeg: number): Vec2 {
  return towardBearing(setTrueDeg, faceBearingDeg);
}

// ---- parsing ------------------------------------------------------------------------------------------------

/** Anything a /ws/sim socket may deliver. */
export type SimMessage = { kind: 'frame'; frame: SimFrame } | { kind: 'lifecycle'; lifecycle: SimLifecycle } | { kind: 'unknown' };

export function parseSimMessage(raw: unknown): SimMessage {
  if (!raw || typeof raw !== 'object') return { kind: 'unknown' };
  const m = raw as Record<string, unknown>;
  if (m.type === 'session_lifecycle') return { kind: 'lifecycle', lifecycle: raw as SimLifecycle };
  if (typeof m.t_s === 'number' && m.pose && typeof m.pose === 'object') return { kind: 'frame', frame: raw as SimFrame };
  return { kind: 'unknown' };
}

/** Index of the last frame at or before `tS`; frames are ordered by time within a run. */
export function frameIndexAt(frames: { t_s: number }[], tS: number): number {
  if (!frames.length) return -1;
  let lo = 0;
  let hi = frames.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (frames[mid].t_s <= tS) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** Colour band for a load against its capacity; null when either is missing (never assume zero). */
export function utilizationStatus(load: number | null, capacity: number | null): 'GREEN' | 'AMBER' | 'RED' | null {
  if (load == null || capacity == null || capacity <= 0) return null;
  const u = Math.abs(load) / capacity;
  return u >= 1 ? 'RED' : u >= 0.6 ? 'AMBER' : 'GREEN';
}
