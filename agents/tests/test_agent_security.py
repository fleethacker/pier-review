"""Opt-in identities propagate through HTTP and background jobs; no network is used."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app as modeling_app
from mooring.demo_cases import docking_cases
from mooring_agents.api import security
from mooring_agents.api.main import app, get_client
from mooring_agents.api.state import JOBS
from mooring_agents.physics.client import ModelingClient

P = '/api/v1'
ALICE = {'Authorization': 'Bearer ' + 'a' * 32}
BOB = {'Authorization': 'Bearer ' + 'b' * 32}


@pytest.fixture
def secured(monkeypatch):
    keys = json.dumps({'alice': 'a' * 32, 'bob': 'b' * 32})
    monkeypatch.setenv('MOORING_API_KEYS', keys)
    monkeypatch.delenv('AGENTS_API_KEYS', raising=False)
    monkeypatch.setenv('AGENTS_RATE_PER_MINUTE', '0')
    monkeypatch.setenv('MOORING_RATE_PER_MINUTE', '0')
    monkeypatch.setenv('AGENTS_LLM_PROVIDER', 'none')
    monkeypatch.setitem(app.dependency_overrides, get_client, lambda: ModelingClient(
        base_url='http://modeling/api/v1', transport=httpx.ASGITransport(app=modeling_app),
        authorization=security.credential.get()))
    return TestClient(app), TestClient(modeling_app)


def complete(client, accepted, headers=ALICE):
    # Test synchronization only. The API caller remains scoped by its HTTP credential.
    job = JOBS.jobs[accepted['job_id']]
    job.future.result(timeout=30)
    status = client.get(f"{P}/jobs/{accepted['job_id']}", headers=headers)
    assert status.status_code == 200, status.text
    assert status.json()['state'] == 'succeeded', status.text
    return status.json()['result']


def test_auth_defaults_required_configuration_and_body_limit(monkeypatch):
    client = TestClient(app)
    monkeypatch.delenv('MOORING_API_KEYS', raising=False)
    monkeypatch.delenv('AGENTS_API_KEYS', raising=False)
    monkeypatch.setenv('AGENTS_AUTH_REQUIRED', '0')
    assert client.get(f'{P}/tools').status_code == 200
    monkeypatch.setenv('AGENTS_AUTH_REQUIRED', '1')
    assert client.get(f'{P}/tools').status_code == 503
    assert client.get(f'{P}/health').status_code == 200
    monkeypatch.setenv('AGENTS_API_KEYS', json.dumps({'alice': 'a' * 32}))
    assert client.get(f'{P}/tools').status_code == 401
    assert client.get(f'{P}/tools', headers=BOB).status_code == 401
    assert client.get(f'{P}/tools', headers=ALICE).status_code == 200
    monkeypatch.setenv('AGENTS_MAX_BODY_BYTES', '32')
    oversized = client.post(f'{P}/intake/reports', headers=ALICE, content=b'x' * 33)
    assert oversized.status_code == 413
    monkeypatch.setenv('AGENTS_MAX_BODY_BYTES', 'invalid')
    assert client.get(f'{P}/tools', headers=ALICE).status_code == 503


def test_rate_limit_is_per_principal_with_retry_header(secured, monkeypatch):
    client, _ = secured
    now = [0.0]
    monkeypatch.setattr(security, 'RATE', security.RateLimit(lambda: now[0]))
    monkeypatch.setenv('AGENTS_RATE_PER_MINUTE', '1')
    assert client.get(f'{P}/tools', headers=ALICE).status_code == 200
    rejected = client.get(f'{P}/tools', headers=ALICE)
    assert rejected.status_code == 429 and int(rejected.headers['Retry-After']) > 0
    assert client.get(f'{P}/tools', headers=BOB).status_code == 200
    now[0] = 60.0
    assert client.get(f'{P}/tools', headers=ALICE).status_code == 200


def test_authenticated_chain_preserves_identity_and_isolates_every_agent_resource(secured):
    client, modeling = secured
    case = docking_cases()[0]
    env = modeling.post(f'{P}/env/scenarios', json=case.environment_request.model_dump(mode='json'), headers=ALICE).json()
    body = case.scenario_request.model_dump(mode='json')
    body['env_source']['env_scenario_id'] = env['env_scenario_id']
    scenario = modeling.post(f'{P}/scenarios', json=body, headers=ALICE).json()['scenario_id']
    accepted = client.post(f'{P}/intake/reports', json={'scenario_id': scenario, 'horizon_hours': 24}, headers=ALICE)
    assert accepted.status_code == 202, accepted.text
    report = complete(client, accepted.json())
    assert report['planning_conditions']
    report_path = f"{P}/intake/reports/{report['report_id']}"
    assert client.get(report_path, headers=BOB).status_code == 404
    assert client.get(report_path, headers=ALICE).status_code == 200
    job_path = f"{P}/jobs/{accepted.json()['job_id']}"
    assert client.get(job_path, headers=BOB).status_code == 404
    assert client.get(job_path + '/events', headers=BOB).status_code == 404
    assert client.delete(job_path, headers=BOB).status_code == 404
    assert client.post(f'{P}/agent/plans', json={'scenario_id': scenario}, headers=BOB).status_code == 404

    accepted = client.post(f'{P}/agent/plans', json={'scenario_id': scenario, 'intake_report_id': report['report_id']}, headers=ALICE)
    assert accepted.status_code == 202, accepted.text
    plan = complete(client, accepted.json())
    plan_path = f"{P}/agent/plans/{plan['plan_id']}"
    assert client.get(plan_path, headers=BOB).status_code == 404
    assert client.get(plan_path + '/events', headers=BOB).status_code == 404
    assert client.post(plan_path + '/messages', json={'text': 'Explain'}, headers=BOB).status_code == 404
    assert client.get(f"{P}/safety/watch/{plan['plan_id']}", headers=BOB).status_code == 404
    assert client.get(f'{P}/physics/calls', params={'plan_id': plan['plan_id']}, headers=BOB).status_code == 404
    alice_calls = {c['call_id'] for c in client.get(f'{P}/physics/calls', headers=ALICE).json()}
    bob_calls = {c['call_id'] for c in client.get(f'{P}/physics/calls', headers=BOB).json()}
    assert alice_calls and alice_calls.isdisjoint(bob_calls)
    assert client.get(f'{P}/physics/calls', params={'plan_id': plan['plan_id']}, headers=ALICE).json()
    assert client.get(f'{P}/physics/calls', params={'plan_id': report['report_id']}, headers=ALICE).json()
    spoof = client.post(f'{P}/physics/tools/get_ship', headers=BOB,
                        json={'plan_id': plan['plan_id'], 'input': {'class_id': 'DDG-51-FIIA'}})
    assert spoof.status_code == 404

    bob_env = modeling.post(f'{P}/env/scenarios', json=case.environment_request.model_dump(mode='json'), headers=BOB).json()
    bob_body = case.scenario_request.model_dump(mode='json')
    bob_body['env_source']['env_scenario_id'] = bob_env['env_scenario_id']
    bob_scenario = modeling.post(f'{P}/scenarios', json=bob_body, headers=BOB).json()['scenario_id']
    mixed = client.post(f'{P}/agent/plans', json={'scenario_id': bob_scenario,
                       'intake_report_id': report['report_id']}, headers=BOB)
    assert mixed.status_code == 202
    mixed_job = JOBS.jobs[mixed.json()['job_id']]
    mixed_job.future.result(timeout=30)
    assert mixed_job.state == 'failed' and mixed_job.result is None
    assert 'not found' in mixed_job.error

    accepted = client.post(f'{P}/safety/reviews', json={'plan_id': plan['plan_id']}, headers=ALICE)
    review = complete(client, accepted.json())
    assert review['validity']['state'] == 'limited'
    assert client.get(f"{P}/safety/reviews/{review['review_id']}", headers=BOB).status_code == 404
    sheet = client.post(f'{P}/safety-sheets', json={'plan_id': plan['plan_id'], 'review_id': review['review_id']}, headers=ALICE)
    assert sheet.status_code == 201, sheet.text
    sheet_path = f"{P}/safety-sheets/{sheet.json()['sheet_id']}"
    assert client.get(sheet_path, headers=BOB).status_code == 404
    assert client.get(sheet_path + '/render', headers=BOB).status_code == 404
    assert client.post(sheet_path + '/approvals', json={'role': 'co', 'name': 'Other', 'decision': 'approve'}, headers=BOB).status_code == 404
    approved = client.post(sheet_path + '/approvals', json={'role': 'co', 'name': 'Owner', 'decision': 'approve'}, headers=ALICE)
    assert approved.status_code == 200 and approved.json()['locked']


def test_vision_confirm_is_bound_to_own_job(secured):
    client, _ = secured
    accepted = client.post(f'{P}/berth-vision/analyze', headers=ALICE,
        files={'image': ('draft.png', b'catalog draft', 'image/png')},
        data={'metadata': json.dumps({'image_kind': 'satellite', 'berth_id': 'NAVSTA-NORFOLK-P12-N'})})
    assert accepted.status_code == 202, accepted.text
    result = complete(client, accepted.json())
    body = {'berth': result['result']['draft_berth']}
    path = f"{P}/berth-vision/{accepted.json()['job_id']}/confirm"
    assert client.post(path, headers=BOB, json=body).status_code == 404
    assert client.post(path, headers=ALICE, json=body).status_code == 201


@pytest.mark.parametrize('configuration', ['not-json', '[]', '{}', '{"alice":"short"}',
    json.dumps({'alice': 'x' * 32, 'bob': 'x' * 32})])
def test_bad_or_ambiguous_key_configuration_fails_closed(monkeypatch, configuration):
    monkeypatch.setenv('AGENTS_API_KEYS', configuration)
    response = TestClient(app).get(f'{P}/tools', headers=ALICE)
    assert response.status_code == 503
    assert 'configuration' in response.json()['detail']


def test_body_limit_counts_received_bytes_not_content_length(monkeypatch):
    monkeypatch.setenv('AGENTS_API_KEYS', '')
    monkeypatch.setenv('AGENTS_AUTH_REQUIRED', '0')
    monkeypatch.setenv('AGENTS_MAX_BODY_BYTES', '16')
    response = TestClient(app).post(f'{P}/intake/reports', headers={'Content-Length': '0'}, content=b'x' * 17)
    assert response.status_code == 413


def test_repeated_authenticated_reviews_have_separate_bounded_operations(secured, monkeypatch):
    client, modeling = secured
    case = docking_cases()[0]
    eid = modeling.post(f'{P}/env/scenarios', json=case.environment_request.model_dump(mode='json'), headers=ALICE).json()['env_scenario_id']
    body = case.scenario_request.model_dump(mode='json')
    body['env_source']['env_scenario_id'] = eid
    sid = modeling.post(f'{P}/scenarios', json=body, headers=ALICE).json()['scenario_id']
    plan = complete(client, client.post(f'{P}/agent/plans', json={'scenario_id':sid}, headers=ALICE).json())
    monkeypatch.setenv('AGENTS_MAX_TOOL_CALLS', '2')  # one analysis + one envelope per one-condition review
    reviews = [complete(client, client.post(f'{P}/safety/reviews', json={'plan_id':plan['plan_id']}, headers=ALICE).json()) for _ in range(2)]
    assert reviews[0]['review_id'] != reviews[1]['review_id']
    calls = client.get(f'{P}/physics/calls', params={'plan_id':plan['plan_id']}, headers=ALICE).json()
    safety_calls = [call for call in calls if call['caller']=='safety']
    assert len(safety_calls) == 4
    assert len({call['operation_id'] for call in safety_calls}) == 2
    assert not any(call.get('error') for call in safety_calls)
