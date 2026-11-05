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
    from mooring.core import store
    database = store.Database(':memory:')
    monkeypatch.setattr(store, 'db', lambda: database)
    monkeypatch.setenv('MOORING_RATE_PER_MINUTE', '0')
    yield TestClient(app)
    database.close()


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


@pytest.mark.parametrize('problem', [
    'empty_depth', 'duplicate_depth', 'duplicate_fitting', 'duplicate_fender',
    'fitting_fender_collision', 'latitude', 'longitude',
])
def test_invalid_asset_cannot_poison_catalog_listing(catalog, monkeypatch, problem):
    monkeypatch.setenv('MOORING_API_KEYS', '')
    monkeypatch.setenv('MOORING_AUTH_REQUIRED', '0')
    value = refdata.berth(SEED).model_dump(mode='json')
    value['berth_id'] = 'INVALID-'+problem
    if problem == 'empty_depth':
        value['depth_profile'] = []
    elif problem == 'duplicate_depth':
        value['depth_profile'].append(value['depth_profile'][0] | {'depth_mllw_ft': 1})
    elif problem == 'duplicate_fitting':
        value['fittings'].append(dict(value['fittings'][0]))
    elif problem == 'duplicate_fender':
        value['fenders'].append(dict(value['fenders'][0]))
    elif problem == 'fitting_fender_collision':
        value['fenders'][0]['fender_id'] = value['fittings'][0]['fitting_id']
    elif problem == 'latitude':
        value['origin_lat'] = 91
    else:
        value['origin_lon'] = 181
    response = catalog.post(f'{P}/berths', json=value)
    assert response.status_code == 422
    listing = catalog.get(f'{P}/berths')
    assert listing.status_code == 200
    assert value['berth_id'] not in {b['berth_id'] for b in listing.json()}


def test_single_or_unordered_unique_depth_samples_remain_supported(catalog, monkeypatch):
    from mooring.core.geometry import depth_at
    monkeypatch.setenv('MOORING_API_KEYS', '')
    monkeypatch.setenv('MOORING_AUTH_REQUIRED', '0')
    value = refdata.berth(SEED).model_dump(mode='json')
    value['berth_id'] = 'SINGLE-DEPTH'
    value['depth_profile'] = [{'x_ft': 0, 'depth_mllw_ft': 30}]
    assert catalog.post(f'{P}/berths', json=value).status_code == 201
    assert depth_at(refdata.berth(value['berth_id']), 100) == 30
    value['berth_id'] = 'UNORDERED-DEPTH'
    value['depth_profile'] = [{'x_ft': 100, 'depth_mllw_ft': 40}, {'x_ft': 0, 'depth_mllw_ft': 30}]
    assert catalog.post(f'{P}/berths', json=value).status_code == 201
    assert depth_at(refdata.berth(value['berth_id']), 50) == 35


def test_confirmed_berth_survives_reopen_and_backup_restore(tmp_path, monkeypatch):
    from mooring.core import store
    from mooring.core.backup import backup, restore

    live_path = str(tmp_path / 'catalog.sqlite')
    backup_path = str(tmp_path / 'backup.sqlite')
    restore_path = str(tmp_path / 'restored.sqlite')
    database = store.Database(live_path)
    monkeypatch.setattr(store, 'db', lambda: database)
    original = refdata.berth(SEED).model_copy(update={'berth_id': 'DURABLE-CATALOG'})
    try:
        refdata.add_berth(original)
        import os
        import subprocess
        import sys
        child = subprocess.run(
            [sys.executable, "-c", "from mooring import refdata; print(refdata.berth('DURABLE-CATALOG').model_dump_json())"],
            env={**os.environ, "MOORING_DB": live_path}, capture_output=True, text=True, check=True,
        )
        assert json.loads(child.stdout) == original.model_dump(mode='json')
        backup(database, backup_path)
        database.close()
        database = store.Database(live_path)
        assert refdata.berth(original.berth_id) == original
        restore(backup_path, restore_path)
        database.close()
        database = store.Database(restore_path)
        assert refdata.berth(original.berth_id) == original
        assert refdata.add_berth(original) == original
        with pytest.raises(refdata.ReferenceConflict):
            refdata.add_berth(original.model_copy(update={'name': 'Changed after recovery'}))
        assert sum(b.berth_id == original.berth_id for b in refdata.berths()) == 1
    finally:
        database.close()


def test_catalog_follows_database_not_process_memory(monkeypatch):
    from mooring.core import store

    first, second = store.Database(':memory:'), store.Database(':memory:')
    monkeypatch.setattr(store, 'db', lambda: first)
    original = refdata.berth(SEED).model_copy(update={'berth_id': 'DATABASE-SCOPED'})
    try:
        refdata.add_berth(original)
        monkeypatch.setattr(store, 'db', lambda: second)
        with pytest.raises(refdata.NotFound):
            refdata.berth(original.berth_id)
        assert original.berth_id not in {b.berth_id for b in refdata.berths()}
        monkeypatch.setattr(store, 'db', lambda: first)
        assert refdata.berth(original.berth_id) == original
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize('same_definition', [False, True])
def test_seed_upgrade_never_silently_rebinds_stored_reference(catalog, monkeypatch, same_definition):
    original = refdata.berth(SEED).model_copy(update={'berth_id': 'LATER-SEED'})
    refdata.add_berth(original)
    later = original if same_definition else original.model_copy(update={'name': 'Changed seed definition'})
    seeds = {**refdata._seed_berths(), later.berth_id: later}
    monkeypatch.setattr(refdata, '_seed_berths', lambda: seeds)
    if same_definition:
        assert refdata.berth(original.berth_id) == original
        assert refdata.add_berth(original) == original
        assert sum(b.berth_id == original.berth_id for b in refdata.berths()) == 1
    else:
        for lookup in (lambda: refdata.berth(original.berth_id), refdata.berths, lambda: refdata.add_berth(later)):
            with pytest.raises(refdata.InvalidReference, match='conflicts with the installed seed catalog'):
                lookup()


def test_independent_processes_cannot_replace_a_registration(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from mooring.core import store

    path = str(tmp_path / 'concurrent.sqlite')
    database = store.Database(path)
    monkeypatch.setattr(store, 'db', lambda: database)
    script = """
import sys
from mooring import refdata
candidate = refdata.berth('NAVSTA-NORFOLK-P12-N').model_copy(update={
    'berth_id': 'PROCESS-RACE', 'name': sys.argv[1]})
try:
    refdata.add_berth(candidate)
    print('created')
except refdata.ReferenceConflict:
    print('conflict')
"""
    def register(index):
        result = subprocess.run([sys.executable, '-c', script, str(index)],
                                env={**os.environ, 'MOORING_DB': path},
                                capture_output=True, text=True, check=True, timeout=20)
        return index, result.stdout.strip()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(register, range(4)))
        winners = [index for index, outcome in outcomes if outcome == 'created']
        assert len(winners) == 1
        assert sum(outcome == 'conflict' for _, outcome in outcomes) == 3
        assert refdata.berth('PROCESS-RACE').name == str(winners[0])
    finally:
        database.close()
