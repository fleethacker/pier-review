"""Compatibility training series with explicit coverage; never a public forecast."""
import math
from datetime import timedelta

from mooring.core.schemas import EnvironmentMetadata, ForecastSeries


def generate(berth_id, now, hours, step_min, stations, snapshot_factory):
    """Retain the legacy hourly anchor, but cover now + horizon at any clock phase."""
    start = now.replace(minute=0, second=0, microsecond=0)
    end = now + timedelta(hours=hours)
    intervals = math.ceil((end-start).total_seconds()/(step_min*60))
    series = []
    for index in range(intervals+1):
        at = start + timedelta(minutes=index*step_min)
        snapshot = snapshot_factory(at, 'mock', stations)
        series.append(snapshot.model_copy(update={'metadata':EnvironmentMetadata(
            basis='scenario', source='Legacy deterministic training generator; not a public forecast',
            quality='unknown', wind_averaging_s=60, gust_duration_s=30, wind_reference_height_m=10)}))
    return ForecastSeries(berth_id=berth_id, step_min=step_min, series=series)
