"""Provider protocol and failure paths, with no network or credentials."""
import asyncio
import json

import httpx
import pytest

from mooring_agents.shared.anthropic import AnthropicMessagesLLM
from mooring_agents.shared.llm import ImageInput, LLMError, LLMNotConfigured, Message, ToolUse, get_llm

TOOLS = [{'type': 'function', 'name': 'inspect', 'description': 'Read a cited result',
          'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}, 'strict': True}]


def response(content=None, reason='end_turn'):
    return {'stop_reason': reason, 'content': content or [{'type': 'text', 'text': 'Cited observations.'}],
            'usage': {'input_tokens': 4, 'output_tokens': 3, 'cache_details': {}}}


def test_configuration_is_explicit_and_no_default_model(monkeypatch):
    monkeypatch.setenv('AGENTS_LLM_PROVIDER', 'anthropic')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake')
    monkeypatch.delenv('AGENTS_LLM_MODEL', raising=False)
    with pytest.raises(LLMNotConfigured): get_llm()
    monkeypatch.setenv('AGENTS_LLM_MODEL', 'deployment-chosen-model')
    assert isinstance(get_llm(), AnthropicMessagesLLM)
    monkeypatch.setenv('AGENTS_LLM_PROVIDER', 'none')
    with pytest.raises(LLMNotConfigured): get_llm()


def test_messages_images_tools_and_results_round_trip():
    def handler(request):
        body = json.loads(request.content)
        assert request.url == 'https://api.anthropic.com/v1/messages'
        assert request.headers['x-api-key'] == 'fake'
        assert request.headers['anthropic-version'] == '2026-10-21'
        assert body['model'] == 'configured' and body['max_tokens'] == 4096
        assert 'temperature' not in body and body['system'] == 'Only cite facts.'
        assert body['messages'][0]['content'][0]['source'] == {
            'type': 'base64', 'media_type': 'image/png', 'data': 'aW1hZ2U='}
        assert body['messages'][1]['content'][0]['type'] == 'tool_use'
        assert body['messages'][2]['content'][0]['tool_use_id'] == 't1'
        assert body['tools'][0]['input_schema'] == TOOLS[0]['parameters']
        assert body['tool_choice']['disable_parallel_tool_use'] is True
        return httpx.Response(200, json=response())
    provider = AnthropicMessagesLLM('configured', 'fake', transport=httpx.MockTransport(handler))
    reply = asyncio.run(provider.chat([
        Message(role='system', content='Only cite facts.'),
        Message(role='user', content='Inspect', images=[ImageInput(media_type='image/png', data_base64='aW1hZ2U=')]),
        Message(role='assistant', content='', tool_uses=[ToolUse(id='t1', name='inspect', arguments={})]),
        Message(role='tool', content='result citation', tool_use_id='t1'),
    ], tools=TOOLS, max_tokens=4096))
    assert reply.text == 'Cited observations.' and reply.stop_reason == 'completed'
    assert reply.usage == {'input_tokens': 4, 'output_tokens': 3}


def test_tool_proposal_is_returned_for_application_validation():
    provider = AnthropicMessagesLLM('configured', 'fake', transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=response([{'type': 'tool_use', 'id': 't2', 'name': 'inspect',
                                                     'input': {}}], 'tool_use'))))
    reply = asyncio.run(provider.chat([Message(role='user', content='Inspect')], tools=TOOLS))
    assert reply.tool_uses == [ToolUse(id='t2', name='inspect', arguments={})]
    assert reply.stop_reason == 'tool_use'


@pytest.mark.parametrize('payload', [
    {**response(), 'stop_details': {'type': 'refusal'}},
    response(reason='max_tokens'), response(reason='refusal'), response(reason='pause_turn'),
    {'stop_reason': 'end_turn', 'content': []}, {'stop_reason': 'end_turn'},
    response([{'type': 'text', 'text': '  '}]),
    response([{'type': 'server_tool_use', 'name': 'search'}]),
    response([{'type': 'tool_use', 'id': 'bad', 'name': 'invented', 'input': {}}], 'tool_use'),
    response([{'type': 'tool_use', 'id': 'bad', 'name': 'inspect', 'input': []}], 'tool_use'),
    response([{'type': 'tool_use', 'id': 'bad', 'name': 'inspect', 'input': {}}], 'end_turn'),
])
def test_malformed_truncated_refused_and_unknown_output_fails_closed(payload):
    provider = AnthropicMessagesLLM('configured', 'fake', transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=payload)))
    with pytest.raises(LLMError):
        asyncio.run(provider.chat([Message(role='user', content='Inspect')], tools=TOOLS))


@pytest.mark.parametrize('status', [401, 429, 500])
def test_http_errors_do_not_expose_provider_body(status):
    provider = AnthropicMessagesLLM('configured', 'fake', transport=httpx.MockTransport(
        lambda _: httpx.Response(status, json={'error': 'sensitive provider body'})))
    with pytest.raises(LLMError, match='LLM request or response failed') as error:
        asyncio.run(provider.chat([Message(role='user', content='Inspect')]))
    assert 'sensitive' not in str(error.value)
