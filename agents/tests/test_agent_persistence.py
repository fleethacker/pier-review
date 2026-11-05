"""Optional durable agents: completed chain, ownership, audit and approvals survive reopening."""
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app as modeling_app
from mooring.core import access, store
from mooring.core.jobs import JobStore
from mooring.demo_cases import docking_cases
from mooring_agents.api import security, state
from mooring_agents.api.main import app, get_client
from mooring_agents.api.routers import intake, planner, safety, system, vision
from mooring_agents.planner.agent import PLANS
from mooring_agents.safety.sheet import SHEETS, approve
from mooring_agents.safety.schemas import ApprovalCreate
from mooring_agents.shared.storage import AgentStore, persistence_enabled

P = '/api/v1'
ALICE = {'Authorization': 'Bearer ' + 'a' * 32}
BOB = {'Authorization': 'Bearer ' + 'b' * 32}


def test_persistence_requires_explicit_file_configuration(monkeypatch):
    monkeypatch.setenv('AGENTS_PERSIST', '1')
    monkeypatch.delenv('MOORING_DB', raising=False)
    with pytest.raises(ValueError, match='file-backed'): persistence_enabled()
    monkeypatch.setenv('AGENTS_PERSIST', 'perhaps')
    with pytest.raises(ValueError, match='0 or 1'): persistence_enabled()


def test_durable_full_chain_and_owner_survive_restart(monkeypatch, tmp_path):
    path = str(tmp_path / 'agents.sqlite')
    monkeypatch.setenv('MOORING_DB', path)
    monkeypatch.setenv('AGENTS_PERSIST', '1')
    monkeypatch.delenv('AGENTS_LEDGER_DB', raising=False)
    monkeypatch.setenv('MOORING_API_KEYS', json.dumps({'alice': 'a' * 32, 'bob': 'b' * 32}))
    monkeypatch.delenv('AGENTS_API_KEYS', raising=False)
    monkeypatch.setenv('AGENTS_RATE_PER_MINUTE', '0')
    monkeypatch.setenv('MOORING_RATE_PER_MINUTE', '0')
    monkeypatch.setenv('AGENTS_LLM_PROVIDER', 'none')
    store.reset_db(path)
    jobs = JobStore(P, persist=True, namespace='agents')
    modules = (state, intake, planner, safety, system, vision)
    for module in modules: monkeypatch.setattr(module, 'JOBS', jobs)
    monkeypatch.setitem(app.dependency_overrides, get_client, lambda: __import__(
        'mooring_agents.physics.client', fromlist=['ModelingClient']).ModelingClient(
        base_url='http://modeling/api/v1', transport=httpx.ASGITransport(app=modeling_app),
        authorization=security.credential.get()))
    client, modeling = TestClient(app), TestClient(modeling_app)

    def complete(response):
        assert response.status_code == 202, response.text
        accepted = response.json()
        jobs.jobs[accepted['job_id']].future.result(timeout=30)
        result = client.get(f"{P}/jobs/{accepted['job_id']}", headers=ALICE)
        assert result.json()['state'] == 'succeeded', result.text
        return result.json()['result']

    try:
        case = docking_cases()[0]
        eid = modeling.post(f'{P}/env/scenarios', json=case.environment_request.model_dump(mode='json'), headers=ALICE).json()['env_scenario_id']
        body = case.scenario_request.model_dump(mode='json')
        body['env_source']['env_scenario_id'] = eid
        sid = modeling.post(f'{P}/scenarios', json=body, headers=ALICE).json()['scenario_id']
        report = complete(client.post(f'{P}/intake/reports', json={'scenario_id': sid}, headers=ALICE))
        plan = complete(client.post(f'{P}/agent/plans', json={'scenario_id': sid, 'intake_report_id': report['report_id']}, headers=ALICE))
        review = complete(client.post(f'{P}/safety/reviews', json={'plan_id': plan['plan_id']}, headers=ALICE))
        created = client.post(f'{P}/safety-sheets', json={'plan_id': plan['plan_id'], 'review_id': review['review_id']}, headers=ALICE)
        assert created.status_code == 201, created.text
        sheet_id = created.json()['sheet_id']
        plan_path = f"{P}/agent/plans/{plan['plan_id']}"
        sheet_path = f'{P}/safety-sheets/{sheet_id}'
        assert client.post(plan_path + '/messages', json={'text': 'Explain'}, headers=ALICE).status_code == 202
        approved = client.post(sheet_path + '/approvals', json={'role': 'co', 'name': 'Original', 'decision': 'approve'}, headers=ALICE).json()
        events = client.get(plan_path + '/events?follow=false', headers=ALICE).text
        calls = client.get(f'{P}/physics/calls', params={'plan_id': plan['plan_id']}, headers=ALICE).json()
        assert calls and approved['locked']
        # No credential-bearing toolkit/transport is serialized into the plan document.
        raw = store.db().execute('SELECT body FROM docs WHERE namespace=? AND key=?', ('agent_plan', plan['plan_id']))[0][0]
        assert 'toolkit' not in raw and 'authorization' not in raw and 'a' * 32 not in raw
        jobs.shutdown()
        store.reset_db(path)
        jobs = JobStore(P, persist=True, namespace='agents')
        for module in modules: monkeypatch.setattr(module, 'JOBS', jobs)
        assert PLANS[plan['plan_id']].toolkit is None
        assert PLANS[plan['plan_id']].messages
        for route in (plan_path, sheet_path, f"{P}/intake/reports/{report['report_id']}", f"{P}/safety/reviews/{review['review_id']}"):
            assert client.get(route, headers=ALICE).status_code == 200
            assert client.get(route, headers=BOB).status_code == 404
        assert client.get(sheet_path, headers=ALICE).json() == approved
        assert client.get(plan_path, headers=ALICE).json()['safety_sheet_id'] == sheet_id
        assert client.get(plan_path + '/events?follow=false', headers=ALICE).text == events
        assert client.get(f'{P}/physics/calls', params={'plan_id': plan['plan_id']}, headers=ALICE).json() == calls
        assert client.get(sheet_path + '/render', headers=ALICE).status_code == 200
        # A stale caller's sheet cannot overwrite another approval. Reread under the store lock.
        stale = SHEETS[sheet_id]
        def add(index):
            token = access.principal.set('alice')
            try: return approve(stale, ApprovalCreate(role='pilot', name=f'Concurrent {index}', decision='approve'))
            finally: access.principal.reset(token)
        with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(add, range(4)))
        assert len(SHEETS[sheet_id].approvals) == 5
        assert SHEETS[sheet_id].line_plan == stale.line_plan
        assert client.post(plan_path + '/messages', json={'text': 'NW 4 kt'}, headers=ALICE).status_code == 202
        assert len(PLANS[plan['plan_id']].messages) == 2
    finally:
        jobs.shutdown()
        store.reset_db(':memory:')


def test_documents_do_not_grant_access_to_another_owner(monkeypatch, tmp_path):
    path = str(tmp_path / 'owners.sqlite')
    monkeypatch.setenv('MOORING_DB', path)
    monkeypatch.setenv('AGENTS_PERSIST', '1')
    store.reset_db(path)
    enabled = access.enforced.set(True)
    token = access.principal.set('alice')
    try:
        docs = AgentStore('test_agents', dict)
        docs['one'] = {'value': 1}
        access.principal.set('bob')
        assert list(docs) == [] and 'one' not in docs
        with pytest.raises(PermissionError): docs['one'] = {'value': 2}
        with pytest.raises(KeyError): del docs['one']
        access.principal.set('alice')
        assert docs['one'] == {'value': 1}
    finally:
        access.principal.reset(token)
        access.enforced.reset(enabled)
        store.reset_db(':memory:')


def test_interrupted_plan_stays_failed_and_cannot_be_reviewed(monkeypatch, tmp_path):
    from mooring.core.jobs import Job
    from mooring.core.envelopes import utcnow
    from mooring_agents.planner.schemas import AgentPlanRequest
    path = str(tmp_path / 'interrupted.sqlite')
    monkeypatch.setenv('MOORING_DB', path)
    monkeypatch.setenv('AGENTS_PERSIST', '1')
    monkeypatch.setenv('AGENTS_API_KEYS', '')
    monkeypatch.setenv('AGENTS_AUTH_REQUIRED', '0')
    store.reset_db(path)
    try:
        original = JobStore(P, persist=True, namespace='agents')
        original._persist(Job('job_interrupted', 'agent.plan', utcnow(), task=True, task_state='running'))
        planner.PLAN_JOBS['plan_interrupted'] = 'job_interrupted'
        planner.PLAN_REQUESTS['plan_interrupted'] = AgentPlanRequest(scenario_id='saved_scenario')
        store.reset_db(path)
        recovered = JobStore(P, persist=True, namespace='agents')
        monkeypatch.setattr(planner, 'JOBS', recovered)
        client = TestClient(app)
        response = client.get(f'{P}/agent/plans/plan_interrupted')
        assert response.status_code == 200 and response.json()['state'] == 'failed'
        assert response.json()['status'] == 'RED'
        assert 'interrupted by restart' in response.json()['open_questions'][0]
        assert client.post(f'{P}/safety/reviews', json={'plan_id': 'plan_interrupted'}).status_code == 409
    finally:
        store.reset_db(':memory:')
