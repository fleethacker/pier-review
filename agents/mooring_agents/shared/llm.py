"""Provider-agnostic LLM interface. Every agent codes to this, never to a vendor SDK directly.

The first agent that needs a real model adds a provider class here and registers it in `get_llm`.
Provider and model come from the environment (AGENTS_LLM_PROVIDER, AGENTS_LLM_MODEL); keys never live in code.
Tests and mock mode don't call an LLM.
"""

import os
from typing import Any, Literal, Protocol

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


def get_llm() -> LLM:
    provider = os.environ.get("AGENTS_LLM_PROVIDER", "none")
    raise LLMNotConfigured(
        f"No LLM provider implemented for AGENTS_LLM_PROVIDER='{provider}'. Add one in mooring_agents/shared/llm.py."
    )
