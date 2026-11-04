"""Validated, budgeted gateway to modeling. No LLM and no physics calculations."""

import asyncio
import json
import math
import os
import time
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from mooring.core.envelopes import inputs_hash, new_id, utcnow, validity_state
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
from .ledger import LEDGER, calls_for, reserve_call, update_call  # noqa: F401 (public compatibility)
from .schemas import ToolCall
from .tools import TOOLS_BY_NAME, input_errors


class UnknownTool(KeyError):
    pass


def _request_hash(request: Any) -> str:
    try:
        return inputs_hash(request)
    except (TypeError, ValueError, RecursionError):
        # Even malformed Python inputs (e.g. circular data) need an audit entry.
        return inputs_hash({"invalid_input_repr": repr(request)})


class PhysicsToolkit:
    def __init__(self, client: ModelingClient, caller: str, plan_id: str | None = None):
        self.client, self.caller, self.plan_id = client, caller, plan_id
        self.max_calls = int(os.environ.get("AGENTS_MAX_TOOL_CALLS", "40"))
        self.timeout_s = float(os.environ.get("AGENTS_TOOL_TIMEOUT_S", "30"))
        if self.max_calls < 0:
            raise ValueError("AGENTS_MAX_TOOL_CALLS must be a nonnegative integer")
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("AGENTS_TOOL_TIMEOUT_S must be finite and positive")
        # Anonymous callers share no plan; each toolkit still gets its own budget.
        self._scope_id = new_id("scope")
        self.last_call: ToolCall | None = None

    def _finish(self, call: ToolCall, start: float, *, output: Any = None, error: str | None = None) -> None:
        result_id = output.get("result_id") if isinstance(output, dict) else None
        status = output.get("status") if isinstance(output, dict) else None
        completed = call.model_copy(update={
            "result_id": result_id,
            "status": status if status in ("GREEN", "AMBER", "RED") else None,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            "error": error,
            # S00a: record the validity the modeling service reported; absent means unknown, never valid.
            "validity_state": validity_state(output) if isinstance(output, dict) else "unknown",
        })
        update_call(completed)
        self.last_call = completed

    def _reject(self, call: ToolCall, start: float, code: str, message: str, **details: Any) -> dict:
        error = {"code": code, "message": message, **details}
        self._finish(call, start, error=json.dumps(error, sort_keys=True))
        return {"error": error}

    # ---- Generic (LLM tool use and the HTTP gateway) ----
    async def call(self, name: str, input: dict[str, Any]) -> Any:
        """Return modeling output, or a correctable local error with a ledger entry.

        Every attempt consumes the plan's budget, including invalid inputs and failures.
        Reservations happen before awaiting HTTP so concurrent calls cannot overspend.
        The timeout covers the complete request, including async-job polling.
        Modeling HTTP failures retain their existing ModelingError behavior.
        """
        start = time.perf_counter()
        call = ToolCall(call_id=new_id("call"), at_utc=utcnow(), caller=self.caller, plan_id=self.plan_id,
                        tool=name, request_hash=_request_hash(input), result_id=None, status=None, duration_ms=0)
        allowed = reserve_call(call, self.max_calls, scope_id=self._scope_id)
        self.last_call = call
        if not allowed:
            return self._reject(call, start, "budget_exceeded",
                                f"Tool call budget of {self.max_calls} exhausted for this plan; stop calling tools.",
                                plan_id=self.plan_id, max_calls=self.max_calls)

        try:
            spec = TOOLS_BY_NAME.get(name)
            if spec is None:
                raise UnknownTool(f"Unknown tool '{name}'")
            errors = input_errors(name, input)
            if errors:
                return self._reject(call, start, "invalid_input",
                                    f"Invalid input for '{name}'; correct the listed fields.", fields=errors)

            params = dict(input)
            path = spec.path
            for segment in spec.path.split("/"):
                if segment.startswith("{"):
                    key = segment[1:-1]
                    path = path.replace(segment, quote(str(params.pop(key)), safe=""))
            async with asyncio.timeout(self.timeout_s):
                if spec.method == "GET":
                    # HTTP query strings cannot represent JSON null. Optional nulls mean omission.
                    output = await self.client.request("GET", path,
                                                       params={k: v for k, v in params.items() if v is not None})
                elif spec.async_job:
                    output = await self.client.job(path, params)
                else:
                    output = await self.client.request("POST", path, json=params)
        except (TimeoutError, httpx.TimeoutException):
            return self._reject(call, start, "timeout",
                                f"Tool '{name}' exceeded its {self.timeout_s:g} s timeout.",
                                timeout_s=self.timeout_s)
        except ModelingError as exc:
            self._finish(call, start, error=exc.detail)
            raise
        except httpx.RequestError as exc:
            detail = f"Modeling request failed: {exc}"
            self._finish(call, start, error=detail)
            raise ModelingError(502, detail) from exc
        except asyncio.CancelledError:
            self._finish(call, start, error="Tool call cancelled")
            raise
        except Exception as exc:
            self._finish(call, start, error=str(exc))
            raise
        self._finish(call, start, output=output)
        return output

    async def _typed(self, name: str, request: dict, response_type):
        output = await self.call(name, request)
        if isinstance(output, dict) and "error" in output:
            error = output["error"]
            status = {"invalid_input": 422, "budget_exceeded": 429, "timeout": 504}[error["code"]]
            raise ModelingError(status, json.dumps(error, sort_keys=True))
        try:
            return response_type.model_validate(output)
        except ValidationError as exc:
            # Preserve the result ID while recording a typed response failure.
            detail = f"Invalid modeling response for '{name}': {exc}"
            self.last_call = self.last_call.model_copy(update={"error": detail})
            update_call(self.last_call)
            raise ModelingError(502, detail) from exc

    # ---- Typed helpers (same validation, budget, timeout and ledger as call) ----
    async def scenario(self, scenario_id: str) -> Scenario:
        return await self._typed("get_scenario", {"scenario_id": scenario_id}, Scenario)

    async def ship(self, class_id: str) -> ShipClass:
        return await self._typed("get_ship", {"class_id": class_id}, ShipClass)

    async def berth(self, berth_id: str) -> Berth:
        return await self._typed("get_berth", {"berth_id": berth_id}, Berth)

    async def env_now(self, berth_id: str, env_scenario_id: str | None = None) -> EnvironmentSnapshot:
        req = {"berth_id": berth_id, "env_scenario_id": env_scenario_id}
        return await self._typed("get_environment", req, EnvironmentSnapshot)

    async def forecast(self, berth_id: str, hours: int = 24, step_min: int = 30) -> ForecastSeries:
        req = {"berth_id": berth_id, "hours": hours, "step_min": step_min}
        return await self._typed("get_forecast", req, ForecastSeries)

    async def analyze(self, body: dict) -> AnalyzeResponse:
        return await self._typed("analyze_mooring", body, AnalyzeResponse)

    async def envelope(self, body: dict) -> LimitEnvelopeResponse:
        return await self._typed("limit_envelope", body, LimitEnvelopeResponse)

    async def recommend(self, body: dict) -> RecommendResponse:
        return await self._typed("recommend_config", body, RecommendResponse)

    async def sequence(self, body: dict) -> SequenceResponse:
        return await self._typed("generate_sequence", body, SequenceResponse)

    async def berthing_tugs(self, body: dict) -> TugPlanResponse:
        return await self._typed("plan_tugs", body, TugPlanResponse)

    async def hold_tugs(self, body: dict) -> TugPlanResponse:
        return await self._typed("hold_tugs", body, TugPlanResponse)

    async def exceedance(self, body: dict) -> ExceedanceResponse:
        return await self._typed("risk_exceedance", body, ExceedanceResponse)

    async def windows(self, body: dict) -> BerthingWindowsResponse:
        return await self._typed("berthing_windows", body, BerthingWindowsResponse)
