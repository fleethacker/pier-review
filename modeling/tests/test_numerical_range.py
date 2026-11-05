"""Finite inputs can still overflow derived calculations; never report a usable result."""
import copy

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.demo_cases import docking_cases
from mooring.examples import EXAMPLES


@pytest.mark.parametrize('route,field,value', [
    ('/loads/environmental', 'water_density_kgm3', 5e-324),
    ('/mooring/analyze', 'water_density_kgm3', 5e-324),
    ('/mooring/envelope', 'water_density_kgm3', 5e-324),
    ('/loads/environmental', 'wind_gust_kt', 1e153),
    ('/loads/environmental', 'wind_gust_kt', 1e308),
    ('/loads/environmental', 'current_speed_kt', 1e153),
    ('/loads/environmental', 'current_speed_kt', 1e308),
    ('/loads/polar', 'wind_speed_kt', 1e153),
    ('/loads/polar', 'wind_speed_kt', 1e308),
    ('/mooring/analyze', 'wind_gust_kt', 1e308),
    ('/mooring/analyze', 'current_speed_kt', 1e308),
    ('/mooring/analyze', 'water_level_mllw_ft', 1e308),
    ('/mooring/analyze', 'ship_x_ft', 1e308),
    ('/mooring/envelope', 'wind_gust_kt', 1e308),
])
def test_unrepresentable_calculation_returns_explicit_422(route, field, value):
    if route.startswith('/loads/'):
        body = copy.deepcopy(EXAMPLES['loads_polar' if route.endswith('polar') else 'loads_environmental'])
    else:
        body = docking_cases()[0].analysis_request.model_dump(mode='json')
    target = body if route.endswith('polar') else body['config'] if field == 'ship_x_ft' else body['environment']
    target[field] = value
    response = TestClient(app, raise_server_exceptions=False).post('/api/v1'+route, json=body)
    assert response.status_code == 422, response.text
    payload = response.json()
    assert 'numerical range' in payload['detail']
    assert 'result' not in payload and 'result_id' not in payload


def test_loads_guard_does_not_hide_non_numeric_validation_errors(monkeypatch):
    from pydantic import ValidationError
    from mooring.core.schemas import ForceSet
    from mooring.loads import service

    def malformed(*args, **kwargs):
        return ForceSet(fx_lbf="not a number", fy_lbf=0, mz_ftlbf=0)

    monkeypatch.setattr(service, "compute_loads", malformed)
    with pytest.raises(ValidationError):
        service._checked_loads()
