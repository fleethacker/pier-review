import type { ShipClass } from './types';

/** Catalog coverage only. Fittings/areas do not establish physical qualification or rule compliance. */
export function classSupport(ship: ShipClass | null, selectedClassId: string, loading: string) {
  const current = !!ship && ship.class_id === selectedClassId;
  const hasLoading = current && ship.loading_conditions.some((item) => item.name === loading);
  const hasFittings = current && (ship.fittings?.length ?? 0) > 0;
  const hasLoadInputs = hasLoading && [ship.wind_area_lateral_ft2, ship.wind_area_frontal_ft2]
    .every((area) => Number.isFinite(area) && area > 0);
  const reason = !current ? 'Waiting for the selected class data.'
    : !hasLoading ? 'No loading condition is available for this selection.'
      : !hasFittings ? 'No class-specific mooring fittings are supplied. Layouts, sequences and safety sheets are unavailable.'
        : null;
  return { current, hasLoading, hasFittings, hasLoadInputs, canPlan: current && hasLoading && hasFittings, reason };
}
