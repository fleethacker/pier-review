"""Polling failures, cancellation cleanup and untrusted job links stay bounded."""
import asyncio

import httpx
import pytest

from mooring_agents.physics.client import ModelingClient, ModelingError


@pytest.mark.parametrize('state,code', [('cancelled', 409), ('failed', 500)])
def test_remote_terminal_failure_returns_immediately_without_polling_again(state, code):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(202 if request.method == 'POST' else 200, json=(
            {'job_id': 'job_test', 'status_url': '/api/v1/jobs/job_test'} if request.method == 'POST' else
            {'state': state, 'error': 'stopped'}))
    client = ModelingClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ModelingError) as error:
        asyncio.run(client._job('/work', {}, poll_s=0))
    assert error.value.status == code and calls == ['POST', 'GET']


def test_external_cancellation_cancels_the_accepted_modeling_job():
    calls = []
    async def scenario():
        entered = asyncio.Event()
        async def handler(request):
            calls.append(request.method)
            if request.method == 'POST':
                return httpx.Response(202, json={'job_id': 'job_test', 'status_url': '/api/v1/jobs/job_test'})
            if request.method == 'GET':
                entered.set()
                await asyncio.Event().wait()
            return httpx.Response(200, json={'state': 'cancelled'})
        client = ModelingClient(transport=httpx.MockTransport(handler))
        task = asyncio.create_task(client._job('/work', {}))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())
    assert calls == ['POST', 'GET', 'DELETE']


def test_deadline_covers_http_wait_and_cleanup_error_does_not_replace_timeout():
    calls = []
    async def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            return httpx.Response(202, json={'job_id': 'job_test', 'status_url': '/api/v1/jobs/job_test'})
        if request.method == 'DELETE':
            return httpx.Response(503, json={'detail': 'unavailable'})
        await asyncio.Event().wait()
    client = ModelingClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ModelingError) as error:
        asyncio.run(client._job('/work', {}, timeout_s=.01))
    assert error.value.status == 504 and calls == ['POST', 'GET', 'DELETE']


@pytest.mark.parametrize('accepted', [
    {'job_id': 'job_ok', 'status_url': 'https://untrusted.invalid/steal'},
    {'job_id': '../scenarios/other', 'status_url': '/api/v1/jobs/../scenarios/other'},
    {'job_id': 'job_ok', 'status_url': '/api/v1/jobs/different'},
])
def test_returned_job_links_cannot_redirect_authenticated_requests(accepted):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        assert request.url.host == 'modeling'
        return httpx.Response(202, json=accepted)
    client = ModelingClient(base_url='http://modeling/api/v1', transport=httpx.MockTransport(handler),
                            authorization='Bearer test-only')
    with pytest.raises(ModelingError) as error:
        asyncio.run(client._job('/work', {}))
    assert error.value.status == 502 and calls == ['http://modeling/api/v1/work']


def test_submission_itself_is_inside_the_deadline():
    async def handler(request):
        await asyncio.Event().wait()
    client = ModelingClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ModelingError) as error:
        asyncio.run(client._job('/work', {}, timeout_s=.01))
    assert error.value.status == 504 and 'before acknowledgement' in error.value.detail
