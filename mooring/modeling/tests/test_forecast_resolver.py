"""Offline revision and coverage tests; all numbers here are synthetic fixtures."""
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from mooring import refdata
from mooring.core.schemas.environment import (
    EnvironmentComponentProvenance, EnvironmentMetadata, EnvironmentSnapshot, StationQuality,
)
from mooring.core.schemas.forecast_planning import ForecastDockingRequest
from mooring.moored.forecast_resolver import input_problem, resolve_forecast


AS_OF = datetime(2026, 11, 5, 12, tzinfo=UTC)
START = AS_OF + timedelta(hours=24)
HOUR = timedelta(hours=1)


def samples():
    return [EnvironmentSnapshot(
        valid_at_utc=START + i * HOUR, source='scenario',
        wind_speed_kt=10 + i, wind_gust_kt=14 + i, wind_from_true_deg=90,
        current_speed_kt=0.4, current_set_true_deg=180, water_level_mllw_ft=1 + i / 10,
        metadata=EnvironmentMetadata(basis='scenario', source='Synthetic resolver test',
            wind_averaging_s=60, gust_duration_s=3, wind_reference_height_m=10,
            current_depth_ft=6, vertical_datum='MLLW', quality='good'),
        quality=[StationQuality(station_id='test-scenario', age_s=0, flags=['synthetic'])],
    ) for i in range(4)]


def public_samples():
    """Fictional provider records exercise timing rules, never represent public data."""
    out = samples()
    for sample in out:
        sample.source = 'forecast'
        sample.metadata.basis = 'prediction'
        sample.metadata.issued_at_utc = AS_OF - HOUR
        sample.metadata.components = [EnvironmentComponentProvenance(
            component=component, source=f'Synthetic {component} provider fixture', basis='prediction',
            issued_at_utc=AS_OF-HOUR, retrieved_at_utc=AS_OF,
            valid_from_utc=START, valid_to_utc=START+3*HOUR,
            quality='good', limitations=['Synthetic test values, not observed or predicted weather.'],
        ) for component in ('wind', 'current', 'water_level')]
    return out


def resolved(series=None, **kwargs):
    options = {'as_of_utc': AS_OF, 'from_utc': START, 'to_utc': START+3*HOUR}
    options.update(kwargs)
    return resolve_forecast(samples() if series is None else series, **options)


def test_fixture_covers_plus_24_hours_through_docking_and_holding():
    path = Path(__file__).parents[2] / 'contract/examples/modeling/mooring_forecast_plan.json'
    req = ForecastDockingRequest.model_validate(json.loads(path.read_text()))
    end = req.arrival_to_utc + timedelta(hours=req.operation_hours + req.holding_hours)
    revision = resolve_forecast(req.forecast, as_of_utc=req.as_of_utc,
        from_utc=req.arrival_from_utc, to_utc=end, max_gap_min=req.max_gap_min)
    revision.require_coverage()
    assert req.arrival_from_utc >= req.as_of_utc + timedelta(hours=24)
    assert revision.snapshots()[-1].valid_at_utc >= end
    assert all(s.source == 'scenario' for s in revision.snapshots())


@pytest.mark.parametrize('options', [
    {'from_utc': AS_OF-HOUR},
    {'to_utc': START},
    {'to_utc': AS_OF+timedelta(hours=121)},
])
def test_direct_resolver_cannot_bypass_api_horizon_limits(options):
    with pytest.raises(refdata.InvalidReference, match='horizon'):
        resolved(**options)


def test_input_and_output_mutation_cannot_change_frozen_revision():
    original = public_samples()
    revision = resolved(original)
    content_hash, binding_hash = revision.content_hash, revision.binding_hash
    original[0].wind_gust_kt = 999
    original[0].metadata.components[0].limitations.append('Changed source object')
    original.clear()
    copy = revision.snapshots()
    copy[0].wind_gust_kt = 888
    copy[0].quality[0].flags.append('unavailable')
    copy[0].metadata.components[0].limitations.clear()
    manifest = revision.manifest()
    manifest['content_hash'] = 'changed'
    fresh = revision.snapshots()
    assert fresh[0].wind_gust_kt == 14
    assert fresh[0].quality[0].flags == ['synthetic']
    assert fresh[0].metadata.components[0].limitations == ['Synthetic test values, not observed or predicted weather.']
    assert revision.content_hash == content_hash
    assert revision.binding_hash == binding_hash
    assert revision.coverage_problem(START, START+3*HOUR) is None
    with pytest.raises(FrozenInstanceError):
        revision.content_hash = 'changed'


def test_equivalent_utc_offsets_and_component_order_have_identical_hashes():
    original = public_samples()
    shifted = [sample.model_copy(deep=True) for sample in original]
    zone = timezone(timedelta(hours=-5))
    for sample in shifted:
        sample.valid_at_utc = sample.valid_at_utc.astimezone(zone)
        sample.metadata.issued_at_utc = sample.metadata.issued_at_utc.astimezone(zone)
        for component in sample.metadata.components:
            for field in ('issued_at_utc', 'retrieved_at_utc', 'valid_from_utc', 'valid_to_utc'):
                setattr(component, field, getattr(component, field).astimezone(zone))
        sample.metadata.components.reverse()
    first = resolved(original)
    second = resolved(shifted, as_of_utc=AS_OF.astimezone(zone),
        from_utc=START.astimezone(zone), to_utc=(START+3*HOUR).astimezone(zone))
    assert first.content_hash == second.content_hash
    assert first.binding_hash == second.binding_hash
    assert first.manifest() == second.manifest()
    assert shifted[0].valid_at_utc.utcoffset() == timedelta(hours=-5)
    assert second.snapshots()[0].valid_at_utc.utcoffset() == timedelta(0)


@pytest.mark.parametrize('override', [
    {'source_id': 'Another declared product'}, {'revision': 'run-2'},
    {'as_of_utc': AS_OF-HOUR}, {'from_utc': START+timedelta(minutes=1)},
    {'to_utc': START+2*HOUR}, {'max_gap_min': 90},
    {'source': 'scenario', 'env_scenario_id': 'test-scenario'},
])
def test_binding_hash_tracks_cutoff_horizon_source_revision_and_policy(override):
    first, second = resolved(), resolved(**override)
    assert first.content_hash == second.content_hash
    assert first.binding_hash != second.binding_hash


@pytest.mark.parametrize('field,value', [
    ('wind_gust_kt', 50), ('current_speed_kt', 1.2), ('water_level_mllw_ft', 2.5),
])
def test_declared_revision_cannot_hide_changed_values(field, value):
    original = samples()
    first = resolved(original, revision='declared-run-1')
    setattr(original[1], field, value)
    second = resolved(original, revision='declared-run-1')
    assert first.revision == second.revision
    assert first.content_hash != second.content_hash
    assert first.binding_hash != second.binding_hash
    with pytest.raises(refdata.InvalidReference, match='content hash'):
        resolved(original, revision='declared-run-1', expected_content_hash=first.content_hash)


def test_provenance_and_depth_are_content_not_only_numbers():
    original = public_samples()
    first = resolved(original)
    original[0].metadata.current_depth_ft = 12
    deeper = resolved(original)
    assert deeper.content_hash != first.content_hash
    original[0].metadata.components[0].limitations.append('Additional applicability restriction')
    limited = resolved(original)
    assert limited.content_hash != deeper.content_hash
    assert limited.snapshots()[0].metadata.current_depth_ft == 12
    assert limited.revision == limited.content_hash
    assert resolved(original, expected_content_hash=limited.content_hash).binding_hash == limited.binding_hash


@pytest.mark.parametrize('options,match', [
    ({'source': 'live'}, 'source'),
    ({'source': 'scenario'}, 'env_scenario_id'),
    ({'env_scenario_id': 'test-scenario'}, 'env_scenario_id'),
    ({'source_id': '  '}, 'source_id'),
    ({'revision': ''}, 'revision'),
    ({'max_gap_min': 0}, 'gap'),
    ({'max_gap_min': 181}, 'gap'),
    ({'max_gap_min': True}, 'gap'),
    ({'from_utc': START.replace(tzinfo=None)}, 'timezone-aware'),
    ({'to_utc': START-HOUR}, 'precedes'),
    ({'as_of_utc': AS_OF.replace(tzinfo=None)}, 'timezone-aware'),
])
def test_invalid_bindings_are_rejected(options, match):
    with pytest.raises(refdata.InvalidReference, match=match):
        resolved(**options)


@pytest.mark.parametrize('case,match', [
    ('empty', 'between 2 and 1201'), ('one', 'between 2 and 1201'),
    ('duplicate', 'increasing'), ('reversed', 'increasing'),
    ('naive', 'timezone-aware'), ('nan', 'Invalid forecast snapshot'),
])
def test_structurally_invalid_series_are_rejected(case, match):
    series = samples()
    if case == 'empty':
        series = []
    elif case == 'one':
        series = series[:1]
    elif case == 'duplicate':
        series[1].valid_at_utc = series[0].valid_at_utc
    elif case == 'reversed':
        series.reverse()
    elif case == 'naive':
        series[1].valid_at_utc = series[1].valid_at_utc.replace(tzinfo=None)
    elif case == 'nan':
        series[1].wind_speed_kt = float('nan')
    with pytest.raises(refdata.InvalidReference, match=match):
        resolved(series)


def test_exact_final_knot_is_covered_but_extrapolation_is_rejected():
    revision = resolved(to_utc=START+4*HOUR)
    assert revision.coverage_problem(START, START+3*HOUR) is None
    assert revision.snapshot_at(START+3*HOUR).wind_speed_kt == 13
    assert 'does not cover' in revision.coverage_problem(START, START+3*HOUR+timedelta(seconds=1))
    with pytest.raises(refdata.InvalidReference, match='does not cover'):
        revision.require_coverage()
    with pytest.raises(refdata.InvalidReference, match='does not cover'):
        revision.snapshot_at(START+3*HOUR+timedelta(seconds=1))


def test_holding_preserves_actual_sample_time_and_values():
    revision = resolved()
    held = revision.snapshot_at(START+timedelta(minutes=20))
    assert held.valid_at_utc == START
    assert held.wind_speed_kt == 10
    assert held.wind_gust_kt == 14
    assert revision.snapshot_at(START+HOUR).wind_speed_kt == 11


def test_source_data_outside_bound_horizon_cannot_be_used():
    revision = resolved(from_utc=START+HOUR, to_utc=START+2*HOUR)
    assert 'bound forecast horizon' in revision.coverage_problem(START, START+HOUR)
    with pytest.raises(refdata.InvalidReference, match='bound forecast horizon'):
        revision.snapshot_at(START+3*HOUR)


def test_missing_start_cannot_be_replaced_by_first_snapshot():
    revision = resolved(from_utc=START-HOUR)
    assert 'does not cover' in revision.coverage_problem(START-HOUR, START+HOUR)
    assert revision.coverage_problem(START, START+HOUR) is None


def test_short_operation_inside_long_source_gap_is_not_covered():
    series = samples()
    del series[1]
    revision = resolved(series)
    assert 'gap' in revision.coverage_problem(START, START+timedelta(minutes=10))
    with pytest.raises(refdata.InvalidReference, match='gap'):
        revision.snapshot_at(START+timedelta(minutes=10))
    # A gap before an independent later arrival does not erase that arrival.
    assert revision.coverage_problem(START+2*HOUR, START+3*HOUR) is None


@pytest.mark.parametrize('target', ['aggregate', 'wind', 'current', 'water_level'])
def test_future_issuance_rejects_only_operations_using_that_sample(target):
    series = public_samples()
    if target == 'aggregate':
        series[1].metadata.issued_at_utc = AS_OF+timedelta(minutes=1)
    else:
        component = next(c for c in series[1].metadata.components if c.component == target)
        component.issued_at_utc = AS_OF+timedelta(minutes=1)
        component.retrieved_at_utc = AS_OF+timedelta(minutes=2)
    revision = resolved(series)
    assert revision.coverage_problem(START, START+timedelta(minutes=30)) is None
    assert revision.coverage_problem(START, START+2*HOUR) is not None
    assert revision.coverage_problem(START+2*HOUR, START+3*HOUR) is None


def test_retrieval_only_provenance_is_retained_and_never_called_issuance():
    series = public_samples()
    for sample in series:
        sample.metadata.issued_at_utc = None
        for component in sample.metadata.components:
            component.issued_at_utc = None
    revision = resolved(series)
    revision.require_coverage()
    assert all(c.issued_at_utc is None for c in revision.snapshots()[0].metadata.components)
    assert all(c.retrieved_at_utc == AS_OF for c in revision.snapshots()[0].metadata.components)
    series[1].metadata.components[0].retrieved_at_utc = AS_OF+HOUR
    late = resolved(series)
    assert 'availability' in late.coverage_problem(START, START+2*HOUR)


@pytest.mark.parametrize('issue', ['poor', 'suspect', 'missing', 'stale', 'observation', 'component_absent'])
def test_bad_interior_sample_and_exact_endpoint_cannot_be_hidden(issue):
    series = public_samples()
    sample = series[1]
    if issue in ('poor', 'suspect'):
        sample.metadata.components[1].quality = issue
    elif issue in ('missing', 'stale'):
        sample.quality[0].flags.append(f'current_{issue}')
    elif issue == 'observation':
        sample.metadata.components[1].basis = 'observation'
    else:
        sample.metadata.components.pop()
    revision = resolved(series)
    assert revision.coverage_problem(START, START+HOUR) is not None
    assert revision.coverage_problem(START, START+2*HOUR) is not None
    assert revision.coverage_problem(START+2*HOUR, START+3*HOUR) is None


@pytest.mark.parametrize('target', ['aggregate', 'wind', 'current', 'water_level'])
def test_component_validity_must_cover_entire_held_interval(target):
    series = public_samples()
    metadata = series[0].metadata
    target_metadata = metadata if target == 'aggregate' else next(c for c in metadata.components if c.component == target)
    target_metadata.valid_to_utc = START+timedelta(minutes=30)
    revision = resolved(series)
    assert revision.coverage_problem(START, START+timedelta(minutes=30)) is None
    assert 'declared validity interval' in revision.coverage_problem(START, START+timedelta(minutes=31))


def test_unknown_basis_stays_unknown_and_synthetic_stays_synthetic():
    series = samples()
    for sample in series:
        sample.metadata = None
    revision = resolved(series)
    revision.require_coverage()
    assert all(s.metadata is None and s.source == 'scenario' for s in revision.snapshots())


def test_direct_input_problem_rejects_invalid_hold_endpoint():
    sample = samples()[0]
    assert 'timezone-aware' in input_problem(sample, AS_OF, START.replace(tzinfo=None))
    assert 'precedes' in input_problem(sample, AS_OF, START-timedelta(seconds=1))
