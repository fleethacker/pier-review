"""HTTP client for the modeling service. Agents reach physics only through this API, never by import.

Base URL from MODELING_API_URL (default http://localhost:8000/api/v1). Tests inject an in-process transport.
"""

import asyncio
import os
from typing import Any

import httpx

from mooring.core.schemas import (
    AnalyzeResponse,
    Berth,
    EnvironmentSnapshot,
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


class ModelingClient:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (base_url or os.environ.get("MODELING_API_URL", DEFAULT_URL)).rstrip("/")
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, transport=self._transport, timeout=60)

    async def _req(self, method: str, path: str, **kw) -> Any:
        async with self._client() as c:
            r = await c.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise ModelingError(r.status_code, f"modeling {method} {path}: {detail}")
        return r.json()

    async def _job(self, path: str, body: dict, poll_s: float = 0.25, timeout_s: float = 120) -> dict:
        accepted = await self._req("POST", path, json=body)
        status_path = accepted["status_url"].removeprefix("/api/v1")
        waited = 0.0
        while True:
            st = await self._req("GET", status_path)
            if st["state"] == "succeeded":
                return st["result"]
            if st["state"] == "failed":
                raise ModelingError(500, st.get("error") or "modeling job failed")
            if waited > timeout_s:
                raise ModelingError(504, f"modeling job {accepted['job_id']} timed out")
            await asyncio.sleep(poll_s)
            waited += poll_s

    # ---- Reference data ----
    async def scenario(self, scenario_id: str) -> Scenario:
        return Scenario.model_validate(await self._req("GET", f"/scenarios/{scenario_id}"))

    async def ship(self, class_id: str) -> ShipClass:
        return ShipClass.model_validate(await self._req("GET", f"/ships/{class_id}"))

    async def berth(self, berth_id: str) -> Berth:
        return Berth.model_validate(await self._req("GET", f"/berths/{berth_id}"))

    async def save_berth(self, berth: Berth) -> str:
        return (await self._req("POST", "/berths", json=berth.model_dump(mode="json")))["berth_id"]

    async def result(self, result_id: str) -> dict:
        return await self._req("GET", f"/results/{result_id}")

    # ---- Environment ----
    async def env_now(self, berth_id: str, heading_true_deg: float | None = None) -> EnvironmentSnapshot:
        params = {"berth_id": berth_id}
        if heading_true_deg is not None:
            params["heading_true_deg"] = heading_true_deg
        return EnvironmentSnapshot.model_validate(await self._req("GET", "/env/now", params=params))

    # ---- Physics tools ----
    async def analyze(self, body: dict) -> AnalyzeResponse:
        return AnalyzeResponse.model_validate(await self._req("POST", "/mooring/analyze", json=body))

    async def envelope(self, body: dict) -> LimitEnvelopeResponse:
        return LimitEnvelopeResponse.model_validate(await self._req("POST", "/mooring/envelope", json=body))

    async def recommend(self, body: dict) -> RecommendResponse:
        return RecommendResponse.model_validate(await self._job("/mooring/recommend", body))

    async def sequence(self, body: dict) -> SequenceResponse:
        return SequenceResponse.model_validate(await self._req("POST", "/mooring/sequence", json=body))

    async def berthing_tugs(self, body: dict) -> TugPlanResponse:
        return TugPlanResponse.model_validate(await self._req("POST", "/tugs/berthing-plan", json=body))

    async def hold_tugs(self, body: dict) -> TugPlanResponse:
        return TugPlanResponse.model_validate(await self._req("POST", "/tugs/hold-plan", json=body))

    async def exceedance(self, body: dict) -> ExceedanceResponse:
        return ExceedanceResponse.model_validate(await self._job("/risk/exceedance", body))
