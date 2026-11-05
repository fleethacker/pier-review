"""Explicit supplied tide coverage and interpolation; never substitute missing public data."""
from bisect import bisect_left, bisect_right
from datetime import timedelta

from mooring import refdata
from mooring.core.schemas import ValidityReason
from mooring.data_simulation.tides import legacy_tide_levels

MAX_INTERPOLATION_GAP_MIN = 60  # Application sampling limit, not a tidal-model coefficient.


def levels(req, berth, step_min):
    times = {req.from_utc, req.to_utc, *(action.at_utc for action in req.tending)}
    for interval in (step_min, req.step_min):
        at = req.from_utc
        while at < req.to_utc:
            times.add(at)
            at += timedelta(minutes=interval)
    if req.water_level_forecast is None:
        return legacy_tide_levels(berth, sorted(times))
    samples = req.water_level_forecast
    dates = [s.valid_at_utc for s in samples]
    lower = max(0, bisect_right(dates, req.from_utc)-1)
    upper = min(bisect_left(dates, req.to_utc), len(samples)-1)
    relevant = samples[lower:upper+1]
    for sample in relevant:
        metadata = sample.metadata
        if metadata and metadata.quality == 'poor':
            raise refdata.InvalidReference('Poor-quality water-level forecast cannot establish tide-sweep coverage')
        flags = ' '.join(flag for q in sample.quality for flag in q.flags).lower()
        if any(word in flags for word in ('unavailable', 'missing', 'stale')):
            raise refdata.InvalidReference('Supplied water-level forecast has missing/unavailable/stale source flags')
    # Evaluate forecast knots too: an interior peak must not disappear between reporting samples.
    times.update(t for t in dates if req.from_utc <= t <= req.to_utc)
    out = []
    for at in sorted(times):
        index = max(0, bisect_right(dates, at)-1)
        a = samples[index]
        if a.valid_at_utc == at:
            out.append((at, a.water_level_mllw_ft))
            continue
        b = samples[index+1]
        gap = b.valid_at_utc - a.valid_at_utc
        if gap > timedelta(minutes=MAX_INTERPOLATION_GAP_MIN):
            raise refdata.InvalidReference(f'Water-level interpolation gap exceeds {MAX_INTERPOLATION_GAP_MIN} minutes')
        fraction = (at-a.valid_at_utc).total_seconds()/gap.total_seconds()
        water = a.water_level_mllw_ft + fraction*(b.water_level_mllw_ft-a.water_level_mllw_ft)
        out.append((at, water))
    return out


def source_reasons(req):
    if req.water_level_forecast is None:
        return [ValidityReason(code='SYNTHETIC_TIDE_SERIES', affected_components=['water_level'],
            message='Training tide generator used; no actual water-level forecast was supplied.')]
    reasons = [ValidityReason(code='TIDE_INTERPOLATION_UNQUALIFIED', affected_components=['water_level'],
        message='Supplied MLLW levels are linearly interpolated between samples; temporal/berth representativeness is not qualified.')]
    if any(s.source in ('mock', 'scenario') or (s.metadata and s.metadata.basis == 'scenario') for s in req.water_level_forecast):
        reasons.append(ValidityReason(code='SYNTHETIC_TIDE_SERIES', affected_components=['water_level'],
            message='Supplied water-level series contains synthetic scenario data, not a public forecast.'))
    return reasons
