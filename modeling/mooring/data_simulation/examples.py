"""Small deterministic examples for the advance-planning API and future training UI."""
from datetime import timedelta

from mooring.core.schemas.data_simulation import SyntheticForecastRequest
from mooring.core.schemas.forecast_planning import ForecastBinding, ForecastDockingRequest, ForecastRecheckRequest, ForecastResolveRequest
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
    reassessment = request.model_copy(update={'allow_short_lead': True, 'as_of_utc': simulation.start_utc+timedelta(hours=20)})
    resolution = ForecastResolveRequest(berth_id=base.berth_id, as_of_utc=simulation.start_utc,
        from_utc=request.arrival_from_utc,
        to_utc=request.arrival_to_utc+timedelta(hours=request.operation_hours+request.holding_hours),
        forecast=forecast.series,
        forecast_binding=ForecastBinding(source_id='synthetic-training-example', revision='training-v1'))
    recheck = ForecastRecheckRequest(prior_result_id='replace-with-owned-forecast-plan-result-id',
        as_of_utc=reassessment.as_of_utc, forecast=forecast.series,
        forecast_binding=ForecastBinding(source_id='synthetic-training-example', revision='training-v2'))
    return {'mooring_forecast_recheck': recheck.model_dump(mode='json'),
            'mooring_forecast_resolve': resolution.model_dump(mode='json'),
            'mooring_forecast_reassessment': reassessment.model_dump(mode='json'),
            'data_simulation_forecast': simulation.model_dump(mode='json'),
            'mooring_forecast_plan': request.model_dump(mode='json')}
