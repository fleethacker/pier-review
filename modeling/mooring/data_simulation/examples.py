"""Small deterministic examples for the advance-planning API and future training UI."""
from datetime import timedelta

from mooring.core.schemas.data_simulation import SyntheticForecastRequest
from mooring.core.schemas.forecast_planning import ForecastDockingRequest
from mooring.demo_cases import docking_cases
from .forecast import generate


def examples():
    base = docking_cases()[0].analysis_request
    simulation = SyntheticForecastRequest(berth_id=base.berth_id, baseline=base.environment,
        start_utc=base.environment.valid_at_utc, duration_hours=48, step_min=60, seed=42, gust_peak_kt=15)
    forecast = generate(simulation)
    request = ForecastDockingRequest(ship_class_id=base.ship_class_id, loading=base.loading,
        berth_id=base.berth_id, config=base.config, as_of_utc=simulation.start_utc,
        arrival_from_utc=simulation.start_utc+timedelta(hours=24),
        arrival_to_utc=simulation.start_utc+timedelta(hours=30), forecast=forecast.series)
    return {'data_simulation_forecast': simulation.model_dump(mode='json'),
            'mooring_forecast_plan': request.model_dump(mode='json')}
