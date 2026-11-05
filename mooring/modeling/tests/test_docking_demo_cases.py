"""Named examples exercise actual computations, not status fixtures."""
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.demo_cases import docking_cases
from mooring.core.schemas.demo import DockingDemoCase


def test_demo_cases_are_fetchable_and_create_isolated_saved_scenarios():
    with TestClient(app) as client:
        response = client.get('/api/v1/demo/docking-cases')
        assert response.status_code == 200
        cases = [DockingDemoCase.model_validate(c) for c in response.json()]
        assert len(cases) == 4
        for case in cases:
            env = client.post('/api/v1/env/scenarios', json=case.environment_request.model_dump(mode='json'))
            assert env.status_code == 201
            scenario = case.scenario_request.model_dump(mode='json')
            scenario['env_source']['env_scenario_id'] = env.json()['env_scenario_id']
            saved = client.post('/api/v1/scenarios', json=scenario)
            assert saved.status_code == 201
            assert saved.json()['config'] == scenario['config']


def test_named_outcomes_are_real_and_honestly_labeled():
    with TestClient(app) as client:
        for case in docking_cases():
            response = client.post('/api/v1/mooring/analyze', json=case.analysis_request.model_dump(mode='json'))
            assert response.status_code == 200
            result = response.json()
            if case.expected_outcome == 'supported_limited':
                assert result['status'] == 'AMBER'
                assert result['validity']['state'] == 'limited'
                assert result['validity']['diagnostics']['converged']
                assert result['result']['min_margin']['pct_wll'] < 20
            elif case.expected_outcome == 'overloaded':
                assert result['status'] == 'RED'
                assert result['validity']['diagnostics']['converged']
                assert result['result']['min_margin']['pct_wll'] > 100
            elif case.expected_outcome == 'invalid_data':
                assert result['status'] == 'RED' and result['validity']['state'] == 'invalid'
                assert 'DEPTH_NOT_ABOVE_DRAFT' in {r['code'] for r in result['validity']['reasons']}
            else:
                envelope = client.post('/api/v1/mooring/envelope', json=case.envelope_request.model_dump(mode='json')).json()
                assert envelope['status'] == 'RED'
                assert all(p['outcome'] == 'undetermined' and p['limit_wind_kt'] is None for p in envelope['result']['points'])
