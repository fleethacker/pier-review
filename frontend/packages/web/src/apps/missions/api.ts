import { MODELING_BASE, authHeaders, awaitJob } from '../mooring/api';
import type {
  JobAccepted,
  Mission,
  MissionCreate,
  MissionTrack,
  MediaItem,
  MediaMetadata,
  Report,
  ReportCreate,
  Storyboard,
  TrackFix,
  TrackFormat,
  TrackIngestResult,
  TransitPreset,
  TransitRequest,
  TransitResponse,
  TransitSeries,
} from './types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** The backend is not implemented yet (501), not routed (5xx from the proxy) or not reachable at all. */
export function isUnavailable(e: unknown): boolean {
  if (e instanceof ApiError) return e.status >= 500;
  const text = e instanceof Error ? e.message : String(e);
  return e instanceof TypeError || /Failed to fetch|NetworkError|Load failed|ECONNREFUSED/i.test(text);
}

/** Resolve a service-rooted path ("/api/v1/...") through the configured proxy prefix, like job status URLs. */
export function serviceUrl(path: string, base: string = MODELING_BASE): string {
  if (/^(https?:|data:|blob:)/.test(path)) return path;
  const u = new URL(base);
  return `${u.origin}${u.pathname.replace(/\/$/, '')}${path}`;
}

async function request<T>(method: string, path: string, body?: { json?: unknown; form?: FormData }, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders() };
  let payload: BodyInit | undefined;
  if (body?.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body.json);
  } else if (body?.form) {
    payload = body.form; // the browser sets the multipart boundary
  }
  const res = await fetch(serviceUrl(path), { method, headers, body: payload, signal });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = JSON.stringify(await res.json()).slice(0, 300);
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, `${res.status} ${path}: ${detail}`);
  }
  return (await res.json()) as T;
}

/** Fetch protected mission resources with the same bearer credentials as JSON calls.
 * Never attach a token to an off-service URL returned in response data, or follow redirects.
 */
export async function fetchMissionBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const url = new URL(serviceUrl(path));
  const allowed = new URL(serviceUrl('/api/v1/missions/'));
  if (url.origin !== allowed.origin || !url.pathname.startsWith(allowed.pathname) || url.username || url.password) {
    throw new Error('Mission resource is outside the configured modeling service.');
  }
  const response = await fetch(url.href, { headers: authHeaders(), signal, redirect: 'error' });
  if (!response.ok) throw new ApiError(response.status, `Could not load mission resource (${response.status}).`);
  return response.blob();
}

const enc = encodeURIComponent;

export const missionsApi = {
  listMissions: () => request<Mission[]>('GET', '/api/v1/missions'),
  createMission: (m: MissionCreate) => request<Mission>('POST', '/api/v1/missions', { json: m }),
  storyboard: (id: string, maxInterpGapS?: number, signal?: AbortSignal) =>
    request<Storyboard>('GET', `/api/v1/missions/${enc(id)}/storyboard${maxInterpGapS ? `?max_interp_gap_s=${maxInterpGapS}` : ''}`, undefined, signal),
  // Contract maximum: a decimated response must never become playback evidence.
  track: (id: string, signal?: AbortSignal) =>
    request<MissionTrack>('GET', `/api/v1/missions/${enc(id)}/track?max_points=200000`, undefined, signal),
  ingestTrackJson: (id: string, fixes: TrackFix[]) => request<TrackIngestResult>('POST', `/api/v1/missions/${enc(id)}/track`, { json: { fixes } }),
  ingestTrackFile: (id: string, form: FormData) => request<TrackIngestResult>('POST', `/api/v1/missions/${enc(id)}/track/file`, { form }),
  uploadMedia: (id: string, form: FormData) => request<MediaItem>('POST', `/api/v1/missions/${enc(id)}/media`, { form }),
  addReport: (id: string, r: ReportCreate) => request<Report>('POST', `/api/v1/missions/${enc(id)}/reports`, { json: r }),
  geojsonUrl: (id: string) => serviceUrl(`/api/v1/missions/${enc(id)}/storyboard.geojson`),
  listPresets: () => request<TransitPreset[]>('GET', '/api/v1/transit/presets'),
  series: (seriesUrl: string) => request<TransitSeries>('GET', seriesUrl),
};

/** POST the transit request, poll the job, return the envelope. */
export async function runTransit(req: TransitRequest, onProgress?: (p: number) => void, signal?: AbortSignal): Promise<TransitResponse> {
  const accepted = await request<JobAccepted>('POST', '/api/v1/transit/simulate', { json: req }, signal);
  return awaitJob<TransitResponse>(MODELING_BASE, accepted, onProgress, signal);
}

export interface TrackFormInput {
  file: File | Blob;
  filename?: string;
  format: TrackFormat;
  utcOffsetMin?: number | null;
  nmeaDate?: string | null;
}

/** Multipart body for POST /missions/{id}/track/file. Optional fields are left out when blank. */
export function buildTrackForm(i: TrackFormInput): FormData {
  const f = new FormData();
  f.append('file', i.file, i.filename ?? (i.file instanceof File ? i.file.name : 'track'));
  f.append('format', i.format);
  if (i.utcOffsetMin != null && Number.isFinite(i.utcOffsetMin)) f.append('utc_offset_min', String(i.utcOffsetMin));
  if (i.nmeaDate) f.append('nmea_date', i.nmeaDate);
  return f;
}

export interface MediaFormInput {
  file: File | Blob;
  filename?: string;
  /** UTC "YYYY-MM-DDTHH:MM[:SS]" (no zone); sent as UTC. Overrides EXIF time. */
  capturedUtc?: string | null;
  exifUtcOffsetMin?: number | null;
  cameraClockOffsetS?: number | null;
  caption?: string | null;
}

/** "2026-11-05T12:03" -> "2026-11-05T12:03:00Z"; a value that already has a zone is kept. */
export function toUtcIso(local: string): string {
  const v = local.trim();
  if (/(Z|[+-]\d{2}:?\d{2})$/.test(v)) return v;
  return `${v.length === 16 ? `${v}:00` : v}Z`;
}

export function buildMediaMetadata(i: MediaFormInput): MediaMetadata {
  const m: MediaMetadata = {};
  if (i.capturedUtc) m.captured_utc = toUtcIso(i.capturedUtc);
  if (i.exifUtcOffsetMin != null && Number.isFinite(i.exifUtcOffsetMin)) m.exif_utc_offset_min = Math.round(i.exifUtcOffsetMin);
  if (i.cameraClockOffsetS != null && Number.isFinite(i.cameraClockOffsetS) && i.cameraClockOffsetS !== 0) m.camera_clock_offset_s = i.cameraClockOffsetS;
  if (i.caption?.trim()) m.caption = i.caption.trim();
  return m;
}

/** Multipart body for POST /missions/{id}/media: an `image` part and a `metadata` JSON string part. */
export function buildMediaForm(i: MediaFormInput): FormData {
  const f = new FormData();
  f.append('image', i.file, i.filename ?? (i.file instanceof File ? i.file.name : 'image'));
  f.append('metadata', JSON.stringify(buildMediaMetadata(i)));
  return f;
}
