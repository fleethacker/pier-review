"""Agents service: berth map analysis (M8), planning agent (M9), safety sheet (M10). Port 8001.

Calls the modeling service over HTTP (MODELING_API_URL). Run both with `make mock` from the repo root.
"""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Body, Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError
from pydantic.json_schema import models_json_schema

from mooring import refdata
from mooring.core.jobs import JobStore, sse
from mooring.core.schemas import BerthCreated, Health, JobAccepted, JobStatus, VersionInfo

from ..backend import BACKENDS, planner, sheet, vision
from ..clients import ModelingClient, ModelingError
from ..schemas import (
    AgentDoneEvent,
    AgentMessage,
    AgentMessageAccepted,
    AgentMessageEvent,
    AgentPlan,
    AgentPlanAccepted,
    AgentPlanRequest,
    AgentProposalEvent,
    AgentStepEvent,
    ApprovalCreate,
    SafetySheet,
    SafetySheetCreate,
    SafetySheetCreated,
    VisionConfirm,
    VisionMetadata,
)
from ..tools import TOOLS, ToolSpec

API_PREFIX = "/api/v1"
JOBS = JobStore(API_PREFIX)
PLAN_JOBS: dict[str, str] = {}  # plan_id -> job_id
VISION_RESULTS: dict[str, dict] = {}  # job_id -> VisionResponse JSON

TAGS = [
    {"name": "M8 Berth vision", "description": "Image of a berth -> draft berth and line placement, human-confirmed."},
    {"name": "M9 Planning agent", "description": "Plan, evaluate, adjust loop over modeling tools; streams progress."},
    {"name": "M10 Safety sheet", "description": "Mooring Evolution Safety Sheet assembly, rendering and approvals."},
    {"name": "System", "description": "Jobs, tool catalog, health."},
]
DESCRIPTION = """
LLM agent service for the mooring assistant. Agents reach physics only through the modeling API
(`contract/modeling.openapi.yaml`) and cite every number by `result_id`. **All agents currently run as mocks**
(deterministic, no LLM). Plan progress streams as Server-Sent Events: `step`, `proposal`, `message`, `done`.
"""


def get_client() -> ModelingClient:
    return ModelingClient()


Client = Annotated[ModelingClient, Depends(get_client)]

app = FastAPI(title="Mooring Assistant: Agents API", version="1.0.0", description=DESCRIPTION, openapi_tags=TAGS,
              separate_input_output_schemas=False)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
router = APIRouter(prefix=API_PREFIX)


@app.middleware("http")
async def backend_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Mooring-Backend"] = "mock"
    return response


@app.exception_handler(ModelingError)
async def modeling_error(_: Request, exc: ModelingError):
    code = exc.status if exc.status in (404, 422) else 502
    return JSONResponse(status_code=code, content={"detail": exc.detail})


@app.exception_handler(refdata.NotFound)
async def not_found(_: Request, exc: refdata.NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


# ---------- M8 Berth vision ----------

VISION_META_EXAMPLE = '{"image_kind": "satellite", "georef": {"scale_ft_per_px": 0.5}, "ship_class_id": "DDG-51-FIIA", "side_to": "starboard"}'


@router.post("/berth-vision/analyze", response_model=JobAccepted, status_code=202, tags=["M8 Berth vision"],
             summary="Analyze a berth image (multipart: image + metadata JSON). Job result is a VisionResponse.")
async def vision_analyze(client: Client, image: Annotated[UploadFile, File(description="PNG, JPEG or PDF page")],
                         metadata: Annotated[str, Form(description=f"VisionMetadata as JSON, e.g. {VISION_META_EXAMPLE}")]):
    try:
        meta = VisionMetadata.model_validate_json(metadata)
    except ValidationError as e:
        return JSONResponse(status_code=422, content={"detail": json.loads(e.json())})
    resp = await vision.analyze(await image.read(), image.filename or "upload", meta, client)
    accepted = JOBS.submit("berth_vision.analyze", resp)
    VISION_RESULTS[accepted.job_id] = resp.model_dump(mode="json")
    return accepted


@router.post("/berth-vision/{job_id}/confirm", response_model=BerthCreated, status_code=201, tags=["M8 Berth vision"],
             summary="Save the human-confirmed berth to the modeling service")
async def vision_confirm(job_id: str, req: VisionConfirm, client: Client):
    if job_id not in VISION_RESULTS:
        raise refdata.NotFound(f"Vision job '{job_id}' not found")
    berth = req.berth.model_copy(update={"provenance": req.berth.provenance.model_copy(
        update={"notes": (req.berth.provenance.notes or "") + " Confirmed by user."})})
    return BerthCreated(berth_id=await client.save_berth(berth))


# ---------- M9 Planning agent ----------


@router.post("/agent/plans", response_model=AgentPlanAccepted, status_code=202, tags=["M9 Planning agent"],
             summary="Start the planning agent on a saved scenario")
async def create_plan(req: Annotated[AgentPlanRequest, Body(openapi_examples={"default": {
        "summary": "Plan for a saved scenario", "value": {"scenario_id": "<scenario_id from modeling POST /scenarios>",
                                                          "objective": "moor_for_forecast", "target_margin_pct_wll": 80}}})],
                      client: Client):
    rec = await planner.run(req, client)
    accepted = JOBS.submit("agent.plan", rec.plan)
    PLAN_JOBS[rec.plan.plan_id] = accepted.job_id
    return AgentPlanAccepted(plan_id=rec.plan.plan_id, job_id=accepted.job_id,
                             events_url=f"{API_PREFIX}/agent/plans/{rec.plan.plan_id}/events")


def _plan_record(plan_id: str):
    if plan_id not in planner.PLANS:
        raise refdata.NotFound(f"Plan '{plan_id}' not found")
    return planner.PLANS[plan_id], JOBS.get(PLAN_JOBS[plan_id])


@router.get("/agent/plans/{plan_id}", response_model=AgentPlan, tags=["M9 Planning agent"])
def get_plan(plan_id: str):
    rec, job = _plan_record(plan_id)
    if job.state == "running":
        return AgentPlan(plan_id=plan_id, scenario_id=rec.scenario.scenario_id, state="running")
    return rec.plan


@router.get("/agent/plans/{plan_id}/events", tags=["M9 Planning agent"],
            summary="SSE: step (AgentStepEvent), proposal (AgentProposalEvent), message (AgentMessageEvent), "
                    "done (AgentDoneEvent). follow=true keeps the stream open for follow-up answers.",
            response_class=StreamingResponse, responses={200: {"content": {"text/event-stream": {}}}})
def plan_events(plan_id: str, follow: bool = True):
    rec, job = _plan_record(plan_id)

    async def gen():
        sent = 0
        while True:
            p = job.progress
            due = len(rec.events) if p >= 1 else int(len(rec.events) * p)
            while sent < due:
                name, data = rec.events[sent]
                yield sse(name, data)
                sent += 1
            if p >= 1:
                break
            await asyncio.sleep(min(0.5, max(job.delay_s / 20, 0.05)))
        msent, idle = 0, 0.0
        while follow and idle < 600:
            while msent < len(rec.messages):
                name, data = rec.messages[msent]
                yield sse(name, data)
                msent, idle = msent + 1, 0.0
            await asyncio.sleep(0.5)
            idle += 0.5
            if idle % 15 == 0:
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/agent/plans/{plan_id}/messages", response_model=AgentMessageAccepted, status_code=202,
             tags=["M9 Planning agent"], summary="Ask a follow-up; the answer streams as a `message` event")
async def plan_message(plan_id: str, req: AgentMessage, client: Client):
    rec, _ = _plan_record(plan_id)
    msg = await planner.answer(rec, req.text, client)
    return AgentMessageAccepted(message_id=msg.message_id)


# ---------- M10 Safety sheet ----------


@router.post("/safety-sheets", response_model=SafetySheetCreated, status_code=201, tags=["M10 Safety sheet"],
             summary="Build a safety sheet from a finished plan")
def create_sheet(req: SafetySheetCreate):
    rec, job = _plan_record(req.plan_id)
    if job.state != "succeeded":
        return JSONResponse(status_code=409, content={"detail": "Plan is still running"})
    s = sheet.build(rec)
    rec.plan.safety_sheet_id = s.sheet_id
    return SafetySheetCreated(sheet_id=s.sheet_id, version=s.version)


def _sheet(sheet_id: str) -> SafetySheet:
    if sheet_id not in sheet.SHEETS:
        raise refdata.NotFound(f"Safety sheet '{sheet_id}' not found")
    return sheet.SHEETS[sheet_id]


@router.get("/safety-sheets/{sheet_id}", response_model=SafetySheet, tags=["M10 Safety sheet"])
def get_sheet(sheet_id: str):
    return _sheet(sheet_id)


@router.get("/safety-sheets/{sheet_id}/render", tags=["M10 Safety sheet"], response_class=HTMLResponse,
            summary="Printable sheet. format=html now; pdf returns 501 until the renderer lands.")
def render_sheet(sheet_id: str, format: str = "html"):
    s = _sheet(sheet_id)
    if format != "html":
        return JSONResponse(status_code=501, content={"detail": f"format '{format}' not implemented yet"})
    return HTMLResponse(sheet.render_html(s))


@router.post("/safety-sheets/{sheet_id}/approvals", response_model=SafetySheet, tags=["M10 Safety sheet"],
             summary="Record an approval or rejection; the sheet locks on the first one")
def approve_sheet(sheet_id: str, req: Annotated[ApprovalCreate, Body(openapi_examples={"default": {
        "summary": "CO approval", "value": {"role": "co", "name": "Commanding Officer", "decision": "approve"}}})]):
    return sheet.approve(_sheet(sheet_id), req)


# ---------- System ----------


@router.get("/jobs/{job_id}", response_model=JobStatus, tags=["System"])
def job_status(job_id: str):
    st = JOBS.status(job_id)
    if st is None:
        raise refdata.NotFound(f"Job '{job_id}' not found")
    return st


@router.get("/jobs/{job_id}/events", tags=["System"], response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}}})
def job_events(job_id: str):
    if JOBS.get(job_id) is None:
        raise refdata.NotFound(f"Job '{job_id}' not found")
    return StreamingResponse(JOBS.stream(job_id), media_type="text/event-stream")


@router.get("/tools", response_model=list[ToolSpec], tags=["System"], summary="Modeling tools the agents may call")
def tools():
    return TOOLS


@router.get("/health", response_model=Health, tags=["System"])
def health():
    return Health(status="ok", backend="mock")


@router.get("/version", response_model=VersionInfo, tags=["System"])
def version():
    return VersionInfo(api_version="1.0.0", modules=BACKENDS)


app.include_router(router)

STREAM_MODELS = [AgentStepEvent, AgentProposalEvent, AgentMessageEvent, AgentDoneEvent, VisionMetadata]


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
