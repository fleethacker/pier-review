"""Forecast identity is reproducible across executions and exposed over HTTP."""
import json
from datetime import timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring import environment, refdata
from mooring.core import store
from mooring.core.envelopes import resolved_inputs_hash
from mooring.core.schemas import EnvironmentMetadata, EnvScenario
from mooring.core.schemas.forecast_planning import (
    ForecastBinding, ForecastDockingRequest, ForecastResolveRequest, ForecastResolvedResponse,
)
from mooring.moored.forecast_planning import assess
from mooring.moored.forecast_service import resolve, resolve_request


def _request():
    path = Path(__file__).resolve().parents[2] / 'contract/examples/modeling/mooring_forecast_plan.json'
    req = ForecastDockingRequest.model_validate(json.loads(path.read_text()))
    return req.model_copy(update={'arrival_to_utc': req.arrival_from_utc})


def _resolution(**changes):
    req = _request()
    return ForecastResolveRequest(**(dict(berth_id=req.berth_id, as_of_utc=req.as_of_utc,
        from_utc=req.arrival_from_utc, to_utc=req.arrival_to_utc+timedelta(hours=req.operation_hours+req.holding_hours),
        forecast=req.forecast, max_gap_min=req.max_gap_min) | changes))


def test_http_resolution_exposes_frozen_series_without_calling_live_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Supplied resolution must not acquire a live provider')
    monkeypatch.setattr(environment, 'forecast', forbidden)
    req = _resolution()
    with TestClient(app) as client:
        response = client.post('/api/v1/mooring/forecast/resolve', json=req.model_dump(mode='json'))
    assert response.status_code == 200, response.text
    result = ForecastResolvedResponse.model_validate(response.json())
    assert result.backend == 'real' and result.status == 'AMBER'
    assert result.validity.state == 'limited' and result.result.coverage_complete
    assert result.result.berth_id == req.berth_id
    assert result.result.series == list(resolve_request(req).snapshots())
    assert result.manifest.environment_hash == result.result.forecast_manifest.content_hash
    assert resolved_inputs_hash(store.load_snapshot(result.manifest.resolved_inputs_hash)) == result.manifest.resolved_inputs_hash


def test_repeated_planning_keeps_hashes_but_allocates_separate_audit_results():
    req = _request()
    first, second = assess(req), assess(req)
    assert first.result_id != second.result_id
    first_ids = {c.analysis_result_id for c in first.result.conditions if c.analysis_result_id}
    second_ids = {c.analysis_result_id for c in second.result.conditions if c.analysis_result_id}
    assert first_ids and second_ids and first_ids.isdisjoint(second_ids)
    assert first.manifest.resolved_inputs_hash == second.manifest.resolved_inputs_hash
    assert first.result.result_hash == second.result.result_hash
    assert first.result.forecast_manifest == second.result.forecast_manifest
    saved = store.load_snapshot(first.manifest.resolved_inputs_hash)
    assert resolved_inputs_hash(saved) == first.manifest.resolved_inputs_hash
    assert 'analysis_result_ids' not in saved and 'recommendation_result_id' not in saved
    assert {r.id for r in first.manifest.records if r.kind == 'analysis_result'} == first_ids
    assert {r.id for r in second.manifest.records if r.kind == 'analysis_result'} == second_ids


def test_equivalent_timezone_representation_keeps_assessment_identity():
    req = _request()
    zone = timezone(timedelta(hours=-5))
    changed = req.model_copy(deep=True)
    for sample in changed.forecast:
        sample.valid_at_utc = sample.valid_at_utc.astimezone(zone)
        if sample.metadata:
            for field in ('issued_at_utc', 'valid_from_utc', 'valid_to_utc'):
                if value := getattr(sample.metadata, field):
                    setattr(sample.metadata, field, value.astimezone(zone))
    first, second = assess(req), assess(changed)
    assert first.manifest.resolved_inputs_hash == second.manifest.resolved_inputs_hash
    assert first.result.result_hash == second.result.result_hash


def test_changed_catalog_input_changes_resolved_identity(monkeypatch):
    req = _request()
    first = assess(req)
    ship = refdata.ship(req.ship_class_id)
    changed = ship.model_copy(update={'wind_area_lateral_ft2': ship.wind_area_lateral_ft2*1.05})
    monkeypatch.setattr(refdata, 'ship', lambda _: changed)
    second = assess(req)
    assert first.result.forecast_manifest == second.result.forecast_manifest
    assert first.manifest.resolved_inputs_hash != second.manifest.resolved_inputs_hash
    assert first.result.result_hash != second.result.result_hash


def test_expected_hash_rejects_changed_values_under_same_declared_revision():
    req = _resolution(forecast_binding=ForecastBinding(source_id='test-series', revision='same-revision'))
    original = resolve(req)
    pinned = req.model_copy(deep=True)
    pinned.forecast_binding.expected_content_hash = original.result.forecast_manifest.content_hash
    assert resolve(pinned).result.forecast_manifest == original.result.forecast_manifest
    pinned.forecast[24].wind_gust_kt += 1
    with TestClient(app) as client:
        response = client.post('/api/v1/mooring/forecast/resolve', json=pinned.model_dump(mode='json'))
    assert response.status_code == 422
    assert 'hash' in response.json()['detail'].lower()


@pytest.mark.parametrize('problem', ['future_issued', 'gap', 'truncated'])
def test_unusable_resolution_is_explicit_and_never_fills_missing_data(problem):
    req = _resolution()
    if problem == 'future_issued':
        req.forecast = [s.model_copy(update={'source': 'forecast', 'metadata': EnvironmentMetadata(
            basis='prediction', issued_at_utc=req.as_of_utc+timedelta(minutes=1))}) for s in req.forecast]
    elif problem == 'gap':
        req.forecast = req.forecast[:25] + req.forecast[28:]
    else:
        req.forecast = req.forecast[:25]
    response = resolve(req)
    assert response.status == 'RED' and response.validity.state == 'invalid'
    assert not response.result.coverage_complete and response.result.problems
    assert len(response.result.series) == len(req.forecast)
    assert response.result.series[-1].valid_at_utc == req.forecast[-1].valid_at_utc


@pytest.mark.parametrize('kind', ['steady', 'ramp'])
def test_scenario_binding_is_sampled_and_replays_with_identical_hashes(kind):
    req = _request()
    extra = {'ramp_to_wind_kt': 20, 'ramp_minutes': 36*60} if kind == 'ramp' else {}
    scenario = EnvScenario(env_scenario_id='p1-service-'+kind, name='Explicit training', kind=kind,
        created_at_utc=req.as_of_utc, wind_speed_kt=0, **extra)
    store.DocStore('env_scenario', EnvScenario)[scenario.env_scenario_id] = scenario
    values = req.model_dump(mode='json')
    values.pop('forecast')
    values['forecast_binding'] = {'source': 'scenario', 'env_scenario_id': scenario.env_scenario_id}
    bound = ForecastDockingRequest.model_validate(values)
    response = resolve(ForecastResolveRequest(berth_id=req.berth_id, as_of_utc=req.as_of_utc,
        from_utc=req.arrival_from_utc, to_utc=req.arrival_to_utc+timedelta(hours=8),
        forecast_binding=bound.forecast_binding))
    assert response.result.coverage_complete and response.validity.state == 'limited'
    assert all(s.source == 'scenario' and s.metadata.basis == 'scenario' for s in response.result.series)
    if kind == 'ramp':
        assert response.result.series[0].wind_speed_kt < response.result.series[-1].wind_speed_kt
    first, second = assess(bound), assess(bound)
    assert first.result.result_hash == second.result.result_hash
    saved = store.load_snapshot(first.manifest.resolved_inputs_hash)
    restored = ForecastDockingRequest.model_validate(saved['request'])
    assert restored.forecast is None and restored.forecast_binding.env_scenario_id == scenario.env_scenario_id
    assert first.result.forecast_manifest == response.result.forecast_manifest


def test_scenario_source_failure_is_an_explicit_http_error(monkeypatch):
    from mooring.environment.errors import ProviderError
    req = _request()
    scenario = EnvScenario(env_scenario_id='p1-service-failure', name='Failure test', kind='steady',
        created_at_utc=req.as_of_utc)
    store.DocStore('env_scenario', EnvScenario)[scenario.env_scenario_id] = scenario
    def unavailable(*args, **kwargs):
        raise ProviderError('no_data', 'archive gap')
    monkeypatch.setattr(environment, 'scenario_snapshot', unavailable)
    body = _resolution().model_dump(mode='json')
    body.pop('forecast')
    body['forecast_binding'] = {'source': 'scenario', 'env_scenario_id': scenario.env_scenario_id}
    with TestClient(app) as client:
        response = client.post('/api/v1/mooring/forecast/resolve', json=body)
    assert response.status_code == 422
    assert 'archive gap' in response.json()['detail']
