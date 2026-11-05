import type { ShipClass, SideTo } from './types';

/** Catalog coverage only. Fittings/areas do not establish physical qualification or rule compliance. */
export function classSupport(ship: ShipClass | null, selectedClassId: string, loading: string, side: SideTo) {
  const current = !!ship && ship.class_id === selectedClassId;
  const hasLoading = current && ship.loading_conditions.some((item) => item.name === loading);
  const hasFittings = current && (ship.fittings?.length ?? 0) > 0;
  const usableBitts = current ? (ship.fittings ?? []).filter((fitting) => fitting.kind === 'bitt' && fitting.side === side).length : 0;
  const hasLoadInputs = hasLoading && [ship.wind_area_lateral_ft2, ship.wind_area_frontal_ft2]
    .every((area) => Number.isFinite(area) && area > 0);
  const reason = !current ? 'Waiting for the selected class data.'
    : !hasLoading ? 'No loading condition is available for this selection.'
      : !hasFittings ? 'No class-specific mooring fittings are supplied. Layouts, sequences and safety sheets are unavailable.'
        : usableBitts === 0 ? `No mooring bitts are supplied on the ${side} side. Planning and line editing are unavailable for this side-to.`
          : null;
  return { current, hasLoading, hasFittings, usableBitts, hasLoadInputs, canPlan: current && hasLoading && usableBitts > 0, reason };
}
