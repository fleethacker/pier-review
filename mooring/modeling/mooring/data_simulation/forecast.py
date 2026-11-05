"""Seeded training forcing. Shape/period are scenario inputs, not physical prediction coefficients."""
import math
import random
from datetime import timedelta

from mooring.core.schemas import EnvironmentMetadata, ForecastSeries, StationQuality
from mooring.core.schemas.data_simulation import SyntheticForecastRequest


def generate(req: SyntheticForecastRequest) -> ForecastSeries:
    rng = random.Random(req.seed)
    duration_min = req.duration_hours * 60
    times = list(range(0, duration_min, req.step_min)) + [duration_min]
    series = []
    for minutes in times:
        fraction = minutes / duration_min
        pulse = 1 - abs(2 * fraction - 1)
        gust = max(req.baseline.wind_speed_kt, req.baseline.wind_gust_kt +
                   (req.gust_peak_kt - req.baseline.wind_gust_kt) * pulse + rng.gauss(0, req.gust_noise_sigma_kt))
        at = req.start_utc + timedelta(minutes=minutes)
        water = req.baseline.water_level_mllw_ft + req.water_level_amplitude_ft * math.sin(
            2 * math.pi * minutes / (req.water_level_period_hours * 60))
        series.append(req.baseline.model_copy(update={
            'valid_at_utc': at, 'source': 'scenario', 'wind_gust_kt': gust, 'water_level_mllw_ft': water,
            'wind_rel_ship_deg': None, 'current_rel_ship_deg': None,
            'quality': [StationQuality(station_id='synthetic-training', age_s=0, flags=['synthetic', 'not_a_forecast'])],
            'metadata': EnvironmentMetadata(basis='scenario', source=f'synthetic-training seed={req.seed}',
                issued_at_utc=req.start_utc, wind_averaging_s=60, gust_duration_s=30,
                wind_reference_height_m=10, vertical_datum='MLLW', quality='unknown'),
        }))
    return ForecastSeries(berth_id=req.berth_id, step_min=req.step_min, series=series)
