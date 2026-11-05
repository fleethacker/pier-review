"""The offline training forecast covers the full requested horizon at any clock phase."""
from datetime import UTC, datetime, timedelta

import pytest

from mooring.environment import mock
from mooring.moored.forecast_planning import _input_problem


@pytest.mark.parametrize('hour', [0, 6, 12, 23])
@pytest.mark.parametrize('minute,second', [(0,0), (1,1), (29,59), (59,59)])
@pytest.mark.parametrize('step', [6, 30, 180])
def test_training_series_covers_current_time_plus_requested_duration(monkeypatch, hour, minute, second, step):
    now = datetime(2026, 11, 5, hour, minute, second, tzinfo=UTC)
    monkeypatch.setattr(mock, 'utcnow', lambda: now)
    result = mock.forecast('NAVSTA-NORFOLK-P12-N', 24, step)
    times = [sample.valid_at_utc for sample in result.series]
    assert times[0] <= now and times[-1] >= now+timedelta(hours=24)
    assert times[-1] < now+timedelta(hours=24, minutes=step)
    assert all(b-a == timedelta(minutes=step) for a,b in zip(times,times[1:]))
    assert len(result.series) <= 252  # One hour of lead-in plus the 24-hour horizon at the smallest step.
    assert all(sample.source == 'mock' and sample.metadata.basis == 'scenario' for sample in result.series)
    assert all(sample.metadata.issued_at_utc is None for sample in result.series)
    assert all(_input_problem(sample, now) is None for sample in result.series)
    assert result.model_dump() == mock.forecast('NAVSTA-NORFOLK-P12-N',24,step).model_dump()


def test_maximum_horizon_remains_bounded_and_does_not_truncate_partial_step(monkeypatch):
    now = datetime(2026,11,5,23,59,59,tzinfo=UTC)
    monkeypatch.setattr(mock, 'utcnow', lambda: now)
    result = mock.forecast('NAVSTA-NORFOLK-P12-N',120,6)
    assert result.series[-1].valid_at_utc >= now+timedelta(hours=120)
    assert len(result.series) == 1211
