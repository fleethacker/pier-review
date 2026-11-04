"""Agents service (port 8001): Intake, Physics, Planner, Safety/Brief and Berth Map agents.

Agents reach physics only through the Physics agent's logged toolkit (MODELING_API_URL). One router per agent.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic.json_schema import models_json_schema

from mooring import refdata

from ..physics.client import ModelingError
from ..planner.schemas import AgentDoneEvent, AgentMessageEvent, AgentProposalEvent, AgentStepEvent
from ..safety.schemas import GustWarning
from ..vision.schemas import VisionMetadata, VisionResponse
from ..intake.schemas import IntakeReport
from ..safety.schemas import SafetyReview
from .routers import intake, physics, planner, safety, system, vision
from .state import API_PREFIX, get_client  # noqa: F401  (tests override get_client)

TAGS = [
    {"name": "Intake agent", "description": "Environment data -> windows of concern, MST assessment, design conditions."},
    {"name": "Physics agent", "description": "Logged gateway to modeling tools. No LLM, no math: modeling computes."},
    {"name": "Planner agent", "description": "Plan, evaluate, adjust loop over physics tools; streams progress."},
    {"name": "Safety agent", "description": "Independent review, live gust warnings, Mooring Evolution Safety Sheet."},
    {"name": "Berth map agent", "description": "Image of a berth -> draft berth and line placement, human-confirmed."},
    {"name": "System", "description": "Jobs, health."},
]
DESCRIPTION = """
LLM agent service for the mooring assistant. Typical flow: `POST /intake/reports` → `POST /agent/plans`
(with `intake_report_id`) → `POST /safety/reviews` → `POST /safety-sheets` → approvals, with
`GET /safety/watch/{plan_id}` for live gust warnings. Agents reach physics only through the Physics agent
(`/tools`, `/physics/*`), which logs every call; every number in a plan cites a logged `result_id`.
**Mixed implementation:** Intake and Planner have guarded optional LLM layers; other agent and modeling
capabilities still include mocks. See `/version` for module status.
"""

app = FastAPI(title="Mooring Assistant: Agents API", version="1.1.0", description=DESCRIPTION, openapi_tags=TAGS,
              separate_input_output_schemas=False)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def backend_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Mooring-Backend"] = "mock"
    return response


@app.exception_handler(ModelingError)
async def modeling_error(_: Request, exc: ModelingError):
    code = exc.status if exc.status in (404, 409, 422) else 502
    return JSONResponse(status_code=code, content={"detail": exc.detail})


@app.exception_handler(refdata.NotFound)
async def not_found(_: Request, exc: refdata.NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


for r in (intake, physics, planner, safety, vision, system):
    app.include_router(r.router, prefix=API_PREFIX)

# Job results and SSE payloads that no endpoint references directly; added so clients get their types.
STREAM_MODELS = [IntakeReport, SafetyReview, VisionResponse, GustWarning, AgentStepEvent, AgentProposalEvent,
                 AgentMessageEvent, AgentDoneEvent, VisionMetadata]


def openapi_schema() -> dict:
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes,
                         tags=TAGS, separate_input_output_schemas=False)
    _, defs = models_json_schema([(m, "validation") for m in STREAM_MODELS], ref_template="#/components/schemas/{model}")
    comps = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, s in defs.get("$defs", {}).items():
        comps.setdefault(name, s)
    schema["servers"] = [{"url": "http://localhost:8001", "description": "Local mock server"}]
    return schema


def _custom_openapi():
    if app.openapi_schema is None:
        app.openapi_schema = openapi_schema()
    return app.openapi_schema


app.openapi = _custom_openapi
