import { ApiError, serviceUrl } from './api';
import { authHeaders } from '../mooring/api';
import { samplePredictRequest, samplePrediction } from './fixtures';
import type { Projector } from './scene';
import type { SceneEntity, SceneLink } from '../../scene/types';
import type {
  ObservedShipState,
  PredictionAlternative,
  PredictionRequest,
  PredictionResponse,
  TransitTugState,
  TransitVesselState,
  WhatIf,
} from './types';

export const CAMERA_DISCLAIMER =
  'surrogate maneuvering model; decision support, not navigational guidance';
export const CAMERA_BERTH = 'NAVSTA-NORFOLK-P12-N';
export const REFRESH_MIN_MS = 1000;
export const FOOTPRINT_EVERY_S = 30;
export const HOLD_ID = 'hold';

export const WHAT_IFS: { id: string; label: string; alt: WhatIf }[] = [
  {
    id: 'rudder-port-15',
    label: 'Rudder 15° port',
    alt: {
      alt_id: 'rudder-port-15',
      label: 'Rudder 15 deg port',
      helm_commands: [{ t_s: 0, rudder_deg: 15 }],
      tug_commands: [],
    },
  },
  {
    id: 'rudder-stbd-15',
    label: 'Rudder 15° stbd',
    alt: {
      alt_id: 'rudder-stbd-15',
      label: 'Rudder 15 deg starboard',
      helm_commands: [{ t_s: 0, rudder_deg: -15 }],
      tug_commands: [],
    },
  },
  {
    id: 'engine-astern-half',
    label: 'Engine astern half',
    alt: {
      alt_id: 'engine-astern-half',
      label: 'Engine astern half',
      helm_commands: [{ t_s: 0, engine_order: -0.5 }],
      tug_commands: [],
    },
  },
  {
    id: 'tug-push-stbd',
    label: 'Tug push to starboard (port shoulder)',
    alt: {
      alt_id: 'tug-push-stbd',
      label: 'Tug pushes to starboard at the port shoulder',
      helm_commands: [],
      tug_commands: [
        { t_s: 0, tug_id: 'T1', point: 'port_shoulder', force_lbf: 30000, direction_rel_deg: 90 },
      ],
    },
  },
];

/** TransitVesselState -> ObservedShipState. Same sign conventions on both sides: sway + port, yaw + CCW, rudder + port. */
export function toObservedState(
  v: TransitVesselState,
  shipClassId: string,
  observedUtc: string,
  job: string,
): ObservedShipState {
  return {
    vessel_id: v.vessel_id,
    ship_class_id: shipClassId,
    loading: 'full_load',
    observed_utc: observedUtc,
    position: { lat: v.lat, lon: v.lon },
    heading_true_deg: ((v.heading_true_deg % 360) + 360) % 360,
    surge_kt: v.u_kt ?? v.stw_kt,
    sway_kt: v.v_kt,
    yaw_rate_degps: v.r_degps,
    rudder_deg: Math.max(-45, Math.min(45, v.rudder_deg)),
    engine_order: Math.max(-1, Math.min(1, v.engine_order)),
    tugs: (v.tugs ?? [])
      .slice(0, 4)
      .map((t: TransitTugState) => ({
        tug_id: t.tug_id,
        point: t.point,
        force_lbf: t.force_lbf,
        direction_rel_deg: ((t.direction_rel_deg % 360) + 360) % 360,
      })),
    source: `sim:${job}`,
  };
}

export interface BuildOpts {
  whatIfId?: string | null;
  samples?: number;
  asOfUtc?: string;
}

/** Request with 'hold' implicit plus, when chosen, one what-if. The what-if buttons pick one at a time. */
export function buildPredictionRequest(
  vessel: ObservedShipState,
  o: BuildOpts = {},
): PredictionRequest {
  const w = WHAT_IFS.find((x) => x.id === o.whatIfId);
  return {
    vessel,
    as_of_utc: o.asOfUtc ?? vessel.observed_utc,
    horizon_s: 300,
    tick_s: 10,
    dt_s: 0.2,
    alternatives: w ? [structuredClone(w.alt)] : [],
    uncertainty: { samples: o.samples ?? 8, seed: 7, model: 's10_gust_current', percentile: 90 },
    hazards: { berth_id: CAMERA_BERTH, coastline: true, min_clearance_ft: 50 },
  };
}

/** Preset request with the what-if replacing its alternatives; the preset's other settings are kept. */
export function withWhatIf(base: PredictionRequest, whatIfId: string | null): PredictionRequest {
  const w = WHAT_IFS.find((x) => x.id === whatIfId);
  return {
    ...structuredClone(base),
    alternatives: w ? [structuredClone(w.alt)] : structuredClone(base.alternatives ?? []),
  };
}

export function bannerText(alt: PredictionAlternative | undefined): {
  text: string;
  level: 'breach' | 'ok' | 'none';
} {
  if (!alt) return { text: 'No prediction yet.', level: 'none' };
  const b = alt.first_breach;
  if (b) {
    const p = b.probability != null ? `, ${Math.round(b.probability * 100)}% of samples` : '';
    return {
      text: `Predicted ${b.kind === 'pier' || b.kind === 'fender' ? 'pier' : b.kind} contact in ${Math.round(b.t_s)} s (clearance ${Math.round(b.clearance_ft)} ft${p})`,
      level: 'breach',
    };
  }
  const c = alt.closest_approach;
  if (c)
    return {
      text: `Closest approach ${Math.round(c.clearance_ft)} ft at +${Math.round(c.t_s)} s`,
      level: 'ok',
    };
  return { text: 'No hazard approach reported.', level: 'none' };
}

export function limitedText(res: PredictionResponse): string {
  const age = Math.round(res.result.input_age_s);
  const state = res.validity?.state ?? 'unknown';
  const label = state.charAt(0).toUpperCase() + state.slice(1);
  return `${label}: ${CAMERA_DISCLAIMER}; inputs ${age} s old`;
}

export function missingHazards(res: PredictionResponse): string[] {
  const checked = new Set<string>(res.result.hazards_checked);
  return (['coastline'] as const).filter((k) => !checked.has(k));
}

export interface CameraLook {
  holdColor: string;
  selectedColor: string;
  dimColor: string;
}
const LOOK: CameraLook = { holdColor: '#22d3ee', selectedColor: '#fb923c', dimColor: '#64748b' };
export const CAMERA_KINDS = ['cam-label', 'cam-breach', 'cam-closest'];

/** Map content for a prediction: centre paths, footprints every 30 s with labels, corridor, closest approach and breach markers. */
export function cameraContent(
  res: PredictionResponse,
  p: Projector,
  selectedAlt: string | null,
): { entities: SceneEntity[]; links: SceneLink[] } {
  const entities: SceneEntity[] = [];
  const links: SceneLink[] = [];
  const xy = (q: { lat: number; lon: number }) => ({ ...p.toXY(q.lat, q.lon), z: 0 });
  const ring = (
    id: string,
    kind: string,
    pts: { lat: number; lon: number }[],
    color: string,
    w: number,
  ) => {
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i];
      const b = pts[(i + 1) % pts.length];
      links.push({ id: `${id}:${i}`, kind, from: xy(a), to: xy(b), color, widthPx: w });
    }
  };
  for (const alt of res.result.alternatives) {
    const isHold = alt.alt_id === HOLD_ID;
    const isSel = alt.alt_id === selectedAlt;
    const color = isHold ? LOOK.holdColor : isSel ? LOOK.selectedColor : LOOK.dimColor;
    const w = isHold || isSel ? 3 : 1;
    alt.ticks
      .slice(1)
      .forEach((t, i) =>
        links.push({
          id: `cam-path:${alt.alt_id}:${i}`,
          kind: 'cam-path',
          from: xy(alt.ticks[i].position),
          to: xy(t.position),
          color,
          widthPx: w,
        }),
      );
    if (!(isHold || isSel)) continue;
    if (alt.corridor && alt.corridor.length > 2)
      ring(`cam-corr:${alt.alt_id}`, 'cam-corridor', alt.corridor, color, 1);
    alt.ticks.forEach((t) => {
      if (t.t_s % FOOTPRINT_EVERY_S !== 0) return;
      ring(`cam-fp:${alt.alt_id}:${t.t_s}`, 'cam-footprint', t.footprint, color, 2);
      if (t.t_s > 0) {
        const lbl = t.footprint[0];
        entities.push({
          id: `cam-label:${alt.alt_id}:${t.t_s}`,
          kind: 'cam-label',
          label: `+${Math.round(t.t_s)}s`,
          labelAlways: true,
          pose: { ...xy(lbl), headingDeg: 0 },
          geometry: { type: 'point', sizePx: 4 },
          color,
          selectable: false,
        });
      }
    });
    if (alt.closest_approach) {
      const c = alt.closest_approach;
      entities.push({
        id: `cam-closest:${alt.alt_id}`,
        kind: 'cam-closest',
        label: `${alt.alt_id}: ${Math.round(c.clearance_ft)} ft at +${Math.round(c.t_s)}s`,
        labelAlways: isHold,
        pose: { ...xy(c.position), headingDeg: 0 },
        geometry: { type: 'point', sizePx: 9 },
        color: '#facc15',
        selectable: false,
      });
    }
    if (alt.first_breach) {
      const b = alt.first_breach;
      entities.push({
        id: `cam-breach:${alt.alt_id}`,
        kind: 'cam-breach',
        label: `CONTACT +${Math.round(b.t_s)}s`,
        labelAlways: true,
        pose: { ...xy(b.position), headingDeg: 0 },
        geometry: { type: 'point', sizePx: 16 },
        color: '#ef4444',
        selectable: false,
      });
    }
  }
  return { entities, links };
}

/** Translucent corridor polygon as one entity per alternative (polygon geometry is local to the pose). */
export function corridorEntities(
  res: PredictionResponse,
  p: Projector,
  selectedAlt: string | null,
): SceneEntity[] {
  const out: SceneEntity[] = [];
  for (const alt of res.result.alternatives) {
    if (!alt.corridor || alt.corridor.length < 3) continue;
    if (alt.alt_id !== HOLD_ID && alt.alt_id !== selectedAlt) continue;
    const pts = alt.corridor.map((q) => p.toXY(q.lat, q.lon));
    const o = pts[0];
    out.push({
      id: `cam-corridor:${alt.alt_id}`,
      kind: 'cam-corridor',
      pose: { x: o.x, y: o.y, z: 0, headingDeg: 0 },
      geometry: {
        type: 'polygon',
        points: pts.map((q) => [q.x - o.x, q.y - o.y] as [number, number]),
        heightM: 0,
      },
      color: alt.alt_id === HOLD_ID ? LOOK.holdColor : LOOK.selectedColor,
      opacity: 0.18,
      noOutline: true,
      selectable: false,
    });
  }
  return out;
}

export function cameraFitPoints(res: PredictionResponse): { lat: number; lon: number }[] {
  return res.result.alternatives.flatMap((a) => a.ticks.map((t) => t.position));
}

export const CAMERA_ALL_KINDS = [...CAMERA_KINDS, 'cam-corridor'];

/** POST the prediction. Aborts on `signal`. 501/unreachable are for the caller to turn into the sample. */
export async function postPrediction(
  req: PredictionRequest,
  signal?: AbortSignal,
): Promise<PredictionResponse> {
  const res = await fetch(serviceUrl('/api/v1/predict/trajectory'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
    signal,
  });
  if (!res.ok) throw new ApiError(res.status, `${res.status} /api/v1/predict/trajectory`);
  return (await res.json()) as PredictionResponse;
}

export async function fetchPredictPresets(): Promise<
  { preset_id: string; title: string; request: PredictionRequest }[]
> {
  const res = await fetch(serviceUrl('/api/v1/predict/presets'), { headers: authHeaders() });
  if (!res.ok) throw new ApiError(res.status, `${res.status} /api/v1/predict/presets`);
  return (await res.json()) as { preset_id: string; title: string; request: PredictionRequest }[];
}

export const SAMPLE_PRESET = {
  preset_id: 'sample',
  title: 'Contract example (sample)',
  request: samplePredictRequest,
};
export { samplePrediction };

export function selectedAltId(
  res: PredictionResponse | null,
  whatIf: string | null,
): string | null {
  if (!res) return null;
  const alts = res.result.alternatives.filter((a) => a.alt_id !== HOLD_ID);
  return alts.find((a) => a.alt_id === whatIf)?.alt_id ?? alts[0]?.alt_id ?? null;
}

/**
 * At most one request in flight and at most one per REFRESH_MIN_MS. A call while one is in flight or too soon is
 * dropped (never queued); the next playback tick asks again. `force` cancels the in-flight request (a what-if change).
 */
export class PredictionThrottle {
  private ctl: AbortController | null = null;
  private last = -Infinity;
  constructor(
    private now: () => number = Date.now,
    private minMs: number = REFRESH_MIN_MS,
  ) {}
  get inFlight(): boolean {
    return this.ctl != null;
  }
  async run<T>(
    fn: (signal: AbortSignal) => Promise<T>,
    force = false,
  ): Promise<{ ran: boolean; value?: T; aborted?: boolean }> {
    const t = this.now();
    if (!force && (this.ctl || t - this.last < this.minMs)) return { ran: false };
    this.ctl?.abort();
    const ctl = new AbortController();
    this.ctl = ctl;
    this.last = t;
    try {
      const value = await fn(ctl.signal);
      return ctl.signal.aborted ? { ran: true, aborted: true } : { ran: true, value };
    } finally {
      if (this.ctl === ctl) this.ctl = null;
    }
  }
  cancel(): void {
    this.ctl?.abort();
    this.ctl = null;
  }
}
