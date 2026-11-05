"""HTTP client for the modeling service. Agents reach physics only through this API, never by import.

Base URL from MODELING_API_URL (default http://localhost:8000/api/v1). Tests inject an in-process transport.
"""

import asyncio
import os
import re
from typing import Any

import httpx
from pydantic import ValidationError
from mooring.core.schemas.forecast_planning import ForecastResolvedResponse

from mooring.core.schemas import (
    AnalyzeResponse,
    Berth,
    BerthingWindowsResponse,
    EnvironmentSnapshot,
    ForecastSeries,
    ExceedanceResponse,
    LimitEnvelopeResponse,
    RecommendResponse,
    Scenario,
    SequenceResponse,
    ShipClass,
    TugPlanResponse,
)

DEFAULT_URL = "http://localhost:8000/api/v1"


class ModelingError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _validate_response(model, payload):
    """Keep upstream schema failures on the same explicit error path as HTTP failures."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ModelingError(502, f"Modeling returned an invalid {model.__name__} response") from exc


class ModelingClient:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None, *, authorization: str | None = None):
        self.base_url = (base_url or os.environ.get("MODELING_API_URL", DEFAULT_URL)).rstrip("/")
        self._transport = transport
        self._authorization = authorization
        self.checkpoint = lambda: None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, transport=self._transport, timeout=60,
                                 headers={"Authorization": self._authorization} if self._authorization else None)

    async def _req(self, method: str, path: str, **kw) -> Any:
        async with self._client() as c:
            r = await c.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                payload = r.json()
                detail = payload.get("detail", r.text) if isinstance(payload, dict) else r.text
            except ValueError:
                detail = r.text
            raise ModelingError(r.status_code, f"modeling {method} {path}: {detail}")
        try:
            return r.json()
        except ValueError as exc:
            raise ModelingError(502, f"Modeling returned invalid JSON for {method} {path}") from exc

    async def _job(self, path: str, body: dict, poll_s: float = 0.25, timeout_s: float = 120) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout_s
        try:
            async with asyncio.timeout(timeout_s):
                accepted = await self._req("POST", path, json=body)
        except TimeoutError as exc:
            raise ModelingError(504, "Modeling job submission timed out before acknowledgement") from exc
        jid = accepted.get("job_id") if isinstance(accepted, dict) else None
        if not isinstance(jid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", jid):
            raise ModelingError(502, "Modeling returned an invalid job identifier")
        status_path = f"/jobs/{jid}"
        if accepted.get("status_url") not in (status_path, "/api/v1" + status_path):
            raise ModelingError(502, "Modeling returned an unexpected job status path")
        terminal = False
        try:
            # Deadline includes HTTP latency, not just the sum of polling sleeps.
            async with asyncio.timeout(max(0, deadline - asyncio.get_running_loop().time())):
                while True:
                    self.checkpoint()
                    st = await self._req("GET", status_path)
                    if not isinstance(st, dict) or not isinstance(st.get("state"), str):
                        raise ModelingError(502, "Modeling returned an invalid job status")
                    if st["state"] == "succeeded":
                        if not isinstance(st.get("result"), dict):
                            raise ModelingError(502, "Modeling returned an invalid job result")
                        terminal = True
                        return st["result"]
                    if st["state"] in ("failed", "cancelled"):
                        terminal = True
                        raise ModelingError(409 if st["state"] == "cancelled" else 500,
                                            st.get("error") or f"modeling job {st['state']}")
                    if st["state"] not in ("queued", "running"):
                        raise ModelingError(502, "Modeling returned an unknown job state")
                    await asyncio.sleep(poll_s)
        except TimeoutError as exc:
            raise ModelingError(504, f"modeling job {jid} timed out") from exc
        finally:
            if not terminal:
                # A stopped agent must not leave expensive modeling work running indefinitely.
                # Best effort only: cleanup failure must preserve the original error/cancellation.
                try:
                    async with asyncio.timeout(1.0):
                        await self._req("DELETE", status_path)
                except (Exception, asyncio.CancelledError):
                    pass

    # ---- Reference data ----
    async def scenario(self, scenario_id: str) -> Scenario:
        return _validate_response(Scenario, await self._req("GET", f"/scenarios/{scenario_id}"))

    async def ship(self, class_id: str) -> ShipClass:
        return _validate_response(ShipClass, await self._req("GET", f"/ships/{class_id}"))

    async def berth(self, berth_id: str) -> Berth:
        return _validate_response(Berth, await self._req("GET", f"/berths/{berth_id}"))

    async def save_berth(self, berth: Berth) -> str:
        return (await self._req("POST", "/berths", json=berth.model_dump(mode="json")))["berth_id"]

    async def result(self, result_id: str) -> dict:
        return await self._req("GET", f"/results/{result_id}")

    # ---- Environment ----
    async def scenario_environment(self, scenario_id: str) -> EnvironmentSnapshot:
        return _validate_response(EnvironmentSnapshot, await self._req("GET", f"/scenarios/{scenario_id}/environment"))

    async def env_now(self, berth_id: str, heading_true_deg: float | None = None,
                      env_scenario_id: str | None = None) -> EnvironmentSnapshot:
        params: dict = {"berth_id": berth_id}
        if heading_true_deg is not None:
            params["heading_true_deg"] = heading_true_deg
        if env_scenario_id:
            params["env_scenario_id"] = env_scenario_id
        return _validate_response(EnvironmentSnapshot, await self._req("GET", "/env/now", params=params))

    async def forecast(self, berth_id: str, hours: int = 24, step_min: int = 30) -> ForecastSeries:
        params = {"berth_id": berth_id, "hours": hours, "step_min": step_min}
        return _validate_response(ForecastSeries, await self._req("GET", "/env/forecast", params=params))

    async def resolve_forecast(self, body: dict) -> ForecastResolvedResponse:
        return _validate_response(ForecastResolvedResponse, await self._req("POST", "/mooring/forecast/resolve", json=body))

    # ---- Generic access (used by the tool gateway) ----
    async def request(self, method: str, path: str, **kw) -> Any:
        return await self._req(method, path, **kw)

    async def job(self, path: str, body: dict) -> dict:
        return await self._job(path, body)

    async def windows(self, body: dict) -> BerthingWindowsResponse:
        return _validate_response(BerthingWindowsResponse, await self._req("POST", "/windows/berthing", json=body))

    # ---- Physics tools ----
    async def analyze(self, body: dict) -> AnalyzeResponse:
        return _validate_response(AnalyzeResponse, await self._req("POST", "/mooring/analyze", json=body))

    async def envelope(self, body: dict) -> LimitEnvelopeResponse:
        return _validate_response(LimitEnvelopeResponse, await self._req("POST", "/mooring/envelope", json=body))

    async def recommend(self, body: dict) -> RecommendResponse:
        return _validate_response(RecommendResponse, await self._job("/mooring/recommend", body))

    async def sequence(self, body: dict) -> SequenceResponse:
        return _validate_response(SequenceResponse, await self._req("POST", "/mooring/sequence", json=body))

    async def berthing_tugs(self, body: dict) -> TugPlanResponse:
        return _validate_response(TugPlanResponse, await self._req("POST", "/tugs/berthing-plan", json=body))

    async def hold_tugs(self, body: dict) -> TugPlanResponse:
        return _validate_response(TugPlanResponse, await self._req("POST", "/tugs/hold-plan", json=body))

    async def exceedance(self, body: dict) -> ExceedanceResponse:
        return _validate_response(ExceedanceResponse, await self._job("/risk/exceedance", body))
