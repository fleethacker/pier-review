"""Provider quality cannot disappear when a caller bypasses intake/forecast planning."""
from datetime import timedelta

import pytest

from mooring import refdata
from mooring.core.schemas import EnvironmentMetadata, StationQuality, LoadsRequest, LimitEnvelopeRequest, RecommendRequest
from mooring.demo_cases import docking_cases
from mooring.examples import EXAMPLES
from mooring.loads import service
from mooring.loads.validity import environment_findings
from mooring.moored import solver, search


def metadata(**updates):
    return EnvironmentMetadata(basis='scenario', quality='good', wind_averaging_s=60,
                               gust_duration_s=30, wind_reference_height_m=10, **updates)


def modified_env(kind):
    env = docking_cases()[0].analysis_request.environment
    if kind in ('poor', 'suspect'):
        return env.model_copy(update={'metadata': metadata().model_copy(update={'quality': kind})})
    if kind == 'outside_interval':
        return env.model_copy(update={'metadata': metadata(valid_to_utc=env.valid_at_utc-timedelta(seconds=1))})
    if kind == 'naive':
        return env.model_copy(update={'valid_at_utc': env.valid_at_utc.replace(tzinfo=None)})
    return env.model_copy(update={'quality': [StationQuality(station_id='current', age_s=0, flags=[kind])]})


@pytest.mark.parametrize('kind,state', [('poor','invalid'), ('current_missing','invalid'),
    ('outside_interval','invalid'), ('naive','invalid'), ('stale','limited'), ('suspect','limited')])
def test_loads_honor_quality_even_with_published_geometry(monkeypatch, kind, state):
    ship = refdata.ship('DDG-51-FIIA').model_copy(deep=True)
    ship.provenance.confidence = 'published'
    monkeypatch.setattr(service.refdata, 'ship', lambda _: ship)
    req = LoadsRequest(**EXAMPLES['loads_environmental']).model_copy(update={'environment': modified_env(kind)})
    result = service.environmental(req)
    assert result.validity.state == state
    assert result.status == ('RED' if state == 'invalid' else 'AMBER')
    assert any(reason.code.startswith('ENVIRONMENT_') for reason in result.validity.reasons)


@pytest.mark.parametrize('kind', ['poor', 'current_unavailable', 'outside_interval'])
def test_mooring_and_limits_cannot_use_bad_environment(kind):
    req = docking_cases()[0].analysis_request.model_copy(update={'environment': modified_env(kind)})
    result = solver.analyze(req)
    assert result.status == 'RED' and result.validity.state == 'invalid'
    assert solver.analyze_full(req, run_rules=False)[2].state == 'invalid'
    limits = solver.limit_envelope(LimitEnvelopeRequest(**req.model_dump(), step_deg=90))
    assert limits.status == 'RED' and limits.validity.state == 'invalid'
    assert all(p.outcome == 'invalid_inputs' and p.limit_wind_kt is None and p.limit_gust_kt is None
               for p in limits.result.points)


def test_search_never_calls_missing_environment_feasible():
    req = docking_cases()[0].analysis_request
    result = search.recommend(RecommendRequest(ship_class_id=req.ship_class_id, berth_id=req.berth_id,
        side_to=req.config.side_to, ship_x_ft=req.config.ship_x_ft, design_basis='forecast_only',
        forecast_env=[modified_env('current_missing')], max_evaluations=2))
    assert result.status == 'RED'
    assert not any(candidate.feasible for candidate in result.result.candidates)


def test_explicit_asof_is_not_replaced_by_wall_clock_expiry():
    env = docking_cases()[0].analysis_request.environment
    # Archived what-if inputs remain assessable; provider flags, not today's wall clock, govern this layer.
    old = env.valid_at_utc - timedelta(days=365)
    env = env.model_copy(update={'valid_at_utc': old, 'metadata': metadata(valid_from_utc=old, valid_to_utc=old)})
    assert not environment_findings(env)


def test_undocumented_public_quality_is_limited_and_low_gust_is_disclosed():
    env = docking_cases()[0].analysis_request.environment.model_copy(update={'source':'forecast', 'metadata':None,
        'wind_speed_kt':10, 'wind_gust_kt':5})
    reasons = environment_findings(env)
    assert all(state == 'limited' for state, _ in reasons)
    assert {r.code for _,r in reasons} == {'ENVIRONMENT_QUALITY_UNVERIFIED','WIND_GUST_BELOW_SUSTAINED','WIND_BASIS_UNVERIFIED'}
