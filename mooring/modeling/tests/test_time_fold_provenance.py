"""Named-zone repeated hours must use absolute ordering, not Python wall-clock comparisons."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from mooring.core.forecast_provenance import availability_problem
from mooring.core.schemas import EnvironmentComponentProvenance, EnvironmentMetadata, EnvironmentSnapshot
from mooring.loads.validity import environment_findings

NY = ZoneInfo('America/New_York')
EARLIER = datetime(2026, 11, 1, 1, 45, tzinfo=NY, fold=0)  # 05:45Z
LATER = datetime(2026, 11, 1, 1, 15, tzinfo=NY, fold=1)  # 06:15Z


def snapshot(**updates):
    return EnvironmentSnapshot(valid_at_utc=LATER, source='scenario', wind_speed_kt=5, wind_gust_kt=8,
        wind_from_true_deg=180, current_speed_kt=0, current_set_true_deg=0,
        water_level_mllw_ft=0).model_copy(update=updates)


def metadata(model, **timing):
    extra = {'component': 'current'} if model is EnvironmentComponentProvenance else {}
    return model(source='fixture', basis='prediction', quality='good', **extra, **timing)


@pytest.mark.parametrize('model', [EnvironmentMetadata, EnvironmentComponentProvenance])
def test_forward_interval_across_repeated_hour_is_accepted(model):
    value = metadata(model, valid_from_utc=EARLIER, valid_to_utc=LATER)
    assert value.valid_from_utc == EARLIER and value.valid_to_utc == LATER


@pytest.mark.parametrize('model', [EnvironmentMetadata, EnvironmentComponentProvenance])
def test_reverse_interval_across_repeated_hour_is_rejected(model):
    with pytest.raises(ValidationError, match='before'):
        metadata(model, valid_from_utc=LATER, valid_to_utc=EARLIER)


def test_issuance_after_retrieval_is_rejected_in_repeated_hour():
    with pytest.raises(ValidationError, match='issuance is after'):
        metadata(EnvironmentComponentProvenance, issued_at_utc=LATER, retrieved_at_utc=EARLIER)


def test_later_observation_cannot_pass_as_available_during_repeated_hour():
    value = snapshot(source='live', metadata=EnvironmentMetadata(basis='observation', age_s=0))
    assert 'Future observations' in availability_problem(value, EARLIER)


def test_later_issuance_cannot_pass_as_available_during_repeated_hour():
    value = snapshot(source='forecast', metadata=EnvironmentMetadata(basis='prediction', issued_at_utc=LATER))
    assert 'issued after' in availability_problem(value, EARLIER)


@pytest.mark.parametrize('component', [False, True])
def test_loads_reject_snapshot_from_the_next_occurrence_of_the_hour(component):
    interval = {'valid_from_utc': EARLIER.replace(minute=0), 'valid_to_utc': EARLIER}
    meta = EnvironmentMetadata(basis='prediction', quality='good', **({} if component else interval))
    if component:
        meta.components = [metadata(EnvironmentComponentProvenance, **interval)]
    findings = environment_findings(snapshot(metadata=meta))
    code = 'ENVIRONMENT_COMPONENT_OUTSIDE_VALID_INTERVAL' if component else 'ENVIRONMENT_OUTSIDE_VALID_INTERVAL'
    assert any(state == 'invalid' and reason.code == code for state, reason in findings)
