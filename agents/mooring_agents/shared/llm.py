"""Provider-agnostic LLM interface. Every agent codes to this, never to a vendor SDK directly.

Provider and model come from the environment (AGENTS_LLM_PROVIDER, AGENTS_LLM_MODEL); keys never live in code.
Tests and mock mode don't call an LLM.
"""

import os
from typing import Any, Literal, Protocol

import httpx

from pydantic import BaseModel, Field


class ToolUse(BaseModel):
    id: str
    name: str = Field(description="A name from mooring_agents.physics.tools.TOOLS.")
    arguments: dict[str, Any]


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
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
    """Text-only adapter using the Responses API; tool execution is not supported.

    https://developers.openai.com/api/docs/guides/text
    Keys/model are configuration only; no default model or implicit live calls.
    """

    def __init__(self, model: str, api_key: str, *, transport=None):
        self.model, self._api_key, self._transport = model, api_key, transport

    async def chat(self, messages: list[Message], tools=None, *, max_tokens=2048, temperature=0.0) -> Reply:
        if tools or any(m.tool_uses or m.role == "tool" for m in messages):
            raise LLMError("This provider adapter supports text narration only")
        # Temperature is deliberately omitted: not all reasoning models accept it.
        # Determinism and validity come from application guardrails, not sampling controls.
        body = {"model": self.model, "input": [{"role": m.role, "content": m.content} for m in messages],
                "max_output_tokens": max_tokens, "store": False}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=25.0) as client:
                response = await client.post("https://api.openai.com/v1/responses", json=body,
                                             headers={"Authorization": f"Bearer {self._api_key}"})
                response.raise_for_status()
                data = response.json()
            if data.get("status") != "completed":
                raise LLMError("Provider did not complete the response")
            if any(item.get("type") not in ("message", "reasoning") for item in data["output"]):
                raise LLMError("Provider returned unsupported non-text output")
            text = "\n".join(part["text"] for item in data["output"] if item.get("type") == "message"
                             for part in item.get("content", []) if part.get("type") == "output_text")
            if not text:
                raise LLMError("Provider returned no text")
            return Reply(text=text, stop_reason="completed",
                         usage={k: v for k, v in (data.get("usage") or {}).items() if type(v) is int})
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise LLMError("LLM request or response failed") from exc


def get_llm() -> LLM:
    provider = os.environ.get("AGENTS_LLM_PROVIDER", "none").strip().lower()
    if provider in ("none", ""):
        raise LLMNotConfigured("No LLM configured")
    if provider != "openai":
        raise LLMNotConfigured(f"Unsupported AGENTS_LLM_PROVIDER={provider!r}")
    model = os.environ.get("AGENTS_LLM_MODEL", "").strip()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not model or not key:
        raise LLMNotConfigured("Set AGENTS_LLM_MODEL and OPENAI_API_KEY to enable narration")
    return OpenAIResponsesLLM(model, key)
