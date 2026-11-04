"""Safety/Brief agent endpoints: review, live gust warnings, safety sheet."""

from typing import Annotated

from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from mooring import refdata
from mooring.core.jobs import sse
from mooring.core.schemas import JobAccepted

from ...backend import safety, sheet
from ...safety.schemas import (
    ApprovalCreate,
    SafetyReview,
    SafetyReviewRequest,
    SafetySheet,
    SafetySheetCreate,
    SafetySheetCreated,
)
from ..state import JOBS, Client, SafetyTools
from .planner import plan_record

router = APIRouter(tags=["Safety agent"])


@router.post("/safety/reviews", response_model=JobAccepted, status_code=202,
             summary="Independently review a finished plan (job; result is a SafetyReview)")
async def create_review(tk: SafetyTools, req: Annotated[SafetyReviewRequest, Body(openapi_examples={"default": {
        "summary": "Review a plan", "value": {"plan_id": "<plan_id>", "intake_report_id": "<optional report_id>"}}})]):
    _, job = plan_record(req.plan_id)
    if job.state != "succeeded":
        return JSONResponse(status_code=409, content={"detail": "Plan is still running"})
    return JOBS.submit("safety.review", await safety.review(req, tk))


@router.get("/safety/reviews/{review_id}", response_model=SafetyReview)
def get_review(review_id: str):
    if review_id not in safety.REVIEWS:
        raise refdata.NotFound(f"Review '{review_id}' not found")
    return safety.REVIEWS[review_id]


@router.get("/safety/watch/{plan_id}", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}}},
            summary="SSE `warning` events (GustWarning): live gusts vs the plan's working-load and breaking limits")
def watch(plan_id: str, client: Client, interval_s: float = 5.0, limit: int = 0,
          heartbeat_minutes: float = 5.0):
    plan_record(plan_id)

    async def gen():
        async for w in safety.watch(plan_id, client, interval_s, limit, heartbeat_minutes):
            yield sse("warning", w.model_dump(mode="json"))

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/safety-sheets", response_model=SafetySheetCreated, status_code=201,
             summary="Build a safety sheet from a reviewed plan (runs a review if none is given)")
async def create_sheet(req: SafetySheetCreate, tk: SafetyTools):
    rec, job = plan_record(req.plan_id)
    if job.state != "succeeded":
        return JSONResponse(status_code=409, content={"detail": "Plan is still running"})
    if req.review_id:
        rv = safety.REVIEWS.get(req.review_id)
        if rv is None or rv.plan_id != req.plan_id:
            raise refdata.NotFound(f"Review '{req.review_id}' not found for plan '{req.plan_id}'")
    else:
        rv = await safety.review(SafetyReviewRequest(plan_id=req.plan_id), tk)
    s = sheet.build(rec, rv)
    rec.plan.safety_sheet_id = s.sheet_id
    return SafetySheetCreated(sheet_id=s.sheet_id, version=s.version)


def _sheet(sheet_id: str) -> SafetySheet:
    if sheet_id not in sheet.SHEETS:
        raise refdata.NotFound(f"Safety sheet '{sheet_id}' not found")
    return sheet.SHEETS[sheet_id]


@router.get("/safety-sheets/{sheet_id}", response_model=SafetySheet)
def get_sheet(sheet_id: str):
    return _sheet(sheet_id)


@router.get("/safety-sheets/{sheet_id}/render",
            summary="Render the printable sheet as HTML or PDF.")
def render_sheet(sheet_id: str, format: str = "html"):
    s = _sheet(sheet_id)
    if format == "html":
        return HTMLResponse(sheet.render_html(s))
    if format == "pdf":
        return Response(sheet.render_pdf(s), media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{sheet_id}.pdf"'})
    return JSONResponse(status_code=422, content={"detail": f"unsupported format '{format}'"})


@router.post("/safety-sheets/{sheet_id}/approvals", response_model=SafetySheet,
             summary="Record an approval or rejection; the sheet locks on the first one")
def approve_sheet(sheet_id: str, req: Annotated[ApprovalCreate, Body(openapi_examples={"default": {
        "summary": "CO approval", "value": {"role": "co", "name": "Commanding Officer", "decision": "approve"}}})]):
    return sheet.approve(_sheet(sheet_id), req)
