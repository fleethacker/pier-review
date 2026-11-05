"""Provider-agnostic LLM interface. Every agent codes to this, never to a vendor SDK directly.

Provider and model come from the environment (AGENTS_LLM_PROVIDER, AGENTS_LLM_MODEL); keys never live in code.
Tests and mock mode don't call an LLM.
"""

import json
import os
from typing import Any, Literal, Protocol

import httpx

from pydantic import BaseModel, Field


class ToolUse(BaseModel):
    id: str
    name: str = Field(description="A name from mooring_agents.physics.tools.TOOLS.")
    arguments: dict[str, Any]


class ImageInput(BaseModel):
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    data_base64: str = Field(max_length=12_000_000)


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    images: list[ImageInput] = Field(default_factory=list, max_length=4)
    tool_use_id: str | None = Field(default=None, description="role='tool': which ToolUse this answers.")
    tool_uses: list[ToolUse] = Field(default_factory=list, description="role='assistant': tools it asked for.")


class Reply(BaseModel):
    text: str
    tool_uses: list[ToolUse] = Field(default_factory=list)
    stop_reason: str
    usage: dict[str, int] = Field(default_factory=dict)


class LLM(Protocol):
    async def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None, *,
                   max_tokens: int = 2048, temperature: float = 0.0) -> Reply: ...


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    """A configured provider failed or returned an unusable response."""


class OpenAIResponsesLLM:
    """Responses adapter for guarded narration and function-call proposals.

    https://developers.openai.com/api/docs/guides/function-calling
    Keys/model are configuration only; no default model or implicit live calls.
    """

    def __init__(self, model: str, api_key: str, *, transport=None):
        self.model, self._api_key, self._transport = model, api_key, transport

    async def chat(self, messages: list[Message], tools=None, *, max_tokens=2048, temperature=0.0) -> Reply:
        inputs = []
        for message in messages:
            if message.role == "tool":
                inputs.append({"type": "function_call_output", "call_id": message.tool_use_id,
                               "output": message.content})
            else:
                if message.images:
                    inputs.append({"role": message.role, "content": [
                        {"type": "input_text", "text": message.content},
                        *({"type": "input_image", "image_url": f"data:{image.media_type};base64,{image.data_base64}"}
                          for image in message.images),
                    ]})
                elif message.content:
                    inputs.append({"role": message.role, "content": message.content})
                for call in message.tool_uses:
                    inputs.append({"type": "function_call", "call_id": call.id, "name": call.name,
                                   "arguments": json.dumps(call.arguments)})
        # Omit temperature: application guardrails, not sampling, enforce validity.
        body = {"model": self.model, "input": inputs,
                "max_output_tokens": max_tokens, "store": False}
        if tools:
            body.update(tools=tools, parallel_tool_calls=False)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=25.0) as client:
                response = await client.post("https://api.openai.com/v1/responses", json=body,
                                             headers={"Authorization": f"Bearer {self._api_key}"})
                response.raise_for_status()
                data = response.json()
            if data.get("status") != "completed":
                raise LLMError("Provider did not complete the response")
            if any(item.get("type") not in ("message", "reasoning", "function_call") for item in data["output"]):
                raise LLMError("Provider returned unsupported output")
            text = "\n".join(part["text"] for item in data["output"] if item.get("type") == "message"
                             for part in item.get("content", []) if part.get("type") == "output_text")
            calls = [ToolUse(id=item["call_id"], name=item["name"], arguments=json.loads(item["arguments"]))
                     for item in data["output"] if item.get("type") == "function_call"]
            if calls and not tools:
                raise LLMError("Provider returned unrequested tool calls")
            if not text and not calls:
                raise LLMError("Provider returned no text")
            return Reply(text=text, tool_uses=calls, stop_reason="completed",
                         usage={k: v for k, v in (data.get("usage") or {}).items() if type(v) is int})
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise LLMError("LLM request or response failed") from exc


def get_llm() -> LLM:
    provider = os.environ.get("AGENTS_LLM_PROVIDER", "none").strip().lower()
    if provider in ("none", ""):
        raise LLMNotConfigured("No LLM configured")
    if provider not in ("openai", "anthropic"):
        raise LLMNotConfigured(f"Unsupported AGENTS_LLM_PROVIDER={provider!r}")
    model = os.environ.get("AGENTS_LLM_MODEL", "").strip()
    key_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    key = os.environ.get(key_name, "").strip()
    if not model or not key:
        raise LLMNotConfigured(f"Set AGENTS_LLM_MODEL and {key_name} to enable narration")
    if provider == "anthropic":
        from .anthropic import AnthropicMessagesLLM
        return AnthropicMessagesLLM(model, key)
    return OpenAIResponsesLLM(model, key)
