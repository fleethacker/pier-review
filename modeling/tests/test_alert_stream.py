"""Alert source continuity and explicit terminal failure without fabricated measurements."""
import copy

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from modeling_api.main import app
from modeling_api import ws as channels
from mooring.core.schemas import Alert, EnvironmentSnapshot
from mooring.environment.errors import ProviderError
from mooring.examples import EXAMPLES

client = TestClient(app)
P = '/api/v1'


def scenario():
    body = copy.deepcopy(EXAMPLES['scenario'])
    return client.post(f'{P}/scenarios', json=body).json()['scenario_id']


def test_saved_source_is_used_for_every_frame_and_installation_stays_fixed(monkeypatch):
    sid = scenario()
    baseline = EnvironmentSnapshot.model_validate(EXAMPLES['mooring_analyze']['environment'])
    samples = iter([baseline.model_copy(update={'water_level_mllw_ft': level}) for level in (-1, 2, 4)])
    monkeypatch.setattr(channels.scenarios, 'environment_for', lambda sc: next(samples))
    monkeypatch.setattr(channels.env, 'now', lambda berth: pytest.fail('Saved source replaced by live feed'))
    seen = []
    def alert(env, req):
        seen.append((env.water_level_mllw_ft, req.environment.water_level_mllw_ft))
        return Alert(alert_id=f'alert-{len(seen)}', at_utc=env.valid_at_utc, severity='AMBER',
                     element_id=None, message='Fixture source', env=env)
    monkeypatch.setattr(channels.risk, 'alert_for', alert)
    with client.websocket_connect(f'/ws/alerts?scenario_id={sid}&interval_s=0&limit=3') as sock:
        messages = [sock.receive_json() for _ in range(3)]
    assert [m['env']['water_level_mllw_ft'] for m in messages] == [-1, 2, 4]
    assert seen == [(-1, -1), (2, -1), (4, -1)]


@pytest.mark.parametrize('saved_source', [False, True])
@pytest.mark.parametrize('fail_after', [0, 1])
def test_provider_failure_closes_without_synthetic_alert(monkeypatch, saved_source, fail_after):
    sid = scenario() if saved_source else None
    baseline = EnvironmentSnapshot.model_validate(EXAMPLES['mooring_analyze']['environment'])
    calls = 0
    def source(_):
        nonlocal calls
        calls += 1
        if calls > fail_after:
            raise ProviderError('stale', 'Diagnostic detail that should not be exposed')
        return baseline
    monkeypatch.setattr(channels.scenarios if saved_source else channels.env,
                        'environment_for' if saved_source else 'now', source)
    path = '/ws/alerts?interval_s=0&limit=2' + (f'&scenario_id={sid}' if sid else '')
    with client.websocket_connect(path) as sock:
        if fail_after:
            Alert.model_validate(sock.receive_json())
        with pytest.raises(WebSocketDisconnect) as err:
            sock.receive_json()
    assert err.value.code == 1013 and 'stale' in err.value.reason
    assert 'Diagnostic detail' not in err.value.reason


def test_unknown_scenario_closes_as_not_found():
    with client.websocket_connect('/ws/alerts?scenario_id=unknown&limit=1') as sock:
        with pytest.raises(WebSocketDisconnect) as err:
            sock.receive_json()
    assert err.value.code == 4404


@pytest.mark.parametrize('query', ['interval_s=-1', 'interval_s=nan', 'interval_s=inf', 'limit=-1', 'interval_s=0&limit=0'])
def test_bad_stream_timing_is_rejected(query):
    with client.websocket_connect('/ws/alerts?' + query) as sock:
        with pytest.raises(WebSocketDisconnect) as err:
            sock.receive_json()
    assert err.value.code == 4400


def test_foreign_scenario_is_not_read_by_alert_stream(monkeypatch):
    import json
    keys = {'alice': 'test-alice-key-' + 'a' * 32, 'bob': 'test-bob-key-' + 'b' * 32}
    monkeypatch.setenv('MOORING_API_KEYS', json.dumps(keys))
    response = client.post(f'{P}/scenarios', json=copy.deepcopy(EXAMPLES['scenario']),
                           headers={'Authorization': f'Bearer {keys["alice"]}'})
    assert response.status_code == 201
    sid = response.json()['scenario_id']
    monkeypatch.setattr(channels.scenarios, 'environment_for', lambda sc: pytest.fail('Foreign scenario was read'))
    with client.websocket_connect(f'/ws/alerts?scenario_id={sid}&limit=1',
                                  headers={'Authorization': f'Bearer {keys["bob"]}'}) as sock:
        with pytest.raises(WebSocketDisconnect) as err:
            sock.receive_json()
    assert err.value.code == 4404 and sid not in err.value.reason


@pytest.mark.parametrize('mode', ['replay', 'forecast'])
def test_unsupported_scenario_mode_never_substitutes_live_feed(monkeypatch, mode):
    from mooring import environment
    body = copy.deepcopy(EXAMPLES['scenario'])
    body['env_source'] = {'mode': mode}
    sid = client.post(f'{P}/scenarios', json=body).json()['scenario_id']
    monkeypatch.setattr(environment, 'now', lambda *a, **k: pytest.fail('Unsupported source fell back to live'))
    with client.websocket_connect(f'/ws/alerts?scenario_id={sid}&limit=1') as sock:
        with pytest.raises(WebSocketDisconnect) as err:
            sock.receive_json()
    assert err.value.code == 4400


@pytest.mark.parametrize('blocked_stage', ['provider', 'calculation'])
def test_blocked_alert_work_does_not_block_http_or_the_event_loop(monkeypatch, blocked_stage):
    import asyncio
    import threading
    import httpx
    from mooring.core import access
    entered, release = threading.Event(), threading.Event()
    timed_out = []
    seen = []
    baseline = EnvironmentSnapshot.model_validate(EXAMPLES['mooring_analyze']['environment'])

    def block():
        seen.append(access.principal.get())
        entered.set()
        if not release.wait(3):
            timed_out.append(True)

    def source(_):
        if blocked_stage == 'provider': block()
        return baseline

    def alert(env, req):
        if blocked_stage == 'calculation': block()
        return Alert(alert_id='offloaded', at_utc=env.valid_at_utc, severity='AMBER',
                     element_id=None, message='Fixture', env=env)

    class Socket:
        messages = []
        async def accept(self): pass
        async def send_json(self, message): self.messages.append(message)
        async def close(self, **kwargs): pass

    monkeypatch.setattr(channels.env, 'now', source)
    monkeypatch.setattr(channels.risk, 'alert_for', alert)

    async def exercise():
        token = access.principal.set('alert-owner')
        socket = Socket()
        task = asyncio.create_task(channels.ws_alerts(socket, limit=1))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as http:
                health = await asyncio.wait_for(http.get(P + '/health'), 1)
            assert health.status_code == 200
            assert not timed_out and not release.is_set()
            release.set()
            await asyncio.wait_for(task, 2)
            assert socket.messages[0]['alert_id'] == 'offloaded'
            assert seen == ['alert-owner']
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            access.principal.reset(token)

    asyncio.run(exercise())


def test_alert_timeout_keeps_worker_slot_until_thread_finishes(monkeypatch):
    import asyncio
    import threading
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(channels, '_ALERT_SLOTS', slots)
    monkeypatch.setattr(channels, 'ALERT_TIMEOUT_S', 0.05)

    def source(_):
        entered.set()
        try:
            assert release.wait(3)
            raise ProviderError('unavailable', 'late provider result')
        finally:
            exited.set()

    class Socket:
        closed = None
        async def accept(self): pass
        async def send_json(self, message): pytest.fail('A timed-out source must not publish an alert')
        async def close(self, **kwargs): self.closed = kwargs

    monkeypatch.setattr(channels.env, 'now', source)

    async def exercise():
        socket = Socket()
        try:
            await asyncio.wait_for(channels.ws_alerts(socket, limit=1), 1)
            assert entered.is_set() and socket.closed['code'] == 1013
            assert not slots.acquire(blocking=False)
            second = Socket()
            await channels.ws_alerts(second, limit=1)
            assert second.closed['code'] == 1013
        finally:
            release.set()
            assert await asyncio.to_thread(exited.wait, 2)
            # Callback release runs immediately after worker exit, without a sleep/poll loop.
            assert await asyncio.to_thread(slots.acquire, True, 2)
            slots.release()

    asyncio.run(exercise())
