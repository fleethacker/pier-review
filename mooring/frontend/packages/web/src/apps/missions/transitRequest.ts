import type { TransitRequest, VesselTransit } from './types';

function mapVessel(req: TransitRequest, idx: number, fn: (v: VesselTransit) => VesselTransit): TransitRequest {
  return { ...req, vessels: req.vessels.map((v, i) => (i === idx ? fn(v) : v)) };
}

/** Switching to own_thrust must drop tug data: the server rejects own_thrust with tug commands or assist. */
export function setVesselMode(req: TransitRequest, idx: number, mode: VesselTransit['mode']): TransitRequest {
  return mapVessel(req, idx, (v) => {
    if (mode === 'own_thrust') {
      const rest = { ...v, mode };
      delete rest.tug_assist;
      return { ...rest, tug_commands: [] };
    }
    return { ...v, mode, tug_assist: v.tug_assist ?? { policy: 'auto', tug_ids: [], assist_below_kt: 5 } };
  });
}

export function setMaxSpeed(req: TransitRequest, idx: number, kt: number | null): TransitRequest {
  return mapVessel(req, idx, (v) => ({ ...v, propulsion: { ...v.propulsion, max_speed_kt: kt } as VesselTransit["propulsion"] }));
}

export function setRouteSpeed(req: TransitRequest, idx: number, wp: number, kt: number): TransitRequest {
  return mapVessel(req, idx, (v) => ({ ...v, route: v.route.map((w, j) => (j === wp ? { ...w, speed_kt: kt } : w)) }));
}

/** Parse the JSON editor text; returns the request or a readable error. Only structural checks; the server validates the rest. */
export function parseRequestText(text: string): { request: TransitRequest } | { error: string } {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (e) {
    return { error: `Not valid JSON: ${e instanceof Error ? e.message : String(e)}` };
  }
  const r = data as Partial<TransitRequest> | null;
  if (!r || typeof r !== 'object' || !Array.isArray(r.vessels) || r.vessels.length === 0) return { error: 'The request needs a non-empty "vessels" list.' };
  for (const v of r.vessels) {
    if (!v || typeof v.vessel_id !== 'string' || !Array.isArray(v.route) || v.route.length === 0 || !v.start) return { error: 'Each vessel needs vessel_id, start and a non-empty route.' };
  }
  return { request: r as TransitRequest };
}
