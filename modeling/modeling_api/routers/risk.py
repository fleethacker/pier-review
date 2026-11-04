from typing import Annotated

from fastapi import APIRouter, Body

from mooring.core.schemas import ExceedanceRequest, JobAccepted, TimelineRequest
from mooring.mock.examples import ex

from ..backend import risk as impl
from ..state import JOBS

router = APIRouter(tags=["M5 Risk"])


@router.post("/risk/exceedance", response_model=JobAccepted, status_code=202,
             summary="Monte Carlo probability of exceeding line limits (job; result is an ExceedanceResponse)")
def exceedance(req: Annotated[ExceedanceRequest, Body(openapi_examples=ex("risk_exceedance"))]):
    return JOBS.submit("risk.exceedance", impl.exceedance(req))


@router.post("/risk/timeline", response_model=JobAccepted, status_code=202,
             summary="Plan status through the forecast (job; result is a TimelineResponse)")
def timeline(req: Annotated[TimelineRequest, Body(openapi_examples=ex("risk_timeline"))]):
    return JOBS.submit("risk.timeline", impl.timeline(req))
