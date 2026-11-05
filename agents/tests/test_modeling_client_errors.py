"""Unusable upstream responses must remain explicit failures, including on SSE watches."""
import asyncio

import httpx
import pytest

from mooring_agents.physics.client import ModelingClient, ModelingError


@pytest.mark.parametrize('response', [
    httpx.Response(200, text='<html>upstream unavailable</html>'),
    httpx.Response(200, json={'wind_speed_kt': 'bad'}),
    httpx.Response(200, json=[]),
])
def test_invalid_environment_response_is_a_typed_upstream_error(response):
    client = ModelingClient(transport=httpx.MockTransport(lambda request: response))
    with pytest.raises(ModelingError) as error:
        asyncio.run(client.scenario_environment('saved'))
    assert error.value.status == 502


@pytest.mark.parametrize('payload', [['offline'], 'offline', None])
def test_non_object_error_body_preserves_upstream_failure_status(payload):
    client = ModelingClient(transport=httpx.MockTransport(lambda request: httpx.Response(503, json=payload)))
    with pytest.raises(ModelingError) as error:
        asyncio.run(client.scenario_environment('saved'))
    assert error.value.status == 503


@pytest.mark.parametrize('payload', [None, [], {}, {'state': 'succeeded'}, {'state': 'succeeded', 'result': None}])
def test_malformed_job_status_fails_explicitly_and_attempts_cleanup(payload):
    seen = []
    def respond(request):
        seen.append(request.method)
        if request.method == 'POST':
            return httpx.Response(202, json={'job_id': 'job_fixture', 'status_url': '/jobs/job_fixture'})
        if request.method == 'DELETE':
            return httpx.Response(200, json={'state': 'cancelled'})
        return httpx.Response(200, json=payload)
    client = ModelingClient(transport=httpx.MockTransport(respond))
    with pytest.raises(ModelingError) as error:
        asyncio.run(client.job('/mooring/recommend', {}))
    assert error.value.status == 502
    assert seen == ['POST', 'GET', 'DELETE']
