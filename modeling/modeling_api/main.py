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
from mooring.core.jobs import JobQueueFull
from mooring.core.schemas import (
    Alert,
    ApproachSimResponse,
    BerthingSimResponse,
    EnvironmentSnapshot,
    JobDoneEvent,
    JobProgressEvent,
    RecommendResponse,
    SimControlMessage,
    SimFrame,
    SimLineEventMessage,
    SimLifecycle,
    SimRecording,
    SimScene,
    SimSpeedMessage,
    SimTugCommandMessage,
    TelemetryAccepted,
    TransitResponse,
    TelemetryRecord,
)

from mooring.core.schemas.forecast_planning import ForecastDockingResponse
from mooring.core.schemas.risk import ExceedanceResponse, TimelineResponse

from .routers import (approach, berthing, env, loads, missions, moored, prediction, qualification, exercise, refdata as refdata_router, system,
                      telemetry, transit)
from .backend import overall_backend
from .security import Controls
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
    {"name": "S5 Missions", "description": "Mission storyboarding: recorded tracks with images and reports located by time."},
    {"name": "S7 Prediction", "description": "Backup camera for ships: predicted path, footprints, corridor and clearance from the current state."},
    {"name": "S6 Port transit", "description": "Ships entering or leaving port on own thrust or with tugs (surrogate maneuvering)."},
    {"name": "System", "description": "Jobs, stored results, health."},
]

DESCRIPTION = """
Physics and planning service for the mooring assistant. `GET /version` reports implementation status;
`GET /capabilities` reports scope and qualification blockers. A `real` backend is not operational certification.
Inspect each result's validity, reasons and source provenance: seed assets, synthetic forcing and unqualified
models remain limited or invalid. Normal launchers default to `auto`: complete current observations, then recorded-real
replay, then explicit failure. Synthetic forcing is used only when `mock` or a synthetic scenario is explicitly selected.

Conventions: unit-suffixed field names (`_kt`, `_ft`, `_lbf`, `_deg`, `_utc`); wind direction is where it blows
FROM, current direction is where it flows TOWARD; long-running endpoints return `202` with a job (poll
`/jobs/{job_id}` or stream `/jobs/{job_id}/events`). WebSocket channels are listed under `x-websockets`.
"""

WEBSOCKETS = {
    "/ws/env": {"query": "berth_id, mode=live|replay|scenario, env_scenario_id, replay_start_utc, speed, interval_s, limit",
                "server_messages": "EnvironmentSnapshot"},
    "/ws/alerts": {"query": "berth_id, scenario_id, interval_s, limit", "server_messages": "Alert",
                   "terminal_close_codes": {"1013": "Environment source unavailable; no replacement snapshot is emitted",
                                            "4404": "Scenario/source/reference not found or not owned",
                                            "4400": "Invalid interval, limit or reference"}},
    "/ws/sim/{session_id}": {"query": "limit (counts all server messages), after_sequence (resend only newer retained lifecycle; the current frame is always sent on connect; a restating lifecycle is sent if history was evicted)",
                             "client_messages": "SimTugCommandMessage | SimLineEventMessage | SimControlMessage | SimSpeedMessage",
                             "server_messages": "SimLifecycle (type=session_lifecycle; reliable, retained) and SimFrame "
                                                "(rm0-v1, latest state only; sequence gaps are dropped display frames), "
                                                "interleaved in session-wide sequence order",
                             "scene": "GET /api/v1/berthing/sessions/{session_id}/scene",
                             "recording": "GET /api/v1/berthing/sessions/{session_id}/recording"},
    "/ws/telemetry": {"client_messages": "TelemetryRecord", "server_messages": "TelemetryAccepted"},
}
JOB_RESULT_MODELS = [ForecastDockingResponse, ExceedanceResponse, TimelineResponse, RecommendResponse,
                     BerthingSimResponse, ApproachSimResponse, TransitResponse]
STREAM_MODELS = [*JOB_RESULT_MODELS, EnvironmentSnapshot, Alert, SimFrame, SimTugCommandMessage, SimLineEventMessage, SimControlMessage,
                 SimSpeedMessage, TelemetryRecord, TelemetryAccepted, JobProgressEvent, JobDoneEvent, SimScene, SimLifecycle,
                 SimRecording]

app = FastAPI(title="Mooring Assistant: Modeling API", version="1.0.0", description=DESCRIPTION,
              openapi_tags=TAGS, separate_input_output_schemas=False)
app.add_middleware(Controls)
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


@app.exception_handler(OverflowError)
async def numerical_range(_: Request, exc: OverflowError):
    return JSONResponse(status_code=422, content={
        "detail": "Inputs exceed the supported numerical range; no result is available."
    })


@app.exception_handler(JobQueueFull)
async def queue_full(_: Request, exc: JobQueueFull):
    return JSONResponse(status_code=429, content={"detail": str(exc)}, headers={"Retry-After": str(exc.retry_after_s)})


@app.exception_handler(refdata.NotFound)
async def not_found(_: Request, exc: refdata.NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(refdata.InvalidReference)
async def invalid_reference(_: Request, exc: refdata.InvalidReference):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


for r in (env, refdata_router, qualification, loads, moored, berthing, approach, telemetry, missions, transit, prediction, system, exercise):
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
    schema["servers"] = [{"url": "http://localhost:8000", "description": "Local modeling service"}]
    schema["x-websockets"] = WEBSOCKETS
    schema["x-motion-contract"] = {
        "schema_version": "rm0-v1",
        "status": "Interactive sessions (POST /berthing/sessions, WS /ws/sim) emit rm0-v1 frames, lifecycle, scene and recording from the live simulator (S1). Batch /berthing/simulate series remain legacy frames.",
        "models": ["SimFrame", "SimScene", "SimLifecycle", "SimRecording"],
        "examples": "contract/examples/modeling/sim_*.json",
        "design": "docs/MOTION_FRAME_DESIGN.md",
    }
    return schema


def _custom_openapi():
    if app.openapi_schema is None:
        app.openapi_schema = openapi_schema()
    return app.openapi_schema


app.openapi = _custom_openapi
