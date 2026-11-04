"""Provider-neutral LLM protocol and the OpenAI Responses API provider."""

from __future__ import annotations

import json
import os
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class ToolUse(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_use_id: str | None = None
    tool_uses: list[ToolUse] = Field(default_factory=list)


class Reply(BaseModel):
    text: str = ""
    tool_uses: list[ToolUse] = Field(default_factory=list)
    stop_reason: str = "stop"
    usage: dict[str, int] = Field(default_factory=dict)


class LLM(Protocol):
    model_id: str

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> Reply: ...


class LLMNotConfigured(RuntimeError):
    pass


class OpenAILLM:
    """Small adapter around ``AsyncOpenAI.responses.create``."""

    def __init__(self, model: str | None = None, client: Any | None = None):
        self.model_id = model or os.environ.get("AGENTS_LLM_MODEL", "gpt-4.1-mini")
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover - depends on deployment extras
                raise LLMNotConfigured("The OpenAI provider requires the 'openai' package.") from exc
            client = AsyncOpenAI()
        self.client = client

    @staticmethod
    def _input(messages: list[Message]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                items.append({"type": "function_call_output", "call_id": message.tool_use_id,
                              "output": message.content})
                continue
            items.append({"role": message.role, "content": message.content})
            if message.role == "assistant":
                items.extend({"type": "function_call", "call_id": call.id, "name": call.name,
                              "arguments": json.dumps(call.arguments)} for call in message.tool_uses)
        return items

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None, *,
                   max_tokens: int = 2048, temperature: float = 0.0) -> Reply:
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "input": self._input(messages),
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "store": False,
        }
        if tools:
            kwargs.update(tools=tools, parallel_tool_calls=False)
        response = await self.client.responses.create(**kwargs)
        calls = [ToolUse(id=item.call_id, name=item.name, arguments=json.loads(item.arguments or "{}"))
                 for item in response.output if getattr(item, "type", None) == "function_call"]
        usage = getattr(response, "usage", None)
        usage_dict = {}
        if usage:
            usage_dict = {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                          "total_tokens": usage.total_tokens}
        return Reply(text=response.output_text or "", tool_uses=calls,
                     stop_reason=getattr(response, "status", "stop"), usage=usage_dict)


def get_llm() -> LLM:
    provider = os.environ.get("AGENTS_LLM_PROVIDER", "none").strip().lower()
    if provider in ("", "none", "mock", "deterministic"):
        raise LLMNotConfigured("No LLM configured.")
    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise LLMNotConfigured("AGENTS_LLM_PROVIDER=openai requires OPENAI_API_KEY.")
        return OpenAILLM()
    raise LLMNotConfigured(f"Unknown AGENTS_LLM_PROVIDER='{provider}'.")
