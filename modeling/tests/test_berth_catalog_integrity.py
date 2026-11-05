"""Shared reference IDs must not be silently rebound under saved scenarios."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring import refdata

P = '/api/v1'
SEED = 'NAVSTA-NORFOLK-P12-N'


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(refdata, '_runtime_berths', {})
    monkeypatch.setenv('MOORING_RATE_PER_MINUTE', '0')
    return TestClient(app)


@pytest.mark.parametrize('authenticated', [False, True])
def test_seed_cannot_be_replaced_even_by_an_authenticated_caller(catalog, monkeypatch, authenticated):
    keys = {'owner': 'a'*32, 'other': 'b'*32} if authenticated else {}
    monkeypatch.setenv('MOORING_API_KEYS', json.dumps(keys) if keys else '')
    monkeypatch.setenv('MOORING_AUTH_REQUIRED', '1' if authenticated else '0')
    headers = {'Authorization': 'Bearer '+keys['other']} if keys else {}
    original = catalog.get(f'{P}/berths/{SEED}', headers=headers).json()
    changed = original | {'name': 'Different geometry under the same reference'}
    changed['depth_profile'] = [{'x_ft': 0, 'depth_mllw_ft': 1}]
    refused = catalog.post(f'{P}/berths', json=changed, headers=headers)
    assert refused.status_code == 409
    assert 'new berth_id' in refused.json()['detail']
    assert catalog.get(f'{P}/berths/{SEED}', headers=headers).json() == original
    assert sum(item['berth_id'] == SEED for item in catalog.get(f'{P}/berths', headers=headers).json()) == 1


def test_runtime_registration_is_idempotent_but_cannot_be_rebound(catalog, monkeypatch):
    monkeypatch.setenv('MOORING_API_KEYS', json.dumps({'owner': 'a'*32, 'other': 'b'*32}))
    a, b = {'Authorization': 'Bearer '+'a'*32}, {'Authorization': 'Bearer '+'b'*32}
    original = catalog.get(f'{P}/berths/{SEED}', headers=a).json() | {'berth_id': 'REGISTERED-FIXTURE'}
    assert catalog.post(f'{P}/berths', json=original, headers=a).status_code == 201
    assert catalog.post(f'{P}/berths', json=original, headers=a).status_code == 201
    for headers in (a, b):
        assert catalog.post(f'{P}/berths', json=original | {'name': 'replacement'}, headers=headers).status_code == 409
    assert catalog.get(f'{P}/berths/REGISTERED-FIXTURE', headers=a).json() == original
    assert sum(item['berth_id'] == 'REGISTERED-FIXTURE' for item in catalog.get(f'{P}/berths', headers=a).json()) == 1


def test_concurrent_conflicting_registration_keeps_one_complete_record(catalog):
    barrier = Barrier(8)
    original = refdata.berth(SEED)
    def submit(index):
        value = original.model_copy(update={'berth_id': 'CONCURRENT-FIXTURE', 'name': f'Candidate {index}'})
        barrier.wait(timeout=5)
        try:
            saved = refdata.add_berth(value)
        except refdata.ReferenceConflict:
            return None
        saved.name = 'Caller edit must not mutate the catalog'
        value.name = 'Input edit must not mutate the catalog'
        return index
    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = [i for i in pool.map(submit, range(8)) if i is not None]
    assert len(winners) == 1
    assert refdata.berth('CONCURRENT-FIXTURE').name == f'Candidate {winners[0]}'
