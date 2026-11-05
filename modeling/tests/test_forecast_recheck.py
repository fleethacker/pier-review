"""Forecast changes require explicit new assessment and leave prior evidence intact."""
from contextlib import contextmanager
from datetime import timedelta, timezone
import json
from pathlib import Path

import pytest

from mooring import refdata
from mooring.core import access, store
from mooring.core.envelopes import RESULTS, new_id
from mooring.core.schemas import EnvironmentComponentProvenance, EnvironmentMetadata
from mooring.core.schemas.forecast_planning import (
    ForecastBinding, ForecastDockingRequest, ForecastRecheckRequest, ForecastRecheckResponse,
)
from mooring.moored.forecast_planning import assess
from mooring.moored.forecast_recheck import recheck


@pytest.fixture(scope='module')
def baseline():
    path = Path(__file__).resolve().parents[2] / 'contract/examples/modeling/mooring_forecast_plan.json'
    raw = json.loads(path.read_text())
    raw.update(arrival_to_utc=raw['arrival_from_utc'], operation_hours=1, holding_hours=0,
               forecast_binding={'source': 'supplied', 'source_id': 'offline-training', 'revision': 'revision-1'})
    for snapshot in raw['forecast']:
        snapshot.update(wind_speed_kt=4, wind_gust_kt=5, current_speed_kt=.1)
    request = ForecastDockingRequest.model_validate(raw)
    result = assess(request)
    assert result.result.selected_arrival_utc is not None
    assert result.validity.state == 'limited'
    return request, result


def check_request(baseline, **changes):
    original, response = baseline
    values = dict(prior_result_id=response.result_id,
                  as_of_utc=original.as_of_utc + timedelta(hours=2),
                  forecast=[sample.model_copy(deep=True) for sample in original.forecast],
                  forecast_binding=original.forecast_binding.model_copy(deep=True))
    return ForecastRecheckRequest(**(values | changes))


def copy_result(response, mutate):
    """Create separate historical fixtures without overwriting any result."""
    value = response.model_dump(mode='json')
    value['result_id'] = new_id('test_forecast')
    mutate(value)
    RESULTS[value['result_id']] = value
    return value['result_id']


def test_identical_revision_at_later_as_of_is_unchanged_and_still_limited(baseline):
    response = recheck(check_request(baseline))
    assert response.result.state == 'unchanged'
    assert response.result.previous_forecast_manifest.content_hash == response.result.current_forecast_manifest.content_hash
    assert response.result.previous_forecast_manifest.as_of_utc != response.result.current_forecast_manifest.as_of_utc
    assert response.result.reassessment_request is None
    assert response.backend == 'real' and response.status == 'AMBER'
    assert response.validity.state == 'limited'
    ForecastRecheckResponse.model_validate(response.model_dump(mode='json'))


def test_revision_change_requires_recheck_without_solving_or_mutating(baseline, monkeypatch):
    original, prior = baseline
    prior_bytes = store.canonical(RESULTS[prior.result_id])
    snapshot_before = store.load_snapshot(prior.manifest.resolved_inputs_hash)
    from mooring.moored import solver
    monkeypatch.setattr(solver, 'analyze', lambda *args, **kwargs: pytest.fail('recheck must not run physics'))
    req = check_request(baseline, forecast_binding=ForecastBinding(
        source='supplied', source_id='offline-training', revision='revision-2'))
    response = recheck(req)
    assert response.result.state == 'recheck_required'
    assert any('revision changed' in reason for reason in response.result.reasons)
    assert response.result.previous_forecast_manifest.content_hash == response.result.current_forecast_manifest.content_hash
    assert store.canonical(RESULTS[prior.result_id]) == prior_bytes
    assert store.load_snapshot(prior.manifest.resolved_inputs_hash) == snapshot_before
    suggested = response.result.reassessment_request
    assert suggested.config == prior.result.selected_config
    assert suggested.installed_at_water_level_mllw_ft == prior.result.installed_at_water_level_mllw_ft
    assert suggested.arrival_from_utc == suggested.arrival_to_utc == prior.result.selected_arrival_utc
    assert suggested.operation_hours == original.operation_hours and suggested.holding_hours == original.holding_hours
    assert suggested.forecast_binding.expected_content_hash == response.result.current_forecast_manifest.content_hash
    assert suggested.allow_short_lead and not suggested.optimize_lines
    assert all(line.paid_out_unstretched_length_ft is not None for line in suggested.config.lines)


def test_explicit_reassessment_at_changed_tide_preserves_installation_and_prior_result(baseline):
    _, prior = baseline
    before = store.canonical(RESULTS[prior.result_id])
    req = check_request(baseline)
    for snapshot in req.forecast:
        snapshot.water_level_mllw_ft += .5
    comparison = recheck(req)
    assert comparison.result.state == 'recheck_required'
    repeated = assess(comparison.result.reassessment_request)
    assert repeated.result_id != prior.result_id
    assert repeated.result.selected_config == prior.result.selected_config
    assert repeated.result.installed_at_water_level_mllw_ft == prior.result.installed_at_water_level_mllw_ft
    assert all(condition.installed_at_water_level_mllw_ft == prior.result.installed_at_water_level_mllw_ft
               for condition in repeated.result.conditions if condition.analysis_result_id)
    assert repeated.result.forecast_manifest.content_hash != prior.result.forecast_manifest.content_hash
    assert repeated.validity.state == 'limited'
    assert store.canonical(RESULTS[prior.result_id]) == before


def test_changed_values_under_same_revision_are_not_trusted(baseline):
    req = check_request(baseline)
    req.forecast[24].wind_gust_kt += 2
    response = recheck(req)
    assert response.result.state == 'recheck_required'
    assert response.result.previous_forecast_manifest.revision == response.result.current_forecast_manifest.revision
    assert response.result.previous_forecast_manifest.content_hash != response.result.current_forecast_manifest.content_hash
    assert any('content or source provenance changed' in reason for reason in response.result.reasons)


def test_changed_source_identity_requires_recheck_even_when_values_match(baseline):
    req = check_request(baseline, forecast_binding=ForecastBinding(
        source='supplied', source_id='different-training-series', revision='revision-1'))
    response = recheck(req)
    assert response.result.state == 'recheck_required'
    assert any('source or environment scenario changed' in reason for reason in response.result.reasons)


@pytest.mark.parametrize('kind', ['issuance', 'retrieval'])
def test_provenance_only_change_remains_visible(baseline, kind):
    req = check_request(baseline)
    for sample in req.forecast:
        if kind == 'issuance':
            sample.metadata.issued_at_utc += timedelta(minutes=1)
        else:
            sample.metadata.components = [EnvironmentComponentProvenance(
                component=component, source='offline fixture', basis='scenario',
                issued_at_utc=baseline[0].as_of_utc,
                retrieved_at_utc=req.as_of_utc - timedelta(minutes=1),
            ) for component in ('wind', 'current', 'water_level')]
    response = recheck(req)
    assert response.result.state == 'recheck_required'
    assert response.result.previous_forecast_manifest.content_hash != response.result.current_forecast_manifest.content_hash


@pytest.mark.parametrize('kind', ['future_issue', 'poor_quality', 'stale', 'short_coverage', 'gap'])
def test_unusable_replacement_never_offers_reassessment_as_if_covered(baseline, kind):
    req = check_request(baseline)
    if kind == 'future_issue':
        for sample in req.forecast:
            sample.metadata.issued_at_utc = req.as_of_utc + timedelta(minutes=1)
    elif kind == 'poor_quality':
        req.forecast[24].metadata.quality = 'poor'
    elif kind == 'stale':
        req.forecast[24].quality[0].flags.append('stale')
    elif kind == 'short_coverage':
        req.forecast = req.forecast[:25]
    else:
        req.forecast = req.forecast[:24] + req.forecast[26:]
    response = recheck(req)
    assert response.result.state == 'unavailable'
    assert response.status == 'RED' and response.validity.state == 'invalid'
    assert response.result.reassessment_request is None
    assert response.result.reasons


def test_actual_issuance_allows_later_archive_retrieval_without_faking_issue_time(baseline):
    req = check_request(baseline)
    for sample in req.forecast:
        sample.source = 'forecast'
        sample.metadata = EnvironmentMetadata(basis='prediction', issued_at_utc=baseline[0].as_of_utc,
            quality='good', components=[EnvironmentComponentProvenance(
                component=component, source='offline archive fixture', basis='prediction',
                issued_at_utc=baseline[0].as_of_utc,
                retrieved_at_utc=req.as_of_utc + timedelta(days=1), quality='good',
            ) for component in ('wind', 'current', 'water_level')])
    response = recheck(req)
    assert response.result.state == 'recheck_required'
    assert response.result.reassessment_request is not None
    assert response.validity.state == 'limited'
    assert all(component.issued_at_utc == baseline[0].as_of_utc
               for component in response.result.reassessment_request.forecast[24].metadata.components)


def test_equivalent_time_offsets_do_not_create_a_new_revision(baseline):
    req = check_request(baseline)
    offset = timezone(timedelta(hours=-5))
    req.as_of_utc = req.as_of_utc.astimezone(offset)
    for sample in req.forecast:
        sample.valid_at_utc = sample.valid_at_utc.astimezone(offset)
        sample.metadata.issued_at_utc = sample.metadata.issued_at_utc.astimezone(offset)
    response = recheck(req)
    assert response.result.state == 'unchanged'


@pytest.mark.parametrize('timing', ['before_original', 'after_arrival'])
def test_recheck_cannot_retroactively_approve_or_predate_its_evidence(baseline, timing):
    original, prior = baseline
    as_of = (original.as_of_utc - timedelta(seconds=1) if timing == 'before_original'
             else prior.result.selected_arrival_utc + timedelta(seconds=1))
    response = recheck(check_request(baseline, as_of_utc=as_of))
    assert response.result.state == 'unavailable'
    assert response.result.reassessment_request is None
    assert response.status == 'RED'


def test_future_selected_arrival_survives_elapsed_unselected_alternative(baseline):
    original, _ = baseline
    candidate = original.model_copy(deep=True)
    candidate.arrival_to_utc += timedelta(hours=2)
    candidate.forecast[24].wind_gust_kt = 100
    prior = assess(candidate)
    assert prior.result.selected_arrival_utc == original.arrival_from_utc + timedelta(hours=1)
    response = recheck(check_request((candidate, prior),
        as_of_utc=original.arrival_from_utc + timedelta(minutes=30)))
    assert response.result.state == 'unchanged'
    assert response.result.current_forecast_manifest.from_utc == prior.result.selected_arrival_utc


def test_no_selected_installation_keeps_original_candidates_without_inventing_tide(baseline):
    original, _ = baseline
    candidate = original.model_copy(deep=True)
    candidate.arrival_to_utc += timedelta(hours=1)
    for snapshot in candidate.forecast:
        snapshot.wind_gust_kt = 100
    prior = assess(candidate)
    assert prior.result.selected_arrival_utc is None
    req = check_request((candidate, prior), forecast_binding=ForecastBinding(
        source='supplied', source_id='offline-training', revision='revision-2'))
    response = recheck(req)
    assert response.result.state == 'recheck_required'
    assert response.result.reassessment_request.arrival_from_utc == candidate.arrival_from_utc
    assert response.result.reassessment_request.arrival_to_utc == candidate.arrival_to_utc
    assert response.result.reassessment_request.config == prior.result.config
    assert response.result.reassessment_request.installed_at_water_level_mllw_ft is None
    assert response.result.installed_at_water_level_mllw_ft is None
    assert response.status == 'RED'


def test_missing_result_and_wrong_model_are_explicit_errors(baseline):
    with pytest.raises(refdata.NotFound):
        recheck(check_request(baseline, prior_result_id='not-a-result'))
    wrong_id = copy_result(baseline[1], lambda value: value.update(model='mooring.static'))
    with pytest.raises(refdata.InvalidReference, match='forecast docking'):
        recheck(check_request(baseline, prior_result_id=wrong_id))


def test_legacy_result_with_no_revision_is_unavailable(baseline):
    legacy_id = copy_result(baseline[1], lambda value: value['result'].pop('forecast_manifest'))
    response = recheck(check_request(baseline, prior_result_id=legacy_id))
    assert response.result.state == 'unavailable'
    assert response.result.previous_forecast_manifest is None


def test_unusable_legacy_manifest_does_not_crash_or_establish_identity(baseline):
    legacy_id = copy_result(baseline[1], lambda value: value['result']['forecast_manifest'].update(content_hash='unknown'))
    response = recheck(check_request(baseline, prior_result_id=legacy_id))
    assert response.result.state == 'unavailable'
    assert response.result.previous_forecast_manifest is None


def test_missing_snapshot_or_mismatched_manifest_is_unavailable(baseline):
    missing_id = copy_result(baseline[1], lambda value: value['manifest'].update(resolved_inputs_hash='sha256:missing'))
    response = recheck(check_request(baseline, prior_result_id=missing_id))
    assert response.result.state == 'unavailable'
    mismatch_id = copy_result(baseline[1], lambda value: value['result']['forecast_manifest'].update(revision='mismatch'))
    response = recheck(check_request(baseline, prior_result_id=mismatch_id))
    assert response.result.state == 'unavailable'


@contextmanager
def identity(principal):
    token = access.principal.set(principal)
    enforced = access.enforced.set(True)
    try:
        yield
    finally:
        access.enforced.reset(enforced)
        access.principal.reset(token)


def test_foreign_prior_is_hidden_before_snapshot_lookup(baseline, monkeypatch):
    with identity('recheck-owner-a'):
        owned_id = copy_result(baseline[1], lambda value: None)
    monkeypatch.setattr(store, 'load_snapshot', lambda *args: pytest.fail('foreign snapshot must not be loaded'))
    with identity('recheck-owner-b'), pytest.raises(refdata.NotFound):
        recheck(check_request(baseline, prior_result_id=owned_id))


def test_identical_rechecks_have_new_ids_and_stable_input_evidence(baseline):
    req = check_request(baseline, forecast_binding=ForecastBinding(
        source='supplied', source_id='offline-training', revision='revision-2'))
    first, second = recheck(req), recheck(req)
    assert first.result_id != second.result_id
    assert first.manifest.resolved_inputs_hash == second.manifest.resolved_inputs_hash
    assert first.result == second.result
    assert RESULTS[first.result_id]['result'] == RESULTS[second.result_id]['result']


def test_invalid_prior_cannot_be_upgraded_by_unchanged_guidance(baseline):
    invalid_id = copy_result(baseline[1], lambda value: value.update(
        status='RED', validity={'state': 'invalid', 'reasons': [{'code': 'TEST_INVALID', 'message': 'Unusable prior'}]}))
    response = recheck(check_request(baseline, prior_result_id=invalid_id))
    assert response.result.state == 'unchanged'
    assert response.status == 'RED' and response.validity.state == 'invalid'


def test_suggested_request_and_stored_prior_are_independent_objects(baseline):
    req = check_request(baseline, forecast_binding=ForecastBinding(
        source='supplied', source_id='offline-training', revision='revision-2'))
    before = store.canonical(RESULTS[baseline[1].result_id])
    response = recheck(req)
    response.result.reassessment_request.config.lines[0].parts += 1
    req.forecast[24].wind_gust_kt += 100
    assert store.canonical(RESULTS[baseline[1].result_id]) == before
    stored = RESULTS[response.result_id]
    assert stored['result']['reassessment_request']['config']['lines'][0]['parts'] != response.result.reassessment_request.config.lines[0].parts
