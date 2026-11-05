"""Temporal availability checks shared by forecast planning and agent intake.

No physical calculations: observations are not future guidance, and a later
retrieval is never silently promoted to a provider issue time.
"""

from datetime import UTC


def availability_problem(snapshot, as_of, *, require_forecast=False):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        return 'Planning as-of timestamp must be timezone-aware'
    if snapshot.valid_at_utc.tzinfo is None or snapshot.valid_at_utc.utcoffset() is None:
        return 'Snapshot timestamp must be timezone-aware'
    as_of = as_of.astimezone(UTC)
    meta = snapshot.metadata
    # Current/past observations still cannot be held as future forcing by a forecast consumer.
    future = require_forecast or snapshot.valid_at_utc > as_of
    public_forecast = snapshot.source == 'forecast' or (snapshot.source == 'replay' and future)
    if public_forecast:
        if meta is None or meta.basis != 'prediction':
            return 'Public forecast or future replay requires prediction basis and availability provenance'
        if meta.components:
            if {item.component for item in meta.components} != {'wind', 'current', 'water_level'}:
                return 'Composed forecasts require provenance for wind, current and water level'
            for item in meta.components:
                if item.basis != 'prediction':
                    return f'{item.component}: future public guidance requires prediction basis'
                available = item.issued_at_utc or item.retrieved_at_utc
                if available is None or available > as_of:
                    return f'{item.component}: availability by planning as-of time is not established'
        elif meta.issued_at_utc is None:
            return 'Public forecast or future replay lacks issuance time; observations are not advance guidance'
    for item in meta.components if meta else []:
        if item.basis == 'observation' and future:
            return f'{item.component}: future observations cannot be used as a forecast'
        if item.issued_at_utc and item.issued_at_utc > as_of:
            return f'{item.component}: forecast was issued after planning as-of time'
    if meta and meta.basis == 'observation' and future:
        return 'Future observations cannot be used as a forecast'
    if meta and meta.issued_at_utc and meta.issued_at_utc > as_of:
        return 'Forecast was issued after planning as-of time'
    if snapshot.source in ('live', 'ship_sensor') and future:
        return 'Future observations cannot be used as a forecast'
    return None
