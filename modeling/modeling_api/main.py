"""Modeling service: physics and ML endpoints (modules M1-M7, M11-M13). Run with `make mock` from the repo root."""

import math

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic.json_schema import models_json_schema

from mooring import refdata
from mooring.core.schemas import (
    Alert,
    EnvironmentSnapshot,
    JobDoneEvent,
    JobProgressEvent,
    SimControlMessage,
    SimFrame,
    SimLineEventMessage,
    SimTugCommandMessage,
    TelemetryAccepted,
    TelemetryRecord,
)

from .routers import approach, berthing, env, loads, moored, refdata as refdata_router, system, telemetry
from .backend import overall_backend
from .state import API_PREFIX
from .ws import router as ws_router

TAGS = [
    {"name": "M1 Environment", "description": "Wind, current and water level from every source, normalized."},
    {"name": "M2 Reference data", "description": "Ships, lines, berths, tugs and saved scenarios."},
    {"name": "M3 Environmental loads", "description": "Wind and current forces (UFC 4-159-03 Chapter 4)."},
    {"name": "M4 Static mooring", "description": "Line and fitting loads, NSTM 582 checks, limiting wind, tide sweep."},
    {"name": "M5 Risk", "description": "Gust exceedance probability and forecast timeline."},
    {"name": "M6 Tugs", "description": "Tug force, bollard pull and horsepower; berthing windows."},
    {"name": "M7 Planning", "description": "Recommended line configuration and line sequence."},
    {"name": "M11 Berthing simulator", "description": "Phase 2: time-domain berthing, batch and interactive."},
    {"name": "M12 Approach", "description": "Phase 3: route, under-keel clearance, approach simulation."},
    {"name": "M13 Telemetry", "description": "Ship sensor ingest for deployment."},
    {"name": "System", "description": "Jobs, stored results, health."},
]

DESCRIPTION = """
Physics and ML modeling service for the mooring assistant. **Most modules still run on mock backends.**
Environmental loads (M3, UFC 4-159-03) and reference data are real; `GET /version` lists each module's status.
Check `backend` in every response envelope; the `X-Mooring-Backend` header is `mixed` while some modules are mock.

Conventions: unit-suffixed field names (`_kt`, `_ft`, `_lbf`, `_deg`, `_utc`); wind direction is where it blows
FROM, current direction is where it flows TOWARD; long-running endpoints return `202` with a job (poll
`/jobs/{job_id}` or stream `/jobs/{job_id}/events`). WebSocket channels are listed under `x-websockets`.
"""

WEBSOCKETS = {
    "/ws/env": {"query": "berth_id, mode=live|replay|scenario, env_scenario_id, replay_start_utc, speed, interval_s, limit",
                "server_messages": "EnvironmentSnapshot"},
    "/ws/alerts": {"query": "berth_id, scenario_id, interval_s, limit", "server_messages": "Alert"},
    "/ws/sim/{session_id}": {"query": "limit",
                             "client_messages": "SimTugCommandMessage | SimLineEventMessage | SimControlMessage",
                             "server_messages": "SimFrame (10 Hz)"},
    "/ws/telemetry": {"client_messages": "TelemetryRecord", "server_messages": "TelemetryAccepted"},
}
STREAM_MODELS = [EnvironmentSnapshot, Alert, SimFrame, SimTugCommandMessage, SimLineEventMessage, SimControlMessage,
                 TelemetryRecord, TelemetryAccepted, JobProgressEvent, JobDoneEvent]

app = FastAPI(title="Mooring Assistant: Modeling API", version="1.0.0", description=DESCRIPTION,
              openapi_tags=TAGS, separate_input_output_schemas=False)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def backend_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Mooring-Backend"] = overall_backend()
    return response


def _finite(value):
    """Echoed invalid input can be NaN/Infinity, which JSON cannot carry; show it as text instead of crashing."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def invalid_body(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": _finite(jsonable_encoder(exc.errors()))})


@app.exception_handler(refdata.NotFound)
async def not_found(_: Request, exc: refdata.NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(refdata.InvalidReference)
async def invalid_reference(_: Request, exc: refdata.InvalidReference):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


for r in (env, refdata_router, loads, moored, berthing, approach, telemetry, system):
    app.include_router(r.router, prefix=API_PREFIX)
app.include_router(ws_router)


def openapi_schema() -> dict:
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes,
                         tags=TAGS, separate_input_output_schemas=False)
    _, defs = models_json_schema([(m, "validation") for m in STREAM_MODELS],
                                 ref_template="#/components/schemas/{model}")
    comps = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, s in defs.get("$defs", {}).items():
        comps.setdefault(name, s)
    schema["servers"] = [{"url": "http://localhost:8000", "description": "Local mock server"}]
    schema["x-websockets"] = WEBSOCKETS
    return schema


def _custom_openapi():
    if app.openapi_schema is None:
        app.openapi_schema = openapi_schema()
    return app.openapi_schema


app.openapi = _custom_openapi
