from typing import Annotated

from fastapi import APIRouter, Body

from mooring import refdata
from mooring.core.envelopes import new_id
from mooring.core.schemas import ApproachSimRequest, ApproachTrack, JobAccepted, RouteRequest, RouteResponse, UkcRequest, UkcResponse
from mooring.mock.examples import ex

from ..backend import dynamics
from ..state import API_PREFIX, JOBS

router = APIRouter(tags=["M12 Approach"])


@router.post("/approach/route", response_model=RouteResponse, summary="Channel route from the sea buoy to the berth")
def route(req: Annotated[RouteRequest, Body(openapi_examples=ex("approach_route"))]):
    return dynamics.route(req)


@router.post("/approach/ukc", response_model=UkcResponse, summary="Under-keel clearance per leg with tide and squat")
def ukc(req: Annotated[UkcRequest, Body(openapi_examples=ex("approach_ukc"))]):
    return dynamics.ukc(req)


@router.post("/approach/simulate", response_model=JobAccepted, status_code=202,
             summary="Approach simulation (job; result is an ApproachSimResponse)")
def simulate(req: Annotated[ApproachSimRequest, Body(openapi_examples=ex("approach_simulate"))]):
    jid = new_id("job")
    return JOBS.submit("approach.simulate", dynamics.simulate_approach(req, jid, API_PREFIX), job_id=jid)


@router.get("/approach/simulations/{job_id}/track", response_model=ApproachTrack)
def track(job_id: str):
    if job_id not in dynamics.TRACKS:
        raise refdata.NotFound(f"No approach track for job '{job_id}'")
    return dynamics.TRACKS[job_id]
