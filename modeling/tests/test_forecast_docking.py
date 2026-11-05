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


def test_selected_installation_preserves_rest_lengths_when_rechecked_at_later_tide():
    from mooring.core.envelopes import RESULTS
    from mooring.core.schemas import AnalyzeRequest, MooringConfig
    from mooring.moored import solver
    req = request()
    series = [snapshot.model_copy(update={'water_level_mllw_ft': 1.8+(index-24)*0.05})
              for index,snapshot in enumerate(req.forecast)]
    req = req.model_copy(update={'forecast':series})
    response = assess(req)
    selected = next(window for window in response.result.windows if window.arrival_utc == response.result.selected_arrival_utc)
    config = MooringConfig.model_validate(response.result.selected_config.model_dump())
    expected_level = next(s.water_level_mllw_ft for s in series if s.valid_at_utc == selected.arrival_utc)
    assert response.result.installed_at_water_level_mllw_ft == selected.installed_at_water_level_mllw_ft == expected_level
    assert all(line.paid_out_unstretched_length_ft > 0 and line.pretension_lbf is None and line.slack_ft is None for line in config.lines)
    assert all(line.paid_out_unstretched_length_ft is None for line in req.config.lines)  # original request untouched
    # The selected window's last condition uses a different tide but the same installed line lengths.
    stored = RESULTS[selected.analysis_result_ids[-1]]
    last = next(s for s in series if s.valid_at_utc == selected.holding_end_utc)
    repeated = solver.analyze(AnalyzeRequest(ship_class_id=req.ship_class_id, berth_id=req.berth_id, loading=req.loading,
        config=config, environment=last, mst=req.mst, tugs=req.tugs))
    assert [line.tension_lbf for line in repeated.result.lines] == pytest.approx(
        [line['tension_lbf'] for line in stored['result']['lines']], rel=1e-9)
    assert all(condition.installed_at_water_level_mllw_ft is not None
               for condition in response.result.conditions if condition.analysis_result_id)


def test_unsupported_arrivals_do_not_publish_a_selected_installation():
    req = request()
    result = assess(req.model_copy(update={'forecast':req.forecast[:25]})).result
    assert result.selected_config is None and result.installed_at_water_level_mllw_ft is None
    assert 'selected_config' not in result.model_dump(mode='json')
    assert all(window.installed_at_water_level_mllw_ft is None for window in result.windows)



@pytest.mark.parametrize('basis', [None, 'scenario', 'observation', 'prediction_missing_issue'])
def test_future_replay_requires_archived_forecast_provenance(basis):
    req = request(optimize_lines=True)
    metadata = None if basis is None else EnvironmentMetadata(
        basis='prediction' if basis == 'prediction_missing_issue' else basis,
        issued_at_utc=None if basis == 'prediction_missing_issue' else req.as_of_utc,
        quality='good')
    series = [snapshot.model_copy(update={'source':'replay', 'metadata':metadata}) for snapshot in req.forecast]
    response = assess(req.model_copy(update={'forecast':series}))
    assert response.result.recommendation_result_id is None and response.result.evaluations == 0
    assert response.result.selected_arrival_utc is None
    assert response.validity.state == 'invalid' and response.status == 'RED'
    assert all(window.outcome == 'unavailable' for window in response.result.windows)


def test_archived_forecast_replay_with_known_issue_time_remains_usable():
    req = request()
    series = [snapshot.model_copy(update={'source':'replay', 'metadata':EnvironmentMetadata(
        basis='prediction', issued_at_utc=req.as_of_utc, quality='good', source='synthetic archived-forecast test')})
              for snapshot in req.forecast]
    response = assess(req.model_copy(update={'forecast':series}))
    assert response.result.selected_arrival_utc and response.validity.state == 'limited'
    later = [snapshot.model_copy(update={'metadata':snapshot.metadata.model_copy(
        update={'issued_at_utc':req.as_of_utc+timedelta(minutes=1)})}) for snapshot in series]
    rejected = assess(req.model_copy(update={'forecast':later}))
    assert rejected.validity.state == 'invalid' and rejected.result.evaluations == 0


@pytest.mark.parametrize('kind', ['coverage', 'budget', 'depth'])
def test_no_usable_arrival_is_invalid_without_claiming_infeasibility(kind):
    req = request()
    if kind == 'coverage':
        req = req.model_copy(update={'forecast':req.forecast[:25]})
    elif kind == 'budget':
        req = req.model_copy(update={'max_evaluations':1})
    else:
        req = req.model_copy(update={'forecast':[s.model_copy(update={'water_level_mllw_ft':-20}) for s in req.forecast]})
    response = assess(req)
    assert response.validity.state == 'invalid' and response.status == 'RED'
    reason = next(r for r in response.validity.reasons if r.code == 'NO_USABLE_ARRIVAL_ASSESSMENT')
    assert 'does not prove physical infeasibility' in reason.message
    assert response.result.selected_config is None


def test_overloaded_but_assessable_windows_remain_limited_not_invalid():
    req = request()
    req = req.model_copy(update={'forecast':[s.model_copy(update={'wind_speed_kt':75,'wind_gust_kt':100}) for s in req.forecast]})
    response = assess(req)
    assert all(w.outcome == 'overloaded' for w in response.result.windows)
    assert response.status == 'RED' and response.validity.state == 'limited'



@pytest.mark.parametrize("optimize", [False, True])
def test_invalid_depth_snapshot_does_not_abort_other_arrival_assessments(optimize):
    req = request(optimize_lines=optimize)
    bad_at = req.as_of_utc + timedelta(hours=25)
    series = [s.model_copy(update={'water_level_mllw_ft':-100}) if s.valid_at_utc == bad_at else s for s in req.forecast]
    response = assess(req.model_copy(update={'forecast':series}))
    assert response.result.selected_arrival_utc == req.as_of_utc + timedelta(hours=26)
    assert response.result.windows[0].outcome == 'invalid'
    bad = next(c for c in response.result.conditions if c.valid_at_utc == bad_at)
    assert bad.analysis_result_id is None and bad.max_pct_wll is None and bad.validity.state == 'invalid'
    assert bad.validity.reasons[0].code == 'FORECAST_CONDITION_INPUT_INVALID'
    assert response.validity.state == 'limited' and response.status == 'AMBER'


def composed_request(source='forecast', **changes):
    from mooring.core.schemas import EnvironmentComponentProvenance
    req = request(**changes)
    metadata = EnvironmentMetadata(basis='prediction', source='composed test fixture', quality='good',
        wind_averaging_s=60, gust_duration_s=30, wind_reference_height_m=10,
        components=[EnvironmentComponentProvenance(component=kind, source=f'fixture {kind}', basis='prediction',
            issued_at_utc=req.as_of_utc-timedelta(hours=6) if kind == 'wind' else None,
            retrieved_at_utc=req.as_of_utc-timedelta(minutes=1),
            valid_from_utc=req.as_of_utc, valid_to_utc=req.as_of_utc+timedelta(hours=48), quality='good')
            for kind in ('wind', 'current', 'water_level')])
    return req.model_copy(update={'forecast':[snapshot.model_copy(update={'source':source, 'metadata':metadata})
                                              for snapshot in req.forecast]})


@pytest.mark.parametrize('source', ['forecast', 'replay'])
def test_component_retrieval_proves_availability_without_inventing_issuance(source):
    req = composed_request(source)
    before = req.model_dump_json()
    result = assess(req)
    assert result.result.selected_arrival_utc is not None and result.validity.state == 'limited'
    assert result.result.issued_at_utc == [req.as_of_utc-timedelta(hours=6)]
    assert result.result.retrieved_at_utc == [req.as_of_utc-timedelta(minutes=1)]
    assert any('not issuance or forecast freshness' in reason for reason in result.result.limitations)
    assert {'fixture wind', 'fixture current', 'fixture water_level'} <= set(result.result.sources)
    assert all('FORECAST_COMPONENT_ISSUANCE_UNKNOWN' in {r.code for r in c.validity.reasons}
               for c in result.result.conditions)
    assert req.model_dump_json() == before
    assert req.forecast[0].metadata.components[1].issued_at_utc is None


@pytest.mark.parametrize('problem', ['missing_time', 'retrieved_later', 'issued_later', 'observation', 'poor', 'suspect', 'partial'])
def test_component_failure_cannot_be_hidden_by_aggregate_issuance(problem):
    req = composed_request(optimize_lines=True)
    meta = req.forecast[0].metadata
    meta.issued_at_utc = req.as_of_utc-timedelta(hours=6)
    component = meta.components[1]
    if problem == 'missing_time': component.retrieved_at_utc = None
    elif problem == 'retrieved_later': component.retrieved_at_utc = req.as_of_utc+timedelta(minutes=1)
    elif problem == 'issued_later':
        component.issued_at_utc = req.as_of_utc+timedelta(minutes=1)
        component.retrieved_at_utc = req.as_of_utc+timedelta(minutes=2)
    elif problem == 'observation': component.basis = 'observation'
    elif problem == 'partial': meta.components = meta.components[:2]
    else: component.quality = problem
    result = assess(req)
    assert result.result.evaluations == 0 and result.result.recommendation_result_id is None
    assert result.result.selected_arrival_utc is None and result.validity.state == 'invalid'
    assert all(window.outcome == 'unavailable' for window in result.result.windows)


def test_archived_provider_issue_can_predate_planning_even_if_retrieved_later():
    req = composed_request()
    for component in req.forecast[0].metadata.components:
        component.issued_at_utc = req.as_of_utc-timedelta(hours=2)
        component.retrieved_at_utc = req.as_of_utc+timedelta(hours=2)
    result = assess(req)
    assert result.result.selected_arrival_utc is not None
    assert result.result.issued_at_utc == [req.as_of_utc-timedelta(hours=2)]
    assert result.result.retrieved_at_utc == [req.as_of_utc+timedelta(hours=2)]


def test_component_validity_must_cover_the_held_interval():
    req = composed_request()
    req.forecast[0].metadata.components[1].valid_to_utc = req.arrival_from_utc+timedelta(minutes=30)
    result = assess(req)
    assert result.result.selected_arrival_utc is None
    assert all(window.outcome == 'unavailable' for window in result.result.windows)
    assert any('held beyond' in reason for condition in result.result.conditions for reason in condition.reasons)


def test_component_metadata_rejects_duplicate_and_contradictory_timing():
    from mooring.core.schemas import EnvironmentComponentProvenance
    meta = composed_request().forecast[0].metadata
    with pytest.raises(ValueError, match='unique'):
        EnvironmentMetadata.model_validate({**meta.model_dump(), 'components':[meta.components[0],meta.components[0]]})
    with pytest.raises(ValueError, match='issuance is after'):
        EnvironmentComponentProvenance.model_validate({**meta.components[0].model_dump(),
            'issued_at_utc':meta.components[0].retrieved_at_utc+timedelta(seconds=1)})
    with pytest.raises(ValueError):
        EnvironmentComponentProvenance.model_validate({**meta.components[0].model_dump(),
            'retrieved_at_utc':meta.components[0].retrieved_at_utc.replace(tzinfo=None)})


def test_component_quality_and_limits_propagate_to_static_assessment_findings():
    from mooring.loads.validity import environment_findings
    req = composed_request()
    env = req.forecast[0]
    component = env.metadata.components[1]
    component.quality = 'poor'
    component.limitations = ['Tidal-only fixture; no weather residual or pier-depth qualification.']
    findings = environment_findings(env)
    assert ('invalid', 'ENVIRONMENT_COMPONENT_POOR_QUALITY') in {(state, reason.code) for state, reason in findings}
    assert any('Tidal-only' in reason.message for state, reason in findings)
    component.valid_from_utc = req.as_of_utc-timedelta(hours=2)
    component.valid_to_utc = req.as_of_utc-timedelta(hours=1)
    assert any(state == 'invalid' and reason.code == 'ENVIRONMENT_COMPONENT_OUTSIDE_VALID_INTERVAL'
               for state, reason in environment_findings(env))


def test_inactive_component_provenance_preserves_legacy_wire_shape():
    assert 'components' not in EnvironmentMetadata(basis='scenario').model_dump()
    assert 'retrieved_at_utc' not in assess(request()).result.model_dump()
