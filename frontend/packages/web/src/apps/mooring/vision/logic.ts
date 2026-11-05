import type { AgentSchemas } from '../types';

export type VisionResponse = AgentSchemas['VisionResponse'];
export type Detection = AgentSchemas['Detection'];
export type DraftBerth = AgentSchemas['VisionResult']['draft_berth'];
export type ImageKind = 'satellite' | 'chart' | 'berthing_plan' | 'photo';

export const IMAGE_KINDS: { value: ImageKind; label: string }[] = [
  { value: 'satellite', label: 'Satellite image' },
  { value: 'chart', label: 'Chart' },
  { value: 'berthing_plan', label: 'Berthing plan' },
  { value: 'photo', label: 'Photo' },
];

export const MAX_IMAGE_BYTES = 8_000_000;
const ACCEPTED = ['image/png', 'image/jpeg', 'image/webp'];

/** Why a file cannot be sent, or null when it can. */
export function checkImage(file: { type: string; size: number }): string | null {
  if (!ACCEPTED.includes(file.type)) return 'Choose a PNG, JPEG or WebP image.';
  if (file.size === 0) return 'That file is empty.';
  if (file.size > MAX_IMAGE_BYTES) return `That image is larger than ${MAX_IMAGE_BYTES / 1_000_000} MB.`;
  return null;
}

/** Detections the model was not sure about; a person must look at each before the berth is used. */
export function pendingConfirmations(detections: Detection[]): Detection[] {
  return detections.filter((d) => d.needs_confirmation);
}

export function canConfirm(detections: Detection[], confirmed: ReadonlySet<string>, name: string): boolean {
  return name.trim().length > 0 && pendingConfirmations(detections).every((d) => confirmed.has(d.item_id));
}

export type ConfidenceBand = 'high' | 'medium' | 'low';
export function confidenceBand(c: number): ConfidenceBand {
  return c >= 0.8 ? 'high' : c >= 0.6 ? 'medium' : 'low';
}

export interface DraftEdits {
  name: string;
  faceBearingDeg: number;
}

/** The berth sent for saving: the model's draft with only the user's edits applied. Nothing else is altered. */
export function applyEdits(draft: DraftBerth, edits: DraftEdits): DraftBerth {
  return {
    ...draft,
    name: edits.name.trim(),
    face_bearing_true_deg: ((edits.faceBearingDeg % 360) + 360) % 360,
  };
}

/** Fitting capacities the model could not read and filled from defaults; they must be confirmed by a person. */
export function estimatedCapacityNote(questions: string[]): string | null {
  return questions.find((q) => /capacit/i.test(q)) ?? null;
}

/** Readable text for the failure modes of the upload and job calls. */
export function friendlyVisionError(status: number | null, detail: string): string {
  if (status === 413) return 'The image is too large for the service.';
  if (status === 415 || status === 422) return `The service could not read that image or its details: ${detail}`;
  if (status === 429) return 'The service is busy. Wait a few seconds and try again.';
  if (status === 503) return 'The vision service is not available right now. Nothing was changed.';
  return detail;
}
