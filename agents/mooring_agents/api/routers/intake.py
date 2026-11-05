"""Environment/Intake agent endpoints."""

from typing import Annotated

from fastapi import APIRouter, Body

from mooring import refdata
from mooring.core import access

from ...backend import intake
from ...intake.schemas import IntakeReport, IntakeRequest
from ..state import JOBS, IntakeTools
from ..execution import submit_async
from mooring.core.schemas import JobAccepted

router = APIRouter(tags=["Intake agent"])


@router.post("/intake/reports", response_model=JobAccepted, status_code=202,
             summary="Assess the environment for a berth (job; result is an IntakeReport)")
async def create_intake_report(tk: IntakeTools, req: Annotated[IntakeRequest, Body(openapi_examples={"default": {
        "summary": "Next 24 h for a saved scenario",
        "value": {"scenario_id": "<scenario_id from modeling POST /scenarios>", "horizon_hours": 24}}})]):
    return submit_async(JOBS, "intake.report", tk, lambda ctx: intake.assess(req, tk))


@router.get("/intake/reports/{report_id}", response_model=IntakeReport)
def get_intake_report(report_id: str):
    if not access.allowed("agent_report", report_id) or report_id not in intake.REPORTS:
        raise refdata.NotFound(f"Intake report '{report_id}' not found")
    return intake.REPORTS[report_id]
