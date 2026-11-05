"""Stable line identifiers must not alias analysis rows or handling commands."""
import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import MooringConfig
from mooring.demo_cases import docking_cases


@pytest.mark.parametrize('same_geometry', [False, True])
def test_duplicate_line_numbers_are_rejected_without_silent_renumbering(same_geometry):
    original = docking_cases()[0].analysis_request.config.model_dump()
    original['lines'][1] = dict(original['lines'][0]) if same_geometry else {
        **original['lines'][1], 'line_number': original['lines'][0]['line_number']}
    with pytest.raises(ValueError, match='line_number.*unique'):
        MooringConfig.model_validate(original)
    assert original['lines'][0]['line_number'] == original['lines'][1]['line_number']


@pytest.mark.parametrize('endpoint', ['mooring/analyze', 'scenarios'])
def test_duplicate_line_ids_fail_at_http_boundary(endpoint):
    case = docking_cases()[0]
    body = (case.analysis_request if endpoint == 'mooring/analyze' else case.scenario_request).model_dump(mode='json')
    if endpoint == 'scenarios':
        body['env_source'] = {'mode': 'mock'}
    body['config']['lines'].append(dict(body['config']['lines'][0]))
    with TestClient(app) as client:
        response = client.post('/api/v1/'+endpoint, json=body)
    assert response.status_code == 422
    assert 'line_number' in response.text and 'unique' in response.text


def test_empty_and_nonconsecutive_unique_line_ids_remain_valid_inputs():
    original = docking_cases()[0].analysis_request.config.model_dump()
    for number, line in enumerate(original['lines'], start=10):
        line['line_number'] = number*2
    result = MooringConfig.model_validate(original)
    assert [line.line_number for line in result.lines] == [line['line_number'] for line in original['lines']]
    assert MooringConfig.model_validate(original | {'lines': []}).lines == []
