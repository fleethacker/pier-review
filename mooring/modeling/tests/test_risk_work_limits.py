"""Multiplicative Monte Carlo work must be rejected before entering the job queue."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from modeling_api.main import app
from modeling_api.routers import moored
from mooring.core.schemas import ExceedanceRequest, TimelineRequest
from mooring.demo_cases import docking_cases


def base():
    return docking_cases()[0].analysis_request.model_dump(mode='json')


@pytest.mark.parametrize('kind', ['horizon', 'training_timeline', 'supplied_timeline'])
def test_oversized_risk_work_is_rejected_before_queueing(monkeypatch, kind):
    monkeypatch.setattr(moored, 'JOBS', SimpleNamespace(submit_task=lambda *args, **kwargs:
        pytest.fail('Oversized risk request reached the worker queue')))
    body = base()
    endpoint = '/risk/timeline'
    if kind == 'horizon':
        endpoint = '/risk/exceedance'
        body.update(include_horizon=True, horizon_hours=72, horizon_step_min=6, n_trajectories=2000)
    else:
        body.update(forecast_hours=120, step_min=6, n_samples_per_step=2000)
        if kind == 'supplied_timeline':
            start = datetime(2026, 11, 5, tzinfo=UTC)
            # Every supplied knot is solved even though the reporting interval is large.
            body.update(start_utc=start.isoformat(), forecast_hours=2, step_min=180,
                forecast=[body['environment'] | {'valid_at_utc': (start+timedelta(seconds=10*i)).isoformat()}
                          for i in range(721)])
    response = TestClient(app).post('/api/v1'+endpoint, json=body)
    assert response.status_code == 422, response.text
    assert 'solve budget' in response.text


def test_instantaneous_maximum_and_default_horizon_remain_supported():
    assert ExceedanceRequest(**base(), n_samples=20000).n_samples == 20000
    assert ExceedanceRequest(**base(), include_horizon=True).n_trajectories == 200
    assert TimelineRequest(**base(), forecast_hours=24, step_min=60, n_samples_per_step=50).forecast_hours == 24


def test_horizon_budget_counts_base_solve_and_all_trajectory_endpoints():
    # 1 baseline + 10,999 instantaneous + 2,000 * 7 trajectory samples = 25,000.
    values = base() | dict(n_samples=10999, include_horizon=True, horizon_hours=3,
                          horizon_step_min=30, n_trajectories=2000)
    assert ExceedanceRequest(**values).n_samples == 10999
    with pytest.raises(ValidationError, match='solve budget'):
        ExceedanceRequest(**(values | {'n_samples':11000}))
