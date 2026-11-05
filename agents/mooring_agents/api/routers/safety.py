"""Safety/Brief agent endpoints: review, live gust warnings, safety sheet."""

from typing import Annotated

import httpx

from fastapi import APIRouter, Body, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from mooring import refdata
from mooring.core import access
from mooring.core.jobs import sse
from mooring.core.envelopes import utcnow
from mooring.core.schemas import JobAccepted

from ...backend import safety, sheet
from ...safety.schemas import (
    ApprovalCreate,
    SafetyReview,
    SafetyReviewRequest,
    SafetySheet,
    SafetySheetCreate,
    SafetySheetCreated,
    SafetyWatchUnavailable,
)
from ...physics.client import ModelingError
from ..state import JOBS, Client, SafetyTools
from ..execution import submit_async
from .planner import plan_record

router = APIRouter(tags=["Safety agent"])


@router.post("/safety/reviews", response_model=JobAccepted, status_code=202,
             summary="Independently review a finished plan (job; result is a SafetyReview)")
async def create_review(tk: SafetyTools, req: Annotated[SafetyReviewRequest, Body(openapi_examples={"default": {
        "summary": "Review a plan", "value": {"plan_id": "<plan_id>", "intake_report_id": "<optional report_id>"}}})]):
    _, job = plan_record(req.plan_id)
    if job.state != "succeeded":
        return JSONResponse(status_code=409, content={"detail": "Plan is still running"})
    return submit_async(JOBS, "safety.review", tk, lambda ctx: safety.review(req, tk))


@router.get("/safety/reviews/{review_id}", response_model=SafetyReview)
def get_review(review_id: str):
    if not access.allowed("agent_review", review_id) or review_id not in safety.REVIEWS:
        raise refdata.NotFound(f"Review '{review_id}' not found")
    return safety.REVIEWS[review_id]


@router.get("/safety/watch/{plan_id}", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}}},
            summary="SSE warnings and recheck notices; terminal source_unavailable on provider failure")
def watch(plan_id: str, client: Client, interval_s: Annotated[float, Query(ge=0, le=3600)] = 5.0,
          limit: Annotated[int, Query(ge=0, le=1000)] = 0,
          heartbeat_minutes: Annotated[float, Query(ge=0, le=1440)] = 5.0):
    _, job = plan_record(plan_id)
    if job.state != "succeeded":
        raise HTTPException(409, "Plan is still running or did not succeed")
    if interval_s == 0 and limit == 0:
        raise HTTPException(422, "An unbounded watch requires a positive polling interval")

    async def gen():
        try:
            async for w in safety.watch(plan_id, client, interval_s, limit, heartbeat_minutes):
                yield sse("warning", w.model_dump(mode="json"))
        except (ModelingError, httpx.HTTPError) as exc:
            status = exc.status if isinstance(exc, ModelingError) else None
            event = SafetyWatchUnavailable(plan_id=plan_id, at_utc=utcnow(),
                reason="Modeling/environment service unavailable during safety watch; no current limit assessment is available.",
                retryable=status is None or status in (408, 429) or status >= 500)
            yield sse("source_unavailable", event.model_dump(mode="json"))

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/safety-sheets", response_model=SafetySheetCreated, status_code=201,
             summary="Build a safety sheet from a reviewed plan (runs a review if none is given)")
async def create_sheet(req: SafetySheetCreate, tk: SafetyTools):
    rec, job = plan_record(req.plan_id)
    if job.state != "succeeded":
        return JSONResponse(status_code=409, content={"detail": "Plan is still running"})
    if req.review_id:
        rv = safety.REVIEWS.get(req.review_id)
        if not access.allowed("agent_review", req.review_id) or rv is None or rv.plan_id != req.plan_id:
            raise refdata.NotFound(f"Review '{req.review_id}' not found for plan '{req.plan_id}'")
    else:
        rv = await safety.review(SafetyReviewRequest(plan_id=req.plan_id), tk)
    s = sheet.build(rec, rv)
    from ...planner.agent import PLANS
    with PLANS.atomic():
        current = PLANS[req.plan_id]
        current.plan.safety_sheet_id = s.sheet_id
        PLANS[req.plan_id] = current
    return SafetySheetCreated(sheet_id=s.sheet_id, version=s.version)


def _sheet(sheet_id: str) -> SafetySheet:
    if not access.allowed("agent_sheet", sheet_id) or sheet_id not in sheet.SHEETS:
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
        try:
            pdf = sheet.render_pdf(s)
        except sheet.PdfUnavailable as exc:
            return JSONResponse(status_code=501, content={"detail": str(exc)})
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{sheet_id}.pdf"'})
    return JSONResponse(status_code=422, content={"detail": f"unsupported format '{format}'"})


@router.post("/safety-sheets/{sheet_id}/approvals", response_model=SafetySheet,
             summary="Record an approval or rejection; the sheet locks on the first one")
def approve_sheet(sheet_id: str, req: Annotated[ApprovalCreate, Body(openapi_examples={"default": {
        "summary": "CO approval", "value": {"role": "co", "name": "Commanding Officer", "decision": "approve"}}})]):
    return sheet.approve(_sheet(sheet_id), req)
