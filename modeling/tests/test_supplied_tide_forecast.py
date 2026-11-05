"""Supplied water levels replace training tides explicitly, with complete bounded coverage."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from modeling_api.main import app
from mooring import refdata
from mooring.core import store
from mooring.core.schemas import TideSweepRequest
from mooring.demo_cases import docking_cases
from mooring.moored.envelopes_real import tide_sweep, _tide_levels

START = datetime(2026, 11, 6, 12, tzinfo=UTC)


def request(series=True, **updates):
    baseline = docking_cases()[0].analysis_request
    snapshots = [baseline.environment.model_copy(update={'valid_at_utc': START+timedelta(minutes=m),
                 'source': 'forecast', 'water_level_mllw_ft': water}) for m, water in [(0, 1), (12, 4), (30, 1), (60, 1)]]
    return TideSweepRequest(**(baseline.model_dump() | {'from_utc': START, 'to_utc': START+timedelta(hours=1),
        'step_min': 30, 'water_level_forecast': snapshots if series else None} | updates))


def test_supplied_series_includes_interior_peak_and_interpolates_without_extrapolation():
    req = request()
    levels = dict(_tide_levels(req, refdata.berth(req.berth_id)))
    assert levels[START] == 1
    assert levels[START+timedelta(minutes=5)] == pytest.approx(2.25)
    assert levels[START+timedelta(minutes=12)] == 4
    assert levels[START+timedelta(minutes=30)] == 1
    result = tide_sweep(req)
    assert len(result.result.steps) == 3
    assert all(step.water_level_mllw_ft == 1 for step in result.result.steps)
    assert any(r.code == 'TIDE_INTERPOLATION_UNQUALIFIED' for r in result.validity.reasons)
    assert not any(r.code == 'SYNTHETIC_TIDE_SERIES' for r in result.validity.reasons)
    snapshot = store.load_snapshot(result.manifest.resolved_inputs_hash)
    assert len(snapshot['sweep']['water_level_forecast']) == 4


def test_synthetic_default_is_explicitly_limited_and_final_partial_interval_is_reported():
    req = request(False, step_min=7, to_utc=START+timedelta(minutes=16))
    result = tide_sweep(req)
    assert result.validity.state in ('limited', 'invalid') and result.status != 'GREEN'
    assert any(r.code == 'SYNTHETIC_TIDE_SERIES' for r in result.validity.reasons)
    assert [s.valid_at_utc for s in result.result.steps] == [START+timedelta(minutes=m) for m in (0, 7, 14, 16)]


@pytest.mark.parametrize('problem', ['short', 'unordered', 'naive', 'gap', 'missing'])
def test_bad_supplied_forecast_is_rejected_without_synthetic_fallback(problem):
    body = request().model_dump(mode='json')
    if problem == 'short': body['water_level_forecast'] = body['water_level_forecast'][:2]
    elif problem == 'unordered': body['water_level_forecast'].reverse()
    elif problem == 'naive': body['water_level_forecast'][0]['valid_at_utc'] = '2026-11-06T12:00:00'
    elif problem == 'gap':
        body['to_utc'] = (START+timedelta(hours=2)).isoformat()
        body['water_level_forecast'] = [body['water_level_forecast'][0], body['water_level_forecast'][-1]]
        body['water_level_forecast'][-1]['valid_at_utc'] = body['to_utc']
    else: body['water_level_forecast'][1]['quality'] = [{'station_id': 'tide', 'age_s': 0, 'flags': ['unavailable']}]
    response = TestClient(app).post('/api/v1/mooring/tide-sweep', json=body)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('end', [START, START-timedelta(minutes=1), START+timedelta(hours=121)])
def test_time_window_cannot_be_empty_reversed_or_silently_truncated(end):
    with pytest.raises(ValidationError): request(False, to_utc=end)


def test_impossible_tending_is_a_clear_input_error_not_a_solver_crash():
    body = request().model_dump(mode='json')
    body['tending'] = [{'at_utc': START.isoformat(), 'line_number': body['config']['lines'][0]['line_number'],
                        'action': 'heave', 'amount_ft': 1e8}]
    response = TestClient(app).post('/api/v1/mooring/tide-sweep', json=body)
    assert response.status_code == 422 and 'nonpositive' in response.json()['detail']
