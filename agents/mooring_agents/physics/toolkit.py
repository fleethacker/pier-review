"""Minimal logged adapter over the existing modeling client and tool catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..clients import ModelingClient
from ..tools import TOOLS


@dataclass(frozen=True)
class ToolCall:
    plan_id: str | None
    tool: str
    result_id: str | None


LEDGER: list[ToolCall] = []


def calls_for(plan_id: str | None = None) -> list[ToolCall]:
    return [call for call in LEDGER if plan_id is None or call.plan_id == plan_id]


class UnknownTool(KeyError):
    pass


def tool_definitions() -> list[dict[str, Any]]:
    """Return OpenAI-compatible definitions for the physics catalog."""
    return [{"type": "function", "name": spec.name, "description": spec.description,
             "parameters": {"type": "object", "properties": {}, "additionalProperties": True}}
            for spec in TOOLS]


def summarize(value: Any) -> str:
    """Serialize tool data with an explicit untrusted-data boundary for prompts."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return "<physics_data>\n" + json.dumps(value, sort_keys=True, default=str) + "\n</physics_data>"


class PhysicsToolkit:
    def __init__(self, client: ModelingClient, caller: str = "planner", plan_id: str | None = None):
        self.client, self.caller, self.plan_id = client, caller, plan_id

    async def _record(self, name: str, awaitable: Any) -> Any:
        result = await awaitable
        LEDGER.append(ToolCall(self.plan_id, name, getattr(result, "result_id", None)))
        return result

    async def scenario(self, scenario_id: str):
        return await self._record("get_scenario", self.client.scenario(scenario_id))

    async def ship(self, class_id: str):
        return await self._record("get_ship", self.client.ship(class_id))

    async def berth(self, berth_id: str):
        return await self._record("get_berth", self.client.berth(berth_id))

    async def env_now(self, berth_id: str):
        return await self._record("get_environment", self.client.env_now(berth_id))

    async def recommend(self, body: dict):
        return await self._record("recommend_config", self.client.recommend(body))

    async def analyze(self, body: dict):
        return await self._record("analyze_mooring", self.client.analyze(body))

    async def berthing_tugs(self, body: dict):
        return await self._record("plan_tugs", self.client.berthing_tugs(body))

    async def hold_tugs(self, body: dict):
        return await self._record("hold_tugs", self.client.hold_tugs(body))

    async def sequence(self, body: dict):
        return await self._record("generate_sequence", self.client.sequence(body))

    async def exceedance(self, body: dict):
        return await self._record("risk_exceedance", self.client.exceedance(body))

    async def call(self, name: str, body: dict) -> Any:
        methods = {
            "recommend_config": self.recommend,
            "analyze_mooring": self.analyze,
            "plan_tugs": self.berthing_tugs,
            "hold_tugs": self.hold_tugs,
            "generate_sequence": self.sequence,
            "risk_exceedance": self.exceedance,
        }
        if name not in {tool.name for tool in TOOLS} or name not in methods:
            raise UnknownTool(f"Unknown or unavailable tool '{name}'")
        return await methods[name](body)


def ensure_toolkit(value: PhysicsToolkit | ModelingClient) -> PhysicsToolkit:
    return value if isinstance(value, PhysicsToolkit) else PhysicsToolkit(value)
