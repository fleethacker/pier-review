import { describe, expect, it } from 'vitest';
import { applyEdits, canConfirm, checkImage, confidenceBand, estimatedCapacityNote, friendlyVisionError, pendingConfirmations } from './logic';
import type { Detection, DraftBerth } from './logic';

const det = (id: string, c: number, needs: boolean): Detection => ({ item_id: id, kind: 'bollard', bbox_px: [0, 0, 1, 1], confidence: c, needs_confirmation: needs });

describe('checkImage', () => {
  it('accepts normal images and says why it refuses others', () => {
    expect(checkImage({ type: 'image/png', size: 1000 })).toBeNull();
    expect(checkImage({ type: 'application/pdf', size: 1000 })).toMatch(/PNG, JPEG/);
    expect(checkImage({ type: 'image/png', size: 0 })).toMatch(/empty/);
    expect(checkImage({ type: 'image/jpeg', size: 50 * 1024 * 1024 })).toMatch(/larger than/);
  });
});

describe('confirmation gate', () => {
  const ds = [det('A', 0.9, false), det('B', 0.5, true), det('C', 0.55, true)];
  it('lists only the uncertain detections', () => {
    expect(pendingConfirmations(ds).map((d) => d.item_id)).toEqual(['B', 'C']);
  });
  it('stays closed until every flagged item is confirmed and the berth has a name', () => {
    expect(canConfirm(ds, new Set(), 'Pier')).toBe(false);
    expect(canConfirm(ds, new Set(['B']), 'Pier')).toBe(false);
    expect(canConfirm(ds, new Set(['B', 'C']), '  ')).toBe(false);
    expect(canConfirm(ds, new Set(['B', 'C']), 'Pier')).toBe(true);
  });
  it('opens at once when nothing was flagged, and the name is still required', () => {
    expect(canConfirm([det('A', 0.95, false)], new Set(), 'Pier')).toBe(true);
    expect(canConfirm([], new Set(), '')).toBe(false);
  });
});

describe('helpers', () => {
  it('bands confidence', () => {
    expect([0.95, 0.7, 0.3].map(confidenceBand)).toEqual(['high', 'medium', 'low']);
  });
  it('applies only the edits', () => {
    const draft = { berth_id: 'D1', name: 'Draft', face_bearing_true_deg: 99.5, fittings: [{ fitting_id: 'x' }] } as unknown as DraftBerth;
    const out = applyEdits(draft, { name: ' Pier 9 ', faceBearingDeg: -10 });
    expect(out.name).toBe('Pier 9');
    expect(out.face_bearing_true_deg).toBe(350);
    expect(out.berth_id).toBe('D1');
    expect(out.fittings).toBe(draft.fittings);
  });
  it('finds the capacity question', () => {
    expect(estimatedCapacityNote(['Is B1 a cleat?', 'Fitting capacities were not visible; defaults used. Confirm.'])).toMatch(/capacities/);
    expect(estimatedCapacityNote(['Is B1 a cleat?'])).toBeNull();
  });
  it('translates service failures', () => {
    expect(friendlyVisionError(429, 'x')).toMatch(/busy/);
    expect(friendlyVisionError(503, 'x')).toMatch(/not available/);
    expect(friendlyVisionError(422, 'bad')).toMatch(/bad/);
    expect(friendlyVisionError(null, 'boom')).toBe('boom');
  });
});
