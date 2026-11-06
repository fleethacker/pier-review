"""Scenario sampling is explicit training, deterministic, and ownership-aware."""
from datetime import UTC, datetime, timedelta, timezone
import json

import pytest

from mooring import environment, refdata
from mooring.core import access, store
from mooring.core.envelopes import resolved_inputs_hash
from mooring.core.schemas.environment import (
    EnvironmentComponentProvenance, EnvironmentMetadata, EnvScenario,
)
from mooring.data_simulation.scenario_forecast import sample_scenario


AS_OF = datetime(2026, 11, 5, 12, tzinfo=UTC)
ARCHIVE_START = datetime(2026, 3, 1, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch):
    database = store.Database(':memory:')
    monkeypatch.setattr(store, '_db', database)
    principal = access.principal.set('scenario-test-owner')
    enforced = access.enforced.set(False)
    yield
    access.principal.reset(principal)
    access.enforced.reset(enforced)
    database.close()


def scenario(**changes):
    values = dict(name='Synthetic sampling test', kind='steady', env_scenario_id='scenario-test',
        created_at_utc=AS_OF, wind_speed_kt=10, wind_gust_kt=15, wind_from_true_deg=90,
        current_speed_kt=0.4, current_set_true_deg=180, water_level_mllw_ft=1)
    values.update(changes)
    value = EnvScenario(**values)
    store.DocStore('env_scenario', EnvScenario)[value.env_scenario_id] = value
    return value


def sample(value=None, **changes):
    value = value or scenario()
    options = dict(as_of_utc=AS_OF, from_utc=AS_OF, to_utc=AS_OF+timedelta(hours=1))
    options.update(changes)
    return sample_scenario(value.env_scenario_id, **options)


def test_steady_samples_exact_times_and_partial_endpoint_without_live_calls(monkeypatch):
    value = scenario()
    calls = []
    original = environment.scenario_snapshot

    def trace(identity, at):
        calls.append((identity, at))
        return original(identity, at)

    def forbidden(*args, **kwargs):
        pytest.fail('Scenario sampling must not read the live clock, current conditions or a public forecast')

    monkeypatch.setattr(environment, 'scenario_snapshot', trace)
    for name in ('now', 'forecast', 'history'):
        monkeypatch.setattr(environment, name, forbidden)
    monkeypatch.setenv('MOORING_ENV_SOURCE', 'coops')
    out, revision = sample(value, to_utc=AS_OF+timedelta(minutes=65))
    expected_times = [AS_OF+timedelta(minutes=i) for i in (0, 30, 60, 65)]
    assert calls == [(value.env_scenario_id, at) for at in expected_times]
    assert [s.valid_at_utc for s in out] == expected_times
    assert [s.wind_speed_kt for s in out] == [10]*4
    assert [s.wind_gust_kt for s in out] == [15]*4
    assert all(s.source == 'scenario' and s.metadata.basis == 'scenario' for s in out)
    assert all('not_a_forecast' in s.quality[-1].flags for s in out)
    assert all(s.metadata.wind_averaging_s is None for s in out)
    assert all(s.metadata.original['scenario_definition_hash'] == revision for s in out)
    assert revision.startswith('sha256:')


def test_ramp_is_sampled_at_each_time_and_stops_at_declared_target():
    value = scenario(kind='ramp', ramp_to_wind_kt=30, ramp_minutes=60)
    out, _ = sample(value, to_utc=AS_OF+timedelta(minutes=75))
    assert [s.wind_speed_kt for s in out] == [10, 20, 30, 30]
    assert [s.wind_gust_kt for s in out] == [15, 30, 45, 45]
    assert [s.valid_at_utc for s in out] == [AS_OF+timedelta(minutes=i) for i in (0, 30, 60, 75)]


def test_steady_supports_plus_24_hour_arrival_with_holding():
    out, _ = sample(from_utc=AS_OF+timedelta(hours=24), to_utc=AS_OF+timedelta(hours=32))
    assert out[0].valid_at_utc == AS_OF+timedelta(hours=24)
    assert out[-1].valid_at_utc == AS_OF+timedelta(hours=32)
    assert len(out) == 17


def test_recorded_replay_keeps_distinct_values_and_full_original_provenance():
    value = scenario(kind='replay', replay_source='recorded_fixture', replay_start_utc=ARCHIVE_START,
                     replay_end_utc=ARCHIVE_START+timedelta(hours=1))
    out, _ = sample(value, to_utc=AS_OF+timedelta(minutes=12), step_min=6)
    assert [s.wind_speed_kt for s in out] == [12, 12.6, 13.2]
    assert [s.water_level_mllw_ft for s in out] == [1, 1.1, 1.2]
    for index, snapshot in enumerate(out):
        mapped = AS_OF+timedelta(minutes=index*6)
        historical = ARCHIVE_START+timedelta(minutes=index*6)
        assert snapshot.valid_at_utc == mapped
        assert snapshot.source == 'scenario' and snapshot.metadata.basis == 'scenario'
        assert snapshot.metadata.issued_at_utc is None
        assert 'not_a_forecast' in snapshot.quality[-1].flags
        original = snapshot.metadata.original
        assert datetime.fromisoformat(original['original_valid_at_utc']) == historical
        assert datetime.fromisoformat(original['replay_query_at_utc']) == historical
        assert original['original_source'] == 'replay'
        raw = json.loads(original['original_snapshot_json'])
        assert original['original_snapshot_hash'] == resolved_inputs_hash(raw)
        assert raw['wind_speed_kt'] == snapshot.wind_speed_kt
        assert raw['metadata']['source'] == 'synthetic recorded-format fixture'
        # Exact recorded knots have zero-width validity; never manufacture a longer archive interval.
        assert snapshot.metadata.valid_from_utc == mapped
        assert snapshot.metadata.valid_to_utc == mapped


def test_synthetic_replay_samples_its_mapping_instead_of_repeating_current():
    value = scenario(kind='replay', replay_start_utc=ARCHIVE_START,
                     replay_end_utc=ARCHIVE_START+timedelta(hours=2))
    out, _ = sample(value)
    expected = [environment.scenario_snapshot(value.env_scenario_id, AS_OF+timedelta(minutes=i))
                for i in (0, 30, 60)]
    assert [s.wind_speed_kt for s in out] == [s.wind_speed_kt for s in expected]
    assert len({s.water_level_mllw_ft for s in out}) > 1
    assert all(s.metadata.original['replay_source'] == 'synthetic' for s in out)
    assert all(s.source == 'scenario' and s.metadata.basis == 'scenario' for s in out)


@pytest.mark.parametrize('replay_source', ['recorded_fixture', 'synthetic'])
def test_finite_replay_exhaustion_rejects_before_any_sampling(monkeypatch, replay_source):
    value = scenario(kind='replay', replay_source=replay_source, replay_start_utc=ARCHIVE_START,
                     replay_end_utc=ARCHIVE_START+timedelta(hours=1))
    calls = []
    monkeypatch.setattr(environment, 'scenario_snapshot', lambda *args: calls.append(args))
    with pytest.raises(refdata.InvalidReference, match='exhausted'):
        sample(value, to_utc=AS_OF+timedelta(hours=1, seconds=1))
    assert calls == []
    with pytest.raises(refdata.InvalidReference, match='exhausted'):
        sample(value, from_utc=AS_OF+timedelta(hours=24), to_utc=AS_OF+timedelta(hours=25))


def test_actual_recorded_coverage_failure_is_propagated_without_synthetic_fallback():
    # Directly stored fixture is deliberately incompatible with the archive.
    value = scenario(kind='replay', replay_source='recorded_fixture',
        replay_start_utc=ARCHIVE_START-timedelta(hours=1), replay_end_utc=ARCHIVE_START)
    from mooring.environment.errors import ProviderError
    with pytest.raises(ProviderError, match='outside the recorded horizon'):
        sample(value, to_utc=AS_OF+timedelta(minutes=6), step_min=6)


def test_definition_hash_is_repeatable_and_includes_creation_anchor_and_values():
    value = scenario()
    first, first_hash = sample(value)
    again, again_hash = sample(value)
    assert [s.model_dump() for s in first] == [s.model_dump() for s in again]
    assert first_hash == again_hash
    assert sample(value, step_min=15)[1] == first_hash
    value.created_at_utc -= timedelta(minutes=1)
    store.DocStore('env_scenario', EnvScenario)[value.env_scenario_id] = value
    assert sample(value)[1] != first_hash
    value.created_at_utc += timedelta(minutes=1)
    value.wind_speed_kt += 1
    store.DocStore('env_scenario', EnvScenario)[value.env_scenario_id] = value
    assert sample(value)[1] != first_hash


def test_input_offsets_are_equivalent_and_source_objects_are_unchanged():
    value = scenario()
    original_definition = value.model_dump()
    first, first_hash = sample(value)
    zone = timezone(timedelta(hours=-5))
    other, other_hash = sample(value, as_of_utc=AS_OF.astimezone(zone),
        from_utc=AS_OF.astimezone(zone), to_utc=(AS_OF+timedelta(hours=1)).astimezone(zone))
    assert first_hash == other_hash
    assert [s.model_dump() for s in first] == [s.model_dump() for s in other]
    first[0].quality.clear()
    first[0].metadata.original.clear()
    fresh, _ = sample(value)
    assert fresh[0].quality
    assert fresh[0].metadata.original
    assert environment.get_scenario(value.env_scenario_id).model_dump() == original_definition


def test_original_quality_components_and_physical_basis_are_preserved_without_mutation(monkeypatch):
    value = scenario(kind='replay', replay_start_utc=ARCHIVE_START)
    original = environment.scenario_snapshot(value.env_scenario_id, AS_OF)
    original.metadata = EnvironmentMetadata(basis='prediction', source='Fictional provider test record',
        issued_at_utc=ARCHIVE_START-timedelta(hours=2), valid_from_utc=ARCHIVE_START,
        valid_to_utc=ARCHIVE_START+timedelta(hours=2), wind_averaging_s=60, gust_duration_s=3,
        current_depth_ft=12, quality='suspect', components=[EnvironmentComponentProvenance(
            component='current', source='Fictional current test record', basis='prediction',
            issued_at_utc=ARCHIVE_START-timedelta(hours=2), retrieved_at_utc=ARCHIVE_START-timedelta(hours=1),
            valid_from_utc=ARCHIVE_START, valid_to_utc=ARCHIVE_START+timedelta(hours=2),
            quality='suspect', limitations=['Depth representativeness unknown'])])
    original.quality[0].flags.append('current_stale')
    before = original.model_dump()

    def supplied(identity, at):
        return original.model_copy(deep=True, update={'valid_at_utc': ARCHIVE_START+(at-AS_OF)})

    monkeypatch.setattr(environment, 'scenario_snapshot', supplied)
    out, _ = sample(value)
    item = out[0]
    assert item.metadata.wind_averaging_s == 60 and item.metadata.gust_duration_s == 3
    assert item.metadata.current_depth_ft == 12 and item.metadata.quality == 'suspect'
    assert 'current_stale' in item.quality[0].flags
    current = item.metadata.components[0]
    assert current.quality == 'suspect' and current.basis == 'scenario'
    assert current.issued_at_utc is None and current.retrieved_at_utc is None
    assert current.valid_from_utc == AS_OF and current.valid_to_utc == AS_OF+timedelta(hours=2)
    assert current.limitations[0] == 'Depth representativeness unknown'
    stored = json.loads(item.metadata.original['original_snapshot_json'])
    assert stored['metadata']['components'][0]['issued_at_utc'] is not None
    assert original.model_dump() == before


def test_public_getter_preserves_principal_ownership():
    token = access.enforced.set(True)
    try:
        value = scenario()
        sample(value)
        other = access.principal.set('different-principal')
        try:
            with pytest.raises(refdata.NotFound):
                sample(value)
        finally:
            access.principal.reset(other)
    finally:
        access.enforced.reset(token)


def test_changed_definition_during_sampling_is_rejected(monkeypatch):
    value = scenario()
    original = environment.scenario_snapshot

    def changed(identity, at):
        snapshot = original(identity, at)
        revised = environment.get_scenario(identity)
        revised.water_level_mllw_ft += 1
        store.DocStore('env_scenario', EnvScenario)[identity] = revised
        return snapshot

    monkeypatch.setattr(environment, 'scenario_snapshot', changed)
    with pytest.raises(refdata.InvalidReference, match='changed while'):
        sample(value)


def test_sampler_returning_current_snapshot_instead_of_requested_time_is_rejected(monkeypatch):
    value = scenario()
    current = environment.scenario_snapshot(value.env_scenario_id, AS_OF)
    monkeypatch.setattr(environment, 'scenario_snapshot', lambda *args: current)
    with pytest.raises(refdata.InvalidReference, match='requested sample time'):
        sample(value)


@pytest.mark.parametrize('options,match', [
    ({'from_utc': AS_OF-timedelta(minutes=1)}, 'before planning'),
    ({'to_utc': AS_OF}, 'after its start'),
    ({'as_of_utc': AS_OF.replace(tzinfo=None)}, 'timezone-aware'),
    ({'from_utc': AS_OF.replace(tzinfo=None)}, 'timezone-aware'),
    ({'to_utc': AS_OF.replace(tzinfo=None)}, 'timezone-aware'),
    ({'step_min': 0}, 'step'), ({'step_min': 181}, 'step'), ({'step_min': True}, 'step'),
    ({'to_utc': AS_OF+timedelta(minutes=721), 'step_min': 1}, '721 samples'),
    ({'max_samples': 0}, 'sample limit'), ({'max_samples': 1202}, 'sample limit'),
    ({'max_samples': True}, 'sample limit'), ({'max_samples': 1.5}, 'sample limit'),
])
def test_invalid_schedule_and_work_limit_are_rejected(options, match):
    with pytest.raises(refdata.InvalidReference, match=match):
        sample(**options)


def test_scenario_created_after_as_of_cannot_be_backfilled_into_a_plan():
    value = scenario(created_at_utc=AS_OF+timedelta(minutes=1),
                     kind='ramp', ramp_to_wind_kt=30, ramp_minutes=60)
    with pytest.raises(refdata.InvalidReference, match='created after'):
        sample(value)


def test_exact_sample_count_limit_is_allowed():
    out, _ = sample(to_utc=AS_OF+timedelta(minutes=720), step_min=1)
    assert len(out) == 721
    assert out[-1].valid_at_utc == AS_OF+timedelta(minutes=720)
