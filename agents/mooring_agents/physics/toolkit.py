"""Physics toolkit: the only way agents run physics. Wraps the modeling client and records every call.

No LLM and no math here: every number comes from the modeling service. Agents use the typed helpers; the LLM
tool loop and the HTTP gateway use `call(name, input)`.
"""

import time
from collections.abc import Awaitable
from typing import Any

from mooring.core.envelopes import inputs_hash, new_id, utcnow
from mooring.core.schemas import (
    AnalyzeResponse,
    Berth,
    BerthingWindowsResponse,
    EnvironmentSnapshot,
    ExceedanceResponse,
    ForecastSeries,
    LimitEnvelopeResponse,
    RecommendResponse,
    Scenario,
    SequenceResponse,
    ShipClass,
    TugPlanResponse,
)

from .client import ModelingClient, ModelingError
from .schemas import ToolCall
from .tools import TOOLS_BY_NAME

LEDGER: list[ToolCall] = []


def calls_for(plan_id: str | None = None) -> list[ToolCall]:
    return [c for c in LEDGER if plan_id is None or c.plan_id == plan_id]


class UnknownTool(KeyError):
    pass


class PhysicsToolkit:
    def __init__(self, client: ModelingClient, caller: str, plan_id: str | None = None):
        self.client, self.caller, self.plan_id = client, caller, plan_id
        self.last_call: ToolCall | None = None

    async def _run(self, tool: str, request: Any, coro: Awaitable[Any]) -> Any:
        start = time.perf_counter()
        call = dict(call_id=new_id("call"), at_utc=utcnow(), caller=self.caller, plan_id=self.plan_id, tool=tool,
                    request_hash=inputs_hash(request))
        try:
            out = await coro
        except ModelingError as e:
            self.last_call = ToolCall(**call, result_id=None, status=None,
                                      duration_ms=round((time.perf_counter() - start) * 1000, 1), error=e.detail)
            LEDGER.append(self.last_call)
            raise
        rid = getattr(out, "result_id", None) or (out.get("result_id") if isinstance(out, dict) else None)
        status = getattr(out, "status", None) or (out.get("status") if isinstance(out, dict) else None)
        self.last_call = ToolCall(**call, result_id=rid, status=status if status in ("GREEN", "AMBER", "RED") else None,
                                  duration_ms=round((time.perf_counter() - start) * 1000, 1))
        LEDGER.append(self.last_call)
        return out

    # ---- Generic (LLM tool use and the HTTP gateway) ----
    async def call(self, name: str, input: dict[str, Any]) -> Any:
        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            raise UnknownTool(f"Unknown tool '{name}'")
        params = dict(input)
        path = spec.path
        for key in [seg[1:-1] for seg in spec.path.split("/") if seg.startswith("{")]:
            if key not in params:
                raise ModelingError(422, f"Tool '{name}' needs '{key}'")
            path = path.replace("{" + key + "}", str(params.pop(key)))
        if spec.method == "GET":
            coro = self.client.request("GET", path, params=params)
        elif spec.async_job:
            coro = self.client.job(path, params)
        else:
            coro = self.client.request("POST", path, json=params)
        return await self._run(name, input, coro)

    # ---- Typed helpers ----
    async def scenario(self, scenario_id: str) -> Scenario:
        return await self._run("get_scenario", {"scenario_id": scenario_id}, self.client.scenario(scenario_id))

    async def ship(self, class_id: str) -> ShipClass:
        return await self._run("get_ship", {"class_id": class_id}, self.client.ship(class_id))

    async def berth(self, berth_id: str) -> Berth:
        return await self._run("get_berth", {"berth_id": berth_id}, self.client.berth(berth_id))

    async def env_now(self, berth_id: str, env_scenario_id: str | None = None) -> EnvironmentSnapshot:
        req = {"berth_id": berth_id, "env_scenario_id": env_scenario_id}
        return await self._run("get_environment", req, self.client.env_now(berth_id, env_scenario_id=env_scenario_id))

    async def forecast(self, berth_id: str, hours: int = 24, step_min: int = 30) -> ForecastSeries:
        req = {"berth_id": berth_id, "hours": hours, "step_min": step_min}
        return await self._run("get_forecast", req, self.client.forecast(berth_id, hours, step_min))

    async def analyze(self, body: dict) -> AnalyzeResponse:
        return await self._run("analyze_mooring", body, self.client.analyze(body))

    async def envelope(self, body: dict) -> LimitEnvelopeResponse:
        return await self._run("limit_envelope", body, self.client.envelope(body))

    async def recommend(self, body: dict) -> RecommendResponse:
        return await self._run("recommend_config", body, self.client.recommend(body))

    async def sequence(self, body: dict) -> SequenceResponse:
        return await self._run("generate_sequence", body, self.client.sequence(body))

    async def berthing_tugs(self, body: dict) -> TugPlanResponse:
        return await self._run("plan_tugs", body, self.client.berthing_tugs(body))

    async def hold_tugs(self, body: dict) -> TugPlanResponse:
        return await self._run("hold_tugs", body, self.client.hold_tugs(body))

    async def exceedance(self, body: dict) -> ExceedanceResponse:
        return await self._run("risk_exceedance", body, self.client.exceedance(body))

    async def windows(self, body: dict) -> BerthingWindowsResponse:
        return await self._run("berthing_windows", body, self.client.windows(body))
