"""Additive forecast binding preserves legacy callers and rejects ambiguous inputs."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from mooring.core.schemas.forecast_planning import (
    ForecastBinding, ForecastDockingRequest, ForecastDockingResult, ForecastResolveRequest,
)


def _legacy():
    path = Path(__file__).resolve().parents[2] / 'contract/examples/modeling/mooring_forecast_plan.json'
    return json.loads(path.read_text())


def test_legacy_forecast_request_wire_is_unchanged():
    payload = _legacy()
    assert ForecastDockingRequest.model_validate(payload).model_dump(mode='json') == payload


@pytest.mark.parametrize('model,fields', [
    (ForecastDockingRequest, ['forecast', 'forecast_binding', 'forecast_step_min']),
    (ForecastDockingResult, ['forecast_manifest', 'result_hash']),
    (ForecastResolveRequest, ['forecast', 'forecast_binding', 'step_min', 'max_gap_min']),
])
def test_optional_wire_fields_stay_optional_for_typescript_generation(model, fields):
    schema = model.model_json_schema()
    for name in fields:
        assert name not in schema.get('required', [])
        # The generator promotes schema defaults to required properties. Runtime
        # defaults remain available, but must not contradict wire omission here.
        assert 'default' not in schema['properties'][name]


@pytest.mark.parametrize('binding', [dict(source='scenario'), dict(env_scenario_id='unselected')])
def test_source_selection_cannot_be_ambiguous(binding):
    with pytest.raises(ValidationError):
        ForecastBinding(**binding)


def test_scenario_selection_does_not_also_accept_a_supplied_series():
    payload = _legacy()
    payload['forecast_binding'] = dict(source='scenario', env_scenario_id='training-ramp')
    with pytest.raises(ValidationError, match='exactly one'):
        ForecastDockingRequest.model_validate(payload)
    del payload['forecast']
    request = ForecastDockingRequest.model_validate(payload)
    assert request.forecast is None
    assert request.forecast_binding.env_scenario_id == 'training-ramp'


def test_resolution_horizon_uses_elapsed_utc_and_rejects_retrospective_start():
    request = ForecastDockingRequest.model_validate(_legacy())
    values = dict(berth_id=request.berth_id, as_of_utc=request.as_of_utc,
        from_utc=request.arrival_from_utc, to_utc=request.arrival_to_utc+timedelta(hours=8),
        forecast=request.forecast)
    resolved = ForecastResolveRequest(**values)
    assert resolved.from_utc.utcoffset() == timedelta(0)
    with pytest.raises(ValidationError, match='start at/after'):
        ForecastResolveRequest(**(values | {'from_utc': request.as_of_utc-timedelta(seconds=1)}))
    with pytest.raises(ValidationError, match='120 hours'):
        ForecastResolveRequest(**(values | {'to_utc': request.as_of_utc+timedelta(hours=121)}))
