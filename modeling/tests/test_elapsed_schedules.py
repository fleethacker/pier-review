"""Tide tending and risk horizons follow elapsed UTC, not repeated/skipped wall hours."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mooring import refdata
from mooring.core.schemas import EnvironmentMetadata, TideSweepRequest, TimelineRequest
from mooring.demo_cases import docking_cases
from mooring.moored import risk
from mooring.moored.tide_inputs import levels

NY = ZoneInfo('America/New_York')
STARTS = [datetime(2026, 3, 8, 1, 30, tzinfo=NY), datetime(2026, 11, 1, 0, 30, tzinfo=NY)]


def samples(start, *, poor=False):
    env = docking_cases()[0].analysis_request.environment
    return [env.model_copy(update={'valid_at_utc': (start.astimezone(UTC)+timedelta(minutes=m)).astimezone(start.tzinfo),
        'water_level_mllw_ft': m/60, 'metadata': EnvironmentMetadata(basis='scenario', quality='poor' if poor else 'good')})
        for m in range(0, 121, 30)]


@pytest.mark.parametrize('start', STARTS)
def test_training_tide_schedule_uses_two_elapsed_hours(start):
    baseline = docking_cases()[0].analysis_request
    end = (start.astimezone(UTC)+timedelta(hours=2)).astimezone(NY)
    req = TideSweepRequest(**baseline.model_dump(), from_utc=start, to_utc=end, step_min=30)
    actual = [at.astimezone(UTC) for at, _ in levels(req, refdata.berth(req.berth_id), 30)]
    assert actual == [start.astimezone(UTC)+timedelta(minutes=m) for m in range(0, 121, 30)]


def test_supplied_tide_and_tending_keep_both_occurrences_of_repeated_hour():
    baseline = docking_cases()[0].analysis_request
    series = samples(STARTS[1])
    action = {'at_utc': series[3].valid_at_utc, 'line_number': baseline.config.lines[0].line_number,
              'action': 'slack', 'amount_ft': 0.1}
    req = TideSweepRequest(**baseline.model_dump(), from_utc=series[0].valid_at_utc, to_utc=series[-1].valid_at_utc,
        step_min=30, water_level_forecast=series, tending=[action])
    actual = [(at.astimezone(UTC), water) for at, water in levels(req, refdata.berth(req.berth_id), 30)]
    assert actual == [(s.valid_at_utc.astimezone(UTC), s.water_level_mllw_ft) for s in series]
    assert req.tending[0].at_utc.tzinfo is UTC
    assert series[3].valid_at_utc.tzinfo is NY  # Validation does not mutate supplied objects.


@pytest.mark.parametrize('start', STARTS)
def test_training_risk_timeline_uses_elapsed_hours(start):
    baseline = docking_cases()[0].analysis_request
    req = TimelineRequest(**baseline.model_dump(), start_utc=start, forecast_hours=2, step_min=30)
    result = risk.timeline(req)
    assert [s.valid_at_utc.astimezone(UTC) for s in result.result.steps] == [
        start.astimezone(UTC)+timedelta(minutes=m) for m in range(0, 121, 30)]


def test_supplied_risk_timeline_retains_repeated_hour_peak():
    baseline = docking_cases()[0].analysis_request
    series = samples(STARTS[1])
    series[3].wind_gust_kt = 64
    req = TimelineRequest(**baseline.model_dump(), start_utc=series[0].valid_at_utc, forecast_hours=2,
        step_min=30, forecast=series)
    result = risk.timeline(req)
    assert [s.wind_gust_kt for s in result.result.steps] == [s.wind_gust_kt for s in series]
    assert result.result.steps[3].valid_at_utc == datetime(2026, 11, 1, 6, tzinfo=UTC)
    assert series[3].valid_at_utc.tzinfo is NY


def test_offset_timeline_action_text_uses_actual_utc():
    baseline = docking_cases()[0].analysis_request
    series = samples(datetime.fromisoformat('2026-11-04T07:30:00-05:00'), poor=True)
    req = TimelineRequest(**baseline.model_dump(), start_utc=series[0].valid_at_utc, forecast_hours=2,
        step_min=30, forecast=series)
    result = risk.timeline(req)
    assert '12:30Z' in result.result.recommended_actions[0]
    assert '07:30Z' not in result.result.recommended_actions[0]
