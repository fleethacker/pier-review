"""Actual background execution, deterministic gates and bounded worker capacity."""
import threading

import pytest

from mooring.core.jobs import JobQueueFull, JobStore
from mooring_agents.api.execution import submit_async
from mooring_agents.physics.client import ModelingClient
from mooring_agents.physics.toolkit import PhysicsToolkit


def toolkit():
    return PhysicsToolkit(ModelingClient(), 'test-background')


def test_acknowledgement_precedes_work_completion_and_queue_is_bounded():
    store = JobStore('/api/v1', workers=1, queue_size=0)
    entered, release = threading.Event(), threading.Event()

    async def operation(ctx):
        ctx.emit('step', {'message': 'started'})
        entered.set()
        assert release.wait(3)
        return {'complete': True}

    try:
        accepted = submit_async(store, 'test', toolkit(), operation)
        assert entered.wait(3)
        job = store.get(accepted.job_id)
        assert job.state == 'running' and job.result is None
        assert any(name == 'step' for name, _ in job.log)
        with pytest.raises(JobQueueFull): submit_async(store, 'full', toolkit(), operation)
        release.set()
        job.future.result(timeout=3)
        assert store.status(accepted.job_id).result == {'complete': True}
    finally:
        release.set()
        store.shutdown()


def test_cancelled_work_cannot_publish_a_late_success():
    store = JobStore('/api/v1', workers=1, queue_size=0)
    entered, release = threading.Event(), threading.Event()

    async def operation(ctx):
        entered.set()
        assert release.wait(3)
        return {'late': True}

    try:
        accepted = submit_async(store, 'test', toolkit(), operation)
        assert entered.wait(3)
        job = store.cancel(accepted.job_id)
        assert job.state == 'cancelled'
        release.set()
        job.future.result(timeout=3)
        assert job.state == 'cancelled' and job.result is None
    finally:
        release.set()
        store.shutdown()


def test_planner_http_ack_steps_cancel_and_saturation(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from modeling_api.main import app as modeling_app
    from mooring.examples import EXAMPLES
    from mooring_agents.api.main import app, get_client
    from mooring_agents.api.routers import planner, system

    store = JobStore('/api/v1', workers=1, queue_size=0)
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(planner, 'JOBS', store)
    monkeypatch.setattr(system, 'JOBS', store)
    monkeypatch.setitem(app.dependency_overrides, get_client, lambda: ModelingClient(
        base_url='http://modeling/api/v1', transport=httpx.ASGITransport(app=modeling_app)))

    async def blocked(req, tk, *, plan_id, scenario, on_event):
        on_event('step', {'iteration': 1, 'thought_summary': 'A real step is available before completion.',
                          'tool': 'get_scenario', 'result_id': None})
        entered.set()
        assert release.wait(5)
        tk.checkpoint()
        raise AssertionError('Cancelled operation must never reach this point')

    monkeypatch.setattr(planner.planner, 'run', blocked)
    client = TestClient(app)
    sid = TestClient(modeling_app).post('/api/v1/scenarios', json=EXAMPLES['scenario']).json()['scenario_id']
    try:
        accepted = client.post('/api/v1/agent/plans', json={'scenario_id': sid})
        assert accepted.status_code == 202, accepted.text
        body = accepted.json()
        assert entered.wait(5)
        job = store.get(body['job_id'])
        assert any(event == 'step' for event, _ in job.log)
        assert client.get(f"/api/v1/agent/plans/{body['plan_id']}").json()['state'] == 'running'
        overflow = client.post('/api/v1/agent/plans', json={'scenario_id': sid})
        assert overflow.status_code == 429 and int(overflow.headers['Retry-After']) > 0
        cancelled = client.delete(f"/api/v1/jobs/{body['job_id']}")
        assert cancelled.json()['state'] == 'cancelled'
        text = client.get(body['events_url'], params={'follow': False}).text
        assert 'event: step' in text and 'event: done' in text and '"state": "cancelled"' in text
        last_id = len(job.log) - 1
        resumed = client.get(body['events_url'], params={'follow': False}, headers={'Last-Event-ID': str(last_id)})
        assert resumed.status_code == 200 and resumed.text == ''
        release.set()
        job.future.result(timeout=5)
        assert job.result is None and job.state == 'cancelled'
        assert client.get(f"/api/v1/agent/plans/{body['plan_id']}").json()['state'] == 'cancelled'
    finally:
        release.set()
        store.shutdown()


def test_failed_planner_has_terminal_state_and_done_event(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from modeling_api.main import app as modeling_app
    from mooring.examples import EXAMPLES
    from mooring_agents.api.main import app, get_client
    from mooring_agents.api.routers import planner, system

    store = JobStore('/api/v1', workers=1, queue_size=0)
    monkeypatch.setattr(planner, 'JOBS', store)
    monkeypatch.setattr(system, 'JOBS', store)
    monkeypatch.setitem(app.dependency_overrides, get_client, lambda: ModelingClient(
        base_url='http://modeling/api/v1', transport=httpx.ASGITransport(app=modeling_app)))

    async def failed(*args, **kwargs):
        raise RuntimeError('Modeling service unavailable')

    monkeypatch.setattr(planner.planner, 'run', failed)
    client = TestClient(app)
    sid = TestClient(modeling_app).post('/api/v1/scenarios', json=EXAMPLES['scenario']).json()['scenario_id']
    try:
        response = client.post('/api/v1/agent/plans', json={'scenario_id': sid})
        assert response.status_code == 202
        body = response.json()
        store.get(body['job_id']).future.result(timeout=5)
        plan = client.get(f"/api/v1/agent/plans/{body['plan_id']}").json()
        assert plan['state'] == 'failed' and plan['status'] == 'RED'
        assert plan['config'] is None and plan['open_questions']
        events = client.get(body['events_url'], params={'follow': False}).text
        assert events.count('event: done') == 1 and '"state": "failed"' in events
        assert client.post('/api/v1/safety/reviews', json={'plan_id': body['plan_id']}).status_code == 409
    finally:
        store.shutdown()
