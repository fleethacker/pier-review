"""Anthropic Messages transport; model choice is explicit deployment configuration.

Protocol: https://platform.claude.com/docs/en/api/http/messages/create
Version: https://platform.claude.com/docs/en/api/versioning (2026-10-21).
No sampling parameters: this version removes them; application guards decide validity.
"""
from typing import Any

import httpx

from .llm import LLMError, Message, Reply, ToolUse


class AnthropicMessagesLLM:
    def __init__(self, model: str, api_key: str, *, transport=None):
        self.model, self._api_key, self._transport = model, api_key, transport

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None, *,
                   max_tokens: int = 2048, temperature: float = 0.0) -> Reply:
        system, turns = [], []
        for message in messages:
            if message.role == 'system':
                if message.images or message.tool_uses:
                    raise LLMError('System messages cannot contain images or tool calls')
                system.append(message.content)
                continue
            role = 'user' if message.role == 'tool' else message.role
            blocks = []
            if message.role == 'tool':
                if not message.tool_use_id:
                    raise LLMError('Tool result requires a call identifier')
                blocks.append({'type': 'tool_result', 'tool_use_id': message.tool_use_id, 'content': message.content})
            else:
                if message.images and role != 'user':
                    raise LLMError('Images require a user message')
                blocks.extend({'type': 'image', 'source': {'type': 'base64', 'media_type': image.media_type,
                                                          'data': image.data_base64}} for image in message.images)
                if message.content:
                    blocks.append({'type': 'text', 'text': message.content})
                if message.tool_uses and role != 'assistant':
                    raise LLMError('Tool calls require an assistant message')
                blocks.extend({'type': 'tool_use', 'id': call.id, 'name': call.name, 'input': call.arguments}
                              for call in message.tool_uses)
            if blocks:
                if turns and turns[-1]['role'] == role:
                    turns[-1]['content'].extend(blocks)
                else:
                    turns.append({'role': role, 'content': blocks})
        body = {'model': self.model, 'max_tokens': max_tokens, 'messages': turns}
        if system:
            body['system'] = '\n\n'.join(system)
        allowed = set()
        if tools:
            converted = []
            for tool in tools:
                schema = tool.get('parameters', tool.get('input_schema'))
                if not tool.get('name') or not isinstance(schema, dict):
                    raise LLMError('Invalid tool definition')
                allowed.add(tool['name'])
                converted.append({'name': tool['name'], 'description': tool.get('description', ''),
                                  'input_schema': schema})
            body['tools'] = converted
            body['tool_choice'] = {'type': 'auto', 'disable_parallel_tool_use': True}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=25.0) as client:
                response = await client.post('https://api.anthropic.com/v1/messages', json=body,
                    headers={'x-api-key': self._api_key, 'anthropic-version': '2026-10-21'})
                response.raise_for_status()
                data = response.json()
            reason = data['stop_reason']
            if reason not in ('end_turn', 'tool_use') or (data.get('stop_details') or {}).get('type') == 'refusal':
                raise LLMError('Provider did not complete the response')
            text, calls = [], []
            for block in data['content']:
                if block['type'] == 'text':
                    if not isinstance(block['text'], str):
                        raise LLMError('Invalid provider text')
                    text.append(block['text'])
                elif block['type'] == 'tool_use':
                    if block['name'] not in allowed or not isinstance(block['input'], dict):
                        raise LLMError('Unrequested or invalid tool call')
                    calls.append(ToolUse(id=block['id'], name=block['name'], arguments=block['input']))
                elif block['type'] not in ('thinking', 'redacted_thinking'):
                    raise LLMError('Unsupported provider output')
            if (reason == 'tool_use') != bool(calls) or len({call.id for call in calls}) != len(calls):
                raise LLMError('Inconsistent provider tool completion')
            if not any(part.strip() for part in text) and not calls:
                raise LLMError('Provider returned no text')
            return Reply(text='\n'.join(text), tool_uses=calls,
                         stop_reason='tool_use' if calls else 'completed',
                         usage={k: v for k, v in (data.get('usage') or {}).items() if type(v) is int})
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            # Provider bodies may contain secrets or user data. Do not expose them in fallback notes.
            raise LLMError('LLM request or response failed') from exc
