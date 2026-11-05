import { describe, expect, it } from 'vitest';
import { classSupport } from './classSupport';
import type { ShipClass } from './types';

const ship = (classId: string, fittings: unknown[] = []): ShipClass => ({
  class_id: classId, loading_conditions: [{ name: 'full_load' }], fittings,
  wind_area_lateral_ft2: 2000, wind_area_frontal_ft2: 400,
} as ShipClass);

describe('selected class catalog coverage', () => {
  it.each(['CG-47', 'LHD-1', 'CVN-68'])('keeps %s hull/load inputs distinct from unsupported full planning', (id) => {
    const support = classSupport(ship(id), id, 'full_load');
    expect(support.current).toBe(true);
    expect(support.hasLoadInputs).toBe(true);
    expect(support.canPlan).toBe(false);
    expect(support.reason).toContain('No class-specific mooring fittings');
  });

  it('uses actual imported fitting records without requiring DDG identifiers', () => {
    expect(classSupport(ship('CUSTOM', [{ fitting_id: 'FWD-CHOCK-A' }]), 'CUSTOM', 'full_load').canPlan).toBe(true);
  });

  it('blocks the previous ship while the selected class is loading', () => {
    const support = classSupport(ship('DDG', [{}]), 'CG-47', 'full_load');
    expect(support.current).toBe(false);
    expect(support.canPlan).toBe(false);
    expect(support.reason).toContain('Waiting');
  });

  it('does not assume a missing loading condition or unknown areas are usable', () => {
    expect(classSupport(ship('DDG', [{}]), 'DDG', 'missing').canPlan).toBe(false);
    expect(classSupport({ ...ship('DDG', [{}]), wind_area_lateral_ft2: NaN }, 'DDG', 'full_load').hasLoadInputs).toBe(false);
    expect(classSupport(null, '', '').canPlan).toBe(false);
  });
});
