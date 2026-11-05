"""Saved source resolution is shared by agents, alerts and simulation initialization."""
import copy
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring import environment, scenarios, refdata
from mooring.core.schemas import EnvironmentSnapshot
from mooring.environment.errors import ProviderError
from mooring.examples import EXAMPLES

client = TestClient(app)
P = '/api/v1'


def create(mode, **extra):
    body = copy.deepcopy(EXAMPLES['scenario'])
    body['env_source'] = {'mode': mode, **extra}
    response = client.post(P+'/scenarios', json=body)
    assert response.status_code == 201
    return response.json()['scenario_id']


def test_explicit_mock_never_calls_configured_public_provider(monkeypatch):
    monkeypatch.setenv('MOORING_ENV_SOURCE', 'coops')
    at = datetime(2026, 11, 5, 4, 15, 20, tzinfo=UTC)
    monkeypatch.setattr(scenarios, 'utcnow', lambda: at)
    monkeypatch.setattr(environment, 'now', lambda *a, **k: pytest.fail('Explicit mock called configured live source'))
    sid = create('mock')
    result = client.get(f'{P}/scenarios/{sid}/environment')
    assert result.status_code == 200
    snapshot = EnvironmentSnapshot.model_validate(result.json())
    assert snapshot.source == 'mock' and snapshot.valid_at_utc == at.replace(second=0)
    assert snapshot.metadata.basis == 'scenario'
    stations = refdata.berth(EXAMPLES['scenario']['berth_id']).env_station_ids
    assert {q.station_id for q in snapshot.quality} == {stations.wind, stations.current, stations.water_level}
    assert snapshot.model_dump() == scenarios.environment_for(scenarios.get(sid)).model_dump()


def test_selected_environment_scenario_is_resolved_without_provider_switch(monkeypatch):
    sid = create('scenario', env_scenario_id='selected-source')
    baseline = EnvironmentSnapshot.model_validate(EXAMPLES['mooring_analyze']['environment'])
    seen = []
    def selected(identifier, at, berth_id):
        seen.append((identifier, berth_id))
        return baseline
    monkeypatch.setattr(environment, 'scenario_snapshot', selected)
    monkeypatch.setattr(environment, 'now', lambda *a, **k: pytest.fail('Scenario switched to provider'))
    assert client.get(f'{P}/scenarios/{sid}/environment').json() == baseline.model_dump(mode='json')
    assert seen == [('selected-source', EXAMPLES['scenario']['berth_id'])]


def test_live_alias_preserves_configured_provider_failure(monkeypatch):
    sid = create('live')
    def unavailable(*a, **k): raise ProviderError('unavailable', 'fixture source unavailable')
    monkeypatch.setattr(environment, 'live_snapshot', unavailable)
    monkeypatch.setattr(environment, 'now', lambda *a, **k: pytest.fail('Explicit live consulted global fallback mode'))
    assert client.get(f'{P}/scenarios/{sid}/environment').status_code == 503


@pytest.mark.parametrize('mode', ['forecast', 'replay'])
def test_unsupported_saved_modes_fail_without_substitute_snapshot(monkeypatch, mode):
    sid = create(mode)
    monkeypatch.setattr(environment, 'now', lambda *a, **k: pytest.fail('Unsupported source replaced'))
    assert client.get(f'{P}/scenarios/{sid}/environment').status_code == 422


def test_scenario_environment_enforces_owner_before_resolving_source(monkeypatch):
    keys = {'alice':'a'*40, 'bob':'b'*40}
    monkeypatch.setenv('MOORING_API_KEYS', json.dumps(keys))
    body = copy.deepcopy(EXAMPLES['scenario'])
    sid = client.post(P+'/scenarios', json=body, headers={'Authorization':'Bearer '+keys['alice']}).json()['scenario_id']
    monkeypatch.setattr(scenarios, 'environment_for', lambda sc: pytest.fail('Foreign source resolved'))
    result = client.get(f'{P}/scenarios/{sid}/environment', headers={'Authorization':'Bearer '+keys['bob']})
    assert result.status_code == 404
