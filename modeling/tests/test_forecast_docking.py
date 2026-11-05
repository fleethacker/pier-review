"""Advance planning coverage, actual physics, deterministic training inputs and budget gates."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas.data_simulation import SyntheticForecastRequest
from mooring.core.schemas.forecast_planning import ForecastDockingRequest
from mooring.core.schemas import EnvironmentMetadata
from mooring.data_simulation.forecast import generate
from mooring.demo_cases import docking_cases
from mooring.moored.forecast_planning import assess


def request(**changes):
    base = docking_cases()[0].analysis_request
    start = base.environment.valid_at_utc
    series = generate(SyntheticForecastRequest(berth_id=base.berth_id, baseline=base.environment,
                                               start_utc=start, gust_peak_kt=5))
    values = dict(ship_class_id=base.ship_class_id, berth_id=base.berth_id, config=base.config,
                  as_of_utc=start, arrival_from_utc=start+timedelta(hours=24),
                  arrival_to_utc=start+timedelta(hours=26), forecast=series.series,
                  operation_hours=2, holding_hours=2)
    return ForecastDockingRequest(**(values | changes))


def test_arrival_a_day_ahead_uses_full_operation_and_holding_with_result_citations():
    req = request()
    response = assess(req)
    assert response.backend == 'real' and response.status == 'AMBER'
    assert response.validity.state == 'limited'
    assert response.result.complete and response.result.selected_arrival_utc is not None
    assert all(w.outcome == 'supported_limited' for w in response.result.windows)
    assert response.result.windows[0].holding_end_utc == req.as_of_utc + timedelta(hours=28)
    assert response.result.evaluations == 7  # shared snapshots reuse the same installation tide
    assert all(c.analysis_result_id for c in response.result.conditions)
    assert any('not a public weather forecast' in reason for reason in response.result.limitations)
    with TestClient(app) as client:
        for condition in response.result.conditions:
            assert client.get('/api/v1/results/'+condition.analysis_result_id).status_code == 200


def test_interior_peak_blocks_arrivals_without_erasing_the_real_snapshot():
    req = request()
    at = req.as_of_utc + timedelta(hours=27)
    series = [s.model_copy(update={'wind_speed_kt':75,'wind_gust_kt':100}) if s.valid_at_utc == at else s for s in req.forecast]
    response = assess(req.model_copy(update={'forecast': series}))
    assert response.result.selected_arrival_utc is None and response.status == 'RED'
    assert all(w.outcome == 'overloaded' and w.governing_at_utc == at for w in response.result.windows)


def test_a_24_hour_forecast_does_not_cover_tomorrows_operation():
    req = request()
    response = assess(req.model_copy(update={'forecast': req.forecast[:25]}))
    assert response.result.selected_arrival_utc is None
    assert all(w.outcome == 'unavailable' for w in response.result.windows)
    assert response.result.evaluations == 0


def test_forecast_gap_does_not_become_a_calm_interval():
    req = request()
    response = assess(req.model_copy(update={'forecast': req.forecast[:25]+req.forecast[29:]}))
    assert all(w.outcome == 'unavailable' for w in response.result.windows)
    assert response.result.selected_arrival_utc is None


def test_future_issued_data_never_influences_search_or_assessment():
    req = request(optimize_lines=True)
    series = [s.model_copy(update={'source':'forecast', 'metadata':EnvironmentMetadata(basis='prediction',
        issued_at_utc=req.as_of_utc+timedelta(minutes=1))}) for s in req.forecast]
    response = assess(req.model_copy(update={'forecast':series}))
    assert response.result.recommendation_result_id is None and response.result.evaluations == 0
    assert response.result.selected_arrival_utc is None
    assert all(c.outcome == 'unavailable' for c in response.result.conditions)


def test_evaluation_budget_returns_undetermined_not_a_safe_partial_window():
    response = assess(request(max_evaluations=1))
    assert response.result.evaluations == 1 and not response.result.complete
    assert response.result.selected_arrival_utc is None
    assert all(w.outcome == 'undetermined' for w in response.result.windows)


def test_cancellation_is_checked_before_work():
    from mooring.core.jobs import JobCancelled
    class Cancelled:
        def check_cancelled(self): raise JobCancelled()
    with pytest.raises(JobCancelled): assess(request(), Cancelled())


def test_request_rejects_short_lead_naive_duplicate_and_reversed_times():
    req = request()
    with pytest.raises(ValueError, match='at least 24 hours'):
        request(arrival_from_utc=req.as_of_utc)
    with pytest.raises(ValueError, match='strictly increasing'):
        request(forecast=[req.forecast[0],req.forecast[0]])
    with pytest.raises(ValueError, match='timezone-aware'):
        request(forecast=[s.model_copy(update={'valid_at_utc':s.valid_at_utc.replace(tzinfo=None)}) for s in req.forecast])


def test_synthetic_generator_is_reproducible_labeled_and_keeps_end_coverage():
    base = docking_cases()[0].analysis_request
    req = SyntheticForecastRequest(berth_id=base.berth_id,baseline=base.environment,
                                  start_utc=base.environment.valid_at_utc,seed=123,
                                  gust_noise_sigma_kt=1,step_min=37,water_level_amplitude_ft=2)
    a,b=generate(req),generate(req)
    assert a.model_dump_json() == b.model_dump_json()
    assert a.series[-1].valid_at_utc == req.start_utc+timedelta(hours=48)
    assert all(s.source == 'scenario' and s.metadata.basis == 'scenario' for s in a.series)
    assert all('not_a_forecast' in s.quality[0].flags for s in a.series)
    assert a.model_dump_json() != generate(req.model_copy(update={'seed':124})).model_dump_json()


def test_forecast_api_job_and_training_endpoint_validate_against_contract():
    import time
    from mooring.core.schemas.forecast_planning import ForecastDockingResponse
    from mooring.data_simulation.examples import examples
    with TestClient(app) as client:
        simulation = client.post('/api/v1/data-simulation/forecast', json=examples()['data_simulation_forecast'])
        assert simulation.status_code == 200 and len(simulation.json()['series']) == 49
        accepted = client.post('/api/v1/mooring/forecast-plan', json=examples()['mooring_forecast_plan'])
        assert accepted.status_code == 202
        deadline = time.monotonic() + 10
        while True:
            job = client.get(accepted.json()['status_url']).json()
            if job['state'] not in ('queued', 'running'): break
            assert time.monotonic() < deadline
            time.sleep(.01)  # job scheduling, never physics time
        assert job['state'] == 'succeeded', job
        response = ForecastDockingResponse.model_validate(job['result'])
        assert response.manifest and response.manifest.resolved_inputs_hash
        assert response.result.selected_arrival_utc


@pytest.mark.parametrize('kind', ['poor', 'suspect', 'missing_issue', 'future_observation', 'short_validity', 'not_yet_valid'])
def test_unusable_forecast_provenance_cannot_support_arrival_or_sneak_into_search(kind):
    req = request(optimize_lines=True)
    series = []
    for snapshot in req.forecast:
        fields = dict(basis='prediction', source='fixture public provider', issued_at_utc=req.as_of_utc, quality='good')
        if kind in ('poor', 'suspect'): fields['quality'] = kind
        if kind == 'missing_issue': fields['issued_at_utc'] = None
        if kind == 'future_observation': fields['basis'] = 'observation'
        if kind == 'short_validity': fields['valid_to_utc'] = snapshot.valid_at_utc + timedelta(minutes=15)
        if kind == 'not_yet_valid': fields['valid_from_utc'] = snapshot.valid_at_utc + timedelta(minutes=15)
        series.append(snapshot.model_copy(update={'source': 'forecast', 'metadata': EnvironmentMetadata(**fields)}))
    result = assess(req.model_copy(update={'forecast': series}))
    assert result.result.selected_arrival_utc is None
    assert all(window.outcome == 'unavailable' for window in result.result.windows)
    if kind != 'short_validity':
        assert result.result.recommendation_result_id is None
        assert result.result.evaluations == 0


def test_validity_interval_may_cover_short_operation_but_not_later_hold():
    req = request(arrival_step_min=60, operation_hours=.25, holding_hours=0)
    series = [snapshot.model_copy(update={'source': 'forecast', 'metadata': EnvironmentMetadata(
        basis='prediction', issued_at_utc=req.as_of_utc, quality='good',
        valid_from_utc=snapshot.valid_at_utc, valid_to_utc=snapshot.valid_at_utc+timedelta(minutes=15))}) for snapshot in req.forecast]
    result = assess(req.model_copy(update={'forecast': series}))
    assert result.result.selected_arrival_utc is not None
    held = assess(req.model_copy(update={'forecast': series, 'holding_hours':1}))
    assert held.result.selected_arrival_utc is None
