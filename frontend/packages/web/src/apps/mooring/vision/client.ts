import { agents, AGENTS_BASE, awaitJob, unwrap } from '../api';
import type { JobAccepted } from '../types';
import { friendlyVisionError } from './logic';
import type { DraftBerth, ImageKind, VisionResponse } from './logic';

export interface AnalyzeInput {
  image: File;
  kind: ImageKind;
  berthName?: string;
  shipClassId?: string;
  side?: string;
}

class VisionHttpError extends Error {
  constructor(readonly status: number | null, message: string) {
    super(message);
  }
}

/** Uploads the image, waits for the analysis job, and returns the job id with its result. */
export async function analyzeBerthImage(
  input: AnalyzeInput,
  onProgress?: (p: number) => void,
  signal?: AbortSignal,
): Promise<{ jobId: string; response: VisionResponse }> {
  const metadata: Record<string, unknown> = { image_kind: input.kind };
  if (input.berthName) metadata.berth_name = input.berthName;
  if (input.shipClassId) metadata.ship_class_id = input.shipClassId;
  if (input.side) metadata.side_to = input.side;
  const form = new FormData();
  form.set('image', input.image);
  form.set('metadata', JSON.stringify(metadata));
  try {
    const res = await fetch(`${AGENTS_BASE}/api/v1/berth-vision/analyze`, { method: 'POST', body: form, signal });
    if (!res.ok) {
      const detail = (await res.text()).slice(0, 200) || res.statusText;
      throw new VisionHttpError(res.status, friendlyVisionError(res.status, detail));
    }
    const accepted = (await res.json()) as JobAccepted;
    const response = await awaitJob<VisionResponse>(AGENTS_BASE, accepted, onProgress, signal);
    return { jobId: accepted.job_id, response };
  } catch (e) {
    if (e instanceof VisionHttpError || (e instanceof DOMException && e.name === 'AbortError')) throw e;
    throw new VisionHttpError(null, friendlyVisionError(null, e instanceof Error ? e.message : String(e)));
  }
}

/** Saves the confirmed berth to the modeling service and returns its id. */
export async function confirmBerth(jobId: string, berth: DraftBerth): Promise<string> {
  try {
    const created = unwrap(await agents.POST('/api/v1/berth-vision/{job_id}/confirm', { params: { path: { job_id: jobId } }, body: { berth } }));
    return created.berth_id;
  } catch (e) {
    const text = e instanceof Error ? e.message : String(e);
    const status = /^(\d{3}) /.exec(text)?.[1];
    throw new VisionHttpError(status ? Number(status) : null, friendlyVisionError(status ? Number(status) : null, text));
  }
}
